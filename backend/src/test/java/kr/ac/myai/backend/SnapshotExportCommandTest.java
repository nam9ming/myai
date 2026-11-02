package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import kr.ac.myai.backend.publication.LocalSnapshotExportCommand;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.service.SnapshotExportService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.DefaultApplicationArguments;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.context.ApplicationContext;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.web.context.WebApplicationContext;

import java.nio.file.Path;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@ExtendWith(OutputCaptureExtension.class)
class SnapshotExportCommandTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    final SnapshotExportService exporter = mock(SnapshotExportService.class);
    final UUID id = UUID.fromString("10000000-0000-4000-8000-000000000007");

    @Test
    void returnsOneSnakeCaseJsonResult(CapturedOutput output) throws Exception {
        when(exporter.export(id, root)).thenReturn(new SnapshotExportService.Result(id.toString(), "0".repeat(64), "snapshot.json", true));
        var command = command(environment(), mock(ApplicationContext.class)); command.run(new DefaultApplicationArguments());
        assertThat(command.getExitCode()).isZero(); var result = result(output);
        assertThat(result.path("status").asText()).isEqualTo("succeeded");
        assertThat(result.path("result").path("snapshot_id").asText()).isEqualTo(id.toString());
        assertThat(result.path("result").path("already_exported").asBoolean()).isTrue();
        assertThat(output.getOut().lines().filter(line -> line.startsWith("{")).count()).isEqualTo(1);
    }

    @Test
    void rejectsInvalidMissingAndNonCanonicalIdsBeforeDatabase(CapturedOutput output) throws Exception {
        for (String value : List.of("", "../PRIVATE_PATH", "10000000-0000-4000-8000-00000000000A")) {
            var env = environment().withProperty("myai.export.snapshot-id", value);
            var command = command(env, mock(ApplicationContext.class)); command.run(new DefaultApplicationArguments());
            assertThat(command.getExitCode()).isEqualTo(2); assertThat(result(output).path("error").path("retryable").asBoolean()).isFalse();
        }
        var missingDirectory = command(environment().withProperty("myai.export.directory", ""), mock(ApplicationContext.class));
        missingDirectory.run(new DefaultApplicationArguments()); assertThat(missingDirectory.getExitCode()).isEqualTo(2);
        var env = new MockEnvironment();
        var command = command(env, mock(ApplicationContext.class)); command.run(new DefaultApplicationArguments());
        assertThat(command.getExitCode()).isEqualTo(2); verifyNoInteractions(exporter);
        assertThat(output.getOut()).doesNotContain("PRIVATE_PATH");
    }

    @Test
    void refusesWebAndEveryOtherLocalProfileBeforeExport(CapturedOutput output) throws Exception {
        var command = command(environment(), mock(WebApplicationContext.class)); command.run(new DefaultApplicationArguments());
        assertThat(command.getExitCode()).isEqualTo(2);
        for (String profile : List.of("local-import", "local-publication")) {
            var env = environment(); env.setActiveProfiles("local-export", profile);
            command = command(env, mock(ApplicationContext.class)); command.run(new DefaultApplicationArguments());
            assertThat(command.getExitCode()).isEqualTo(2);
        }
        verifyNoInteractions(exporter); assertThat(result(output).path("error").path("retryable").asBoolean()).isFalse();
    }

    @Test
    void mapsSafeFailureCodesWithoutPathOrPrivateCause(CapturedOutput output) throws Exception {
        var codes = List.of("EXPORT_NOT_FOUND", "EXPORT_INVALID_SNAPSHOT", "EXPORT_FILE_CONFLICT", "EXPORT_DATABASE_UNAVAILABLE", "EXPORT_IO_ERROR");
        int[] exits = {2, 2, 3, 4, 5};
        for (int i = 0; i < codes.size(); i++) {
            doThrow(new PublicationException(codes.get(i), "안전한 안내", null)).when(exporter).export(id, root);
            var command = command(environment(), mock(ApplicationContext.class)); command.run(new DefaultApplicationArguments());
            assertThat(command.getExitCode()).isEqualTo(exits[i]); var error = result(output);
            assertThat(error.path("error").path("code").asText()).isEqualTo(codes.get(i));
            assertThat(error.path("error").path("retryable").asBoolean()).isEqualTo(i >= 3);
            assertThat(UUID.fromString(error.path("request_id").asText())).isNotNull();
        }
        doThrow(new IllegalStateException("PRIVATE_CAUSE " + root)).when(exporter).export(id, root);
        var command = command(environment(), mock(ApplicationContext.class)); command.run(new DefaultApplicationArguments());
        assertThat(command.getExitCode()).isEqualTo(1); assertThat(result(output).path("error").path("retryable").asBoolean()).isFalse();
        assertThat(output.getOut()).doesNotContain("PRIVATE_CAUSE", root.toString());
    }

    private MockEnvironment environment() { return new MockEnvironment().withProperty("myai.export.snapshot-id", id.toString()).withProperty("myai.export.directory", root.toString()); }
    private LocalSnapshotExportCommand command(MockEnvironment env, ApplicationContext context) { return new LocalSnapshotExportCommand(exporter, env, context, mapper); }
    private JsonNode result(CapturedOutput output) throws Exception { return mapper.readTree(output.getOut().lines().filter(line -> line.startsWith("{")).reduce((a, b) -> b).orElseThrow()); }
}
