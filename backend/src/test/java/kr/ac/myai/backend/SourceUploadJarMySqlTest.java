package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.local.SourceUploadStore;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
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
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.*;

@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class SourceUploadJarMySqlTest {
    private static final int MIB = 1024 * 1024;
    private static final String BOUNDARY = "myai-synthetic-upload-boundary";
    private static final String PRIVATE = "SYNTHETIC_PRIVATE_UPLOAD";
    private static final ObjectMapper JSON = new ObjectMapper();
    @TempDir static Path databaseRoot;
    @TempDir Path root;
    private static RecoveryDatabase database;
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1))
            .version(HttpClient.Version.HTTP_1_1).followRedirects(HttpClient.Redirect.NEVER).build();
    private final ReviewedImportReader reader = new ReviewedImportReader();

    @BeforeAll static void startDatabase() throws Exception {
        Files.setPosixFilePermissions(databaseRoot, PosixFilePermissions.fromString("rwx------"));
        database = RecoveryDatabase.start(databaseRoot.toRealPath());
    }

    @AfterAll static void stopDatabase() { if (database != null) database.close(); }
    @AfterEach void closeHttpClient() { http.close(); }

    @Test
    void rejectsAuthenticationOriginHostMalformedPartsAndChunkedLimitsBeforeStorageOrDatabaseWrites() throws Exception {
        var roots = roots();
        var jar = start(roots, "local-api", true);
        try (jar) {
            var before = database();
            var files = files(roots);
            byte[] metadata = bytes(metadata("txt").toString()), raw = bytes(PRIVATE + " body");
            byte[] body = multipart(metadata(metadata), file("text/plain", raw));
            error(jar.send(jar.request("127.0.0.1", false).POST(HttpRequest.BodyPublishers.ofByteArray(body))), 401, "LOCAL_API_UNAUTHORIZED");
            error(jar.send(jar.request("127.0.0.1", true).setHeader("Origin", "http://localhost:" + jar.port)
                    .POST(HttpRequest.BodyPublishers.ofByteArray(body))), 403, "LOCAL_API_FORBIDDEN");
            error(jar.send(jar.request("localhost", true).POST(HttpRequest.BodyPublishers.ofByteArray(body))), 403, "LOCAL_API_FORBIDDEN");
            for (byte[] malformed : List.of(multipart(metadata(metadata)), multipart(file("text/plain", raw)),
                    multipart(metadata(metadata), metadata(metadata), file("text/plain", raw)),
                    multipart(metadata(metadata), file("text/plain", raw), file("text/plain", raw)),
                    multipart(metadata(metadata), file("text/plain", raw), part("extra", null, "text/plain", raw)),
                    multipart(metadata(bytes(metadata("txt").put("use_review", "allowed").toString())), file("text/plain", raw)))) {
                error(jar.send(jar.request("127.0.0.1", true).POST(HttpRequest.BodyPublishers.ofByteArray(malformed))), 422, null);
            }
            error(jar.send(jar.request("127.0.0.1", true).POST(HttpRequest.BodyPublishers.ofByteArray(
                    multipart(metadata(metadata), file("application/octet-stream", raw))))), 415, "UNSUPPORTED_MEDIA_TYPE");
            for (String media : List.of("text/plain", "application/json;charset=UTF-16")) {
                error(jar.send(jar.request("127.0.0.1", true).POST(HttpRequest.BodyPublishers.ofByteArray(
                        multipart(part("metadata", null, media, metadata), file("text/plain", raw))))),
                        415, "UNSUPPORTED_MEDIA_TYPE");
            }
            byte[] largeMetadata = Arrays.copyOf(metadata, 64 * 1024 + 1);
            Arrays.fill(largeMetadata, metadata.length, largeMetadata.length, (byte) ' ');
            error(jar.send(jar.request("127.0.0.1", true).POST(HttpRequest.BodyPublishers.ofByteArray(
                    multipart(metadata(largeMetadata), file("text/plain", raw))))), 413, null);
            error(jar.send(jar.request("127.0.0.1", true).POST(HttpRequest.BodyPublishers.ofByteArray(
                    multipart(metadata(Arrays.copyOf(metadata, 9 * MIB)), file("text/plain", raw))))),
                    413, "SOURCE_UPLOAD_TOO_LARGE");

            byte[] largeFile = multipart(metadata(metadata), file("text/plain", new byte[20 * MIB + 1]));
            var chunked = HttpRequest.BodyPublishers.ofInputStream(() -> new ByteArrayInputStream(largeFile));
            assertThat(chunked.contentLength()).isEqualTo(-1);
            error(jar.send(jar.request("127.0.0.1", true).POST(chunked)), 413, null);
            byte[] largeRequest = multipart(metadata(metadata), file("text/plain", new byte[20 * MIB]),
                    part("extra", null, "text/plain", new byte[MIB]));
            assertThat(largeRequest.length).isGreaterThan(21 * MIB);
            var wholeChunked = HttpRequest.BodyPublishers.ofInputStream(() -> new ByteArrayInputStream(largeRequest));
            assertThat(wholeChunked.contentLength()).isEqualTo(-1);
            error(jar.send(jar.request("127.0.0.1", true).POST(wholeChunked)), 413, null);
            assertThat(database()).isEqualTo(before);
            assertThat(files(roots)).isEqualTo(files);
            jar.awaitLogs();
        }
        safeLogs(jar);
    }

    @Test
    void registersAllThreeFormatsAsPendingReusesExactBytesAndPassesActualPythonInputValidation() throws Exception {
        var roots = roots();
        var jar = start(roots, "local-api", true);
        try (jar) {
            for (String format : List.of("txt", "json", "pdf")) {
                var metadata = metadata(format);
                byte[] metadataBytes = bytes(metadata.toString());
                byte[] raw = switch (format) {
                    case "txt" -> bytes(PRIVATE + " TXT 😀\r\n문의 fixed@example.test / 031-123-4567");
                    case "json" -> bytes("{\"schema_version\":\"text-body-v1\",\"text\":\"" + PRIVATE + " JSON 😀\\r\\n다음 행\"}");
                    default -> pdf(0, PRIVATE + " PDF first", "second page");
                };
                byte[] body = multipart(metadata(metadataBytes), file(media(format), raw));
                var firstResponse = jar.send(jar.request("127.0.0.1", true).POST(HttpRequest.BodyPublishers.ofByteArray(body)));
                assertThat(firstResponse.statusCode()).isEqualTo(200);
                JsonNode first = JSON.readTree(firstResponse.body());
                assertThat(first.path("schema_version").asText()).isEqualTo("source-upload-result-v1");
                assertThat(first.path("use_review").asText()).isEqualTo("pending");
                assertThat(first.path("check_result").asText()).isEqualTo("unchecked");
                assertThat(first.path("raw_sha256").asText()).isEqualTo(sha(raw));
                var store = new SourceUploadStore(roots.source().toString(), roots.requests().toString());
                var saved = store.find(metadata.path("document_version_id").asText(), metadataBytes, raw);
                assertThat(saved).isNotNull();
                assertThat(reader.read(saved.sourceImport(), roots.source()).documents()).hasSize(1);
                JsonNode source = reader.parseJson(saved.sourceImport()).path("documents").get(0);
                assertThat(source.path("checks")).isEmpty();
                assertThat(source.path("last_verified_at").isNull()).isTrue();
                assertThat(source.path("latest_check_attempt_at").isNull()).isTrue();
                assertThat(source.path("use_review").asText()).isEqualTo("pending");
                assertThat(source.path("check_result").asText()).isEqualTo("unchecked");
                assertThat(source.path("raw_asset_path").asText()).isEqualTo("uploads/" + sha(raw) + "." + format);
                assertThat(source.path("text_sha256").asText()).isEqualTo(sha(bytes(source.path("cleaned_text").asText())));
                assertThat(Files.readAllBytes(roots.source().resolve(source.path("raw_asset_path").asText()))).isEqualTo(raw);
                JsonNode dbDocument = JSON.readTree(database.jdbc().queryForObject(
                        "SELECT metadata_json FROM document_versions WHERE document_version_id=?", String.class,
                        metadata.path("document_version_id").asText())).path("document");
                assertThat(dbDocument).isEqualTo(source);
                assertThat(first.path("input_hash").asText()).isEqualTo(sha(saved.aiInput()));
                validatePython(roots, saved.aiInput());
                if (format.equals("pdf")) {
                    assertThat(first.path("text_scope").asText()).isEqualTo("embedded_text_only");
                    assertThat(first.path("text_review_required").asBoolean()).isTrue();
                    assertThat(source.path("block_index")).hasSize(2);
                }
                var state = database();
                var originalFiles = files(roots);
                var again = jar.send(jar.request("127.0.0.1", true).POST(HttpRequest.BodyPublishers.ofByteArray(body)));
                assertThat(again.statusCode()).isEqualTo(200);
                var replay = JSON.readTree(again.body());
                assertThat(replay.path("input_hash")).isEqualTo(first.path("input_hash"));
                assertThat(replay.path("raw_sha256")).isEqualTo(first.path("raw_sha256"));
                assertThat(replay.path("data").path("already_imported").asBoolean()).isTrue();
                assertThat(database()).isEqualTo(state);
                assertThat(files(roots)).isEqualTo(originalFiles);
            }
            var beforeBlank = database();
            error(jar.send(jar.request("127.0.0.1", true).POST(HttpRequest.BodyPublishers.ofByteArray(multipart(
                    metadata(bytes(metadata("pdf").toString())), file("application/pdf", pdf(0, "first page", "")))))),
                    422, "PDF_PAGE_REVIEW_REQUIRED");
            assertThat(database()).isEqualTo(beforeBlank);
            assertPrivateFiles(roots);
            jar.awaitLogs();
        }
        safeLogs(jar);
    }

    @Test
    void acceptsAnActualTwentyMibPdfWithSmallEmbeddedTextAndRejectsOneExtraByte() throws Exception {
        var roots = roots();
        byte[] raw = sizedPdf(20 * MIB);
        assertThat(raw).hasSize(20 * MIB);
        var jar = start(roots, "local-api", true);
        try (jar) {
            byte[] metadata = bytes(metadata("pdf").toString());
            var response = jar.send(jar.request("127.0.0.1", true).POST(HttpRequest.BodyPublishers.ofByteArray(
                    multipart(metadata(metadata), file("application/pdf", raw)))));
            assertThat(response.statusCode()).isEqualTo(200);
            assertThat(JSON.readTree(response.body()).path("raw_sha256").asText()).isEqualTo(sha(raw));
            assertThat(Files.size(roots.source().resolve("uploads/" + sha(raw) + ".pdf"))).isEqualTo(20L * MIB);
            var before = database();
            var originalFiles = files(roots);
            byte[] oversized = multipart(metadata(bytes(metadata("pdf").toString())), file("application/pdf", Arrays.copyOf(raw, raw.length + 1)));
            var chunked = HttpRequest.BodyPublishers.ofInputStream(() -> new ByteArrayInputStream(oversized));
            assertThat(chunked.contentLength()).isEqualTo(-1);
            error(jar.send(jar.request("127.0.0.1", true).POST(chunked)), 413, null);
            assertThat(database()).isEqualTo(before);
            assertThat(files(roots)).isEqualTo(originalFiles);
            jar.awaitLogs();
        }
        safeLogs(jar);
    }

    @Test
    void missingOptionalPdfToolLeavesTextAndExistingJsonRegistrationWorking() throws Exception {
        var roots = roots();
        var jar = start(roots, "local-api", false);
        try (jar) {
            var metadata = metadata("txt");
            byte[] metaBytes = bytes(metadata.toString()), raw = bytes(PRIVATE + " optional-tool TXT");
            assertThat(jar.send(jar.request("127.0.0.1", true).POST(HttpRequest.BodyPublishers.ofByteArray(
                    multipart(metadata(metaBytes), file("text/plain", raw))))).statusCode()).isEqualTo(200);
            var stored = new SourceUploadStore(roots.source().toString(), roots.requests().toString())
                    .find(metadata.path("document_version_id").asText(), metaBytes, raw);
            var before = database();
            var existingJson = jar.send(jar.request("127.0.0.1", true).setHeader("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(stored.sourceImport())));
            assertThat(existingJson.statusCode()).isEqualTo(200);
            assertThat(JSON.readTree(existingJson.body()).path("data").path("already_imported").asBoolean()).isTrue();
            error(jar.send(jar.request("127.0.0.1", true).POST(HttpRequest.BodyPublishers.ofByteArray(multipart(
                    metadata(bytes(metadata("pdf").toString())), file("application/pdf", pdf(0, PRIVATE + " PDF")))))),
                    503, "PDF_TOOL_NOT_READY");
            assertThat(database()).isEqualTo(before);
            assertThat(jar.process.isAlive()).isTrue();
            jar.awaitLogs();
        }
        safeLogs(jar);
    }

    @Test
    void publicAndFixtureProfilesDoNotRegisterTheMultipartManagementRoute() throws Exception {
        for (String profile : List.of("public", "fixture")) {
            var roots = roots();
            var jar = start(roots, profile, false);
            try (jar) {
                var before = database();
                var originalFiles = files(roots);
                error(jar.send(jar.request("127.0.0.1", true).POST(HttpRequest.BodyPublishers.ofByteArray(multipart(
                        metadata(bytes(metadata("txt").toString())), file("text/plain", bytes(PRIVATE)))))), 404, "NOT_FOUND");
                byte[] largeFile = new byte[2 * MIB];
                Arrays.fill(largeFile, (byte) 'a');
                byte[] largeBody = multipart(metadata(bytes(metadata("txt").toString())), file("text/plain", largeFile));
                error(jar.send(jar.request("127.0.0.1", true).POST(HttpRequest.BodyPublishers.ofByteArray(largeBody))), 404, "NOT_FOUND");
                assertThat(database()).isEqualTo(before);
                assertThat(files(roots)).isEqualTo(originalFiles);
                jar.awaitLogs();
            }
            safeLogs(jar);
        }
    }

    @Test
    void coldDatabaseStartupReturnsOnlyTheCommonSafeJsonFailure() throws Exception {
        var roots = roots();
        var before = database();
        var originalFiles = files(roots);
        String token = "SYNTHETIC_UPLOAD_TOKEN_0123456789abcdef";
        Path stdout = root.resolve("cold.stdout"), stderr = root.resolve("cold.stderr");
        var builder = builder(roots, "local-api", 0, token, false, stdout, stderr,
                "--spring.datasource.url=jdbc:mysql://127.0.0.1:1/SYNTHETIC_PRIVATE_DATABASE?connectTimeout=100&socketTimeout=100",
                "--spring.datasource.hikari.connection-timeout=250");
        var process = builder.start();
        try {
            assertThat(process.waitFor(20, TimeUnit.SECONDS)).isTrue();
            assertThat(process.exitValue()).isEqualTo(4);
            String output = Files.readString(stdout);
            assertThat(output.lines().count()).isEqualTo(1);
            JsonNode response = JSON.readTree(output);
            assertThat(UUID.fromString(response.path("request_id").asText())).isNotNull();
            assertThat(response.path("error").path("code").asText()).isEqualTo("LOCAL_API_DATABASE_UNAVAILABLE");
            assertThat(response.path("error").path("retryable").asBoolean()).isTrue();
            assertThat(output + Files.readString(stderr)).doesNotContain(token, root.toRealPath().toString(), PRIVATE,
                    "jdbc:mysql", "Exception", "\tat ", database.password());
            assertThat(database()).isEqualTo(before);
            assertThat(files(roots)).isEqualTo(originalFiles);
        } finally { process.destroyForcibly(); assertThat(process.waitFor(5, TimeUnit.SECONDS)).isTrue(); }
    }

    private ObjectNode metadata(String format) {
        return JSON.createObjectNode().put("schema_version", "source-upload-v1").put("format", format).put("data_kind", "synthetic")
                .put("document_id", UUID.randomUUID().toString()).put("document_version_id", UUID.randomUUID().toString()).put("version_no", 1)
                .put("publisher", "합성 기관").put("official_url", "https://example.invalid/upload/1").put("title", "합성 공지")
                .putNull("official_number").putNull("published_date").put("collected_at", "2026-11-02T00:00:00Z")
                .put("collection_method", "synthetic fixture").put("use_note", PRIVATE + " not reviewed or approved");
    }

    private Roots roots() throws Exception {
        Path base = Files.createTempDirectory(root.toRealPath(), "jar-", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        return new Roots(directory(base.resolve("source")), directory(base.resolve("extraction")), directory(base.resolve("handoff")),
                directory(base.resolve("requests")), directory(base.resolve("servlet-temp")));
    }

    private RunningJar start(Roots roots, String profile, boolean pdf) throws Exception {
        int port;
        try (var socket = new ServerSocket()) {
            socket.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), 0));
            port = socket.getLocalPort();
        }
        String token = "SYNTHETIC_UPLOAD_TOKEN_" + UUID.randomUUID().toString().replace("-", "");
        Path stdout = roots.source().getParent().resolve("stdout"), stderr = roots.source().getParent().resolve("stderr");
        var jar = new RunningJar(builder(roots, profile, port, token, pdf, stdout, stderr).start(), roots, port, token, stdout, stderr);
        try {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(35);
            while (System.nanoTime() < deadline) {
                assertThat(jar.process.isAlive()).as("합성 업로드 JAR readiness 전 생존").isTrue();
                String ready = profile.equals("local-api") ? "/local/readiness" : "/health";
                try {
                    var response = jar.send(jar.request("127.0.0.1", false).uri(URI.create("http://127.0.0.1:" + port + ready))
                            .timeout(Duration.ofSeconds(2)).GET());
                    if (profile.equals("local-api")) error(response, 401, "LOCAL_API_UNAUTHORIZED");
                    else assertThat(response.statusCode()).isEqualTo(200);
                    jar.watch = new TempWatch(roots.temporary());
                    return jar;
                } catch (java.io.IOException notReady) { Thread.sleep(50); }
            }
            throw new AssertionError("합성 업로드 JAR readiness timeout");
        } catch (Exception | AssertionError error) { jar.close(); throw error; }
    }

    private ProcessBuilder builder(Roots roots, String profile, int port, String token, boolean pdf, Path stdout, Path stderr, String... settings) {
        var command = new ArrayList<>(List.of(Path.of(System.getProperty("java.home"), "bin", "java").toString(), "-Xmx512m",
                "-Djava.io.tmpdir=" + roots.temporary(), "-jar", "build/libs/myai-backend-0.1.0.jar", "--spring.profiles.active=" + profile,
                "--server.port=" + port, "--spring.main.banner-mode=off", "--logging.config=classpath:logback-local-import.xml",
                "--logging.level.root=OFF", "--logging.level.kr.ac.myai.backend.logging.PublicRequestLogFilter=INFO"));
        command.addAll(List.of(settings));
        var builder = new ProcessBuilder(command).redirectOutput(stdout.toFile()).redirectError(stderr.toFile());
        var env = builder.environment(); env.clear();
        env.put("DB_URL", database.url()); env.put("DB_USERNAME", database.username()); env.put("DB_PASSWORD", database.password());
        env.put("MYAI_LOCAL_API_TOKEN", token); env.put("MYAI_LOCAL_API_ACTOR", "synthetic-upload-actor");
        env.put("MYAI_LOCAL_API_SOURCE_ROOT", roots.source().toString()); env.put("MYAI_LOCAL_API_EXTRACTION_ROOT", roots.extraction().toString());
        env.put("MYAI_LOCAL_API_HANDOFF_ROOT", roots.handoff().toString()); env.put("MYAI_LOCAL_API_REQUEST_ROOT", roots.requests().toString());
        env.put("MYAI_LOCAL_API_PORT", Integer.toString(port)); env.put("MYAI_PYTHON_WORKDIR", PythonProbe.REPO.toString());
        env.put("MYAI_PYTHON_EXECUTABLE", python());
        if (pdf) env.put("MYAI_LOCAL_API_PDFTOTEXT", pdfTool());
        return builder;
    }

    private void validatePython(Roots roots, byte[] input) throws Exception {
        var builder = new ProcessBuilder(python(), "-c", "from processing.extraction.validation import parse_input; import sys; parse_input(sys.stdin.buffer.read()); print('valid')")
                .directory(PythonProbe.REPO.toFile());
        builder.environment().clear(); builder.environment().put("LANG", "C.UTF-8");
        Path stdout = roots.source().getParent().resolve("python.stdout"), stderr = roots.source().getParent().resolve("python.stderr");
        var process = builder.redirectOutput(stdout.toFile()).redirectError(stderr.toFile()).start();
        try {
            try (var stdin = process.getOutputStream()) { stdin.write(input); }
            assertThat(process.waitFor(10, TimeUnit.SECONDS)).isTrue();
            assertThat(process.exitValue()).isZero();
            assertThat(Files.readString(stdout).trim()).isEqualTo("valid");
            assertThat(Files.readString(stderr)).isEmpty();
        } finally { process.destroyForcibly(); assertThat(process.waitFor(3, TimeUnit.SECONDS)).isTrue(); }
    }

    private void error(HttpResponse<byte[]> response, int status, String code) throws Exception {
        assertThat(response.statusCode()).isEqualTo(status);
        assertThat(response.headers().firstValue("Content-Type").orElse("")).startsWith("application/json");
        var body = JSON.readTree(response.body());
        assertThat(body.path("error").path("code").asText()).isNotBlank();
        if (code != null) assertThat(body.path("error").path("code").asText()).isEqualTo(code);
        assertThat(body.path("error").path("field_errors").isArray()).isTrue();
        assertThat(body.path("error").path("retryable").asBoolean()).isEqualTo(status == 503);
        assertThat(body.path("request_id").asText()).isEqualTo(requestId(response));
    }

    private String requestId(HttpResponse<byte[]> response) {
        String id = response.headers().firstValue("X-Request-ID").orElse("");
        assertThat(UUID.fromString(id).toString()).isEqualTo(id);
        return id;
    }

    private void safeLogs(RunningJar jar) throws Exception {
        String stdout = Files.readString(jar.stdout), stderr = Files.readString(jar.stderr);
        assertThat(stdout).isEmpty();
        var rows = new ArrayList<JsonNode>();
        for (String line : stderr.lines().toList()) {
            int at = line.indexOf("public_request ");
            if (at >= 0) rows.add(JSON.readTree(line.substring(at + "public_request ".length())));
        }
        for (var response : jar.responses) {
            var matching = rows.stream().filter(row -> requestId(response).equals(row.path("request_id").asText())).toList();
            assertThat(matching).hasSize(1);
            var keys = new HashSet<String>(); matching.getFirst().fieldNames().forEachRemaining(keys::add);
            assertThat(keys).containsExactlyInAnyOrder("request_id", "error_code", "latency_ms", "snapshot_id", "rules_version");
            if (response.statusCode() >= 400) assertThat(matching.getFirst().path("error_code").asText())
                    .isEqualTo(JSON.readTree(response.body()).path("error").path("code").asText());
        }
        String visible = stdout + stderr + jar.responses.stream().map(response -> new String(response.body(), StandardCharsets.UTF_8)).reduce("", String::concat);
        assertThat(visible).doesNotContain(jar.token, PRIVATE, "SYNTHETIC_PRIVATE_CLIENT_ID", "SYNTHETIC_PRIVATE_FILENAME", root.toRealPath().toString(),
                database.password(), "jdbc:mysql", "Exception", "\tat ", "fixed@example.test", "031-123-4567");
    }

    private Map<String, List<String>> database() {
        var result = new TreeMap<String, List<String>>();
        for (String table : database.jdbc().queryForList("SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME", String.class)) {
            result.put(table, database.jdbc().queryForList("SELECT * FROM `" + table + "`").stream().map(row -> {
                var cells = new TreeMap<String, String>(); row.forEach((key, value) -> cells.put(key, value == null ? null : value.toString()));
                return JSON.valueToTree(cells).toString();
            }).sorted().toList());
        }
        return result;
    }

    private Map<String, String> files(Roots roots) throws Exception {
        var result = new TreeMap<String, String>();
        for (Path directory : List.of(roots.source(), roots.extraction(), roots.handoff(), roots.requests())) {
            try (var paths = Files.walk(directory)) {
                for (Path path : paths.sorted().toList()) result.put(directory.getFileName() + "/" + directory.relativize(path),
                        PosixFilePermissions.toString(Files.getPosixFilePermissions(path)) + (Files.isRegularFile(path) ? ":" + sha(Files.readAllBytes(path)) : ""));
            }
        }
        return result;
    }

    private void assertPrivateFiles(Roots roots) throws Exception {
        for (String value : files(roots).values()) assertThat(value).startsWith(value.contains(":") ? "rw-------:" : "rwx------");
    }

    private record Roots(Path source, Path extraction, Path handoff, Path requests, Path temporary) { }
    private record Part(String name, String filename, String type, byte[] bytes) { }
    private static Part metadata(byte[] bytes) { return part("metadata", null, "application/json;charset=UTF-8", bytes); }
    private static Part file(String type, byte[] bytes) { return part("file", "../../SYNTHETIC_PRIVATE_FILENAME", type, bytes); }
    private static Part part(String name, String filename, String type, byte[] bytes) { return new Part(name, filename, type, bytes); }

    private static byte[] multipart(Part... parts) throws Exception {
        var output = new ByteArrayOutputStream();
        for (var part : parts) {
            output.write(bytes("--" + BOUNDARY + "\r\nContent-Disposition: form-data; name=\"" + part.name() + "\""
                    + (part.filename() == null ? "" : "; filename=\"" + part.filename() + "\"") + "\r\nContent-Type: " + part.type() + "\r\n\r\n"));
            output.write(part.bytes()); output.write(bytes("\r\n"));
        }
        output.write(bytes("--" + BOUNDARY + "--\r\n"));
        return output.toByteArray();
    }

    private final class RunningJar implements AutoCloseable {
        final Process process; final Roots roots; final int port; final String token; final Path stdout, stderr;
        final List<HttpResponse<byte[]>> responses = new ArrayList<>();
        TempWatch watch;
        RunningJar(Process process, Roots roots, int port, String token, Path stdout, Path stderr) {
            this.process = process; this.roots = roots; this.port = port; this.token = token; this.stdout = stdout; this.stderr = stderr;
        }
        HttpRequest.Builder request(String host, boolean auth) {
            var request = HttpRequest.newBuilder(URI.create("http://" + host + ":" + port + "/local/documents"))
                    .timeout(Duration.ofSeconds(40)).header("Origin", "http://127.0.0.1:" + port)
                    .header("Content-Type", "multipart/form-data; boundary=" + BOUNDARY).header("X-Request-ID", "SYNTHETIC_PRIVATE_CLIENT_ID");
            if (auth) request.header("Authorization", "Bearer " + token);
            return request;
        }
        HttpResponse<byte[]> send(HttpRequest.Builder request) throws Exception {
            var response = http.send(request.build(), HttpResponse.BodyHandlers.ofByteArray()); responses.add(response); return response;
        }
        void awaitLogs() throws Exception {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
            while (System.nanoTime() < deadline) {
                if (Files.readString(stderr).lines().filter(line -> line.contains("public_request ")).count() >= responses.size()) return;
                Thread.sleep(10);
            }
            throw new AssertionError("완료한 업로드 요청의 최소 로그가 기록되지 않음");
        }
        @Override public void close() throws Exception {
            try {
                // 완료한 요청의 관찰을 먼저 끝내 Tomcat의 정상 디렉터리 삭제와 경합하지 않는다.
                if (watch != null) watch.close();
            } finally {
                process.destroy();
                if (!process.waitFor(10, TimeUnit.SECONDS)) { process.destroyForcibly(); assertThat(process.waitFor(5, TimeUnit.SECONDS)).isTrue(); }
            }
        }
    }

    private static final class TempWatch implements AutoCloseable {
        final AtomicBoolean running = new AtomicBoolean(true);
        final Set<Path> observed = ConcurrentHashMap.newKeySet();
        final AtomicReference<Throwable> error = new AtomicReference<>();
        final Thread worker;
        TempWatch(Path temporary) throws Exception {
            Set<Path> baseline;
            try (var paths = Files.walk(temporary)) { baseline = new HashSet<>(paths.filter(Files::isRegularFile).toList()); }
            worker = Thread.ofPlatform().name("synthetic-servlet-temp-watch").daemon(true).start(() -> {
                try {
                    while (running.get()) {
                        try (var paths = Files.walk(temporary)) { paths.filter(Files::isRegularFile).filter(path -> !baseline.contains(path)).forEach(observed::add); }
                        Thread.sleep(2);
                    }
                } catch (Throwable failure) { error.set(failure); }
            });
        }
        @Override public void close() throws Exception {
            running.set(false); worker.join(3_000);
            assertThat(worker.isAlive()).isFalse();
            assertThat(error.get()).isNull();
            assertThat(observed).as("servlet이 원문을 임시 파일로 쓰지 않아야 함").isEmpty();
        }
    }

    private static byte[] sizedPdf(int target) throws Exception {
        int padding = 0;
        byte[] result = pdf(padding, PRIVATE + " twenty MiB PDF");
        while (result.length != target) { padding += target - result.length; result = pdf(padding, PRIVATE + " twenty MiB PDF"); }
        return result;
    }

    private static byte[] pdf(int commentSize, String... pages) throws Exception {
        var objects = new ArrayList<String>();
        objects.add("<< /Type /Catalog /Pages 2 0 R >>");
        var kids = new ArrayList<String>(); for (int i = 0; i < pages.length; i++) kids.add((4 + i) + " 0 R");
        objects.add("<< /Type /Pages /Kids [" + String.join(" ", kids) + "] /Count " + pages.length + " >>");
        objects.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
        for (int i = 0; i < pages.length; i++) objects.add("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents " + (4 + pages.length + i) + " 0 R >>");
        for (String page : pages) {
            String stream = page.isEmpty() ? "" : "BT /F1 12 Tf 50 700 Td (" + page + ") Tj ET\n";
            objects.add("<< /Length " + stream.length() + " >>\nstream\n" + stream + "endstream");
        }
        var output = new ByteArrayOutputStream(); output.write(bytes("%PDF-1.4\n%"));
        byte[] comment = new byte[commentSize]; Arrays.fill(comment, (byte) 'x'); output.write(comment); output.write('\n');
        var offsets = new ArrayList<Integer>();
        for (int i = 0; i < objects.size(); i++) { offsets.add(output.size()); output.write(bytes((i + 1) + " 0 obj\n" + objects.get(i) + "\nendobj\n")); }
        int xref = output.size(); output.write(bytes("xref\n0 " + (objects.size() + 1) + "\n0000000000 65535 f \n"));
        for (int offset : offsets) output.write(bytes(String.format(java.util.Locale.ROOT, "%010d 00000 n \n", offset)));
        output.write(bytes("trailer\n<< /Size " + (objects.size() + 1) + " /Root 1 0 R >>\nstartxref\n" + xref + "\n%%EOF\n"));
        return output.toByteArray();
    }

    private static Path directory(Path path) throws Exception {
        return Files.createDirectory(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
    }
    private static byte[] bytes(String text) { return text.getBytes(StandardCharsets.UTF_8); }
    private static String sha(byte[] bytes) { return ReviewedImportReader.sha256(bytes); }
    private static String media(String format) { return switch (format) { case "txt" -> "text/plain"; case "json" -> "application/json"; default -> "application/pdf"; }; }
    private static String pdfTool() {
        String configured = System.getenv("MYAI_LOCAL_API_PDFTOTEXT");
        if (configured != null && !configured.isBlank()) return configured;
        for (String value : List.of("/opt/homebrew/bin/pdftotext", "/usr/local/bin/pdftotext", "/usr/bin/pdftotext")) if (Files.isExecutable(Path.of(value))) return value;
        throw new AssertionError("Set absolute MYAI_LOCAL_API_PDFTOTEXT for actual JAR upload tests");
    }
    private static String python() {
        Path configured = Path.of(PythonProbe.PYTHON);
        if (configured.isAbsolute()) return configured.toString();
        for (String entry : System.getenv().getOrDefault("PATH", "").split(java.io.File.pathSeparator)) {
            Path candidate = Path.of(entry).resolve(configured);
            if (Files.isExecutable(candidate)) return candidate.toAbsolutePath().normalize().toString();
        }
        throw new AssertionError("Set MYAI_PYTHON_EXECUTABLE for actual input validation");
    }
}
