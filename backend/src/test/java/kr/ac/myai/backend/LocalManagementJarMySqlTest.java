package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import java.io.ByteArrayInputStream;
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
import java.security.MessageDigest;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

@SpringBootTest
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class LocalManagementJarMySqlTest {
    @TempDir Path root;
    @Autowired JdbcTemplate jdbc;
    @Autowired ReviewedImportReader reader;
    @Autowired ReviewedImportService importer;
    private final ObjectMapper mapper = new ObjectMapper();
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1))
            .version(HttpClient.Version.HTTP_1_1).followRedirects(HttpClient.Redirect.NEVER).build();

    @DynamicPropertySource
    static void python(DynamicPropertyRegistry properties) {
        properties.add("app.calculation.workdir", () -> PythonProbe.REPO.toString());
        properties.add("app.calculation.python-executable", () -> PythonProbe.PYTHON);
    }

    @AfterEach
    void closeHttpClient() { http.close(); }

    @Test
    void actualLocalJarAuthenticatesImportsExactBytesAndKeepsDuplicatesAndLogsSafe() throws Exception {
        var directories = privateRoots();
        var fixtures = new SourceReviewFixtures(directories.source(), jdbc, reader, importer);
        var source = fixtures.source(true);
        String privateMarker = "SYNTHETIC_PRIVATE_JAR_BODY_" + UUID.randomUUID();
        SourceReviewFixtures.document(source).put("use_note", privateMarker);
        byte[] body = ("\n  " + mapper.writerWithDefaultPrettyPrinter().writeValueAsString(source) + "\n").getBytes(StandardCharsets.UTF_8);
        byte[] original = Files.readAllBytes(directories.source().resolve("synthetic-source.txt"));
        var before = database();
        var filesBefore = files(directories);
        var jar = start(directories);
        try (jar) {
            error(jar.send(jar.request("/local/documents", false).header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(body))), 401, "LOCAL_API_UNAUTHORIZED");
            error(jar.send(jar.request("/local/documents", true).setHeader("Origin", "http://localhost:" + jar.port)
                    .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofByteArray(body))),
                    403, "LOCAL_API_FORBIDDEN");
            for (String path : List.of("/local/unknown", "/api/v1/config", "/health")) {
                error(jar.send(jar.request(path, true).GET()), 404, "NOT_FOUND");
            }
            assertThat(database()).isEqualTo(before);
            assertThat(files(directories)).isEqualTo(filesBefore);

            var response = jar.send(jar.request("/local/documents", true).header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(body)));
            assertThat(response.statusCode()).isEqualTo(200);
            var result = mapper.readTree(response.body());
            String checksum = sha256(body);
            assertThat(result.path("schema_version").asText()).isEqualTo("local-management-result-v1");
            assertThat(result.path("request_sha256").asText()).isEqualTo(checksum);
            assertThat(result.path("data").path("already_imported").asBoolean()).isFalse();
            assertThat(result.path("data").path("revision_ids")).isEmpty();
            assertThat(result.path("data").path("document_version_ids").get(0).asText()).isEqualTo(SourceReviewFixtures.version(source));
            Path retained = directories.requests().resolve(checksum + ".json");
            assertThat(Files.readAllBytes(retained)).isEqualTo(body);
            assertThat(Files.getPosixFilePermissions(retained)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
            var modified = Files.getLastModifiedTime(retained);
            var imported = database();
            assertThat(imported.keySet()).isEqualTo(before.keySet());
            for (String table : before.keySet()) {
                assertThat(imported.get(table)).containsAll(before.get(table));
                if (Set.of("documents", "document_versions", "import_batches").contains(table)) {
                    assertThat(imported.get(table)).hasSize(before.get(table).size() + 1);
                } else {
                    assertThat(imported.get(table)).isEqualTo(before.get(table));
                }
            }
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM document_versions WHERE document_version_id=?",
                    Long.class, SourceReviewFixtures.version(source))).isEqualTo(1L);

            var repeated = jar.send(jar.request("/local/documents", true).header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(body)));
            assertThat(repeated.statusCode()).isEqualTo(200);
            var duplicate = mapper.readTree(repeated.body());
            assertThat(duplicate.path("request_sha256").asText()).isEqualTo(checksum);
            assertThat(duplicate.path("data").path("already_imported").asBoolean()).isTrue();
            assertThat(duplicate.path("data").path("import_id")).isEqualTo(result.path("data").path("import_id"));
            assertThat(database()).isEqualTo(imported);
            assertThat(Files.getLastModifiedTime(retained)).isEqualTo(modified);
            assertThat(Files.readAllBytes(retained)).isEqualTo(body);
            try (var entries = Files.list(directories.requests())) { assertThat(entries.toList()).containsExactly(retained); }
            assertThat(Files.readAllBytes(directories.source().resolve("synthetic-source.txt"))).isEqualTo(original);
            assertThat(jar.process.isAlive()).isTrue();
            jar.awaitLogs();
        }
        assertSafeLogs(jar, privateMarker, new String(original, StandardCharsets.UTF_8));
    }

    @Test
    void actualLocalJarRejectsChunkedOversizeAndUnsupportedMediaWithoutChangingExistingData() throws Exception {
        var directories = privateRoots();
        var fixtures = new SourceReviewFixtures(directories.source(), jdbc, reader, importer);
        var source = fixtures.source(true);
        fixtures.register(source);
        var before = database();
        var filesBefore = files(directories);
        String privateMarker = "SYNTHETIC_PRIVATE_CHUNKED_BODY";
        byte[] oversized = new byte[8 * 1024 * 1024 + 1];
        Arrays.fill(oversized, (byte) ' ');
        byte[] marker = privateMarker.getBytes(StandardCharsets.UTF_8);
        System.arraycopy(marker, 0, oversized, 0, marker.length);
        var chunked = HttpRequest.BodyPublishers.ofInputStream(() -> new ByteArrayInputStream(oversized));
        assertThat(chunked.contentLength()).isEqualTo(-1);
        var jar = start(directories);
        try (jar) {
            for (String path : List.of("/api/v1/config", "/health")) {
                error(jar.send(jar.request(path, true).GET()), 404, "NOT_FOUND");
            }
            error(jar.send(jar.request("/local/documents", true).header("Content-Type", "application/json").POST(chunked)),
                    413, "PAYLOAD_TOO_LARGE");
            error(jar.send(jar.request("/local/documents", true).header("Content-Type", "text/plain")
                    .POST(HttpRequest.BodyPublishers.ofString(privateMarker, StandardCharsets.UTF_8))), 415, "UNSUPPORTED_MEDIA_TYPE");
            assertThat(jar.process.isAlive()).isTrue();
            assertThat(database()).isEqualTo(before);
            assertThat(files(directories)).isEqualTo(filesBefore);
            jar.awaitLogs();
        }
        assertSafeLogs(jar, privateMarker, SourceReviewFixtures.document(source).path("cleaned_text").asText());
    }

    @Test
    void actualLocalJarReturnsSafeStartupErrorsForColdDatabaseAndMissingDriver() throws Exception {
        var directories = privateRoots();
        var before = database();
        var filesBefore = files(directories);
        String unavailable = "--spring.datasource.url=jdbc:mysql://127.0.0.1:1/SYNTHETIC_PRIVATE_DATABASE?connectTimeout=100&socketTimeout=100";
        failedStartup(directories, 4, "LOCAL_API_DATABASE_UNAVAILABLE", true,
                unavailable, "--spring.datasource.hikari.connection-timeout=250");
        failedStartup(directories, 1, "LOCAL_API_INTERNAL_ERROR", false,
                unavailable, "--spring.datasource.driver-class-name=SYNTHETIC_PRIVATE_DRIVER");
        assertThat(database()).isEqualTo(before);
        assertThat(files(directories)).isEqualTo(filesBefore);
    }

    private Roots privateRoots() throws Exception {
        Path directory = root.toRealPath().resolve("data/private");
        var paths = new ArrayList<Path>();
        for (String name : List.of("source", "extraction", "handoff", "requests")) {
            Path path = Files.createDirectories(directory.resolve(name));
            Files.setPosixFilePermissions(path, PosixFilePermissions.fromString("rwx------"));
            paths.add(path);
        }
        return new Roots(paths.get(0), paths.get(1), paths.get(2), paths.get(3));
    }

    private RunningJar start(Roots directories) throws Exception {
        int port;
        try (var socket = new ServerSocket()) {
            socket.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), 0));
            port = socket.getLocalPort();
        }
        String token = "SYNTHETIC_LOCAL_JAR_TOKEN_" + UUID.randomUUID().toString().replace("-", "");
        Path stdout = root.resolve("local-api.stdout"), stderr = root.resolve("local-api.stderr");
        var jar = new RunningJar(builder(directories, port, token, stdout, stderr).start(), port, token, stdout, stderr);
        try {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(30);
            while (System.nanoTime() < deadline) {
                assertThat(jar.process.isAlive()).as("합성 local-api JAR가 readiness 전에 종료됨").isTrue();
                try {
                    var response = jar.send(jar.request("/local/readiness", false).timeout(Duration.ofSeconds(2)).GET());
                    error(response, 401, "LOCAL_API_UNAUTHORIZED");
                    return jar;
                } catch (IOException notReady) {
                    Thread.sleep(50);
                }
            }
            throw new AssertionError("합성 local-api JAR가 readiness 제한 시간 내 응답하지 않음");
        } catch (Exception | AssertionError failure) {
            jar.close();
            throw failure;
        }
    }

    private void failedStartup(Roots directories, int exit, String code, boolean retryable, String... settings) throws Exception {
        String token = "SYNTHETIC_LOCAL_JAR_TOKEN_" + UUID.randomUUID().toString().replace("-", "");
        String name = UUID.randomUUID().toString();
        Path stdout = root.resolve(name + ".stdout"), stderr = root.resolve(name + ".stderr");
        var process = builder(directories, 0, token, stdout, stderr, settings).start();
        try {
            assertThat(process.waitFor(20, TimeUnit.SECONDS)).as("접속·driver 실패 JAR 종료").isTrue();
            assertThat(process.exitValue()).isEqualTo(exit);
            String output = Files.readString(stdout);
            assertThat(output.lines().count()).isEqualTo(1);
            var response = mapper.readTree(output);
            assertThat(UUID.fromString(response.path("request_id").asText())).isNotNull();
            assertThat(response.path("error").path("code").asText()).isEqualTo(code);
            assertThat(response.path("error").path("retryable").asBoolean()).isEqualTo(retryable);
            assertThat(response.path("error").path("field_errors").isArray()).isTrue();
            String visible = output + Files.readString(stderr);
            for (String forbidden : List.of(token, root.toRealPath().toString(), "SYNTHETIC_PRIVATE", "jdbc:mysql", "Exception", "\tat ", System.getenv("DB_PASSWORD"))) {
                assertThat(visible.contains(forbidden)).as("기동 오류의 비공개 값·stack 비노출").isFalse();
            }
        } finally {
            if (process.isAlive()) {
                process.destroyForcibly();
                assertThat(process.waitFor(5, TimeUnit.SECONDS)).as("실패 시험 JAR 종료").isTrue();
            }
        }
    }

    private ProcessBuilder builder(Roots directories, int port, String token, Path stdout, Path stderr, String... settings) {
        var command = new ArrayList<>(List.of(Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                "-jar", "build/libs/myai-backend-0.1.0.jar", "--spring.profiles.active=local-api"));
        command.addAll(List.of(settings));
        var builder = new ProcessBuilder(command).redirectOutput(stdout.toFile()).redirectError(stderr.toFile());
        var environment = builder.environment();
        environment.clear();
        for (String name : List.of("DB_URL", "DB_USERNAME", "DB_PASSWORD")) {
            String value = System.getenv(name);
            assertThat(value != null && !value.isBlank()).as("격리 시험용 %s 설정 필요", name).isTrue();
            environment.put(name, value);
        }
        environment.put("MYAI_LOCAL_API_TOKEN", token);
        environment.put("MYAI_LOCAL_API_ACTOR", "synthetic-jar-actor");
        environment.put("MYAI_LOCAL_API_SOURCE_ROOT", directories.source().toString());
        environment.put("MYAI_LOCAL_API_EXTRACTION_ROOT", directories.extraction().toString());
        environment.put("MYAI_LOCAL_API_HANDOFF_ROOT", directories.handoff().toString());
        environment.put("MYAI_LOCAL_API_REQUEST_ROOT", directories.requests().toString());
        environment.put("MYAI_LOCAL_API_PORT", Integer.toString(port));
        environment.put("MYAI_PYTHON_EXECUTABLE", PythonProbe.PYTHON);
        environment.put("MYAI_PYTHON_WORKDIR", PythonProbe.REPO.toString());
        return builder;
    }

    private void error(HttpResponse<byte[]> response, int status, String code) throws Exception {
        assertThat(response.statusCode()).isEqualTo(status);
        assertThat(response.headers().firstValue("Content-Type").orElse("")).startsWith("application/json");
        var body = mapper.readTree(response.body());
        assertThat(body.path("error").path("code").asText()).isEqualTo(code);
        assertThat(body.path("error").path("field_errors").isArray()).isTrue();
        assertThat(body.path("error").path("retryable").asBoolean()).isFalse();
        assertThat(body.path("request_id").asText()).isEqualTo(requestId(response));
    }

    private String requestId(HttpResponse<byte[]> response) {
        String id = response.headers().firstValue("X-Request-ID").orElse("");
        assertThat(UUID.fromString(id).toString()).isEqualTo(id);
        return id;
    }

    private void assertSafeLogs(RunningJar jar, String privateMarker, String rawText) throws Exception {
        String stdout = Files.readString(jar.stdout), stderr = Files.readString(jar.stderr);
        assertThat(stdout.isEmpty()).as("local-api 정상 실행은 stdout에 본문·설정을 쓰지 않음").isTrue();
        var rows = new ArrayList<JsonNode>();
        for (String line : stderr.lines().toList()) {
            int at = line.indexOf("public_request ");
            if (at >= 0) rows.add(mapper.readTree(line.substring(at + "public_request ".length())));
        }
        assertThat(rows).hasSize(jar.responses.size());
        var ids = new HashSet<String>();
        for (var response : jar.responses) {
            String id = requestId(response);
            assertThat(ids.add(id)).isTrue();
            var matching = rows.stream().filter(row -> id.equals(row.path("request_id").asText())).toList();
            assertThat(matching).hasSize(1);
            var row = matching.getFirst();
            var fields = new HashSet<String>();
            row.fieldNames().forEachRemaining(fields::add);
            assertThat(fields).containsExactlyInAnyOrder("request_id", "error_code", "latency_ms", "snapshot_id", "rules_version");
            assertThat(row.path("latency_ms").asLong()).isGreaterThanOrEqualTo(0);
            assertThat(row.path("snapshot_id").isNull()).isTrue();
            assertThat(row.path("rules_version").isNull()).isTrue();
            if (response.statusCode() >= 400) {
                assertThat(row.path("error_code").asText()).isEqualTo(mapper.readTree(response.body()).path("error").path("code").asText());
            } else {
                assertThat(row.path("error_code").isNull()).isTrue();
            }
        }
        String visible = stdout + stderr + jar.responses.stream()
                .map(response -> new String(response.body(), StandardCharsets.UTF_8)).reduce("", String::concat);
        for (String forbidden : List.of(jar.token, privateMarker, rawText, root.toRealPath().toString(),
                "SYNTHETIC_PRIVATE_CLIENT_ID", "jdbc:mysql", "Exception", "\tat ", System.getenv("DB_PASSWORD"))) {
            assertThat(visible.contains(forbidden)).as("로그·HTTP 응답의 비공개 값·stack 비노출").isFalse();
        }
        for (String line : rawText.lines().filter(value -> !value.isBlank()).toList()) {
            assertThat(visible.contains(line)).as("로그·HTTP 응답의 원문 비노출").isFalse();
        }
    }

    private Map<String, List<String>> database() {
        var result = new TreeMap<String, List<String>>();
        for (String table : jdbc.queryForList("SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME", String.class)) {
            var rows = jdbc.queryForList("SELECT * FROM `" + table + "`").stream().map(row -> {
                var cells = new TreeMap<String, String>();
                row.forEach((key, value) -> cells.put(key, value == null ? null : value.toString()));
                return mapper.valueToTree(cells).toString();
            }).sorted().toList();
            result.put(table, rows);
        }
        return result;
    }

    private Map<String, String> files(Roots directories) throws Exception {
        var result = new TreeMap<String, String>();
        for (Path directory : List.of(directories.source(), directories.extraction(), directories.handoff(), directories.requests())) {
            try (var entries = Files.walk(directory)) {
                for (Path entry : entries.sorted().toList()) {
                    String mode = PosixFilePermissions.toString(Files.getPosixFilePermissions(entry));
                    result.put(directory.getFileName() + "/" + directory.relativize(entry),
                            mode + (Files.isRegularFile(entry) ? ":" + sha256(Files.readAllBytes(entry)) : ""));
                }
            }
        }
        return result;
    }

    private String sha256(byte[] content) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content));
    }

    private record Roots(Path source, Path extraction, Path handoff, Path requests) {}

    private final class RunningJar implements AutoCloseable {
        final Process process;
        final int port;
        final String token;
        final Path stdout, stderr;
        final List<HttpResponse<byte[]>> responses = new ArrayList<>();

        RunningJar(Process process, int port, String token, Path stdout, Path stderr) {
            this.process = process; this.port = port; this.token = token; this.stdout = stdout; this.stderr = stderr;
        }

        HttpRequest.Builder request(String path, boolean authenticated) {
            String origin = "http://127.0.0.1:" + port;
            var request = HttpRequest.newBuilder(URI.create(origin + path)).timeout(Duration.ofSeconds(15))
                    .header("Origin", origin).header("X-Request-ID", "SYNTHETIC_PRIVATE_CLIENT_ID");
            if (authenticated) request.header("Authorization", "Bearer " + token);
            return request;
        }

        HttpResponse<byte[]> send(HttpRequest.Builder request) throws Exception {
            var response = http.send(request.build(), HttpResponse.BodyHandlers.ofByteArray());
            responses.add(response);
            return response;
        }

        void awaitLogs() throws Exception {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
            while (System.nanoTime() < deadline) {
                if (Files.readString(stderr).lines().filter(line -> line.contains("public_request ")).count() >= responses.size()) return;
                assertThat(process.isAlive()).as("로그 기록 전 합성 JAR 생존").isTrue();
                Thread.sleep(10);
            }
            throw new AssertionError("완료한 HTTP 요청의 최소 로그가 기록되지 않음");
        }

        @Override public void close() throws Exception {
            if (process.isAlive()) {
                process.destroy();
                if (!process.waitFor(10, TimeUnit.SECONDS)) {
                    process.destroyForcibly();
                    assertThat(process.waitFor(5, TimeUnit.SECONDS)).as("시험이 시작한 JAR 종료").isTrue();
                }
            }
        }
    }
}
