package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

class SourceReviewStartupTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();

    @ParameterizedTest
    @ValueSource(strings = {"public", "fixture", "local-import", "local-extraction", "local-publication", "local-export"})
    void mixedProfileIsRejectedBeforeConnecting(String profile) throws Exception {
        var error = failed("SOURCE_REVIEW_VALIDATION_ERROR", 2, false,
                "--spring.profiles.active=local-source-review," + profile);
        assertThat(error.path("field_errors").get(0).path("field").asText()).isEqualTo("spring.profiles.active");
    }

    @ParameterizedTest
    @ValueSource(strings = {"servlet", "reactive"})
    void forcedWebIsRejectedBeforeConnecting(String type) throws Exception {
        var error = failed("SOURCE_REVIEW_VALIDATION_ERROR", 2, false, "--spring.main.web-application-type=" + type);
        assertThat(error.path("field_errors").get(0).path("field").asText()).isEqualTo("spring.main.web-application-type");
    }

    @Test
    void coldConnectionFailureReturnsSafeRetryableError() throws Exception {
        failed("SOURCE_REVIEW_DATABASE_UNAVAILABLE", 4, true);
    }

    @Test
    void otherStartupFailureReturnsSafeInternalError() throws Exception {
        failed("SOURCE_REVIEW_INTERNAL_ERROR", 1, false, "--spring.datasource.driver-class-name=PRIVATE_DRIVER");
    }

    @Test
    @EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
    void accessDeniedReturnsNonRetryableDatabaseError() throws Exception {
        var address = java.net.URI.create(System.getenv("DB_URL").substring("jdbc:".length()));
        String missing = "myai_source_forbidden_" + UUID.randomUUID().toString().replace("-", "");
        String url = "jdbc:mysql://" + address.getRawAuthority() + "/" + missing
                + "?connectTimeout=500&socketTimeout=500&createDatabaseIfNotExist=false";
        Path errorFile = root.resolve("denied.stderr");
        var process = new ProcessBuilder(Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                "-jar", "build/libs/myai-backend-0.1.0.jar", "--spring.profiles.active=local-source-review",
                "--spring.datasource.url=" + url, "--spring.datasource.hikari.connection-timeout=1000")
                .redirectError(errorFile.toFile()).start();
        assertEnded(process);
        String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        assertThat(Files.readString(errorFile)).contains("1044");
        assertThat(process.exitValue()).isEqualTo(4);
        assertThat(output.lines().count()).isEqualTo(1);
        var error = mapper.readTree(output).path("error");
        assertThat(error.path("code").asText()).isEqualTo("SOURCE_REVIEW_DATABASE_UNAVAILABLE");
        assertThat(error.path("retryable").asBoolean()).isFalse();
        assertThat(output).doesNotContain(System.getenv("DB_PASSWORD"), url);
    }

    private JsonNode failed(String code, int exit, boolean retryable, String... settings) throws Exception {
        var command = new ArrayList<>(List.of(Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                "-jar", "build/libs/myai-backend-0.1.0.jar", "--spring.profiles.active=local-source-review",
                "--spring.datasource.url=jdbc:mysql://127.0.0.1:1/unavailable?connectTimeout=500&socketTimeout=500",
                "--spring.datasource.username=PRIVATE_USER", "--spring.datasource.password=PRIVATE_PASSWORD",
                "--spring.datasource.hikari.connection-timeout=1000"));
        command.addAll(List.of(settings));
        var process = new ProcessBuilder(command).redirectError(root.resolve("startup.stderr").toFile()).start();
        assertEnded(process);
        String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        assertThat(process.exitValue()).isEqualTo(exit);
        assertThat(output.lines().count()).isEqualTo(1);
        assertThat(output).doesNotContain("PRIVATE_", "jdbc:mysql");
        var response = mapper.readTree(output);
        assertThat(UUID.fromString(response.path("request_id").asText())).isNotNull();
        var error = response.path("error");
        assertThat(error.path("code").asText()).isEqualTo(code);
        assertThat(error.path("retryable").asBoolean()).isEqualTo(retryable);
        return error;
    }

    private void assertEnded(Process process) throws Exception {
        boolean ended = process.waitFor(20, TimeUnit.SECONDS);
        if (!ended) process.destroyForcibly();
        assertThat(ended).isTrue();
    }
}

