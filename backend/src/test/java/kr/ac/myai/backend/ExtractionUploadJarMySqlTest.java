package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
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
class ExtractionUploadJarMySqlTest {
    private static final int MIB = 1024 * 1024, CONTROL = 64 * 1024;
    private static final String BASE = "/local/extractions/uploads";
    private static final String BOUNDARY = "myai-synthetic-extraction-boundary";
    private static final String PRIVATE = "SYNTHETIC_EXTRACTION_PRIVATE_MARKER";
    private static final ObjectMapper JSON = new ObjectMapper();
    @TempDir static Path databaseRoot;
    @TempDir Path root;
    private static RecoveryDatabase database;
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1))
            .version(HttpClient.Version.HTTP_1_1).followRedirects(HttpClient.Redirect.NEVER).build();

    @BeforeAll static void startDatabase() throws Exception {
        Files.setPosixFilePermissions(databaseRoot, PosixFilePermissions.fromString("rwx------"));
        database = RecoveryDatabase.start(databaseRoot.toRealPath());
    }
    @AfterAll static void stopDatabase() { if (database != null) database.close(); }
    @AfterEach void cleanup() throws Exception { http.close(); ExtractionArchiveReaderTest.unseal(root); }

    @Test
    void actualHttpAndKeylessPythonPreserveOneAndThreeAttemptsAndReuseSealedDatabaseRegistration() throws Exception {
        var roots = roots(); var jar = start(roots, "local-api");
        try (jar) {
            for (int count : List.of(1, 3)) {
                var fixture = count == 1 ? fixture((byte[]) null) : fixture(bytes("not-json"), new byte[] {(byte) 0xff}, null);
                registerSource(jar, fixture);
                var protectedRows = database(); protectedRows.remove("extraction_runs");
                stage(jar, fixture);
                assertThat(database.jdbc().queryForObject("SELECT COUNT(*) FROM extraction_runs WHERE run_id=?", Integer.class, fixture.run())).isZero();
                byte[] control = bytes("\n" + JSON.readTree(fixture.control()).toPrettyString() + "\n ");
                finalResult(finalizeUpload(jar, fixture.run(), control), fixture, control, "validated", false);
                originals(roots, fixture, "validated");
                var after = database(); after.remove("extraction_runs"); assertThat(after).isEqualTo(protectedRows);
                var beforeReplay = database(); var files = files(roots);
                finalResult(finalizeUpload(jar, fixture.run(), control), fixture, control, "validated", true);
                assertThat(database()).isEqualTo(beforeReplay); assertThat(files(roots)).isEqualTo(files);
                assertThat(Files.readAllBytes(roots.requests().resolve(sha(control) + ".json"))).isEqualTo(control);
                error(slot(jar, fixture.run(), 1, "prompt", bytes("changed")), 409, null);
                assertThat(files(roots)).isEqualTo(files); assertThat(database()).isEqualTo(beforeReplay);
            }
            keyless(roots);
            jar.awaitLogs();
        }
        safeLogs(jar);
    }

    @Test
    void failedEmptyInvalidUtf8AndExactFiveMibOutputReturn200AndKeepFullTwentyMibPrompt() throws Exception {
        var roots = roots(); var jar = start(roots, "local-api");
        try (jar) {
            var failures = fixture(bytes("{broken"), new byte[0], new byte[] {(byte) 0xff, 0});
            registerSource(jar, failures); stage(jar, failures);
            finalResult(finalizeUpload(jar, failures.run(), failures.control()), failures, failures.control(), "failed", false);
            originals(roots, failures, "failed");
            var receipt = JSON.readTree(roots.extraction().resolve(failures.run()).resolve("receipt.json").toFile());
            assertThat(receipt.path("attempts")).hasSize(3).allSatisfy(attempt ->
                    assertThat(attempt.path("status").asText()).isEqualTo("failed"));
            var large = fixture(padded(bytes(PRIVATE), 5 * MIB));
            large = new Fixture(large.run(), large.control(), large.metadata(), large.input(),
                    List.of(padded(bytes(PRIVATE + " prompt"), 20 * MIB)), large.outputs());
            registerSource(jar, large); stage(jar, large);
            finalResult(finalizeUpload(jar, large.run(), large.control()), large, large.control(), "failed", false);
            originals(roots, large, "failed");
            var before = database(); var originalFiles = files(roots);
            finalResult(finalizeUpload(jar, large.run(), large.control()), large, large.control(), "failed", true);
            assertThat(database()).isEqualTo(before); assertThat(files(roots)).isEqualTo(originalFiles);
            noEventsOrPublication(); jar.awaitLogs();
        }
        safeLogs(jar);
    }

    @Test
    void allThreeRoutesEnforceStreamLimitsWithoutChangingExistingStageOrDatabase() throws Exception {
        var roots = roots(); var jar = start(roots, "local-api");
        try (jar) {
            var fixture = fixture((byte[]) null);
            byte[] input = padded(fixture.input(), 8 * MIB);
            fixture = new Fixture(fixture.run(), padded(control(fixture.run(), input), CONTROL), padded(fixture.metadata(), CONTROL),
                    input, fixture.prompts(), fixture.outputs());
            staged(initialize(jar, fixture), fixture, initial(fixture));
            var before = database(); var originalFiles = files(roots);
            for (String field : List.of("control", "metadata", "input")) {
                byte[] control = fixture.control(), metadata = fixture.metadata(), raw = fixture.input();
                if (field.equals("control")) control = padded(control, CONTROL + 1);
                if (field.equals("metadata")) metadata = padded(metadata, CONTROL + 1);
                if (field.equals("input")) raw = padded(raw, 8 * MIB + 1);
                error(jar.send(multipartRequest(jar, BASE, true).POST(chunked(multipart(
                        json("control", control), json("metadata", metadata), part("input", "application/json", raw))))), 413, null);
            }
            error(slot(jar, fixture.run(), 1, "output", new byte[5 * MIB + 1]), 413, null);
            error(slot(jar, fixture.run(), 1, "prompt", new byte[20 * MIB + 1]), 413, null);
            error(jar.send(jsonRequest(jar, BASE + "/" + fixture.run() + "/finalize", true)
                    .POST(chunked(padded(fixture.control(), CONTROL + 1)))), 413, "EXTRACTION_UPLOAD_TOO_LARGE");
            byte[] aggregate = multipart(part("file", "application/octet-stream", new byte[20 * MIB]),
                    part("extra", "application/octet-stream", new byte[MIB]));
            assertThat(aggregate.length).isGreaterThan(21 * MIB);
            error(jar.send(multipartRequest(jar, slotPath(fixture.run(), 1, "prompt"), true).PUT(chunked(aggregate))), 413, "EXTRACTION_UPLOAD_TOO_LARGE");
            assertThat(database()).isEqualTo(before); assertThat(files(roots)).isEqualTo(originalFiles);
            jar.awaitLogs();
        }
        safeLogs(jar);
    }

    @Test
    void authenticatesBeforeMultipartParsingAndRejectsPartsMediaOriginAndAcceptWithoutSpooling() throws Exception {
        var roots = roots(); var jar = start(roots, "local-api");
        try (jar) {
            var fixture = fixture((byte[]) null);
            staged(initialize(jar, fixture), fixture, initial(fixture));
            var before = database(); var originalFiles = files(roots);
            // 깨진 multipart가401이면 multipart parsing보다 인증이 먼저다.
            error(jar.send(multipartRequest(jar, BASE, false).POST(chunked(bytes("invalid multipart")))), 401, "LOCAL_API_UNAUTHORIZED");
            error(jar.send(multipartRequest(jar, slotPath(fixture.run(), 1, "prompt"), false)
                    .PUT(chunked(bytes("invalid multipart")))), 401, "LOCAL_API_UNAUTHORIZED");
            error(jar.send(jsonRequest(jar, BASE + "/" + fixture.run() + "/finalize", false)
                    .POST(HttpRequest.BodyPublishers.ofByteArray(bytes("{")))), 401, "LOCAL_API_UNAUTHORIZED");
            error(jar.send(multipartRequest(jar, BASE, true).POST(chunked(bytes("invalid multipart")))),
                    422, "INVALID_REQUEST");
            error(jar.send(multipartRequest(jar, BASE, true).setHeader("Origin", "http://localhost:" + jar.port)
                    .POST(HttpRequest.BodyPublishers.ofByteArray(new byte[0]))), 403, "LOCAL_API_FORBIDDEN");
            error(jar.send(multipartRequest(jar, BASE, true).uri(URI.create("http://localhost:" + jar.port + BASE))
                    .POST(HttpRequest.BodyPublishers.ofByteArray(new byte[0]))), 403, "LOCAL_API_FORBIDDEN");
            for (byte[] malformed : List.of(
                    multipart(json("metadata", fixture.metadata()), part("input", "application/json", fixture.input())),
                    multipart(json("control", fixture.control()), json("control", fixture.control()), json("metadata", fixture.metadata()), part("input", "application/json", fixture.input())),
                    multipart(json("control", fixture.control()), json("metadata", fixture.metadata()), part("input", "application/json", fixture.input()), part("extra", "text/plain", bytes(PRIVATE))))) {
                error(jar.send(multipartRequest(jar, BASE, true).POST(HttpRequest.BodyPublishers.ofByteArray(malformed))), 422, null);
            }
            for (String field : List.of("control", "metadata", "input")) {
                byte[] body = multipart(part("control", field.equals("control") ? "text/plain" : "application/json", fixture.control()),
                        part("metadata", field.equals("metadata") ? "application/json;charset=UTF-16" : "application/json", fixture.metadata()),
                        part("input", field.equals("input") ? "text/plain" : "application/json", fixture.input()));
                error(jar.send(multipartRequest(jar, BASE, true).POST(HttpRequest.BodyPublishers.ofByteArray(body))), 415, "UNSUPPORTED_MEDIA_TYPE");
            }
            error(jar.send(multipartRequest(jar, slotPath(fixture.run(), 1, "prompt"), true).PUT(HttpRequest.BodyPublishers.ofByteArray(
                    multipart(part("file", "application/json", bytes(PRIVATE)))))), 415, "UNSUPPORTED_MEDIA_TYPE");
            error(jar.send(multipartRequest(jar, slotPath(fixture.run(), 1, "prompt"), true).PUT(HttpRequest.BodyPublishers.ofByteArray(
                    multipart(part("file", "text/plain", bytes(PRIVATE)), part("file", "text/plain", bytes(PRIVATE)))))), 422, null);
            error(jar.send(jsonRequest(jar, BASE + "/" + fixture.run() + "/finalize", true)
                    .setHeader("Content-Type", "application/json;charset=UTF-16").POST(HttpRequest.BodyPublishers.ofByteArray(fixture.control()))), 415, null);
            error(jar.send(multipartRequest(jar, BASE, true).header("Accept", "text/html")
                    .POST(HttpRequest.BodyPublishers.ofByteArray(new byte[0]))), 406, "NOT_ACCEPTABLE");
            assertThat(database()).isEqualTo(before); assertThat(files(roots)).isEqualTo(originalFiles);
            jar.awaitLogs();
        }
        safeLogs(jar);
    }

    @Test
    void failedDatabaseInsertKeepsCanonicalAndStagingForExactRetryWithoutAnotherExtraction() throws Exception {
        var roots = roots(); var jar = start(roots, "local-api");
        try (jar) {
            var fixture = fixture((byte[]) null); registerSource(jar, fixture); stage(jar, fixture);
            var before = database(); var stageBefore = tree(roots.requests().resolve("extraction-uploads"));
            String constraint = "synthetic_extraction_failure_" + UUID.randomUUID().toString().replace("-", "");
            database.jdbc().execute("ALTER TABLE extraction_runs ADD CONSTRAINT `" + constraint + "` CHECK (run_id <> '" + fixture.run() + "')");
            try { error(finalizeUpload(jar, fixture.run(), fixture.control()), 500, "EXTRACTION_INTERNAL_ERROR"); }
            finally { database.jdbc().execute("ALTER TABLE extraction_runs DROP CHECK `" + constraint + "`"); }
            assertThat(database()).isEqualTo(before);
            assertThat(tree(roots.requests().resolve("extraction-uploads"))).isEqualTo(stageBefore);
            Path canonical = roots.extraction().resolve(fixture.run());
            assertThat(canonical.resolve("receipt.json")).exists();
            var archiveBefore = tree(roots.extraction());
            finalResult(finalizeUpload(jar, fixture.run(), fixture.control()), fixture, fixture.control(), "validated", false);
            finalResult(finalizeUpload(jar, fixture.run(), fixture.control()), fixture, fixture.control(), "validated", true);
            assertThat(tree(roots.extraction())).isEqualTo(archiveBefore);
            assertThat(tree(roots.requests().resolve("extraction-uploads"))).isEqualTo(stageBefore);
            originals(roots, fixture, "validated"); noEventsOrPublication(); jar.awaitLogs();
        }
        safeLogs(jar);
    }

    @Test
    void publicAndFixtureProfilesExposeNoneOfTheThreeUploadRoutes() throws Exception {
        for (String profile : List.of("public", "fixture")) {
            var roots = roots(); var jar = start(roots, profile);
            try (jar) {
                var before = database(); var originalFiles = files(roots); String run = UUID.randomUUID().toString();
                error(jar.send(multipartRequest(jar, BASE, true).POST(HttpRequest.BodyPublishers.ofByteArray(bytes("broken")))), 404, "NOT_FOUND");
                error(jar.send(multipartRequest(jar, slotPath(run, 1, "prompt"), true).PUT(HttpRequest.BodyPublishers.ofByteArray(bytes("broken")))), 404, "NOT_FOUND");
                error(jar.send(jsonRequest(jar, BASE + "/" + run + "/finalize", true).POST(HttpRequest.BodyPublishers.ofByteArray(bytes("{}")))), 404, "NOT_FOUND");
                assertThat(database()).isEqualTo(before); assertThat(files(roots)).isEqualTo(originalFiles); jar.awaitLogs();
            }
            safeLogs(jar);
        }
    }

    @Test
    void documentedCurlCommandsBypassAControlledProxyAndExactlyReplayActualRegistration() throws Exception {
        var roots = roots(); var jar = start(roots, "local-api");
        try (jar; var proxy = new CurlProxy()) {
            var fixture = fixture((byte[]) null); registerSource(jar, fixture);
            Path proof = directory(roots.source().getParent().resolve("documented-curl"));
            Path upload = directory(proof.resolve("upload")), bin = directory(proof.resolve("bin"));
            Files.createSymbolicLink(bin.resolve("python3.13"), Path.of(python()));
            Files.createSymbolicLink(bin.resolve("curl"), curlExecutable());
            curlFile(upload.resolve("input.json"), fixture.input()); curlFile(upload.resolve("metadata.json"), fixture.metadata());
            curlFile(upload.resolve("prompt-1.txt"), fixture.prompts().getFirst()); curlFile(upload.resolve("output-1.json"), fixture.outputs().getFirst());
            var fences = new ArrayList<String>();
            var matcher = java.util.regex.Pattern.compile("(?s)```bash\\R(.*?)\\R```")
                    .matcher(Files.readString(PythonProbe.REPO.resolve("backend/docs/extraction-upload.md")));
            while (matcher.find()) fences.add(matcher.group(1));
            assertThat(fences.size()).as("문서 bash fence 수").isEqualTo(5);
            String origin = "http://127.0.0.1:" + jar.port;
            String originalSetup = fences.getFirst();
            String originSetting = "UPLOAD_ORIGIN=\"http://127.0.0.1:${MYAI_LOCAL_API_PORT:-8081}\"";
            String directorySetting = "UPLOAD_DIR=\"data/private/synthetic-extraction-upload\"";
            String runSetting = "UPLOAD_RUN_ID=\"71fb66f0-e610-4f9c-8f26-4bb77655ee8c\"";
            assertThat(originalSetup.contains(originSetting) && originalSetup.contains(directorySetting)
                    && originalSetup.contains(runSetting)).as("문서 설정 literal3개").isTrue();
            String setup = originalSetup.replace(originSetting, "UPLOAD_ORIGIN=" + shellQuote(origin))
                    .replace(directorySetting, "UPLOAD_DIR=" + shellQuote(upload.toString()))
                    .replace(runSetting, "UPLOAD_RUN_ID=" + shellQuote(fixture.run()));
            var environment = new TreeMap<String, String>();
            environment.put("PATH", bin.toString()); environment.put("CURL_HOME", proof.toString());
            environment.put("PYTHONNOUSERSITE", "1"); environment.put("PYTHONDONTWRITEBYTECODE", "1");
            environment.put("LANG", "C.UTF-8"); environment.put("LC_ALL", "C.UTF-8");
            environment.put("MYAI_LOCAL_API_TOKEN", jar.token);
            environment.put("http_proxy", proxy.origin()); environment.put("HTTP_PROXY", proxy.origin());
            environment.put("all_proxy", proxy.origin()); environment.put("ALL_PROXY", proxy.origin());
            environment.put("no_proxy", ""); environment.put("NO_PROXY", "");
            assertThat(curlShell(proof, environment, "control-create", setup + "\n" + fences.get(1)))
                    .as("문서의 실제 exclusive control 작성").isZero();
            byte[] control = Files.readAllBytes(upload.resolve("control.json")); var controlJson = JSON.readTree(control);
            var keys = new HashSet<String>(); controlJson.fieldNames().forEachRemaining(keys::add);
            assertThat(keys).containsExactlyInAnyOrder("schema_version", "run_id", "expected_input_hash");
            assertThat(controlJson.path("schema_version").asText()).isEqualTo("extraction-import-request-v1");
            assertThat(controlJson.path("run_id").asText().equals(fixture.run())
                    && controlJson.path("expected_input_hash").asText().equals(sha(fixture.input())))
                    .as("control의 실제 UUID·입력 hash").isTrue();
            assertThat(curlShell(proof, environment, "control-reject-existing", setup + "\n" + fences.get(1)))
                    .as("문서 control은 기존 파일을 덮어쓰지 않음").isNotZero();
            assertThat(Arrays.equals(Files.readAllBytes(upload.resolve("control.json")), control)).isTrue();
            fixture = new Fixture(fixture.run(), control, fixture.metadata(), fixture.input(), fixture.prompts(), fixture.outputs());
            assertThat(curlShell(proof, environment, "proxy-control", setup + "\ncurl --fail-with-body --silent --show-error \"$UPLOAD_ORIGIN/health\""))
                    .as("우회 없는 통제 프록시 대조").isZero();
            assertThat(proxy.requests.get()).as("통제 프록시 수신 대조1").isEqualTo(1);
            String[] slots = fences.get(3).split("\\n\\n", -1);
            assertThat(slots.length).as("문서 PUT 두 명령").isEqualTo(2);
            var commands = List.of(fences.get(2), slots[0], slots[1], fences.get(4));
            for (String command : commands) assertThat(command.contains("--noproxy '*'") && command.contains("--header @-"))
                    .as("문서 curl의 우회·stdin token header").isTrue();
            var protectedRows = database(); protectedRows.remove("extraction_runs"); jar.awaitLogs();
            long logs = curlLogCount(jar);
            var first = documentedCurl(proof, environment, setup, commands, "first");
            curlLogs(jar, logs + 4); assertThat(proxy.requests.get()).as("문서 네 요청의 프록시 추가 수신0").isEqualTo(1);
            curlResponses(first, fixture, false); originals(roots, fixture, "validated");
            var after = database(); after.remove("extraction_runs"); assertThat(after.equals(protectedRows)).as("D05 외 DB 불변").isTrue();
            var rowsBefore = database(); var filesBefore = files(roots); logs = curlLogCount(jar);
            var replay = documentedCurl(proof, environment, setup, commands, "replay");
            curlLogs(jar, logs + 4); assertThat(proxy.requests.get()).as("문서 재전송 네 요청의 프록시 추가 수신0").isEqualTo(1);
            curlResponses(replay, fixture, true);
            assertThat(database().equals(rowsBefore)).as("문서 정확 재전송 DB 불변").isTrue();
            assertThat(files(roots).equals(filesBefore)).as("문서 정확 재전송 원본 불변").isTrue();
            keyless(roots); noEventsOrPublication();
        }
        safeLogs(jar);
    }

    private List<JsonNode> documentedCurl(Path proof, Map<String, String> environment, String setup, List<String> commands, String round) throws Exception {
        var result = new ArrayList<JsonNode>();
        for (int index = 0; index < commands.size(); index++) {
            String label = "documented-" + round + "-" + (index + 1);
            assertThat(curlShell(proof, environment, label, setup + "\n" + commands.get(index)))
                    .as("문서 curl 명령 종료").isZero();
            byte[] response = Files.readAllBytes(proof.resolve(label + ".stdout"));
            String visible = new String(response, StandardCharsets.UTF_8) + Files.readString(proof.resolve(label + ".stderr"));
            assertThat(!visible.contains(PRIVATE) && !visible.contains(environment.get("MYAI_LOCAL_API_TOKEN"))
                    && !visible.contains(root.toRealPath().toString())).as("문서 curl 응답·진단의 private 값 비노출").isTrue();
            result.add(JSON.readTree(response));
        }
        return result;
    }
    private void curlResponses(List<JsonNode> responses, Fixture fixture, boolean replay) {
        assertThat(responses.size()).isEqualTo(4);
        for (JsonNode response : responses.subList(0, 3)) {
            assertThat(response.path("schema_version").asText()).isEqualTo("extraction-upload-result-v1");
            assertThat(response.path("run_id").asText().equals(fixture.run())
                    && response.path("expected_input_hash").asText().equals(sha(fixture.input())))
                    .as("문서 staging 응답의 실행·입력 연결").isTrue();
            assertThat(response.path("state").asText()).isEqualTo("staged");
            assertThat(response.path("review_required").asBoolean()).isTrue();
        }
        JsonNode response = responses.getLast();
        assertThat(response.path("schema_version").asText()).isEqualTo("local-management-result-v1");
        assertThat(response.path("request_sha256").asText().equals(sha(fixture.control()))).as("문서 finalize 원요청 hash").isTrue();
        assertThat(response.path("data").path("status").asText()).isEqualTo("validated");
        assertThat(response.path("data").path("already_registered").asBoolean()).isEqualTo(replay);
    }
    private int curlShell(Path proof, Map<String, String> environment, String label, String script) throws Exception {
        Path stdout = proof.resolve(label + ".stdout"), stderr = proof.resolve(label + ".stderr");
        curlFile(stdout, new byte[0]); curlFile(stderr, new byte[0]);
        var builder = new ProcessBuilder("/bin/bash", "-o", "pipefail", "-c", "set -eu\n" + script).directory(proof.toFile());
        builder.environment().clear(); builder.environment().putAll(environment);
        var process = builder.redirectOutput(stdout.toFile()).redirectError(stderr.toFile()).start();
        try { assertThat(process.waitFor(60, TimeUnit.SECONDS)).as("문서 shell 제한시간").isTrue(); return process.exitValue(); }
        finally {
            process.descendants().forEach(ProcessHandle::destroyForcibly); process.destroyForcibly();
            assertThat(process.waitFor(5, TimeUnit.SECONDS)).as("문서 shell 종료 회수").isTrue();
        }
    }
    private static void curlFile(Path path, byte[] content) throws Exception {
        Files.createFile(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))); Files.write(path, content);
    }
    private static String shellQuote(String value) { return "'" + value.replace("'", "'\"'\"'") + "'"; }
    private static Path curlExecutable() {
        for (String entry : System.getenv().getOrDefault("PATH", "").split(java.io.File.pathSeparator)) {
            Path candidate = Path.of(entry).resolve("curl"); if (Files.isExecutable(candidate)) return candidate.toAbsolutePath().normalize();
        }
        throw new AssertionError("Set PATH with an available curl");
    }
    private long curlLogCount(RunningJar jar) throws Exception { return Files.readString(jar.stderr).lines().filter(line -> line.contains("public_request ")).count(); }
    private void curlLogs(RunningJar jar, long expected) throws Exception {
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
        while (System.nanoTime() < deadline && curlLogCount(jar) < expected) Thread.sleep(10);
        assertThat(curlLogCount(jar)).as("문서 요청4개의 서버 완료 로그").isEqualTo(expected);
    }
    private static final class CurlProxy implements AutoCloseable {
        final ServerSocket server = new ServerSocket();
        final java.util.concurrent.atomic.AtomicInteger requests = new java.util.concurrent.atomic.AtomicInteger();
        final AtomicBoolean running = new AtomicBoolean(true); final AtomicReference<Throwable> error = new AtomicReference<>();
        final Thread worker;
        CurlProxy() throws Exception {
            server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), 0));
            worker = Thread.ofPlatform().name("synthetic-curl-proxy").daemon(true).start(() -> {
                try {
                    while (running.get()) try (var socket = server.accept()) {
                        socket.setSoTimeout(2_000); int tail = 0, size = 0;
                        while (tail != 0x0d0a0d0a && size++ < 16 * 1024) {
                            int value = socket.getInputStream().read(); if (value < 0) throw new java.io.EOFException(); tail = (tail << 8) | value;
                        }
                        if (tail != 0x0d0a0d0a) throw new java.io.IOException("SYNTHETIC_PROXY_HEADERS_TOO_LARGE");
                        requests.incrementAndGet();
                        socket.getOutputStream().write(bytes("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"));
                        socket.getOutputStream().flush();
                    }
                } catch (Throwable failure) { if (running.get()) error.set(failure); }
            });
        }
        String origin() { return "http://127.0.0.1:" + server.getLocalPort(); }
        @Override public void close() throws Exception {
            running.set(false); server.close(); worker.join(3_000);
            assertThat(worker.isAlive()).as("통제 proxy worker 종료").isFalse();
            assertThat(error.get() == null).as("통제 proxy 처리 오류 없음").isTrue();
        }
    }

    private Fixture fixture(byte[]... outputs) throws Exception {
        String run = UUID.randomUUID().toString(), version = UUID.randomUUID().toString();
        var input = (ObjectNode) JSON.readTree(PythonProbe.REPO.resolve("contracts/examples/ai-input.json").toFile()); input.put("document_version_id", version);
        var metadata = (ObjectNode) JSON.readTree(PythonProbe.REPO.resolve("processing/examples/extraction-metadata.json").toFile());
        metadata.put("run_id", run).put("document_version_id", version).put("attempts", outputs.length);
        var prompts = new ArrayList<byte[]>(); var originalOutputs = new ArrayList<byte[]>();
        for (int index = 0; index < outputs.length; index++) {
            prompts.add(bytes(PRIVATE + " prompt " + (index + 1) + " 😀\r\n"));
            if (outputs[index] == null) {
                var output = (ObjectNode) JSON.readTree(PythonProbe.REPO.resolve("contracts/examples/ai-extraction.json").toFile());
                output.put("document_version_id", version); originalOutputs.add(bytes(output.toString()));
            } else originalOutputs.add(outputs[index]);
        }
        byte[] raw = bytes("\n" + input.toPrettyString() + "\n");
        return new Fixture(run, control(run, raw), bytes(" \n" + metadata.toPrettyString() + "\n "), raw, prompts, originalOutputs);
    }

    private void registerSource(RunningJar jar, Fixture fixture) throws Exception {
        var input = JSON.readTree(fixture.input());
        var source = (ObjectNode) JSON.readTree(PythonProbe.REPO.resolve("backend/examples/source-import.json").toFile());
        var document = (ObjectNode) source.path("documents").get(0);
        document.put("document_id", UUID.randomUUID().toString());
        for (String name : List.of("document_version_id", "title", "published_date")) document.set(name, input.path(name));
        document.set("block_index", input.path("blocks"));
        var blocks = new ArrayList<String>(); input.path("blocks").forEach(block -> blocks.add(block.path("text").asText()));
        byte[] raw = bytes(String.join("\n", blocks)); String filename = fixture.run() + ".txt";
        document.put("raw_asset_path", filename).put("raw_sha256", sha(raw)).put("cleaned_text", new String(raw, StandardCharsets.UTF_8))
                .put("text_sha256", sha(raw)).put("preprocessing_version", "fixture-nfc-v1").put("use_review", "pending")
                .put("use_note", PRIVATE).put("check_result", "unchecked").putNull("latest_check_attempt_at").putNull("last_verified_at");
        document.putArray("checks");
        Files.write(jar.roots.source().resolve(filename), raw); Files.setPosixFilePermissions(jar.roots.source().resolve(filename), PosixFilePermissions.fromString("rw-------"));
        var response = jar.send(jsonRequest(jar, "/local/documents", true).POST(HttpRequest.BodyPublishers.ofByteArray(bytes(source.toString()))));
        assertThat(response.statusCode()).isEqualTo(200);
    }

    private void stage(RunningJar jar, Fixture fixture) throws Exception {
        var expected = new TreeMap<>(initial(fixture)); staged(initialize(jar, fixture), fixture, expected);
        for (int index = 0; index < fixture.outputs().size(); index++) {
            expected.put("attempt-" + (index + 1) + ".output", fixture.outputs().get(index));
            staged(slot(jar, fixture.run(), index + 1, "output", fixture.outputs().get(index)), fixture, expected);
            expected.put("attempt-" + (index + 1) + ".prompt", fixture.prompts().get(index));
            staged(slot(jar, fixture.run(), index + 1, "prompt", fixture.prompts().get(index)), fixture, expected);
        }
    }
    private HttpResponse<byte[]> initialize(RunningJar jar, Fixture fixture) throws Exception {
        return jar.send(multipartRequest(jar, BASE, true).POST(HttpRequest.BodyPublishers.ofByteArray(multipart(
                json("control", fixture.control()), json("metadata", fixture.metadata()), part("input", "application/json", fixture.input())))));
    }
    private HttpResponse<byte[]> slot(RunningJar jar, String run, int attempt, String artifact, byte[] raw) throws Exception {
        return jar.send(multipartRequest(jar, slotPath(run, attempt, artifact), true)
                .PUT(HttpRequest.BodyPublishers.ofByteArray(multipart(part("file", "application/octet-stream", raw)))));
    }
    private HttpResponse<byte[]> finalizeUpload(RunningJar jar, String run, byte[] control) throws Exception {
        return jar.send(jsonRequest(jar, BASE + "/" + run + "/finalize", true).POST(HttpRequest.BodyPublishers.ofByteArray(control)));
    }
    private void staged(HttpResponse<byte[]> response, Fixture fixture, Map<String, byte[]> expected) throws Exception {
        assertThat(response.statusCode()).isEqualTo(200); JsonNode result = JSON.readTree(response.body());
        assertThat(result.path("schema_version").asText()).isEqualTo("extraction-upload-result-v1");
        assertThat(result.path("run_id").asText()).isEqualTo(fixture.run());
        assertThat(result.path("expected_input_hash").asText()).isEqualTo(sha(fixture.input()));
        assertThat(result.path("state").asText()).isEqualTo("staged"); assertThat(result.path("review_required").asBoolean()).isTrue();
        var artifacts = new TreeMap<String, JsonNode>();
        result.path("received_files").forEach(file -> assertThat(artifacts.put(file.path("name").asText(), file)).isNull());
        assertThat(artifacts.keySet()).containsExactlyInAnyOrderElementsOf(expected.keySet());
        expected.forEach((name, raw) -> {
            assertThat(artifacts.get(name).path("size_bytes").asLong()).isEqualTo(raw.length);
            assertThat(artifacts.get(name).path("sha256").asText()).isEqualTo(sha(raw));
        });
    }
    private void finalResult(HttpResponse<byte[]> response, Fixture fixture, byte[] control, String status, boolean replay) throws Exception {
        assertThat(response.statusCode()).isEqualTo(200); var result = JSON.readTree(response.body());
        assertThat(result.path("schema_version").asText()).isEqualTo("local-management-result-v1");
        assertThat(result.path("request_sha256").asText()).isEqualTo(sha(control)); var data = result.path("data");
        assertThat(data.path("run_id").asText()).isEqualTo(fixture.run()); assertThat(data.path("status").asText()).isEqualTo(status);
        assertThat(data.path("attempts").asInt()).isEqualTo(fixture.outputs().size());
        assertThat(data.path("already_registered").asBoolean()).isEqualTo(replay); assertThat(data.path("review_required").asBoolean()).isTrue();
    }
    private void originals(Roots roots, Fixture fixture, String status) throws Exception {
        Path canonical = roots.extraction().resolve(fixture.run());
        Path registered = Path.of(database.jdbc().queryForObject("SELECT raw_ref FROM extraction_runs WHERE run_id=?", String.class, fixture.run()));
        assertThat(registered).isNotEqualTo(canonical); var expected = new TreeMap<>(initial(fixture)); expected.remove("control.json");
        for (int index = 0; index < fixture.outputs().size(); index++) {
            expected.put("attempt-" + (index + 1) + ".prompt", fixture.prompts().get(index)); expected.put("attempt-" + (index + 1) + ".output", fixture.outputs().get(index));
        }
        var receipt = JSON.readTree(registered.resolve("receipt.json").toFile()); assertThat(receipt.path("status").asText()).isEqualTo(status);
        for (var entry : expected.entrySet()) {
            for (Path directory : List.of(canonical, registered)) assertThat(Files.readAllBytes(directory.resolve(entry.getKey()))).isEqualTo(entry.getValue());
            assertThat(receipt.path("artifacts").path(entry.getKey()).path("sha256").asText()).isEqualTo(sha(entry.getValue()));
            assertThat(receipt.path("artifacts").path(entry.getKey()).path("size").asLong()).isEqualTo(entry.getValue().length);
        }
        assertThat(database.jdbc().queryForObject("SELECT metadata_json FROM extraction_runs WHERE run_id=?", String.class, fixture.run())).isEqualTo(new String(fixture.metadata(), StandardCharsets.UTF_8));
        assertThat(database.jdbc().queryForObject("SELECT receipt_sha256 FROM extraction_runs WHERE run_id=?", String.class, fixture.run())).isEqualTo(sha(Files.readAllBytes(registered.resolve("receipt.json"))));
        for (String value : tree(registered).values()) assertThat(value).startsWith(value.contains(":") ? "r--------:" : "r-x------");
        noEventsOrPublication();
    }
    private void noEventsOrPublication() {
        for (String table : List.of("events", "event_revisions", "review_audits", "snapshots", "snapshot_revisions", "publication_heads", "publication_audits"))
            assertThat(database.jdbc().queryForObject("SELECT COUNT(*) FROM " + table, Integer.class)).as(table).isZero();
    }

    private Roots roots() throws Exception {
        Path base = Files.createTempDirectory(root.toRealPath(), "jar-", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        return new Roots(directory(base.resolve("source")), directory(base.resolve("extraction")), directory(base.resolve("handoff")),
                directory(base.resolve("requests")), directory(base.resolve("servlet-temp")), forwardingProbe(base), base.resolve("python-proof.jsonl"));
    }
    private Path forwardingProbe(Path base) throws Exception {
        Path probe = directory(base.resolve("probe")); Path module = Files.createDirectories(probe.resolve("processing/extraction"));
        Files.writeString(probe.resolve("processing/__init__.py"), ""); Files.writeString(module.resolve("__init__.py"), "");
        String body = """
                import sys,os,json,runpy
                from pathlib import Path
                import processing,processing.extraction
                Path('pid-'+str(os.getpid())).write_text(str(os.getpid()))
                allowed={'PATH','LANG','LANGUAGE'}
                if sys.platform=='darwin': allowed.add('__CF_USER_TEXT_ENCODING')
                bad=sorted(name for name in os.environ if name not in allowed and not name.startswith('LC_'))
                with Path(%s).open('a',encoding='utf-8') as target:
                    target.write(json.dumps(dict(command=sys.argv[1],unexpected_names=bad,
                        no_user_site=bool(sys.flags.no_user_site),no_bytecode=bool(sys.dont_write_bytecode)))+'\\n')
                if bad or not sys.flags.no_user_site or not sys.dont_write_bytecode: sys.exit(97)
                processing.__path__.append(%s)
                processing.extraction.__path__=[%s]
                runpy.run_module('processing.extraction',run_name='__main__')
                """.formatted(JSON.writeValueAsString(base.resolve("python-proof.jsonl").toString()),
                JSON.writeValueAsString(PythonProbe.REPO.resolve("processing").toString()), JSON.writeValueAsString(PythonProbe.REPO.resolve("processing/extraction").toString()));
        Files.writeString(module.resolve("__main__.py"), body); return probe;
    }
    private void keyless(Roots roots) throws Exception {
        var commands = new HashSet<String>();
        for (String line : Files.readAllLines(roots.proof())) {
            var value = JSON.readTree(line); commands.add(value.path("command").asText());
            assertThat(value.path("unexpected_names")).isEmpty(); assertThat(value.path("no_user_site").asBoolean()).isTrue(); assertThat(value.path("no_bytecode").asBoolean()).isTrue();
        }
        // import/freeze 내부의 verify_run도 같은 keyless 자식에서 실행된다.
        assertThat(commands).contains("import", "freeze");
        assertThat(PythonProbe.processes(roots.probe())).noneMatch(ProcessHandle::isAlive);
    }
    private RunningJar start(Roots roots, String profile) throws Exception {
        int port; try (var socket = new ServerSocket()) { socket.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), 0)); port = socket.getLocalPort(); }
        String token = "SYNTHETIC_EXTRACTION_TOKEN_" + UUID.randomUUID().toString().replace("-", "");
        Path stdout = roots.source().getParent().resolve("stdout"), stderr = roots.source().getParent().resolve("stderr");
        var builder = new ProcessBuilder(Path.of(System.getProperty("java.home"), "bin", "java").toString(), "-Xmx512m", "-Djava.io.tmpdir=" + roots.temporary(),
                "-jar", "build/libs/myai-backend-0.1.0.jar", "--spring.profiles.active=" + profile, "--server.port=" + port,
                "--spring.main.banner-mode=off", "--logging.config=classpath:logback-local-import.xml", "--logging.level.root=OFF",
                "--logging.level.kr.ac.myai.backend.logging.PublicRequestLogFilter=INFO");
        var env = builder.environment(); env.clear();
        env.put("DB_URL", database.url()); env.put("DB_USERNAME", database.username()); env.put("DB_PASSWORD", database.password());
        env.put("MYAI_LOCAL_API_TOKEN", token); env.put("MYAI_LOCAL_API_ACTOR", "synthetic-extraction-manager");
        env.put("MYAI_LOCAL_API_SOURCE_ROOT", roots.source().toString()); env.put("MYAI_LOCAL_API_EXTRACTION_ROOT", roots.extraction().toString());
        env.put("MYAI_LOCAL_API_HANDOFF_ROOT", roots.handoff().toString()); env.put("MYAI_LOCAL_API_REQUEST_ROOT", roots.requests().toString());
        env.put("MYAI_PYTHON_WORKDIR", roots.probe().toString()); env.put("MYAI_PYTHON_EXECUTABLE", python());
        env.put("OPENAI_API_KEY", PRIVATE); env.put("PYTHONPATH", roots.probe().resolve("SYNTHETIC_IGNORED_PATH").toString()); env.put("SYNTHETIC_SECRET_MARKER", PRIVATE);
        var jar = new RunningJar(builder.redirectOutput(stdout.toFile()).redirectError(stderr.toFile()).start(), roots, port, token, stdout, stderr);
        try {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(35);
            while (System.nanoTime() < deadline) {
                assertThat(jar.process.isAlive()).as("합성 JAR readiness 전 생존").isTrue();
                try {
                    var response = jar.send(jar.request(profile.equals("local-api") ? "/local/readiness" : "/health", false).timeout(Duration.ofSeconds(2)).GET());
                    if (profile.equals("local-api")) error(response, 401, "LOCAL_API_UNAUTHORIZED"); else assertThat(response.statusCode()).isEqualTo(200);
                    jar.watch = new TempWatch(roots.temporary()); return jar;
                } catch (java.io.IOException notReady) { Thread.sleep(50); }
            }
            throw new AssertionError("합성 JAR readiness timeout");
        } catch (Exception | AssertionError error) { jar.close(); throw error; }
    }
    private void error(HttpResponse<byte[]> response, int status, String code) throws Exception {
        assertThat(response.statusCode()).isEqualTo(status); assertThat(response.headers().firstValue("Content-Type").orElse("")).startsWith("application/json");
        var result = JSON.readTree(response.body()); assertThat(result.path("error").path("code").asText()).isNotBlank();
        if (code != null) assertThat(result.path("error").path("code").asText()).isEqualTo(code);
        assertThat(result.path("error").path("field_errors").isArray()).isTrue(); assertThat(result.path("request_id").asText()).isEqualTo(requestId(response));
    }
    private void safeLogs(RunningJar jar) throws Exception {
        String stdout = Files.readString(jar.stdout), stderr = Files.readString(jar.stderr); assertThat(stdout).isEmpty();
        var rows = new ArrayList<JsonNode>(); for (String line : stderr.lines().toList()) { int at = line.indexOf("public_request "); if (at >= 0) rows.add(JSON.readTree(line.substring(at + 15))); }
        for (var response : jar.responses) {
            var matching = rows.stream().filter(row -> requestId(response).equals(row.path("request_id").asText())).toList(); assertThat(matching).hasSize(1);
            var keys = new HashSet<String>(); matching.getFirst().fieldNames().forEachRemaining(keys::add);
            assertThat(keys).containsExactlyInAnyOrder("request_id", "error_code", "latency_ms", "snapshot_id", "rules_version");
        }
        String visible = stdout + stderr + jar.responses.stream().map(response -> new String(response.body(), StandardCharsets.UTF_8)).reduce("", String::concat);
        assertThat(visible).doesNotContain(jar.token, PRIVATE, "SYNTHETIC_PRIVATE_FILENAME", "SYNTHETIC_PRIVATE_CLIENT_ID", "SYNTHETIC_INSERT_FAILURE", root.toRealPath().toString(), database.password(), "jdbc:mysql", "Exception", "\tat ");
    }
    private Map<String, List<String>> database() {
        var result = new TreeMap<String, List<String>>();
        for (String table : database.jdbc().queryForList("SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME", String.class))
            result.put(table, database.jdbc().queryForList("SELECT * FROM `" + table + "`").stream().map(row -> { var cells = new TreeMap<String, String>(); row.forEach((key, value) -> cells.put(key, value == null ? null : value.toString())); return JSON.valueToTree(cells).toString(); }).sorted().toList());
        return result;
    }
    private Map<String, String> files(Roots roots) throws Exception {
        var result = new TreeMap<String, String>(); for (Path path : List.of(roots.source(), roots.extraction(), roots.handoff(), roots.requests())) tree(path).forEach((name, value) -> result.put(path.getFileName() + "/" + name, value)); return result;
    }
    private Map<String, String> tree(Path root) throws Exception {
        var result = new TreeMap<String, String>(); try (var paths = Files.walk(root)) { for (Path path : paths.toList()) result.put(root.relativize(path).toString(), PosixFilePermissions.toString(Files.getPosixFilePermissions(path)) + (Files.isRegularFile(path) ? ":" + sha(Files.readAllBytes(path)) : "")); } return result;
    }
    private record Fixture(String run, byte[] control, byte[] metadata, byte[] input, List<byte[]> prompts, List<byte[]> outputs) { }
    private record Roots(Path source, Path extraction, Path handoff, Path requests, Path temporary, Path probe, Path proof) { }
    private record Part(String name, String type, byte[] bytes) { }
    private static Map<String, byte[]> initial(Fixture fixture) { return Map.of("control.json", fixture.control(), "metadata.json", fixture.metadata(), "input.json", fixture.input()); }
    private static Part json(String name, byte[] raw) { return part(name, "application/json;charset=UTF-8", raw); }
    private static Part part(String name, String type, byte[] raw) { return new Part(name, type, raw); }
    private static String slotPath(String run, int attempt, String artifact) { return BASE + "/" + run + "/attempts/" + attempt + "/" + artifact; }
    private static byte[] control(String run, byte[] input) { return bytes(JSON.createObjectNode().put("schema_version", "extraction-import-request-v1").put("run_id", run).put("expected_input_hash", sha(input)).toString()); }
    private static byte[] padded(byte[] raw, int size) { byte[] result = Arrays.copyOf(raw, size); Arrays.fill(result, raw.length, size, (byte) ' '); return result; }
    private static HttpRequest.BodyPublisher chunked(byte[] body) { var result = HttpRequest.BodyPublishers.ofInputStream(() -> new ByteArrayInputStream(body)); assertThat(result.contentLength()).isEqualTo(-1); return result; }
    private static byte[] bytes(String text) { return text.getBytes(StandardCharsets.UTF_8); }
    private static String sha(byte[] raw) { return ReviewedImportReader.sha256(raw); }
    private static Path directory(Path path) throws Exception { return Files.createDirectory(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))); }
    private static String requestId(HttpResponse<byte[]> response) { String id = response.headers().firstValue("X-Request-ID").orElse(""); assertThat(UUID.fromString(id).toString()).isEqualTo(id); return id; }
    private static HttpRequest.Builder multipartRequest(RunningJar jar, String path, boolean auth) { return jar.request(path, auth).header("Content-Type", "multipart/form-data; boundary=" + BOUNDARY); }
    private static HttpRequest.Builder jsonRequest(RunningJar jar, String path, boolean auth) { return jar.request(path, auth).header("Content-Type", "application/json"); }
    private static byte[] multipart(Part... parts) throws Exception {
        var result = new ByteArrayOutputStream();
        for (var part : parts) { result.write(bytes("--" + BOUNDARY + "\r\nContent-Disposition: form-data; name=\"" + part.name() + "\"; filename=\"../../SYNTHETIC_PRIVATE_FILENAME\"\r\nContent-Type: " + part.type() + "\r\n\r\n")); result.write(part.bytes()); result.write(bytes("\r\n")); }
        result.write(bytes("--" + BOUNDARY + "--\r\n")); return result.toByteArray();
    }
    private static String python() {
        Path configured = Path.of(PythonProbe.PYTHON); if (configured.isAbsolute()) return configured.toString();
        for (String entry : System.getenv().getOrDefault("PATH", "").split(java.io.File.pathSeparator)) { Path path = Path.of(entry).resolve(configured); if (Files.isExecutable(path)) return path.toAbsolutePath().normalize().toString(); }
        throw new AssertionError("Set absolute MYAI_PYTHON_EXECUTABLE for actual JAR tests");
    }
    private final class RunningJar implements AutoCloseable {
        final Process process; final Roots roots; final int port; final String token; final Path stdout, stderr;
        final List<HttpResponse<byte[]>> responses = new ArrayList<>(); TempWatch watch;
        RunningJar(Process process, Roots roots, int port, String token, Path stdout, Path stderr) { this.process = process; this.roots = roots; this.port = port; this.token = token; this.stdout = stdout; this.stderr = stderr; }
        HttpRequest.Builder request(String path, boolean auth) {
            String origin = "http://127.0.0.1:" + port;
            var result = HttpRequest.newBuilder(URI.create(origin + path)).timeout(Duration.ofSeconds(60)).header("Origin", origin).header("X-Request-ID", "SYNTHETIC_PRIVATE_CLIENT_ID");
            if (auth) result.header("Authorization", "Bearer " + token); return result;
        }
        HttpResponse<byte[]> send(HttpRequest.Builder request) throws Exception { var result = http.send(request.build(), HttpResponse.BodyHandlers.ofByteArray()); responses.add(result); return result; }
        void awaitLogs() throws Exception {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
            while (System.nanoTime() < deadline) { if (Files.readString(stderr).lines().filter(line -> line.contains("public_request ")).count() >= responses.size()) return; Thread.sleep(10); }
            throw new AssertionError("완료한 업로드 요청 로그 부재");
        }
        @Override public void close() throws Exception {
            try { if (watch != null) watch.close(); }
            finally { process.destroy(); if (!process.waitFor(10, TimeUnit.SECONDS)) { process.destroyForcibly(); assertThat(process.waitFor(5, TimeUnit.SECONDS)).isTrue(); } }
        }
    }
    private static final class TempWatch implements AutoCloseable {
        final AtomicBoolean running = new AtomicBoolean(true); final Set<Path> observed = ConcurrentHashMap.newKeySet();
        final AtomicReference<Throwable> error = new AtomicReference<>(); final Thread worker;
        TempWatch(Path directory) throws Exception {
            Set<Path> baseline; try (var files = Files.walk(directory)) { baseline = new HashSet<>(files.filter(Files::isRegularFile).toList()); }
            worker = Thread.ofPlatform().name("synthetic-extraction-temp-watch").daemon(true).start(() -> {
                try { while (running.get()) { try (var files = Files.walk(directory)) { files.filter(Files::isRegularFile).filter(path -> !baseline.contains(path)).forEach(observed::add); } Thread.sleep(2); } }
                catch (Throwable failure) { error.set(failure); }
            });
        }
        @Override public void close() throws Exception { running.set(false); worker.join(3_000); assertThat(worker.isAlive()).isFalse(); assertThat(error.get()).isNull(); assertThat(observed).as("servlet 원문 임시파일0").isEmpty(); }
    }
}
