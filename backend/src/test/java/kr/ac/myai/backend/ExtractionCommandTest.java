package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import kr.ac.myai.backend.config.LocalExtractionStartupGuard;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.extraction.LocalExtractionCommand;
import kr.ac.myai.backend.service.ExtractionImportService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.DefaultApplicationArguments;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.context.ApplicationContext;
import org.springframework.context.support.GenericApplicationContext;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.web.context.WebApplicationContext;
import org.springframework.web.context.support.GenericWebApplicationContext;

import java.nio.file.Path;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@ExtendWith(OutputCaptureExtension.class)
class ExtractionCommandTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    final ExtractionImportService importer = mock(ExtractionImportService.class);
    final String id = UUID.randomUUID().toString();

    @Test
    void returnsOneSafeSnakeCaseResultEvenForRegisteredFailedRun(CapturedOutput output) throws Exception {
        when(importer.importRun(id, root, "synthetic-registrant")).thenReturn(new ExtractionImportService.Result(
                id, id, "failed", 1, "synthetic", "1".repeat(64), "2".repeat(64), false, true));
        var command = command(environment(), mock(ApplicationContext.class)); command.run(new DefaultApplicationArguments());
        assertThat(command.getExitCode()).isZero(); JsonNode result = result(output);
        assertThat(result.path("status").asText()).isEqualTo("succeeded");
        assertThat(result.path("result").path("status").asText()).isEqualTo("failed");
        assertThat(result.path("result").path("review_required").asBoolean()).isTrue();
        assertThat(result.path("result").path("run_id").asText()).isEqualTo(id);
        assertThat(output.getOut().lines().filter(x -> x.startsWith("{")).count()).isEqualTo(1);
        assertThat(output.getOut()).doesNotContain(root.toString(), "metadata_json", "raw_ref");
    }

    @Test
    void refusesMissingInvalidWebAndMixedSettingsBeforeWork(CapturedOutput output) throws Exception {
        for (String value : List.of("", "../PRIVATE_VALUE", id.toUpperCase())) {
            var command = command(environment().withProperty("myai.extraction.run-id", value), mock(ApplicationContext.class));
            command.run(new DefaultApplicationArguments()); assertThat(command.getExitCode()).isEqualTo(2);
        }
        for (String key : List.of("myai.extraction.archive-root", "myai.extraction.actor")) {
            var command = command(environment().withProperty(key, ""), mock(ApplicationContext.class));
            command.run(new DefaultApplicationArguments()); assertThat(command.getExitCode()).isEqualTo(2);
        }
        var web = command(environment(), mock(WebApplicationContext.class)); web.run(new DefaultApplicationArguments()); assertThat(web.getExitCode()).isEqualTo(2);
        for (String profile : List.of("local-import", "local-publication", "local-export", "public", "fixture")) {
            var env = environment(); env.setActiveProfiles("local-extraction", profile);
            var command = command(env, mock(ApplicationContext.class)); command.run(new DefaultApplicationArguments());
            assertThat(command.getExitCode()).isEqualTo(2);
        }
        verifyNoInteractions(importer); assertThat(output.getOut()).doesNotContain("PRIVATE_VALUE");
    }

    @Test
    void mapsSafeCodesWithoutCausesPathsOrUnknownErrorDetails(CapturedOutput output) throws Exception {
        String[] codes = {"EXTRACTION_VALIDATION_ERROR", "EXTRACTION_CONFLICT", "EXTRACTION_ARCHIVE_INVALID", "EXTRACTION_DATABASE_UNAVAILABLE", "EXTRACTION_RUNTIME_UNAVAILABLE", "EXTRACTION_IO_ERROR", "EXTRACTION_PROTOCOL_ERROR"};
        int[] exits = {2, 3, 3, 4, 4, 5, 1};
        for (int i = 0; i < codes.length; i++) {
            doThrow(new ExtractionException(codes[i], null, i >= 3 && i <= 5)).when(importer).importRun(id, root, "synthetic-registrant");
            var command = command(environment(), mock(ApplicationContext.class)); command.run(new DefaultApplicationArguments());
            assertThat(command.getExitCode()).isEqualTo(exits[i]); assertThat(result(output).path("error").path("code").asText()).isEqualTo(codes[i]);
        }
        doThrow(new IllegalStateException("PRIVATE_VALUE " + root)).when(importer).importRun(id, root, "synthetic-registrant");
        var command = command(environment(), mock(ApplicationContext.class)); command.run(new DefaultApplicationArguments());
        assertThat(command.getExitCode()).isEqualTo(1); assertThat(output.getOut()).doesNotContain("PRIVATE_VALUE", root.toString());
    }

    @Test
    void coldDatabaseFailureReturnsOneSafeJsonFromActualJar() throws Exception {
        Path stderr = root.resolve("startup.stderr");
        var process = new ProcessBuilder(Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                "-jar", "build/libs/myai-backend-0.1.0.jar", "--spring.profiles.active=local-extraction",
                "--spring.datasource.url=jdbc:mysql://127.0.0.1:1/unavailable?connectTimeout=500&socketTimeout=500",
                "--spring.datasource.username=PRIVATE_USER", "--spring.datasource.password=PRIVATE_PASSWORD",
                "--spring.datasource.hikari.connection-timeout=1000").redirectError(stderr.toFile()).start();
        boolean ended = process.waitFor(20, java.util.concurrent.TimeUnit.SECONDS);
        if (!ended) process.destroyForcibly();
        assertThat(ended).isTrue();
        String stdout = new String(process.getInputStream().readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        assertThat(process.exitValue()).isEqualTo(4);
        assertThat(stdout.lines().count()).isEqualTo(1); assertThat(stdout).doesNotContain("PRIVATE_", "jdbc:mysql");
        assertThat(mapper.readTree(stdout).path("error").path("code").asText()).isEqualTo("EXTRACTION_DATABASE_UNAVAILABLE");
    }

    @Test
    void earlyGuardRefusesWebAndMixedProfilesBeforeRefresh() {
        var guard = new LocalExtractionStartupGuard();
        try (var web = new GenericWebApplicationContext()) {
            web.getEnvironment().setActiveProfiles("local-extraction");
            assertThatThrownBy(() -> guard.initialize(web)).isInstanceOf(LocalExtractionStartupGuard.ModeException.class);
        }
        for (String profile : List.of("local-import", "local-publication", "local-export", "public", "fixture")) {
            try (var context = new GenericApplicationContext()) {
                var env = new MockEnvironment(); env.setActiveProfiles("local-extraction", profile); context.setEnvironment(env);
                assertThatThrownBy(() -> guard.initialize(context)).isInstanceOf(LocalExtractionStartupGuard.ModeException.class);
            }
        }
    }

    private MockEnvironment environment() {
        return new MockEnvironment().withProperty("myai.extraction.run-id", id).withProperty("myai.extraction.archive-root", root.toString())
                .withProperty("myai.extraction.actor", "synthetic-registrant");
    }
    private LocalExtractionCommand command(MockEnvironment env, ApplicationContext context) { return new LocalExtractionCommand(importer, env, context, mapper); }
    private JsonNode result(CapturedOutput output) throws Exception { return mapper.readTree(output.getOut().lines().filter(x -> x.startsWith("{")).reduce((a,b) -> b).orElseThrow()); }
}
