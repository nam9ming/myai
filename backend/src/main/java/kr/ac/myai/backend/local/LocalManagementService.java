package kr.ac.myai.backend.local;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.service.ExtractionImportService;
import kr.ac.myai.backend.service.HumanHandoffImportService;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.nio.file.Path;
import java.util.HashSet;
import java.util.Set;
import java.util.function.Function;

@Service
@Profile("local-api")
public class LocalManagementService {
    private static final String UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
    private final ReviewedImportReader json;
    private final PublicationCommandReader commands;
    private final ReviewedImportService imports;
    private final ExtractionImportService extractions;
    private final HumanHandoffImportService handoffs;
    private final PublicationService publication;
    private final LocalRequestStore requests;
    private final Path sourceRoot, extractionRoot, handoffRoot;
    private final String actor;

    public LocalManagementService(ReviewedImportReader json, PublicationCommandReader commands,
                                  ReviewedImportService imports, ExtractionImportService extractions,
                                  HumanHandoffImportService handoffs, PublicationService publication,
                                  LocalRequestStore requests, Environment environment) {
        this.json = json; this.commands = commands; this.imports = imports; this.extractions = extractions;
        this.handoffs = handoffs; this.publication = publication; this.requests = requests;
        sourceRoot = Path.of(environment.getRequiredProperty("myai.local-api.source-root"));
        extractionRoot = Path.of(environment.getRequiredProperty("myai.local-api.extraction-root"));
        handoffRoot = Path.of(environment.getRequiredProperty("myai.local-api.handoff-root"));
        actor = environment.getRequiredProperty("myai.local-api.actor");
    }

    public record Result(String schemaVersion, String requestSha256, Object data) {}

    public Result documents(byte[] body) {
        return execute(body, input -> {
            check(schema(input).equals("source-import-v1"), "schema_version");
            var batch = json.read(body, sourceRoot);
            requests.retain(body);
            return imports.importBatch(batch, actor);
        });
    }

    public Result extraction(byte[] body) {
        return execute(body, input -> {
            var fields = new HashSet<String>(); input.fieldNames().forEachRemaining(fields::add);
            check(schema(input).equals("extraction-import-request-v1")
                    && fields.equals(Set.of("schema_version", "run_id", "expected_input_hash")), "schema_version");
            check(input.path("run_id").isTextual() && input.path("run_id").textValue().matches(UUID), "run_id");
            check(input.path("expected_input_hash").isTextual()
                    && input.path("expected_input_hash").textValue().matches("[0-9a-f]{64}"), "expected_input_hash");
            requests.retain(body);
            return extractions.importRun(input.path("run_id").textValue(), extractionRoot, actor,
                    input.path("expected_input_hash").textValue());
        });
    }

    public Result review(String eventId, byte[] body) {
        return execute(body, input -> {
            check(eventId != null && eventId.matches(UUID), "event_id");
            if (schema(input).equals("publication-command-v1")) {
                var command = commands.read(body);
                check(command instanceof PublicationCommand.Decision, "action");
                var decision = (PublicationCommand.Decision) command;
                check(eventId.equals(decision.eventId().toString()), "event_id");
                requests.retain(body);
                return publication.execute(command, sourceRoot, actor);
            }
            return reviewed(input, body, eventId);
        });
    }

    public Result reviews(byte[] body) {
        return execute(body, input -> reviewed(input, body, null));
    }

    private Object reviewed(JsonNode input, byte[] body, String eventId) {
        if (schema(input).equals("reviewed-import-v1")) {
            var batch = json.read(body, sourceRoot);
            check(eventId == null || batch.events().size() == 1 && eventId.equals(batch.events().getFirst().id()), "event_id");
            requests.retain(body);
            return imports.importBatch(batch, actor);
        }
        check(schema(input).equals("human-handoff-import-v1"), "schema_version");
        var revisions = input.path("revisions");
        check(eventId == null || revisions.isArray() && revisions.size() == 1
                && revisions.get(0).path("event_id").isTextual()
                && eventId.equals(revisions.get(0).path("event_id").textValue()), "event_id");
        return handoffs.importFile(requests.retain(body), sourceRoot, handoffRoot, actor);
    }

    public Result publish(byte[] body) {
        return execute(body, input -> {
            check(schema(input).equals("publication-command-v1"), "schema_version");
            var command = commands.read(body);
            check(!(command instanceof PublicationCommand.Decision), "action");
            if (!command.action().equals("preview")) requests.retain(body);
            return publication.execute(command, sourceRoot, actor);
        });
    }

    private Result execute(byte[] body, Function<JsonNode, Object> operation) {
        try {
            check(body != null && body.length > 0 && body.length <= 8 * 1024 * 1024, "body");
            JsonNode input = json.parseJson(body);
            check(input != null && input.isObject(), "body");
            Object result = operation.apply(input);
            return new Result("local-management-result-v1", ReviewedImportReader.sha256(body), result);
        } catch (ImportException error) {
            throw translated(error.code(), true);
        } catch (PublicationException error) {
            throw translated(error.code(), true);
        } catch (ExtractionException error) {
            throw translated(error.code(), error.retryable());
        }
    }

    private ApiException translated(String code, boolean retryable) {
        HttpStatus status = switch (code) {
            case "IMPORT_VALIDATION_ERROR", "PUBLICATION_VALIDATION_ERROR", "EXTRACTION_VALIDATION_ERROR",
                    "EXTRACTION_ARCHIVE_INVALID" -> HttpStatus.UNPROCESSABLE_ENTITY;
            case "PUBLICATION_NOT_FOUND" -> HttpStatus.NOT_FOUND;
            case "IMPORT_CONFLICT", "PUBLICATION_CONFLICT", "EXTRACTION_CONFLICT" -> HttpStatus.CONFLICT;
            case "IMPORT_DATABASE_UNAVAILABLE", "PUBLICATION_DATABASE_UNAVAILABLE", "EXTRACTION_DATABASE_UNAVAILABLE",
                    "EXTRACTION_RUNTIME_UNAVAILABLE" -> HttpStatus.SERVICE_UNAVAILABLE;
            case "EXTRACTION_IO_ERROR", "EXTRACTION_PROTOCOL_ERROR", "EXTRACTION_INTERNAL_ERROR",
                    "IMPORT_INTERNAL_ERROR", "PUBLICATION_INTERNAL_ERROR" -> HttpStatus.INTERNAL_SERVER_ERROR;
            default -> null;
        };
        if (status == null) return new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "LOCAL_API_INTERNAL_ERROR",
                "로컬 관리 작업을 완료하지 못했습니다.", null);
        return new ApiException(status, code, "로컬 관리 요청을 처리하지 못했습니다. 입력·기록·실행 상태를 확인해 주세요.",
                null, status == HttpStatus.SERVICE_UNAVAILABLE && retryable);
    }

    private String schema(JsonNode input) {
        check(input.path("schema_version").isTextual(), "schema_version");
        return input.path("schema_version").textValue();
    }

    private void check(boolean condition, String field) {
        if (!condition) throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "LOCAL_API_VALIDATION_ERROR",
                "로컬 관리 요청의 형식·필수 값·사건 대응을 확인해 주세요.", field);
    }
}
