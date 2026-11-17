package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import java.io.IOException;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
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
import java.util.Arrays;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.*;

@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class CitizenHumanHandoffJarMySqlTest {
    private static final int MIB = 1024 * 1024;
    private static final String ACTOR = "synthetic-citizen-jar-importer";
    private static final String PRIVATE_REASON = "SYNTHETIC_CITIZEN_RAW_REQUEST_MARKER";
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).followRedirects(HttpClient.Redirect.NEVER).build();

    @AfterEach void closeClientAndUnsealOwnedFiles() throws Exception {
        http.close(); ExtractionArchiveReaderTest.unseal(root);
    }

    @Test
    void actualJarImportsCitizenHandoffsThroughCliAndHttpAndReportsAllProofsWithSelectOnlyAccount() throws Exception {
        Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwx------"));
        Path databaseRoot = directory(root.resolve("database"));
        Path sources = directory(root.resolve("sources")), commonHandoffs = directory(root.resolve("handoffs"));
        Path requests = directory(root.resolve("requests")), unusedExtractions = directory(root.resolve("api-extractions"));
        try (var database = RecoveryDatabase.start(databaseRoot)) {
            assertThat(URI.create(database.url().substring(5)).getRawPath()).isEqualTo("/myai_recovery");
            assertThat(database.jdbc().queryForObject("SELECT DATABASE()", String.class)).isEqualTo("myai_recovery");
            var success = registered(database, sources, null, output -> { });
            byte[] cliBytes = padded(success.request()); Path cliRequest = Files.write(root.resolve("cli-import.json"), cliBytes);
            var first = run(database, database.username(), database.password(), "local-import",
                    "--myai.import.file=" + cliRequest, "--myai.import.source-root=" + sources,
                    "--myai.import.handoff-root=" + success.handoffRoot(), "--myai.import.actor=" + ACTOR);
            assertThat(first.path("result").path("already_imported").asBoolean()).isFalse();
            assertThat(first.path("result").path("revision_ids")).hasSize(5);
            String importId = first.path("result").path("import_id").asText();
            assertThat(database.jdbc().queryForObject("SELECT input_sha256 FROM import_batches WHERE import_id=?", String.class, importId)).isEqualTo(sha(cliBytes));
            var beforeReplay = CitizenNoticeFixtures.rows(database.jdbc());
            var repeated = run(database, database.username(), database.password(), "local-import",
                    "--myai.import.file=" + cliRequest, "--myai.import.source-root=" + sources,
                    "--myai.import.handoff-root=" + success.handoffRoot(), "--myai.import.actor=" + ACTOR);
            assertThat(repeated.path("result").path("already_imported").asBoolean()).isTrue();
            assertThat(repeated.path("result").path("import_id").asText()).isEqualTo(importId);
            assertThat(CitizenNoticeFixtures.rows(database.jdbc())).isEqualTo(beforeReplay);
            assertThat(Files.readAllBytes(cliRequest)).isEqualTo(cliBytes);

            byte[] failedRaw = new byte[5 * MIB + 1]; Arrays.fill(failedRaw, (byte) 0xff);
            var failed = registered(database, sources, failedRaw, output -> {
                var firstItem = output.path("items").get(0).deepCopy(); output.putArray("items").add(firstItem);
            });
            moveImage(failed, commonHandoffs);
            failed.request().put("reason", PRIVATE_REASON);
            byte[] posted = padded(failed.request());
            var parentBefore = database.jdbc().queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", failed.run());
            try (var jar = startApi(database, sources, commonHandoffs, requests, unusedExtractions)) {
                var result = json(jar.send(jar.request("/local/reviews/import", true).POST(HttpRequest.BodyPublishers.ofByteArray(posted))), 200);
                assertThat(result.path("request_sha256").asText()).isEqualTo(sha(posted));
                assertThat(result.path("data").path("revision_ids")).hasSize(1);
                assertThat(result.path("data").path("already_imported").asBoolean()).isFalse();
                assertThat(Files.readAllBytes(requests.resolve(sha(posted) + ".json"))).isEqualTo(posted);
                assertThat(json(jar.send(jar.request("/local/reviews/import", true).POST(HttpRequest.BodyPublishers.ofByteArray(posted))), 200)
                        .path("data").path("already_imported").asBoolean()).isTrue();

                var changed = CitizenHandoffFixture.freeze(root, failed.source(), failed.extraction(), output -> {
                    var firstItem = (ObjectNode) output.path("items").get(0).deepCopy();
                    ((ObjectNode) firstItem.path("title")).put("value", "합성 인계 후속 수정 제목");
                    ((ObjectNode) firstItem.path("categories")).putArray("value").add("support").add("living");
                    for (String field : ReviewedImportReader.CITIZEN_FIELDS.subList(2, 14))
                        firstItem.putObject(field).putNull("value").put("knowledge", "ambiguous").put("reason", "합성 재확인 필요 " + field).putArray("evidence_ids");
                    output.putArray("items").add(firstItem);
                });
                moveImage(changed, commonHandoffs);
                ((ObjectNode) changed.request().path("revisions").get(0)).put("expected_revision_no", 1);
                byte[] put = padded(changed.request());
                var guardedRows = CitizenNoticeFixtures.rows(database.jdbc());
                var guardedRequests = CitizenExtractionArchiveTest.tree(requests);
                error(jar.send(jar.request("/local/events/" + UUID.randomUUID() + "/review", true).PUT(HttpRequest.BodyPublishers.ofByteArray(put))), 422, "LOCAL_API_VALIDATION_ERROR");
                error(jar.send(jar.request("/local/reviews/import", false).POST(HttpRequest.BodyPublishers.ofByteArray(put))), 401, "LOCAL_API_UNAUTHORIZED");
                error(jar.send(jar.request("/local/reviews/import", true).setHeader("Origin", "https://example.invalid")
                        .POST(HttpRequest.BodyPublishers.ofByteArray(put))), 403, "LOCAL_API_FORBIDDEN");
                jar.rejectWrongHost(put);
                byte[] oversized = Arrays.copyOf(put, 8 * MIB + 1); Arrays.fill(oversized, put.length, oversized.length, (byte) ' ');
                error(jar.send(jar.request("/local/reviews/import", true).POST(HttpRequest.BodyPublishers.ofByteArray(oversized))), 413, "PAYLOAD_TOO_LARGE");
                assertThat(CitizenNoticeFixtures.rows(database.jdbc())).isEqualTo(guardedRows);
                assertThat(CitizenExtractionArchiveTest.tree(requests)).isEqualTo(guardedRequests);
                var updated = json(jar.send(jar.request("/local/events/" + changed.eventId() + "/review", true)
                        .PUT(HttpRequest.BodyPublishers.ofByteArray(put))), 200);
                assertThat(updated.path("request_sha256").asText()).isEqualTo(sha(put));
                assertThat(Files.readAllBytes(requests.resolve(sha(put) + ".json"))).isEqualTo(put);
                String secondId = updated.path("data").path("revision_ids").get(0).asText();
                var payload = mapper.readTree(database.jdbc().queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id=?", String.class, secondId));
                assertThat(payload.path("revision").path("revision_no").asLong()).isEqualTo(2);
                assertThat(payload.path("revision").path("origin").asText()).isEqualTo("ai_reviewed");
                assertThat(payload.path("revision").path("review_status").asText()).isEqualTo("needs_review");
                assertThat(payload.path("revision").path("publication_intent").asText()).isEqualTo("hidden");
                assertThat(payload.path("human_handoffs")).hasSize(2);
                var changes = payload.path("revision").path("human_overrides");
                assertThat(changes).hasSize(14);
                assertThat(changes.findValuesAsText("field_path")).containsExactlyInAnyOrderElementsOf(ReviewedImportReader.CITIZEN_FIELDS.subList(0, 14));
                assertThat(payload.path("revision").path("cost").path("value").isNull()).isTrue();
                assertThat(payload.path("revision").path("cost").path("knowledge").asText()).isEqualTo("ambiguous");

                var empty = CitizenHandoffFixture.freeze(root, failed.source(), failed.extraction(), output -> {
                    output.putArray("items"); output.putArray("warnings").add("NO_EVENT_FOUND");
                });
                moveImage(empty, commonHandoffs);
                byte[] emptyRequest = padded(empty.request());
                var emptyResult = json(jar.send(jar.request("/local/reviews/import", true).POST(HttpRequest.BodyPublishers.ofByteArray(emptyRequest))), 200);
                assertThat(emptyResult.path("data").path("revision_ids")).isEmpty();
                assertThat(Files.readAllBytes(requests.resolve(sha(emptyRequest) + ".json"))).isEqualTo(emptyRequest);
                assertThat(database.jdbc().queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", failed.run())).isEqualTo(parentBefore);
            }
            assertNoPublication(database);
            String readUser = "city_handoff_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12);
            String readPassword = UUID.randomUUID().toString().replace("-", "");
            createReadOnly(database, readUser, readPassword);
            var readJdbc = new JdbcTemplate(new DriverManagerDataSource(database.url(), readUser, readPassword));
            assertThatThrownBy(() -> readJdbc.update("UPDATE events SET lock_version=lock_version WHERE event_id=?", failed.eventId())).isInstanceOf(DataAccessException.class);
            Path reports = Files.createDirectories(sources.resolve("data/private/reports"));
            Files.setPosixFilePermissions(reports, PosixFilePermissions.fromString("rwx------"));
            var beforeReport = CitizenNoticeFixtures.rows(database.jdbc());
            var beforeParentFiles = CitizenExtractionArchiveTest.tree(failed.extraction().archive());
            var beforeHandoffs = CitizenExtractionArchiveTest.tree(commonHandoffs);
            byte[] sourceBefore = Files.readAllBytes(sources.resolve(failed.source().path("documents").get(0).path("raw_asset_path").asText()));
            var reported = run(database, readUser, readPassword, "local-review-report", "--spring.flyway.enabled=false",
                    "--myai.report.document-version-id=" + failed.source().path("documents").get(0).path("document_version_id").asText(),
                    "--myai.report.source-root=" + sources, "--myai.report.directory=" + reports);
            String html = Files.readString(reports.resolve(reported.path("result").path("file_name").asText()));
            var reportDocuments = section(html, "documents");
            assertThat(reportDocuments.get(0).path("imports")).hasSize(3);
            for (var batch : reportDocuments.get(0).path("imports")) {
                assertThat(batch.path("validation").path("status").asText()).isEqualTo("valid");
                assertThat(batch.path("database").path("schema_version").asText()).isEqualTo("citizen-human-handoff-import-v1");
                assertThat(batch.path("handoffs")).hasSize(1);
                assertThat(batch.path("handoffs").get(0).path("validation").path("status").asText()).isEqualTo("valid");
            }
            var extractions = section(html, "extractions");
            assertThat(extractions).hasSize(1);
            assertThat(extractions.get(0).path("database").path("status").asText()).isEqualTo("failed");
            var raw = extractions.get(0).path("artifacts").path("attempt-1.output");
            assertThat(raw.path("validation").path("status").asText()).isEqualTo("valid");
            assertThat(Base64.getDecoder().decode(raw.path("base64").asText())).isEqualTo(failedRaw);
            assertThat(section(html, "events").get(0).path("revisions")).hasSize(2);
            assertThat(html).contains("PRIVATE_CITIZEN_REVIEW_DECLARATION", "citizen-human-handoff-projection-v1");
            assertThat(CitizenNoticeFixtures.rows(database.jdbc())).isEqualTo(beforeReport);
            assertThat(CitizenExtractionArchiveTest.tree(failed.extraction().archive())).isEqualTo(beforeParentFiles);
            assertThat(CitizenExtractionArchiveTest.tree(commonHandoffs)).isEqualTo(beforeHandoffs);
            assertThat(Files.readAllBytes(sources.resolve(failed.source().path("documents").get(0).path("raw_asset_path").asText()))).isEqualTo(sourceBefore);
            assertNoPublication(database);
        }
    }

    private CitizenHandoffFixture.Handoff registered(RecoveryDatabase database, Path sources, byte[] output, Consumer<ObjectNode> edit) throws Exception {
        Path work = directory(root.resolve("fixture-" + UUID.randomUUID()));
        var fixture = CitizenExtractionArchiveTest.fixture(work, output);
        var source = CitizenHandoffFixture.source(sources, fixture); var document = source.path("documents").get(0);
        // 첫 CLI는 Flyway로 새 전용 DB를 준비한다. 이 컨테이너의 생성 UUID만 입력한다.
        var imported = run(database, database.username(), database.password(), "local-import", "--myai.import.file=" + write(source),
                "--myai.import.source-root=" + sources, "--myai.import.actor=" + ACTOR);
        assertThat(imported.path("result").path("document_version_ids").get(0).asText()).isEqualTo(document.path("document_version_id").asText());
        assertThat(database.jdbc().queryForObject("SELECT COUNT(*) FROM extraction_runs WHERE run_id=?", Long.class, fixture.run())).isZero();
        CitizenExtractionArchiveTest.importManual(CitizenExtractionArchiveTest.reader(), fixture);
        run(database, database.username(), database.password(), "local-extraction", "--myai.extraction.run-id=" + fixture.run(),
                "--myai.extraction.archive-root=" + fixture.archive(), "--myai.extraction.actor=" + ACTOR);
        var handoff = CitizenHandoffFixture.freeze(root, source, fixture, edit);
        for (var event : handoff.projection().path("events")) assertThat(database.jdbc().queryForObject("SELECT COUNT(*) FROM events WHERE event_id=?", Long.class,
                event.path("event_id").asText())).isZero();
        return handoff;
    }

    private void moveImage(CitizenHandoffFixture.Handoff fixture, Path handoffs) throws Exception { Files.move(fixture.image(), handoffs.resolve(fixture.request().path("handoff_ref").asText())); }
    private Path write(ObjectNode input) throws Exception { return Files.write(root.resolve(UUID.randomUUID() + ".json"), padded(input)); }
    private byte[] padded(JsonNode input) { return (" \r\n" + input.toPrettyString() + "\r\n ").getBytes(StandardCharsets.UTF_8); }
    private String sha(byte[] bytes) { return ReviewedImportReader.sha256(bytes); }
    private Path directory(Path path) throws Exception { return Files.createDirectory(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))).toRealPath(); }

    private JsonNode section(String html, String id) throws Exception {
        int start = html.indexOf("<section id=\"" + id + "\">");
        assertThat(start).isGreaterThanOrEqualTo(0);
        start = html.indexOf("<pre>", start) + 5;
        int end = html.indexOf("</pre></section>", start); assertThat(end).isGreaterThan(start);
        return mapper.readTree(html.substring(start, end).replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&"));
    }

    private void assertNoPublication(RecoveryDatabase database) {
        for (String table : List.of("snapshots", "publication_heads", "snapshot_revisions", "publication_audits"))
            assertThat(database.jdbc().queryForObject("SELECT COUNT(*) FROM " + table, Long.class)).as(table).isZero();
    }

    private JsonNode run(RecoveryDatabase database, String username, String password, String profile, String... options) throws Exception {
        Path out = root.resolve(UUID.randomUUID() + ".out"), err = root.resolve(UUID.randomUUID() + ".err");
        var arguments = new ArrayList<String>(List.of("--spring.profiles.active=" + profile)); arguments.addAll(List.of(options));
        var builder = command(database, username, password, arguments).redirectOutput(out.toFile()).redirectError(err.toFile());
        var process = builder.start();
        try {
            assertThat(process.waitFor(60, TimeUnit.SECONDS)).as("실제 시민 인계 CLI 제한 시간").isTrue();
            assertThat(process.exitValue()).as(Files.readString(err) + Files.readString(out)).isZero();
            var result = mapper.readTree(out.toFile()); assertThat(result.path("status").asText()).isEqualTo("succeeded");
            assertThat(Files.readString(err)).doesNotContain(PRIVATE_REASON, "PRIVATE_CITIZEN_REVIEW_DECLARATION", database.password(), "jdbc:mysql", root.toString());
            return result;
        } finally { if (process.isAlive()) { process.destroyForcibly(); assertThat(process.waitFor(5, TimeUnit.SECONDS)).isTrue(); } }
    }

    private ProcessBuilder command(RecoveryDatabase database, String username, String password, List<String> options) {
        assertThat(URI.create(database.url().substring(5)).getRawPath()).isEqualTo("/myai_recovery");
        var command = new ArrayList<String>(List.of(Path.of(System.getProperty("java.home"), "bin", "java").toString(), "-Xmx512m", "-jar",
                Path.of("build/libs/myai-backend-0.1.0.jar").toAbsolutePath().toString(), "--spring.main.banner-mode=off"));
        command.addAll(options);
        var builder = new ProcessBuilder(command).directory(PythonProbe.REPO.toFile());
        var environment = builder.environment(); environment.clear();
        environment.put("LANG", "C.UTF-8"); environment.put("PATH", System.getenv("PATH"));
        environment.put("DB_URL", database.url()); environment.put("DB_USERNAME", username); environment.put("DB_PASSWORD", password);
        environment.put("MYAI_PYTHON_EXECUTABLE", PythonProbe.PYTHON); environment.put("MYAI_PYTHON_WORKDIR", PythonProbe.REPO.toString());
        return builder;
    }

    private RunningJar startApi(RecoveryDatabase database, Path sources, Path handoffs, Path requests, Path extractions) throws Exception {
        int port; try (var socket = new ServerSocket()) { socket.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), 0)); port = socket.getLocalPort(); }
        String token = "SYNTHETIC_CITIZEN_TOKEN_" + UUID.randomUUID().toString().replace("-", "");
        Path out = root.resolve("api.out"), err = root.resolve("api.err");
        var builder = command(database, database.username(), database.password(), List.of("--spring.profiles.active=local-api", "--server.port=" + port));
        var env = builder.environment(); env.put("MYAI_LOCAL_API_TOKEN", token); env.put("MYAI_LOCAL_API_ACTOR", ACTOR);
        env.put("MYAI_LOCAL_API_PORT", Integer.toString(port)); env.put("MYAI_LOCAL_API_SOURCE_ROOT", sources.toString());
        env.put("MYAI_LOCAL_API_HANDOFF_ROOT", handoffs.toString()); env.put("MYAI_LOCAL_API_REQUEST_ROOT", requests.toString());
        env.put("MYAI_LOCAL_API_EXTRACTION_ROOT", extractions.toString());
        var jar = new RunningJar(builder.redirectOutput(out.toFile()).redirectError(err.toFile()).start(), port, token, out, err, database.password());
        try {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(40);
            while (System.nanoTime() < deadline) {
                assertThat(jar.process.isAlive()).as("시민 인계 local-api readiness").isTrue();
                try { error(jar.send(jar.request("/local/readiness", false).GET()), 401, "LOCAL_API_UNAUTHORIZED"); return jar; }
                catch (IOException notReady) { Thread.sleep(50); }
            }
            throw new AssertionError("시민 인계 local-api readiness timeout");
        } catch (Exception | AssertionError failure) { jar.close(); throw failure; }
    }

    private JsonNode json(HttpResponse<byte[]> response, int status) throws Exception {
        assertThat(response.statusCode()).as(new String(response.body(), StandardCharsets.UTF_8)).isEqualTo(status);
        return mapper.readTree(response.body());
    }
    private void error(HttpResponse<byte[]> response, int status, String code) throws Exception { assertThat(json(response, status).path("error").path("code").asText()).isEqualTo(code); }

    private final class RunningJar implements AutoCloseable {
        final Process process; final int port; final String token; final Path out, err; final String databasePassword;
        RunningJar(Process process, int port, String token, Path out, Path err, String databasePassword) {
            this.process = process; this.port = port; this.token = token; this.out = out; this.err = err; this.databasePassword = databasePassword;
        }
        HttpRequest.Builder request(String path, boolean authenticated) {
            String origin = "http://127.0.0.1:" + port;
            var builder = HttpRequest.newBuilder(URI.create(origin + path)).timeout(Duration.ofSeconds(45)).header("Origin", origin).header("Content-Type", "application/json");
            if (authenticated) builder.header("Authorization", "Bearer " + token);
            return builder;
        }
        HttpResponse<byte[]> send(HttpRequest.Builder builder) throws Exception { return http.send(builder.build(), HttpResponse.BodyHandlers.ofByteArray()); }
        void rejectWrongHost(byte[] body) throws Exception {
            try (var socket = new Socket()) {
                socket.connect(new InetSocketAddress("127.0.0.1", port), 2_000); socket.setSoTimeout(10_000);
                var output = socket.getOutputStream();
                output.write(("POST /local/reviews/import HTTP/1.1\r\nHost: localhost:" + port + "\r\nOrigin: http://127.0.0.1:" + port
                        + "\r\nAuthorization: Bearer " + token + "\r\nContent-Type: application/json\r\nContent-Length: " + body.length
                        + "\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII)); output.write(body); output.flush();
                String response = new String(socket.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
                assertThat(response).startsWith("HTTP/1.1 403").contains("LOCAL_API_FORBIDDEN");
            }
        }
        @Override public void close() throws Exception {
            if (process.isAlive()) { process.destroy(); if (!process.waitFor(10, TimeUnit.SECONDS)) { process.destroyForcibly(); assertThat(process.waitFor(5, TimeUnit.SECONDS)).isTrue(); } }
            assertThat(Files.readString(out) + Files.readString(err)).doesNotContain(token, PRIVATE_REASON, "PRIVATE_CITIZEN_REVIEW_DECLARATION",
                    root.toString(), databasePassword, "jdbc:mysql", "Exception", "\tat ");
        }
    }

    private void createReadOnly(RecoveryDatabase database, String username, String password) throws Exception {
        assertThat(username).matches("city_handoff_[0-9a-f]{12}"); assertThat(password).matches("[0-9a-f]{32}");
        Path out = root.resolve("grant.out"), err = root.resolve("grant.err");
        var process = new ProcessBuilder("docker", "exec", "--interactive", database.id(), "sh", "-c",
                "MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\" exec mysql --user=root --default-character-set=utf8mb4")
                .redirectOutput(out.toFile()).redirectError(err.toFile()).start();
        try {
            try (var input = process.getOutputStream()) {
                input.write(("CREATE USER '" + username + "'@'%' IDENTIFIED BY '" + password + "'; GRANT SELECT ON myai_recovery.* TO '"
                        + username + "'@'%';").getBytes(StandardCharsets.UTF_8));
            }
            assertThat(process.waitFor(15, TimeUnit.SECONDS)).isTrue(); assertThat(process.exitValue()).as(Files.readString(err)).isZero();
        } finally { if (process.isAlive()) { process.destroyForcibly(); assertThat(process.waitFor(5, TimeUnit.SECONDS)).isTrue(); } }
    }
}
