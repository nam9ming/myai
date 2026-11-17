package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class CitizenNoticeJarMySqlTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).followRedirects(HttpClient.Redirect.NEVER).build();

    @AfterEach void closeClient() { http.close(); }

    @Test
    void selectOnlyPublicJarReadsCitizenHistoryWithoutPythonAndExcludesLocalAndFixtureRoutes() throws Exception {
        Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwx------"));
        Path databaseRoot = privateDirectory("database"), sources = privateDirectory("sources");
        try (var database = RecoveryDatabase.start(databaseRoot)) {
            assertThat(URI.create(database.url().substring(5)).getRawPath()).isEqualTo("/myai_recovery");
            assertThat(database.jdbc().queryForObject("SELECT DATABASE()", String.class)).isEqualTo("myai_recovery");
            String citizenId, eventId, legacyId, legacyPoint;
            JsonNode expectedNotice, expectedSources;
            try (var context = new SpringApplicationBuilder(MyaiBackendApplication.class).profiles("public").web(WebApplicationType.NONE)
                    .run("--spring.datasource.url=" + database.url(), "--spring.datasource.username=" + database.username(),
                            "--spring.datasource.password=" + database.password(), "--app.calculation.workdir=", "--spring.main.banner-mode=off")) {
                var fixtures = new CitizenNoticeFixtures(sources, database.jdbc(), context.getBean(ReviewedImportReader.class),
                        context.getBean(ReviewedImportService.class), context.getBean(PublicationCommandReader.class),
                        context.getBean(PublicationService.class), new HashSet<>());
                var input = fixtures.citizen("education", false); String approved = fixtures.approve(input, true);
                var first = fixtures.publish(List.of(approved), null);
                String changed = fixtures.editTitleAndApprove(input, "합성 JAR 재검토 제목");
                fixtures.publish(List.of(changed), 0L); fixtures.publish(List.of(), 1L); fixtures.rollback(first.snapshotId(), 2);
                citizenId = first.snapshotId(); eventId = CitizenNoticeFixtures.event(input);
                var canonical = fixtures.canonical(citizenId); expectedNotice = canonical.path("notices").get(0); expectedSources = canonical.path("sources");
                var legacy = fixtures.legacy(); var old = fixtures.publishLegacy(legacy, fixtures.approve(legacy, false));
                legacyId = old.snapshotId(); legacyPoint = fixtures.canonical(legacyId).path("points").get(0).path("point_id").asText();
            }
            String readUser = "city_query_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12);
            String readPassword = UUID.randomUUID().toString().replace("-", "");
            createReadOnly(database, readUser, readPassword);
            var readJdbc = new JdbcTemplate(new DriverManagerDataSource(database.url(), readUser, readPassword));
            assertThatThrownBy(() -> readJdbc.update("UPDATE publication_heads SET lock_version=lock_version WHERE channel_key='citizen:current'"))
                    .isInstanceOf(DataAccessException.class);
            var before = CitizenNoticeFixtures.rows(database.jdbc()); var sourceBefore = files(sources);
            try (var jar = start(database, readUser, readPassword, "public", sources)) {
                var list = json(jar.get("/api/v1/citizen/notices", false), 200);
                assertThat(list.path("schema_version").asText()).isEqualTo("citizen-api-v1");
                assertThat(list.path("snapshot_id").asText()).isEqualTo(citizenId);
                assertThat(list.path("data").path("notices").get(0)).isEqualTo(expectedNotice);
                assertThat(list.path("data").path("sources")).isEqualTo(expectedSources);
                var detail = json(jar.get("/api/v1/citizen/notices/" + eventId + "?snapshot_id=" + citizenId, false), 200);
                assertThat(detail.path("data").path("notice")).isEqualTo(expectedNotice);
                assertThat(detail.path("data").path("sources")).isEqualTo(expectedSources);
                assertThat(detail.path("data").path("history").path("entries").findValuesAsText("kind"))
                        .containsExactly("first_observed", "changed", "withdrawn", "restored");
                var config = json(jar.get("/api/v1/config", false), 200);
                assertThat(config.path("snapshot_id").asText()).isEqualTo(legacyId);
                var request = (ObjectNode) mapper.readTree(Path.of("../contracts/examples/matches-request.json").toFile());
                request.put("snapshot_id", legacyId).put("point_id", legacyPoint);
                var unavailable = json(jar.post("/api/v1/matches", request), 503);
                assertThat(unavailable.path("error").path("code").asText()).isEqualTo("CALCULATION_UNAVAILABLE");
                assertThat(unavailable.path("error").path("retryable").asBoolean()).isFalse();
                var invalid = json(jar.get("/api/v1/citizen/notices?cost=free", false), 422);
                assertThat(invalid.path("error").path("code").asText()).isEqualTo("INVALID_REQUEST");
                assertThat(detail.toString()).doesNotContain("raw_asset_path", "cleaned_text", "reviewer_id", "human_overrides", "synthetic-reviewer");
            }
            assertThat(CitizenNoticeFixtures.rows(database.jdbc())).isEqualTo(before); assertThat(files(sources)).isEqualTo(sourceBefore);
            try (var jar = start(database, readUser, readPassword, "local-api", sources)) {
                var rejected = json(jar.get("/api/v1/citizen/notices", true), 404);
                assertThat(rejected.path("error").path("code").asText()).isEqualTo("NOT_FOUND");
                var unauthorized = json(jar.get("/api/v1/citizen/notices", false), 401);
                assertThat(unauthorized.path("error").path("code").asText()).isEqualTo("LOCAL_API_UNAUTHORIZED");
            }
            assertThat(CitizenNoticeFixtures.rows(database.jdbc())).isEqualTo(before); assertThat(files(sources)).isEqualTo(sourceBefore);
            try (var jar = start(database, readUser, readPassword, "fixture", sources)) {
                var rejected = json(jar.get("/api/v1/citizen/notices", false), 404);
                assertThat(rejected.path("error").path("code").asText()).isEqualTo("NOT_FOUND");
                assertThat(json(jar.get("/api/v1/config", false), 200).path("schema_version").asText()).isEqualTo("api-v1");
            }
            assertThat(CitizenNoticeFixtures.rows(database.jdbc())).isEqualTo(before); assertThat(files(sources)).isEqualTo(sourceBefore);
        }
    }

    private Path privateDirectory(String name) throws Exception {
        return Files.createDirectory(root.resolve(name), PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
    }

    private RunningJar start(RecoveryDatabase database, String username, String password, String profile, Path sources) throws Exception {
        int port;
        try (var socket = new ServerSocket()) {
            socket.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), 0)); port = socket.getLocalPort();
        }
        String token = "SYNTHETIC_QUERY_" + UUID.randomUUID().toString().replace("-", "");
        Path stdout = root.resolve(profile + ".stdout"), stderr = root.resolve(profile + ".stderr");
        var command = new ArrayList<String>(List.of(Path.of(System.getProperty("java.home"), "bin", "java").toString(), "-jar",
                Path.of("build/libs/myai-backend-0.1.0.jar").toAbsolutePath().toString(), "--spring.profiles.active=" + profile,
                "--spring.flyway.enabled=false", "--server.address=127.0.0.1", "--server.port=" + port));
        var builder = new ProcessBuilder(command).redirectOutput(stdout.toFile()).redirectError(stderr.toFile());
        var environment = builder.environment(); environment.clear(); environment.put("LANG", "C.UTF-8");
        environment.put("PATH", System.getenv("PATH")); environment.put("DB_URL", database.url());
        environment.put("DB_USERNAME", username); environment.put("DB_PASSWORD", password);
        environment.put("MYAI_PYTHON_EXECUTABLE", root.resolve("missing-python").toString());
        environment.put("MYAI_PYTHON_WORKDIR", root.resolve("missing-processing").toString());
        if (profile.equals("local-api")) {
            environment.put("MYAI_LOCAL_API_TOKEN", token); environment.put("MYAI_LOCAL_API_ACTOR", "synthetic-query");
            environment.put("MYAI_LOCAL_API_SOURCE_ROOT", sources.toAbsolutePath().toString());
            for (String kind : List.of("EXTRACTION", "HANDOFF", "REQUEST")) {
                Path directory = privateDirectory(kind.toLowerCase());
                environment.put("MYAI_LOCAL_API_" + kind + "_ROOT", directory.toAbsolutePath().toString());
            }
            environment.put("MYAI_LOCAL_API_PORT", Integer.toString(port));
        }
        var jar = new RunningJar(builder.start(), port, token, stderr);
        try {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(40);
            while (System.nanoTime() < deadline) {
                assertThat(jar.process.isAlive()).as("조회 JAR readiness: %s", Files.readString(stderr)).isTrue();
                try {
                    var response = jar.get(profile.equals("local-api") ? "/local/readiness" : "/health", false);
                    assertThat(response.statusCode()).isEqualTo(profile.equals("local-api") ? 401 : 200); return jar;
                } catch (IOException notReady) { Thread.sleep(50); }
            }
            throw new AssertionError("시민 조회 JAR readiness 제한 시간 초과");
        } catch (Exception | AssertionError failure) { jar.close(); throw failure; }
    }

    private final class RunningJar implements AutoCloseable {
        final Process process;
        final int port;
        final String token;
        final Path stderr;
        RunningJar(Process process, int port, String token, Path stderr) { this.process = process; this.port = port; this.token = token; this.stderr = stderr; }
        HttpRequest.Builder request(String path, boolean authenticated) {
            String origin = "http://127.0.0.1:" + port;
            var request = HttpRequest.newBuilder(URI.create(origin + path)).timeout(Duration.ofSeconds(10)).header("Origin", origin);
            if (authenticated) request.header("Authorization", "Bearer " + token); return request;
        }
        HttpResponse<String> get(String path, boolean authenticated) throws Exception { return http.send(request(path, authenticated).GET().build(), HttpResponse.BodyHandlers.ofString()); }
        HttpResponse<String> post(String path, JsonNode body) throws Exception {
            return http.send(request(path, false).header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body.toString())).build(), HttpResponse.BodyHandlers.ofString());
        }
        @Override public void close() throws Exception {
            if (process.isAlive()) { process.destroy(); if (!process.waitFor(10, TimeUnit.SECONDS)) { process.destroyForcibly(); assertThat(process.waitFor(5, TimeUnit.SECONDS)).isTrue(); } }
        }
    }

    private JsonNode json(HttpResponse<String> response, int status) throws Exception {
        assertThat(response.statusCode()).as(response.body()).isEqualTo(status); return mapper.readTree(response.body());
    }

    private Map<String, String> files(Path directory) throws Exception {
        var result = new LinkedHashMap<String, String>();
        try (var paths = Files.walk(directory)) {
            for (Path file : paths.filter(Files::isRegularFile).sorted().toList()) result.put(directory.relativize(file).toString(), ReviewedImportReader.sha256(Files.readAllBytes(file)));
        }
        return result;
    }

    private void createReadOnly(RecoveryDatabase database, String username, String password) throws Exception {
        Path output = root.resolve("grant.out"), errors = root.resolve("grant.err");
        var process = new ProcessBuilder("docker", "exec", "--interactive", database.id(), "sh", "-c",
                "MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\" exec mysql --user=root --default-character-set=utf8mb4")
                .redirectOutput(output.toFile()).redirectError(errors.toFile()).start();
        try {
            try (var input = process.getOutputStream()) {
                input.write(("CREATE USER '" + username + "'@'%' IDENTIFIED BY '" + password + "'; GRANT SELECT ON myai_recovery.* TO '"
                        + username + "'@'%';").getBytes(StandardCharsets.UTF_8));
            }
            assertThat(process.waitFor(15, TimeUnit.SECONDS)).isTrue(); assertThat(process.exitValue()).as(Files.readString(errors)).isZero();
        } finally { if (process.isAlive()) { process.destroyForcibly(); assertThat(process.waitFor(5, TimeUnit.SECONDS)).isTrue(); } }
    }
}
