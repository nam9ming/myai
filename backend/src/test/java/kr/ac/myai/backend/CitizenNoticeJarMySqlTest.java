package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ReviewedImportService;
import kr.ac.myai.backend.service.SnapshotExportService;
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
            String mysqlVersion = database.jdbc().queryForObject("SELECT VERSION()", String.class);
            String citizenId, eventId, legacyId, legacyPoint;
            JsonNode expectedNotice, expectedSources;
            List<Map<String, ?>> expectedEntries;
            Map<String, ?> invalidFilterError = Map.of("code", "INVALID_REQUEST", "message", "지원하는 조회 조건을 확인해 주세요.",
                    "field_errors", List.of(Map.of("field", "query", "message", "지원하는 조회 조건을 확인해 주세요.")), "retryable", false);
            Path reproDirectory;
            var reproCases = new ArrayList<CitizenNoticeFixtures.ReproCase>();
            try (var context = new SpringApplicationBuilder(MyaiBackendApplication.class).profiles("public").web(WebApplicationType.NONE)
                    .run("--spring.datasource.url=" + database.url(), "--spring.datasource.username=" + database.username(),
                            "--spring.datasource.password=" + database.password(), "--app.calculation.workdir=", "--spring.main.banner-mode=off")) {
                var fixtures = new CitizenNoticeFixtures(sources, database.jdbc(), context.getBean(ReviewedImportReader.class),
                        context.getBean(ReviewedImportService.class), context.getBean(PublicationCommandReader.class),
                        context.getBean(PublicationService.class), new HashSet<>());
                var input = fixtures.citizen("education", false); String approved = fixtures.approve(input, true);
                var first = fixtures.publish(List.of(approved), null);
                String changed = fixtures.editTitleAndApprove(input, "합성 JAR 재검토 제목");
                var changedSnapshot = fixtures.publish(List.of(changed), 0L);
                var emptySnapshot = fixtures.publish(List.of(), 1L);
                var restored = fixtures.rollback(first.snapshotId(), 2);
                citizenId = first.snapshotId(); eventId = CitizenNoticeFixtures.event(input);
                var canonical = fixtures.canonical(citizenId); expectedNotice = canonical.path("notices").get(0); expectedSources = canonical.path("sources");
                var changedCanonical = fixtures.canonical(changedSnapshot.snapshotId());
                var emptyCanonical = fixtures.canonical(emptySnapshot.snapshotId());
                assertThat(emptyCanonical.path("notices")).isEmpty(); assertThat(emptyCanonical.path("sources")).isEmpty();
                assertThat(restored.snapshotId()).isEqualTo(citizenId); assertThat(restored.headVersion()).isEqualTo(3L);
                var firstState = Map.of("notice", expectedNotice, "sources", expectedSources);
                var changedState = Map.of("notice", changedCanonical.path("notices").get(0), "sources", changedCanonical.path("sources"));
                expectedEntries = List.of(
                        Map.of("kind", "first_observed", "snapshot_id", citizenId, "action", "publish",
                                "published_at", publicationTime(database.jdbc(), 0, "publish", null, citizenId),
                                "before", mapper.nullNode(), "after", firstState),
                        Map.of("kind", "changed", "snapshot_id", changedSnapshot.snapshotId(), "action", "publish",
                                "published_at", publicationTime(database.jdbc(), 1, "publish", citizenId, changedSnapshot.snapshotId()),
                                "before", firstState, "after", changedState),
                        Map.of("kind", "withdrawn", "snapshot_id", emptySnapshot.snapshotId(), "action", "publish",
                                "published_at", publicationTime(database.jdbc(), 2, "publish", changedSnapshot.snapshotId(), emptySnapshot.snapshotId()),
                                "before", changedState, "after", mapper.nullNode()),
                        Map.of("kind", "restored", "snapshot_id", citizenId, "action", "rollback",
                                "published_at", publicationTime(database.jdbc(), 3, "rollback", emptySnapshot.snapshotId(), restored.snapshotId()),
                                "before", mapper.nullNode(), "after", firstState));
                reproDirectory = CitizenNoticeFixtures.createReproDirectory("jar-history");
                var snapshotIds = List.of(citizenId, changedSnapshot.snapshotId(), emptySnapshot.snapshotId());
                assertThat(snapshotIds).doesNotHaveDuplicates();
                for (String snapshotId : snapshotIds) {
                    var exported = context.getBean(SnapshotExportService.class).export(UUID.fromString(snapshotId), reproDirectory.resolve("snapshots"));
                    assertThat(Files.readAllBytes(reproDirectory.resolve("snapshots").resolve(exported.fileName())))
                            .isEqualTo(fixtures.canonicalText(snapshotId).getBytes(StandardCharsets.UTF_8));
                }
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
                var listResponse = jar.get("/api/v1/citizen/notices", false);
                var list = json(listResponse, 200);
                assertThat(list.path("schema_version").asText()).isEqualTo("citizen-api-v1");
                assertThat(list.path("snapshot_id").asText()).isEqualTo(citizenId);
                assertThat(list.path("data").path("notices").get(0)).isEqualTo(expectedNotice);
                assertThat(list.path("data").path("sources")).isEqualTo(expectedSources);
                String detailPath = "/api/v1/citizen/notices/" + eventId + "?snapshot_id=" + citizenId;
                var detailResponse = jar.get(detailPath, false);
                var detail = json(detailResponse, 200);
                assertThat(detail.path("data").path("notice")).isEqualTo(expectedNotice);
                assertThat(detail.path("data").path("sources")).isEqualTo(expectedSources);
                var history = detail.path("data").path("history");
                assertThat(keys(history)).containsExactlyInAnyOrder("scope", "completeness", "status", "window", "entries", "error");
                assertThat(history.path("status").asText()).isEqualTo("available"); assertThat(history.path("error").isNull()).isTrue();
                assertThat(history.path("window").path("from_version").asLong(-1)).isZero();
                assertThat(history.path("window").path("to_version").asLong(-1)).isEqualTo(3);
                assertThat(history.path("window").path("has_more").asBoolean()).isFalse();
                assertThat(history.path("entries").findValuesAsText("kind"))
                        .containsExactly("first_observed", "changed", "withdrawn", "restored");
                assertThat(history.path("entries")).isEqualTo(mapper.valueToTree(expectedEntries));
                var newestResponse = jar.get(detailPath + "&history_limit=2", false);
                var newest = json(newestResponse, 200).path("data");
                assertThat(newest.path("notice")).isEqualTo(expectedNotice);
                assertThat(newest.path("sources")).isEqualTo(expectedSources);
                var latestHistory = newest.path("history");
                assertThat(latestHistory.path("status").asText()).isEqualTo("available");
                assertThat(latestHistory.path("window").path("from_version").asLong(-1)).isEqualTo(2);
                assertThat(latestHistory.path("window").path("to_version").asLong(-1)).isEqualTo(3);
                assertThat(latestHistory.path("window").path("has_more").asBoolean()).isTrue();
                assertThat(latestHistory.path("window").path("next_before_version").asLong(-1)).isEqualTo(2);
                assertThat(latestHistory.path("window").path("limit").asInt(-1)).isEqualTo(2);
                assertThat(latestHistory.path("entries").findValuesAsText("kind")).containsExactly("withdrawn", "restored");
                assertThat(latestHistory.path("entries")).isEqualTo(mapper.valueToTree(expectedEntries.subList(2, 4)));
                long cursor = latestHistory.path("window").path("next_before_version").longValue();
                var olderResponse = jar.get(detailPath + "&history_limit=2&history_before_version=" + cursor, false);
                var older = json(olderResponse, 200).path("data");
                assertThat(older.path("notice")).isEqualTo(expectedNotice);
                assertThat(older.path("history").path("status").asText()).isEqualTo("available");
                assertThat(older.path("history").path("window").path("from_version").asLong(-1)).isZero();
                assertThat(older.path("history").path("window").path("to_version").asLong(-1)).isEqualTo(1);
                assertThat(older.path("history").path("window").path("has_more").asBoolean()).isFalse();
                assertThat(older.path("history").path("entries").findValuesAsText("kind")).containsExactly("first_observed", "changed");
                assertThat(older.path("history").path("entries")).isEqualTo(mapper.valueToTree(expectedEntries.subList(0, 2)));
                var config = json(jar.get("/api/v1/config", false), 200);
                assertThat(config.path("snapshot_id").asText()).isEqualTo(legacyId);
                var request = (ObjectNode) mapper.readTree(Path.of("../contracts/examples/matches-request.json").toFile());
                request.put("snapshot_id", legacyId).put("point_id", legacyPoint);
                var unavailable = json(jar.post("/api/v1/matches", request), 503);
                assertThat(unavailable.path("error").path("code").asText()).isEqualTo("CALCULATION_UNAVAILABLE");
                assertThat(unavailable.path("error").path("retryable").asBoolean()).isFalse();
                var invalidResponse = jar.get("/api/v1/citizen/notices?cost=free", false);
                var invalid = json(invalidResponse, 422);
                assertThat(invalid.path("error").path("code").asText()).isEqualTo("INVALID_REQUEST");
                assertThat(invalid.path("error")).isEqualTo(mapper.valueToTree(invalidFilterError));
                assertThat(detail.toString()).doesNotContain("raw_asset_path", "cleaned_text", "reviewer_id", "human_overrides", "synthetic-reviewer");
                reproCases.add(new CitizenNoticeFixtures.ReproCase("list", listResponse, 200,
                        Map.of("/schema_version", "citizen-api-v1", "/snapshot_id", citizenId,
                                "/data/notices", List.of(expectedNotice), "/data/sources", expectedSources)));
                reproCases.add(new CitizenNoticeFixtures.ReproCase("detail", detailResponse, 200,
                        historyChecks(citizenId, expectedNotice, expectedSources, 0, 3, false, null, 1000,
                                expectedEntries)));
                reproCases.add(new CitizenNoticeFixtures.ReproCase("newest", newestResponse, 200,
                        historyChecks(citizenId, expectedNotice, expectedSources, 2, 3, true, 2, 2,
                                expectedEntries.subList(2, 4))));
                reproCases.add(new CitizenNoticeFixtures.ReproCase("older", olderResponse, 200,
                        historyChecks(citizenId, expectedNotice, expectedSources, 0, 1, false, null, 2,
                                expectedEntries.subList(0, 2))));
                reproCases.add(new CitizenNoticeFixtures.ReproCase("invalid-filter", invalidResponse, 422,
                        Map.of("/error", invalidFilterError)));
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
            CitizenNoticeFixtures.writeRepro(reproDirectory, "jar-history", mysqlVersion, reproCases);
        }
    }

    private Map<String, ?> historyChecks(String snapshotId, JsonNode notice, JsonNode sources, int from, int to,
                                         boolean hasMore, Integer next, int limit, List<Map<String, ?>> entries) {
        var window = mapper.createObjectNode().put("from_version", from).put("to_version", to)
                .put("has_more", hasMore).put("limit", limit);
        if (next == null) window.putNull("next_before_version"); else window.put("next_before_version", next.intValue());
        var checks = new LinkedHashMap<String, Object>(Map.of("/schema_version", "citizen-api-v1", "/snapshot_id", snapshotId,
                "/data/notice", notice, "/data/sources", sources, "/data/history/scope", "same_data_kind_published_snapshots",
                "/data/history/completeness", "unknown", "/data/history/status", "available",
                "/data/history/window", window, "/data/history/error", mapper.nullNode()));
        checks.put("/data/history/entries", entries);
        return checks;
    }

    private String publicationTime(JdbcTemplate jdbc, int version, String action, String beforeId, String afterId) {
        return jdbc.queryForObject("SELECT happened_at FROM publication_audits WHERE channel_key='citizen:current' "
                        + "AND head_version=? AND action=? AND before_snapshot_id <=> ? AND after_snapshot_id=?",
                (row, index) -> row.getTimestamp("happened_at").toInstant().toString(), version, action, beforeId, afterId);
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
        HttpResponse<byte[]> get(String path, boolean authenticated) throws Exception { return http.send(request(path, authenticated).GET().build(), HttpResponse.BodyHandlers.ofByteArray()); }
        HttpResponse<byte[]> post(String path, JsonNode body) throws Exception {
            return http.send(request(path, false).header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body.toString())).build(), HttpResponse.BodyHandlers.ofByteArray());
        }
        @Override public void close() throws Exception {
            if (process.isAlive()) { process.destroy(); if (!process.waitFor(10, TimeUnit.SECONDS)) { process.destroyForcibly(); assertThat(process.waitFor(5, TimeUnit.SECONDS)).isTrue(); } }
        }
    }

    private JsonNode json(HttpResponse<byte[]> response, int status) throws Exception {
        assertThat(response.statusCode()).as(new String(response.body(), StandardCharsets.UTF_8)).isEqualTo(status); return mapper.readTree(response.body());
    }

    private java.util.Set<String> keys(JsonNode node) {
        var result = new HashSet<String>(); node.fieldNames().forEachRemaining(result::add); return result;
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
