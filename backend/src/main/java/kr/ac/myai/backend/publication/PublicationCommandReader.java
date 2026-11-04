package kr.ac.myai.backend.publication;

import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.importing.ImportException;
import jakarta.validation.Validator;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.MapperFeature;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.springframework.stereotype.Component;

import java.nio.file.Path;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.HashSet;
import java.util.Set;

@Component
public class PublicationCommandReader {
    private final ReviewedImportReader json;
    private final Validator validator;
    private final JsonMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule())
            .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
            .disable(MapperFeature.ALLOW_COERCION_OF_SCALARS, MapperFeature.ACCEPT_CASE_INSENSITIVE_ENUMS)
            .disable(DeserializationFeature.ACCEPT_FLOAT_AS_INT)
            .enable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, DeserializationFeature.FAIL_ON_MISSING_CREATOR_PROPERTIES,
                    DeserializationFeature.FAIL_ON_NULL_FOR_PRIMITIVES).build();

    public PublicationCommandReader(ReviewedImportReader json, Validator validator) {
        this.json = json;
        this.validator = validator;
    }

    public PublicationCommand read(Path file) {
        try {
            return read(json.readBounded(file, "file"));
        } catch (ImportException | java.io.IOException | IllegalArgumentException ex) { throw invalid("file"); }
    }

    public PublicationCommand read(byte[] content) {
        try {
            JsonNode input = json.parseJson(content);
            check(input.isObject(), "file");
            check(input.path("schema_version").isTextual() && input.path("schema_version").asText().equals("publication-command-v1"), "schema_version");
            validateScalars(input);
            Class<? extends PublicationCommand> type = switch (input.path("action").asText()) {
                case "approve", "reject" -> PublicationCommand.Decision.class;
                case "publish", "preview" -> PublicationCommand.Publish.class;
                case "rollback" -> PublicationCommand.Rollback.class;
                default -> throw invalid("action");
            };
            PublicationCommand command = mapper.treeToValue(input, type);
            var errors = validator.validate(command);
            if (!errors.isEmpty()) throw invalid(errors.iterator().next().getPropertyPath().toString());
            if (command instanceof PublicationCommand.Decision decision) {
                check(new HashSet<>(decision.evidenceIds()).size() == decision.evidenceIds().size(), "evidence_ids");
                check(decision.action().equals("reject") || !decision.evidenceIds().isEmpty(), "evidence_ids");
            } else if (command instanceof PublicationCommand.Publish publish) {
                context(publish.mode(), publish.caseId() == null);
                check(new HashSet<>(publish.revisionIds()).size() == publish.revisionIds().size(), "revision_ids");
                var pointIds = new HashSet<>();
                for (var point : publish.points()) {
                    check(pointIds.add(point.pointId()), "points.point_id");
                    check(point.areaId().equals(publish.area().areaId()), "points.area_id");
                    check(point.dictionaryVersion().equals(publish.dictionaryVersion()), "points.dictionary_version");
                    check(!point.checkedAt().isAfter(Instant.now()), "points.checked_at");
                }
                if (publish.mode().equals("current")) {
                    check(publish.anchorDate() == null && publish.referenceInstant() == null && publish.knowledgeCutoff() == null && publish.historyFidelity() == null, "mode");
                } else {
                    check(publish.anchorDate() != null && publish.referenceInstant() != null && publish.knowledgeCutoff() != null
                            && publish.historyFidelity() != null && Set.of("verified_snapshot", "reconstructed").contains(publish.historyFidelity()), "mode");
                    check(!publish.knowledgeCutoff().isAfter(publish.referenceInstant()) && !publish.referenceInstant().isAfter(Instant.now()), "knowledge_cutoff");
                    check(publish.referenceInstant().atZone(ZoneId.of("Asia/Seoul")).toLocalDate().equals(publish.anchorDate()), "anchor_date");
                }
            } else if (command instanceof PublicationCommand.Rollback rollback) context(rollback.mode(), rollback.caseId() == null);
            return command;
        } catch (PublicationException ex) { throw ex; }
        catch (ImportException | java.io.IOException | IllegalArgumentException | java.time.DateTimeException ex) { throw invalid("file"); }
    }

    private void context(String mode, boolean caseIsNull) {
        check(mode.equals("current") == caseIsNull, "case_id");
    }

    private void validateScalars(JsonNode node) {
        if (node.isArray()) { node.forEach(this::validateScalars); return; }
        if (!node.isObject()) return;
        node.properties().forEach(entry -> {
            String key = entry.getKey(); JsonNode value = entry.getValue();
            if (!value.isNull() && Set.of("event_id", "point_id", "area_id", "case_id", "snapshot_id").contains(key)) {
                check(value.isTextual() && value.asText().matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), key);
            }
            if (key.equals("revision_ids") && value.isArray()) for (JsonNode id : value) {
                check(id.isTextual() && id.asText().matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), key);
            }
            if (!value.isNull() && Set.of("checked_at", "reference_instant", "knowledge_cutoff").contains(key)) {
                check(value.isTextual() && value.asText().matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,6})?Z"), key);
                String text = value.asText();
                check(Integer.parseInt(text.substring(0, 4)) >= 1000, key);
                LocalDate.parse(text.substring(0, 10)); LocalTime.parse(text.substring(11, text.length() - 1));
            }
            if (key.equals("anchor_date") && !value.isNull()) {
                check(value.isTextual() && value.asText().matches("[0-9]{4}-[0-9]{2}-[0-9]{2}"), key);
            }
            validateScalars(value);
        });
    }

    private void check(boolean condition, String field) { if (!condition) throw invalid(field); }

    private PublicationException invalid(String field) {
        return new PublicationException("PUBLICATION_VALIDATION_ERROR", "승인·공개 명령의 형식·필수 값·문맥을 확인해 주세요.", field);
    }
}
