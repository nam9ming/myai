package kr.ac.myai.backend.publication;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.service.SnapshotExportService;
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
@Profile("local-export")
public class LocalSnapshotExportCommand implements ApplicationRunner, ExitCodeGenerator {
    private final SnapshotExportService exporter;
    private final Environment environment;
    private final ApplicationContext context;
    private final ObjectMapper mapper;
    private int exitCode;

    public LocalSnapshotExportCommand(SnapshotExportService exporter, Environment environment, ApplicationContext context, ObjectMapper mapper) {
        this.exporter = exporter; this.environment = environment; this.context = context; this.mapper = mapper;
    }

    @Override
    public void run(ApplicationArguments args) {
        try {
            if (context instanceof WebApplicationContext || environment.matchesProfiles("local-import", "local-publication", "local-extraction", "local-source-review")) {
                throw new PublicationException("EXPORT_VALIDATION_ERROR", "local-export는 HTTP 서버와 다른 로컬 명령 프로필 없이 실행해야 합니다.", "spring.profiles.active");
            }
            String id = required("myai.export.snapshot-id");
            if (!id.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")) throw new IllegalArgumentException();
            var result = exporter.export(UUID.fromString(id), Path.of(required("myai.export.directory")));
            var output = mapper.createObjectNode().put("status", "succeeded");
            output.set("result", mapper.valueToTree(result)); System.out.println(output);
        } catch (PublicationException ex) {
            exitCode = switch (ex.code()) {
                case "EXPORT_VALIDATION_ERROR", "EXPORT_NOT_FOUND", "EXPORT_INVALID_SNAPSHOT" -> 2;
                case "EXPORT_FILE_CONFLICT" -> 3;
                case "EXPORT_DATABASE_UNAVAILABLE" -> 4;
                case "EXPORT_IO_ERROR" -> 5;
                default -> 1;
            };
            error(ex.code(), ex.getMessage(), ex.field(), exitCode == 4 || exitCode == 5);
        } catch (IllegalArgumentException ex) {
            exitCode = 2; error("EXPORT_VALIDATION_ERROR", "snapshot ID와 출력 디렉터리 설정을 확인해 주세요.", null, false);
        } catch (Exception ex) {
            exitCode = 1; error("EXPORT_INTERNAL_ERROR", "내보내기를 완료하지 못했습니다. DB 공개본과 실행 환경을 확인해 주세요.", null, false);
        }
    }

    private String required(String key) {
        String value = environment.getProperty(key);
        if (value == null || value.isBlank()) throw new PublicationException("EXPORT_VALIDATION_ERROR", "필수 내보내기 설정이 없습니다.", key);
        return value;
    }

    private void error(String code, String message, String field, boolean retryable) {
        var output = mapper.createObjectNode().put("request_id", UUID.randomUUID().toString());
        var detail = output.putObject("error").put("code", code).put("message", message).put("retryable", retryable);
        var fields = detail.putArray("field_errors");
        if (field != null) fields.addObject().put("field", field).put("message", message);
        System.out.println(output);
    }

    @Override public int getExitCode() { return exitCode; }
}
