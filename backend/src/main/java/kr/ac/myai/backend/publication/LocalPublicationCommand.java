package kr.ac.myai.backend.publication;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.service.PublicationService;
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
@Profile("local-publication")
public class LocalPublicationCommand implements ApplicationRunner, ExitCodeGenerator {
    private final PublicationCommandReader reader;
    private final PublicationService publication;
    private final Environment environment;
    private final ApplicationContext context;
    private final ObjectMapper mapper;
    private int exitCode;

    public LocalPublicationCommand(PublicationCommandReader reader, PublicationService publication, Environment environment,
                                    ApplicationContext context, ObjectMapper mapper) {
        this.reader = reader; this.publication = publication; this.environment = environment; this.context = context; this.mapper = mapper;
    }

    @Override
    public void run(ApplicationArguments args) {
        try {
            if (context instanceof WebApplicationContext || environment.matchesProfiles("local-import")) {
                throw new PublicationException("PUBLICATION_VALIDATION_ERROR", "local-publication은 HTTP 서버와 다른 로컬 명령 프로필 없이 실행해야 합니다.", "spring.profiles.active");
            }
            PublicationCommand command = reader.read(Path.of(required("myai.publication.file")));
            boolean needsSource = command.action().equals("approve") || command.action().equals("publish") || command.action().equals("preview");
            Path root = needsSource ? Path.of(required("myai.publication.source-root")) : null;
            var result = publication.execute(command, root, required("myai.publication.actor"));
            ObjectNode output = mapper.createObjectNode().put("status", "succeeded");
            output.set("result", mapper.valueToTree(result));
            System.out.println(output);
        } catch (PublicationException ex) {
            exitCode = switch (ex.code()) {
                case "PUBLICATION_VALIDATION_ERROR", "PUBLICATION_NOT_FOUND" -> 2;
                case "PUBLICATION_CONFLICT" -> 3;
                case "PUBLICATION_DATABASE_UNAVAILABLE" -> 4;
                default -> 1;
            };
            error(ex.code(), ex.getMessage(), ex.field(), exitCode == 4);
        } catch (IllegalArgumentException ex) {
            exitCode = 2;
            error("PUBLICATION_VALIDATION_ERROR", "파일 경로와 실행 설정을 확인해 주세요.", null, false);
        } catch (Exception ex) {
            exitCode = 1;
            error("PUBLICATION_INTERNAL_ERROR", "승인·공개 작업을 완료하지 못했습니다. DB 상태와 실행 환경을 확인해 주세요.", null, false);
        }
    }

    private String required(String key) {
        String value = environment.getProperty(key);
        if (value == null || value.isBlank()) throw new PublicationException("PUBLICATION_VALIDATION_ERROR", "필수 로컬 실행 설정이 없습니다.", key);
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
