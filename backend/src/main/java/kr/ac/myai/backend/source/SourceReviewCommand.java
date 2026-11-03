package kr.ac.myai.backend.source;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.service.SourceReviewService;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.ExitCodeGenerator;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

import java.nio.file.Path;
import java.util.UUID;

@Component
@Profile("local-source-review")
public class SourceReviewCommand implements ApplicationRunner, ExitCodeGenerator {
    private final SourceReviewService reviews;
    private final Environment environment;
    private final ObjectMapper mapper;
    private int exitCode;

    public SourceReviewCommand(SourceReviewService reviews, Environment environment, ObjectMapper mapper) {
        this.reviews = reviews; this.environment = environment; this.mapper = mapper;
    }

    @Override
    public void run(ApplicationArguments args) {
        try {
            String source = environment.getProperty("myai.source-review.source-root");
            var result = reviews.review(Path.of(required("myai.source-review.file")),
                    source == null || source.isBlank() ? null : Path.of(source), required("myai.source-review.actor"));
            var output = mapper.createObjectNode().put("status", "succeeded");
            output.set("result", mapper.valueToTree(result));
            System.out.println(output);
        } catch (SourceReviewException ex) {
            exitCode = switch (ex.code()) {
                case "SOURCE_REVIEW_VALIDATION_ERROR" -> 2;
                case "SOURCE_REVIEW_CONFLICT" -> 3;
                case "SOURCE_REVIEW_DATABASE_UNAVAILABLE" -> 4;
                default -> 1;
            };
            error(ex.code(), ex.getMessage(), ex.field(), ex.retryable());
        } catch (IllegalArgumentException ex) {
            exitCode = 2;
            error("SOURCE_REVIEW_VALIDATION_ERROR", "요청 파일·원문 디렉터리·담당자 설정을 확인해 주세요.", null, false);
        } catch (Exception ex) {
            exitCode = 1;
            error("SOURCE_REVIEW_INTERNAL_ERROR", "원문 검토 이력을 저장하지 못했습니다. 실행 환경을 확인해 주세요.", null, false);
        }
    }

    private String required(String name) {
        String value = environment.getProperty(name);
        if (value == null || value.isBlank()) throw new SourceReviewException("SOURCE_REVIEW_VALIDATION_ERROR", name);
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

