package kr.ac.myai.backend.review;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.publication.PublicationException;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.ExitCodeGenerator;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;

import java.nio.file.Path;
import java.util.Set;
import java.util.UUID;

@Component
@Profile("local-review-report")
public class LocalReviewReportCommand implements ApplicationRunner, ExitCodeGenerator {
    private static final Set<String> OPTIONS = Set.of("myai.report.document-version-id", "myai.report.source-root", "myai.report.directory", "myai.report.preview-file");
    private final ReviewReportService service;
    private final ReviewReportWriter writer;
    private final Environment environment;
    private final ObjectMapper mapper;
    private int exitCode;

    public LocalReviewReportCommand(ReviewReportService service, ReviewReportWriter writer, Environment environment, ObjectMapper mapper) {
        this.service = service; this.writer = writer; this.environment = environment; this.mapper = mapper;
    }

    @Override public void run(ApplicationArguments args) {
        try {
            if (!args.getNonOptionArgs().isEmpty()) throw new IllegalArgumentException();
            for (String option : args.getOptionNames()) {
                if (!OPTIONS.contains(option) && !option.startsWith("spring.") && !option.startsWith("logging.")
                        && !option.startsWith("app.calculation.") && !option.startsWith("app.extraction.")) throw new IllegalArgumentException();
                if (args.getOptionValues(option) == null || args.getOptionValues(option).size() != 1) throw new IllegalArgumentException();
            }
            String id = required("myai.report.document-version-id");
            if (!id.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")) throw new IllegalArgumentException();
            Path root = Path.of(required("myai.report.source-root")), output = Path.of(required("myai.report.directory"));
            String preview = environment.getProperty("myai.report.preview-file");
            if (preview != null && (preview.isBlank() || preview.chars().anyMatch(Character::isISOControl))) throw new IllegalArgumentException();
            var report = service.build(UUID.fromString(id), root, preview == null ? null : Path.of(preview));
            var result = writer.write(report, root, output);
            var receipt = mapper.createObjectNode().put("status", "succeeded").put("format_version", "local-review-report-v1");
            receipt.set("result", mapper.valueToTree(result)); System.out.println(receipt);
        } catch (PublicationException ex) {
            String code = ex.code();
            exitCode = switch (code) {
                case "REPORT_VALIDATION_ERROR", "REPORT_NOT_FOUND", "REPORT_TOO_LARGE" -> 2;
                case "REPORT_FILE_CONFLICT" -> 3;
                case "REPORT_DATABASE_UNAVAILABLE" -> 4;
                case "REPORT_IO_ERROR" -> 5;
                default -> 1;
            };
            error(exitCode == 1 ? "REPORT_INTERNAL_ERROR" : code);
        } catch (IllegalArgumentException ex) { exitCode = 2; error("REPORT_VALIDATION_ERROR"); }
        catch (Exception ex) { exitCode = 1; error("REPORT_INTERNAL_ERROR"); }
    }

    private String required(String key) {
        String value = environment.getProperty(key);
        if (value == null || value.isBlank() || value.chars().anyMatch(Character::isISOControl)) throw new IllegalArgumentException();
        return value;
    }

    private void error(String code) {
        var output = mapper.createObjectNode().put("request_id", UUID.randomUUID().toString());
        var error = output.putObject("error").put("code", code).put("retryable", exitCode == 4 || exitCode == 5);
        error.put("message", switch (exitCode) {
            case 2 -> "보고서 설정·문서 ID·전체 크기를 확인해 주세요.";
            case 3 -> "출력 파일과 충돌합니다. 기존 파일을 보존했습니다.";
            case 4 -> "보고서 DB에 연결하지 못했습니다. 연결 상태를 확인해 주세요.";
            case 5 -> "private 출력 경로와 파일 권한을 확인해 주세요.";
            default -> "보고서를 만들지 못했습니다. 실행 환경을 확인해 주세요.";
        });
        error.putArray("field_errors"); System.out.println(output);
    }
    @Override public int getExitCode() { return exitCode; }
}
