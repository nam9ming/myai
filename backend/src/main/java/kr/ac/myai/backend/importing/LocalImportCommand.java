package kr.ac.myai.backend.importing;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.service.ReviewedImportService;
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
@Profile("local-import")
public class LocalImportCommand implements ApplicationRunner, ExitCodeGenerator {
    private final ReviewedImportReader reader;
    private final ReviewedImportService importer;
    private final Environment environment;
    private final ApplicationContext context;
    private final ObjectMapper mapper;
    private int exitCode;

    public LocalImportCommand(ReviewedImportReader reader, ReviewedImportService importer, Environment environment,
                              ApplicationContext context, ObjectMapper mapper) {
        this.reader = reader;
        this.importer = importer;
        this.environment = environment;
        this.context = context;
        this.mapper = mapper;
    }

    @Override
    public void run(ApplicationArguments args) {
        try {
            if (environment.matchesProfiles("local-publication")) {
                throw new ImportException("IMPORT_VALIDATION_ERROR", "local-import와 local-publication은 함께 실행할 수 없습니다.", "spring.profiles.active");
            }
            if (context instanceof WebApplicationContext) {
                throw new ImportException("IMPORT_VALIDATION_ERROR", "local-import는 웹 서버 없이 실행해야 합니다.", "spring.main.web-application-type");
            }
            var batch = reader.read(Path.of(required("myai.import.file")), Path.of(required("myai.import.source-root")));
            var result = importer.importBatch(batch, required("myai.import.actor"));
            ObjectNode output = mapper.createObjectNode().put("status", "succeeded");
            output.set("result", mapper.valueToTree(result));
            System.out.println(output);
        } catch (ImportException ex) {
            exitCode = switch (ex.code()) {
                case "IMPORT_VALIDATION_ERROR" -> 2;
                case "IMPORT_CONFLICT" -> 3;
                case "IMPORT_DATABASE_UNAVAILABLE" -> 4;
                default -> 1;
            };
            error(ex.code(), ex.getMessage(), ex.field(), exitCode == 4);
        } catch (IllegalArgumentException ex) {
            exitCode = 2;
            error("IMPORT_VALIDATION_ERROR", "import 파일·원문 디렉터리·담당자 설정을 확인해 주세요.", null, false);
        } catch (Exception ex) {
            exitCode = 1;
            error("IMPORT_INTERNAL_ERROR", "import를 완료하지 못했습니다. DB의 배치 상태와 실행 환경을 확인해 주세요.", null, false);
        }
    }

    private String required(String key) {
        String value = environment.getProperty(key);
        if (value == null || value.isBlank()) throw new ImportException("IMPORT_VALIDATION_ERROR", "필수 import 설정이 없습니다.", key);
        return value;
    }

    private void error(String code, String message, String field, boolean retryable) {
        ObjectNode output = mapper.createObjectNode().put("request_id", UUID.randomUUID().toString());
        var detail = output.putObject("error").put("code", code).put("message", message).put("retryable", retryable);
        var fields = detail.putArray("field_errors");
        if (field != null) fields.addObject().put("field", field).put("message", message);
        System.out.println(output);
    }

    @Override
    public int getExitCode() { return exitCode; }
}
