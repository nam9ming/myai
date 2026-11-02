package kr.ac.myai.backend.extraction;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.service.ExtractionImportService;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.ExitCodeGenerator;
import org.springframework.context.ApplicationContext;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;
import org.springframework.web.context.WebApplicationContext;

import java.nio.file.Path;
import java.util.UUID;

@Component
@Profile("local-extraction")
public class LocalExtractionCommand implements ApplicationRunner, ExitCodeGenerator {
    private final ExtractionImportService importer;
    private final Environment environment;
    private final ApplicationContext context;
    private final ObjectMapper mapper;
    private int exitCode;

    public LocalExtractionCommand(ExtractionImportService importer, Environment environment, ApplicationContext context, ObjectMapper mapper) {
        this.importer = importer; this.environment = environment; this.context = context; this.mapper = mapper;
    }

    @Override
    public void run(ApplicationArguments args) {
        try {
            if (context instanceof WebApplicationContext || environment.matchesProfiles("fixture", "public", "local-import", "local-publication", "local-export")) {
                throw new ExtractionException("EXTRACTION_VALIDATION_ERROR", "spring.profiles.active", false);
            }
            String id = required("myai.extraction.run-id");
            if (!id.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")) throw new IllegalArgumentException();
            Path root = Path.of(required("myai.extraction.archive-root"));
            if (!root.isAbsolute()) throw new IllegalArgumentException();
            String actor = required("myai.extraction.actor"); ExtractionImportService.validateActor(actor);
            var result = importer.importRun(id, root, actor);
            var output = mapper.createObjectNode().put("status", "succeeded");
            output.set("result", mapper.valueToTree(result)); System.out.println(output);
        } catch (ExtractionException ex) {
            exitCode = switch (ex.code()) {
                case "EXTRACTION_VALIDATION_ERROR" -> 2;
                case "EXTRACTION_CONFLICT", "EXTRACTION_ARCHIVE_INVALID" -> 3;
                case "EXTRACTION_DATABASE_UNAVAILABLE", "EXTRACTION_RUNTIME_UNAVAILABLE" -> 4;
                case "EXTRACTION_IO_ERROR" -> 5;
                default -> 1;
            };
            error(ex.code(), ex.getMessage(), ex.field(), ex.retryable());
        } catch (IllegalArgumentException ex) {
            exitCode = 2; error("EXTRACTION_VALIDATION_ERROR", "실행 UUID·비공개 archive 절대 경로·담당자 설정을 확인해 주세요.", null, false);
        } catch (Exception ex) {
            exitCode = 1; error("EXTRACTION_INTERNAL_ERROR", "AI 실행 기록을 등록하지 못했습니다. 기존 원본은 보존됩니다.", null, false);
        }
    }

    private String required(String key) {
        String value = environment.getProperty(key);
        if (value == null || value.isBlank()) throw new ExtractionException("EXTRACTION_VALIDATION_ERROR", key, false);
        return value;
    }

    private void error(String code, String message, String field, boolean retryable) {
        var output = mapper.createObjectNode().put("request_id", UUID.randomUUID().toString());
        var error = output.putObject("error").put("code", code).put("message", message).put("retryable", retryable);
        var fields = error.putArray("field_errors");
        if (field != null) fields.addObject().put("field", field).put("message", message);
        System.out.println(output);
    }

    @Override public int getExitCode() { return exitCode; }
}
