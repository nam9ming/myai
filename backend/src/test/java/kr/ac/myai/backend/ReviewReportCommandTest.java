package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.review.LocalReviewReportCommand;
import kr.ac.myai.backend.review.ReviewReportService;
import kr.ac.myai.backend.review.ReviewReportWriter;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.DefaultApplicationArguments;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.mock.env.MockEnvironment;

import java.nio.file.Path;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@ExtendWith(OutputCaptureExtension.class)
class ReviewReportCommandTest {
    @TempDir Path root;
    final UUID id = UUID.fromString("10000000-0000-4000-8000-000000000007");
    final ObjectMapper mapper = new ObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    final ReviewReportService service = mock(ReviewReportService.class);
    final ReviewReportWriter writer = mock(ReviewReportWriter.class);

    @Test
    void printsOnlySafeReceiptAndForwardsOptionalPreview(CapturedOutput output) throws Exception {
        var report = mapper.createObjectNode().put("PRIVATE_SOURCE", "PRIVATE_RAW");
        Path preview = root.resolve("PRIVATE_PREVIEW.json");
        when(service.build(id, root, preview)).thenReturn(report);
        when(writer.write(report, root, root)).thenReturn(new ReviewReportWriter.Result(id.toString(), "review.html", "a".repeat(64), false));
        var env = environment().withProperty("myai.report.preview-file", preview.toString());
        var command = command(env); command.run(new DefaultApplicationArguments());
        assertThat(command.getExitCode()).isZero();
        var response = mapper.readTree(output.getOut());
        assertThat(response.path("result").path("document_version_id").asText()).isEqualTo(id.toString());
        assertThat(response.path("result").path("checksum").asText()).isEqualTo("a".repeat(64));
        assertThat(output.getOut()).doesNotContain("PRIVATE_", root.toString());
        verify(writer).write(report, root, root);
    }

    @Test
    void rejectsBadIdsMissingSettingsUnknownAndRepeatedArgsBeforeDatabase(CapturedOutput output) {
        for (String value : new String[]{"", "../PRIVATE_BAD", "10000000-0000-4000-8000-00000000000A"}) {
            var command = command(environment().withProperty("myai.report.document-version-id", value));
            command.run(new DefaultApplicationArguments()); assertThat(command.getExitCode()).isEqualTo(2);
        }
        for (String[] arguments : new String[][]{{"--myai.report.typo=PRIVATE"}, {"stray"}, {"--myai.report.directory=a", "--myai.report.directory=b"}}) {
            var command = command(environment()); command.run(new DefaultApplicationArguments(arguments)); assertThat(command.getExitCode()).isEqualTo(2);
        }
        var missing = command(new MockEnvironment()); missing.run(new DefaultApplicationArguments()); assertThat(missing.getExitCode()).isEqualTo(2);
        verifyNoInteractions(service, writer); assertThat(output.getOut()).doesNotContain("PRIVATE_BAD", "PRIVATE\"");
    }

    @Test
    void mapsFailuresAndNeverPrintsPrivateException(CapturedOutput output) throws Exception {
        String[] codes = {"REPORT_NOT_FOUND", "REPORT_TOO_LARGE", "REPORT_FILE_CONFLICT", "REPORT_DATABASE_UNAVAILABLE", "REPORT_IO_ERROR"};
        int[] exits = {2, 2, 3, 4, 5};
        for (int i = 0; i < codes.length; i++) {
            doThrow(new PublicationException(codes[i], "PRIVATE_CAUSE", "PRIVATE_FIELD")).when(service).build(id, root, null);
            var command = command(environment()); command.run(new DefaultApplicationArguments());
            assertThat(command.getExitCode()).isEqualTo(exits[i]);
        }
        doThrow(new IllegalStateException("PRIVATE_CAUSE")).when(service).build(id, root, null);
        var command = command(environment()); command.run(new DefaultApplicationArguments()); assertThat(command.getExitCode()).isEqualTo(1);
        assertThat(output.getOut()).doesNotContain("PRIVATE_CAUSE", "PRIVATE_FIELD", root.toString());
        verifyNoInteractions(writer);
    }

    MockEnvironment environment() { return new MockEnvironment().withProperty("myai.report.document-version-id", id.toString()).withProperty("myai.report.source-root", root.toString()).withProperty("myai.report.directory", root.toString()); }
    LocalReviewReportCommand command(MockEnvironment env) { return new LocalReviewReportCommand(service, writer, env, mapper); }
}
