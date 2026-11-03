package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.config.LocalImportStartupGuard;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.context.support.GenericApplicationContext;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.web.context.support.GenericWebApplicationContext;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

class HumanHandoffStartupTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();

    @Test
    void coldDatabaseFailureReturnsOneSafeImportJsonFromActualJar() throws Exception {
        failed("IMPORT_DATABASE_UNAVAILABLE", 4, true);
    }

    @Test
    void nonDatabaseStartupFailureReturnsSafeInternalErrorFromActualJar() throws Exception {
        failed("IMPORT_INTERNAL_ERROR", 1, false, "--spring.datasource.driver-class-name=PRIVATE_DRIVER");
    }

    @ParameterizedTest
    @ValueSource(strings = {"public", "fixture", "local-publication", "local-export", "local-extraction"})
    void mixedProfilesReturnImportValidationBeforeDatabaseFromActualJar(String profile) throws Exception {
        var error = failed("IMPORT_VALIDATION_ERROR", 2, false, "--spring.profiles.active=local-import," + profile);
        assertThat(error.path("field_errors").get(0).path("field").asText()).isEqualTo("spring.profiles.active");
    }

    @ParameterizedTest
    @ValueSource(strings = {"servlet", "reactive"})
    void forcedWebReturnsImportValidationBeforeDatabaseFromActualJar(String type) throws Exception {
        var error = failed("IMPORT_VALIDATION_ERROR", 2, false, "--spring.main.web-application-type=" + type);
        assertThat(error.path("field_errors").get(0).path("field").asText()).isEqualTo("spring.main.web-application-type");
    }

    @Test
    void earlyGuardRejectsWebAndMixedProfilesBeforeRefresh() {
        var guard = new LocalImportStartupGuard();
        try (var web = new GenericWebApplicationContext()) {
            web.getEnvironment().setActiveProfiles("local-import");
            assertThatThrownBy(() -> guard.initialize(web)).isInstanceOf(LocalImportStartupGuard.ModeException.class);
            assertThat(web.isActive()).isFalse();
        }
        for (String profile : List.of("public", "fixture", "local-publication", "local-export", "local-extraction")) {
            try (var context = new GenericApplicationContext()) {
                context.getEnvironment().setActiveProfiles("local-import", profile);
                assertThatThrownBy(() -> guard.initialize(context)).isInstanceOf(LocalImportStartupGuard.ModeException.class);
                assertThat(context.isActive()).isFalse();
            }
        }
        try (var context = new GenericApplicationContext()) {
            context.setEnvironment(new MockEnvironment().withProperty("spring.main.web-application-type", "servlet"));
            context.getEnvironment().setActiveProfiles("local-import");
            assertThatThrownBy(() -> guard.initialize(context)).isInstanceOf(LocalImportStartupGuard.ModeException.class);
        }
    }

    @Test
    void earlyGuardAllowsImportWithoutWebAndLeavesOtherProfilesAlone() {
        var guard = new LocalImportStartupGuard();
        try (var context = new GenericApplicationContext()) {
            context.getEnvironment().setActiveProfiles("local-import");
            assertThatNoException().isThrownBy(() -> guard.initialize(context));
        }
        try (var web = new GenericWebApplicationContext()) {
            web.getEnvironment().setActiveProfiles("fixture");
            assertThatNoException().isThrownBy(() -> guard.initialize(web));
        }
    }

    private JsonNode failed(String code, int exit, boolean retryable, String... settings) throws Exception {
        var command = new ArrayList<>(List.of(Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                "-jar", "build/libs/myai-backend-0.1.0.jar", "--spring.profiles.active=local-import",
                "--spring.datasource.url=jdbc:mysql://127.0.0.1:1/unavailable?connectTimeout=500&socketTimeout=500",
                "--spring.datasource.username=PRIVATE_USER", "--spring.datasource.password=PRIVATE_PASSWORD",
                "--spring.datasource.hikari.connection-timeout=1000"));
        command.addAll(List.of(settings));
        var process = new ProcessBuilder(command).redirectError(root.resolve("startup.stderr").toFile()).start();
        boolean ended = process.waitFor(20, TimeUnit.SECONDS);
        if (!ended) process.destroyForcibly();
        assertThat(ended).isTrue();
        String stdout = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        assertThat(process.exitValue()).isEqualTo(exit);
        assertThat(stdout.lines().count()).isEqualTo(1);
        assertThat(stdout).doesNotContain("PRIVATE_", "jdbc:mysql");
        var result = mapper.readTree(stdout);
        assertThat(UUID.fromString(result.path("request_id").asText())).isNotNull();
        var error = result.path("error");
        assertThat(error.path("code").asText()).isEqualTo(code);
        assertThat(error.path("retryable").asBoolean()).isEqualTo(retryable);
        return error;
    }
}
