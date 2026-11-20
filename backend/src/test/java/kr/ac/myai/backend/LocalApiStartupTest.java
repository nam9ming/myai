package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.config.LocalApiStartupGuard;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.context.support.GenericApplicationContext;
import org.springframework.core.env.SystemEnvironmentPropertySource;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.web.context.support.GenericWebApplicationContext;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

class LocalApiStartupTest {
    private static final String TOKEN = "SYNTHETIC_LOCAL_TOKEN_0123456789_abcdef";
    @TempDir Path root;
    private final ObjectMapper mapper = new ObjectMapper();

    @ParameterizedTest
    @ValueSource(strings = {"TOKEN", "ACTOR", "SOURCE_ROOT", "EXTRACTION_ROOT", "HANDOFF_ROOT", "REQUEST_ROOT"})
    void missingEnvironmentIsRejectedBeforeDatabaseAndWeb(String name) throws Exception {
        var environment = validEnvironment();
        environment.remove("MYAI_LOCAL_API_" + name);
        rejected(environment);
    }

    @ParameterizedTest
    @ValueSource(strings = {"TOKEN", "ACTOR", "SOURCE_ROOT", "EXTRACTION_ROOT", "HANDOFF_ROOT", "REQUEST_ROOT"})
    void blankEnvironmentIsRejectedBeforeDatabaseAndWeb(String name) throws Exception {
        var environment = validEnvironment();
        environment.put("MYAI_LOCAL_API_" + name, "   ");
        rejected(environment);
    }

    @ParameterizedTest
    @ValueSource(strings = {"short", "SYNTHETIC_LOCAL_TOKEN_0123456789+abcdef", "SYNTHETIC_LOCAL_TOKEN_0123456789/abcdef", "SYNTHETIC_LOCAL_TOKEN_0123456789=abcdef"})
    void invalidBearerTokenIsRejectedBeforeDatabaseAndWeb(String token) throws Exception {
        var environment = validEnvironment();
        environment.put("MYAI_LOCAL_API_TOKEN", token);
        rejected(environment);
    }

    @Test
    void oversizedBearerTokenIsRejectedBeforeDatabaseAndWeb() throws Exception {
        var environment = validEnvironment();
        environment.put("MYAI_LOCAL_API_TOKEN", "S".repeat(129));
        rejected(environment);
    }

    @ParameterizedTest
    @ValueSource(strings = {"SOURCE_ROOT", "EXTRACTION_ROOT", "HANDOFF_ROOT", "REQUEST_ROOT"})
    void relativeRootIsRejectedBeforeDatabaseAndWeb(String name) throws Exception {
        var environment = validEnvironment();
        environment.put("MYAI_LOCAL_API_" + name, "SYNTHETIC_PRIVATE_PATH/relative");
        rejected(environment);
    }

    @ParameterizedTest
    @ValueSource(strings = {"public", "fixture", "local-import", "local-extraction", "local-publication", "local-export", "local-source-review", "local-review-report", "unknown"})
    void everyMixedProfileIsRejectedBeforeDatabaseAndWeb(String profile) throws Exception {
        rejected(validEnvironment(), "--spring.profiles.active=local-api," + profile);
    }

    @ParameterizedTest
    @CsvSource({"server.address,0.0.0.0", "server.address,localhost", "server.address,::1",
            "spring.main.web-application-type,none", "spring.main.web-application-type,reactive",
            "server.forward-headers-strategy,native", "server.forward-headers-strategy,framework",
            "server.port,-1", "server.port,65536"})
    void unsafeOverrideIsRejectedBeforeDatabaseAndWeb(String name, String value) throws Exception {
        rejected(validEnvironment(), "--" + name + "=" + value);
    }

    @Test
    void applicationPropertiesCannotReplaceMissingRequiredEnvironment() throws Exception {
        var environment = validEnvironment();
        environment.remove("MYAI_LOCAL_API_TOKEN");
        rejected(environment, "--myai.local-api.token=" + TOKEN);
    }

    @Test
    void propertyOverrideCannotReplaceValidatedEnvironmentToken() throws Exception {
        rejected(validEnvironment(), "--myai.local-api.token=short");
    }

    @ParameterizedTest
    @CsvSource({"spring.servlet.multipart.max-file-size,21MB", "spring.servlet.multipart.max-file-size,-1B",
            "spring.servlet.multipart.max-request-size,22MB", "spring.servlet.multipart.max-request-size,-1B",
            "spring.servlet.multipart.file-size-threshold,0B", "spring.servlet.multipart.file-size-threshold,20MB",
            "spring.servlet.multipart.file-size-threshold,2147483648B", "spring.servlet.multipart.enabled,false",
            "spring.servlet.multipart.resolve-lazily,false", "spring.servlet.multipart.max-request-size,not-size",
            "server.tomcat.max-http-form-post-size,2MB", "server.tomcat.max-http-form-post-size,22MB",
            "server.tomcat.max-http-form-post-size,-1B", "server.tomcat.max-http-form-post-size,not-size"})
    void earlyGuardRejectsUnsafeMultipartSettingsBeforeContextRefresh(String field, String value) throws Exception {
        try (var context = new GenericWebApplicationContext()) {
            var env = environment(validEnvironment()); env.setProperty(field, value); context.setEnvironment(env);
            assertThatThrownBy(() -> new LocalApiStartupGuard().initialize(context))
                    .isInstanceOfSatisfying(LocalApiStartupGuard.ModeException.class, error -> assertThat(error.field()).isEqualTo(field));
            assertThat(context.isActive()).isFalse();
        }
    }

    @Test
    void actualJarRefusesMultipartDiskSpoolingBeforeDatabaseStartup() throws Exception {
        rejected(validEnvironment(), "--spring.servlet.multipart.file-size-threshold=0B");
    }

    @Test
    void earlyGuardAllowsServletEphemeralPortAndTokenBoundaryLengths() throws Exception {
        for (String token : List.of("A".repeat(32), "Z".repeat(128))) {
            try (var context = new GenericWebApplicationContext()) {
                var values = validEnvironment();
                values.put("MYAI_LOCAL_API_TOKEN", token);
                context.setEnvironment(environment(values));
                assertThatNoException().isThrownBy(() -> new LocalApiStartupGuard().initialize(context));
                assertThat(context.isActive()).isFalse();
            }
        }
    }

    @Test
    void earlyGuardAllowsActorAt128CharacterLimit() throws Exception {
        try (var context = new GenericWebApplicationContext()) {
            var values = validEnvironment();
            values.put("MYAI_LOCAL_API_ACTOR", "A".repeat(128));
            context.setEnvironment(environment(values));
            assertThatNoException().isThrownBy(() -> new LocalApiStartupGuard().initialize(context));
            assertThat(context.isActive()).isFalse();
        }
    }

    @Test
    void earlyGuardRejects129CharacterActorBeforeContextRefresh() throws Exception {
        rejectsActor("A".repeat(129));
    }

    @ParameterizedTest
    @ValueSource(ints = {0, 9, 10, 13, 31, 127, 128, 159})
    void earlyGuardRejectsActorControlCharactersBeforeContextRefresh(int codePoint) throws Exception {
        rejectsActor("SYNTHETIC_PRIVATE_ACTOR" + (char) codePoint);
    }

    @Test
    void earlyGuardRejectsNonServletContextAndDefaultProfileMix() throws Exception {
        try (var context = new GenericApplicationContext()) {
            context.setEnvironment(environment(validEnvironment()));
            assertThatThrownBy(() -> new LocalApiStartupGuard().initialize(context))
                    .isInstanceOf(LocalApiStartupGuard.ModeException.class);
        }
        try (var context = new GenericWebApplicationContext()) {
            var environment = environment(validEnvironment());
            environment.setActiveProfiles();
            environment.setDefaultProfiles("local-api", "fixture");
            context.setEnvironment(environment);
            assertThatThrownBy(() -> new LocalApiStartupGuard().initialize(context))
                    .isInstanceOf(LocalApiStartupGuard.ModeException.class);
        }
    }

    @Test
    void guardLeavesExistingProfilesAlone() {
        for (String profile : List.of("public", "fixture", "local-import", "local-extraction", "local-publication",
                "local-export", "local-source-review", "local-review-report")) {
            try (var context = new GenericApplicationContext()) {
                context.getEnvironment().setActiveProfiles(profile);
                assertThatNoException().isThrownBy(() -> new LocalApiStartupGuard().initialize(context));
            }
        }
    }

    private void rejectsActor(String actor) throws Exception {
        try (var context = new GenericWebApplicationContext()) {
            var values = validEnvironment();
            values.put("MYAI_LOCAL_API_ACTOR", actor);
            context.setEnvironment(environment(values));
            assertThatThrownBy(() -> new LocalApiStartupGuard().initialize(context))
                    .isInstanceOfSatisfying(LocalApiStartupGuard.ModeException.class, error -> {
                        assertThat(error.field()).isEqualTo("myai.local-api.actor");
                        assertThat(error.getMessage()).doesNotContain(actor, root.toString(), TOKEN);
                    });
            assertThat(context.isActive()).isFalse();
        }
    }

    private Map<String, String> validEnvironment() throws Exception {
        var values = new HashMap<String, String>();
        values.put("MYAI_LOCAL_API_TOKEN", TOKEN);
        values.put("MYAI_LOCAL_API_ACTOR", "SYNTHETIC_PRIVATE_ACTOR");
        values.put("MYAI_LOCAL_API_PORT", "0");
        for (String name : List.of("SOURCE", "EXTRACTION", "HANDOFF", "REQUEST")) {
            values.put("MYAI_LOCAL_API_" + name + "_ROOT",
                    Files.createDirectories(root.resolve("SYNTHETIC_PRIVATE_PATH_" + name)).toString());
        }
        return values;
    }

    private MockEnvironment environment(Map<String, String> values) {
        var environment = new MockEnvironment().withProperty("spring.main.web-application-type", "servlet")
                .withProperty("server.address", "127.0.0.1").withProperty("server.port", "0")
                .withProperty("server.forward-headers-strategy", "NONE")
                .withProperty("server.tomcat.max-http-form-post-size", "21MB")
                .withProperty("spring.servlet.multipart.enabled", "true")
                .withProperty("spring.servlet.multipart.resolve-lazily", "true")
                .withProperty("spring.servlet.multipart.max-file-size", "20MB")
                .withProperty("spring.servlet.multipart.max-request-size", "21MB")
                .withProperty("spring.servlet.multipart.file-size-threshold", "21MB");
        environment.setActiveProfiles("local-api");
        environment.getPropertySources().addFirst(new SystemEnvironmentPropertySource("systemEnvironment", new HashMap<>(values)));
        for (String suffix : List.of("TOKEN", "ACTOR", "SOURCE_ROOT", "EXTRACTION_ROOT", "HANDOFF_ROOT", "REQUEST_ROOT")) {
            environment.withProperty("myai.local-api." + suffix.toLowerCase(java.util.Locale.ROOT).replace('_', '-'),
                    values.get("MYAI_LOCAL_API_" + suffix));
        }
        return environment;
    }

    private void rejected(Map<String, String> values, String... settings) throws Exception {
        var command = new ArrayList<>(List.of(Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                "-jar", "build/libs/myai-backend-0.1.0.jar", "--spring.profiles.active=local-api",
                "--spring.datasource.url=jdbc:mysql://127.0.0.1:1/SYNTHETIC_PRIVATE_DATABASE?connectTimeout=100&socketTimeout=100",
                "--spring.datasource.username=SYNTHETIC_PRIVATE_USER", "--spring.datasource.password=SYNTHETIC_PRIVATE_PASSWORD",
                "--spring.datasource.hikari.connection-timeout=250"));
        command.addAll(List.of(settings));
        Path stdout = root.resolve("startup.stdout"), stderr = root.resolve("startup.stderr");
        var builder = new ProcessBuilder(command).redirectOutput(stdout.toFile()).redirectError(stderr.toFile());
        builder.environment().keySet().removeIf(name -> name.startsWith("MYAI_") || name.startsWith("DB_")
                || name.startsWith("SPRING_") || name.equals("PORT") || name.equals("JAVA_TOOL_OPTIONS") || name.equals("JDK_JAVA_OPTIONS"));
        builder.environment().putAll(values);
        var process = builder.start();
        try {
            assertThat(process.waitFor(20, TimeUnit.SECONDS)).as("기동 설정 오류는 서버·DB 초기화 전에 종료되어야 한다").isTrue();
            String output = Files.readString(stdout), errors = Files.readString(stderr);
            assertThat(process.exitValue()).isEqualTo(2);
            assertThat(output.lines().count()).isEqualTo(1);
            assertThat(output + errors).doesNotContain(TOKEN, root.toString(), "SYNTHETIC_PRIVATE", "jdbc:mysql", "Hikari", "Tomcat", "Flyway", "Exception", "\tat ");
            String token = values.get("MYAI_LOCAL_API_TOKEN");
            if (token != null && !token.isBlank()) assertThat(output + errors).doesNotContain(token);
            var response = mapper.readTree(output);
            assertThat(UUID.fromString(response.path("request_id").asText())).isNotNull();
            assertThat(response.path("error").path("code").asText()).isEqualTo("LOCAL_API_VALIDATION_ERROR");
            assertThat(response.path("error").path("field_errors").isArray()).isTrue();
            assertThat(response.path("error").path("retryable").asBoolean()).isFalse();
        } finally {
            if (process.isAlive()) {
                process.destroyForcibly();
                process.waitFor(5, TimeUnit.SECONDS);
            }
        }
    }
}
