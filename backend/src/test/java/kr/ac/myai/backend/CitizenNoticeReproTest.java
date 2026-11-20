package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.MockedStatic;

import javax.net.ssl.SSLSession;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpHeaders;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.LinkOption;
import java.nio.file.OpenOption;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class CitizenNoticeReproTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final String SNAPSHOT = "30000000-0000-4000-8000-000000000001";
    private static final String EVENT = "20000000-0000-4000-8000-000000000004";
    private static final String REQUEST_ID = "34199ef2-1792-4349-a604-d0f7d7be01ae";
    @TempDir Path root;

    @Test
    void preservesUtf8ResponseAndIndependentChecksWithRelativeRequestAndFingerprints() throws Exception {
        Path directory = directory();
        byte[] body = (" \n" + success().toPrettyString() + "\n").getBytes(StandardCharsets.UTF_8);
        var checks = Map.<String, Object>of("/data/notices/0/title", "합성 시민 공지 😀", "/data/notice_count", 1,
                "/data/notices/0/cost/value", JSON.nullNode());
        String path = "/api/v1/citizen/notices?snapshot_id=" + SNAPSHOT;
        CitizenNoticeFixtures.writeRepro(directory, "utf8-list", "8.4.13", List.of(sample("list", path, 200, body, checks)));

        assertThat(Files.readAllBytes(directory.resolve("list.actual.json"))).isEqualTo(body);
        var request = JSON.readTree(directory.resolve("list.request.json").toFile());
        assertThat(request.path("method").asText()).isEqualTo("GET");
        assertThat(request.path("path_query").asText()).isEqualTo(path);
        assertThat(request.path("body").isNull()).isTrue();
        assertThat(request.size()).isEqualTo(3);
        var expected = JSON.readTree(directory.resolve("list.expected.json").toFile());
        assertThat(expected.path("status").asInt()).isEqualTo(200);
        assertThat(expected.path("checks")).isEqualTo(JSON.valueToTree(checks));
        var manifest = JSON.readTree(directory.resolve("manifest.json").toFile());
        assertThat(manifest.path("schema_version").asText()).isEqualTo("citizen-api-repro-v1");
        assertThat(manifest.path("response_checks").asText()).isEqualTo("passed");
        assertThat(manifest.path("data_kind").asText()).isEqualTo("synthetic");
        assertThat(manifest.path("runtime").path("java").asText()).isEqualTo(System.getProperty("java.version"));
        assertThat(manifest.path("runtime").path("spring_boot").asText()).isEqualTo(org.springframework.boot.SpringBootVersion.getVersion());
        assertThat(manifest.path("runtime").path("mysql").asText()).isEqualTo("8.4.13");
        assertThat(manifest.path("runtime").path("jar_sha256").asText()).matches("[0-9a-f]{64}");
        assertThat(manifest.path("cases").get(0).path("actual_status").asInt()).isEqualTo(200);
        assertThat(manifest.path("cases").get(0).path("expected_status").asInt()).isEqualTo(200);
        assertThat(manifest.path("snapshot_ids")).contains(JSON.valueToTree(SNAPSHOT));
        assertThat(manifest.path("event_ids")).contains(JSON.valueToTree(EVENT));
        assertThat(manifest.path("artifacts")).hasSize(3);
        for (var file : manifest.path("artifacts")) {
            byte[] bytes = Files.readAllBytes(directory.resolve(file.path("path").asText()));
            assertThat(file.path("size").asLong()).isEqualTo(bytes.length);
            assertThat(file.path("sha256").asText()).isEqualTo(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)));
        }
        assertThat(Files.readString(directory.resolve("manifest.json"))).doesNotContain("127.0.0.1", "DO_NOT_EXPORT_AUTH", "DO_NOT_EXPORT_COOKIE", root.toString());
    }

    @Test
    void recordsHttpErrorStatusWithoutInventingSyntheticSuccessData() throws Exception {
        Path directory = directory();
        String error = "{\"error\":{\"code\":\"INVALID_REQUEST\",\"message\":\"지원 조건 확인\",\"retryable\":false,\"field_errors\":[]},\"request_id\":\"34199ef2-1792-4349-a604-d0f7d7be01ae\"}";
        CitizenNoticeFixtures.writeRepro(directory, "invalid-filter", "8.4.13", List.of(sample("invalid-filter",
                "/api/v1/citizen/notices?cost=free", 422, error, Map.of("/error/code", "INVALID_REQUEST"))));
        assertThat(Files.readString(directory.resolve("invalid-filter.actual.json"))).isEqualTo(error);
        var recorded = JSON.readTree(directory.resolve("manifest.json").toFile()).path("cases").get(0);
        assertThat(recorded.path("actual_status").asInt()).isEqualTo(422);
        assertThat(recorded.path("expected_status").asInt()).isEqualTo(422);
    }

    @ParameterizedTest
    @ValueSource(strings = {"status", "value", "type", "missing", "nan"})
    void rejectsDisagreementBeforeWritingAnyCompletionOrCaseFile(String defect) throws Exception {
        Path directory = directory();
        Map<String, ?> checks = switch (defect) {
            case "value" -> Map.of("/data/notices/0/title", "다른 제목");
            case "type" -> Map.of("/data/notice_count", "1");
            case "missing" -> Map.of("/data/absent", JSON.nullNode());
            case "nan" -> Map.of("/data/notice_count", Double.NaN);
            default -> Map.of("/data/notice_count", 1);
        };
        var response = response("GET", "/api/v1/citizen/notices", 200, success().toString());
        var selected = new CitizenNoticeFixtures.ReproCase("list", response, defect.equals("status") ? 422 : 200, checks);
        assertThatThrownBy(() -> CitizenNoticeFixtures.writeRepro(directory, "mismatch", "8.4.13", List.of(selected)));
        try (var entries = Files.list(directory)) { assertThat(entries.map(path -> path.getFileName().toString())).containsExactly("snapshots"); }
    }

    @ParameterizedTest
    @ValueSource(strings = {"../escape", "/absolute", "nested/name", "case.json", ""})
    void rejectsUnsafeCaseNamesWithoutWritingOutsideBundle(String id) throws Exception {
        Path directory = directory();
        var selected = sample(id, "/api/v1/citizen/notices", 200, success().toString(), Map.of("/data/notice_count", 1));
        assertThatThrownBy(() -> CitizenNoticeFixtures.writeRepro(directory, "safe-paths", "8.4.13", List.of(selected)));
        assertThat(directory.resolve("manifest.json")).doesNotExist();
        assertThat(root.resolve("escape.actual.json")).doesNotExist();
    }

    @ParameterizedTest
    @ValueSource(strings = {"private", "real", "non-citizen", "post", "credentials-query"})
    void refusesNonPublicOrNonSyntheticResponsesBeforeWritingArtifacts(String defect) throws Exception {
        Path directory = directory();
        var body = success();
        if (defect.equals("private")) ((ObjectNode) body.path("data")).put("raw_asset_path", "/private/DO_NOT_EXPORT_SOURCE");
        if (defect.equals("real")) ((ObjectNode) body.path("data")).put("data_kind", "real");
        String path = defect.equals("non-citizen") ? "/local/reviews/import" : "/api/v1/citizen/notices";
        if (defect.equals("credentials-query")) path += "?token=DO_NOT_EXPORT_AUTH";
        var response = response(defect.equals("post") ? "POST" : "GET", path, 200, body.toString());
        assertThatThrownBy(() -> CitizenNoticeFixtures.writeRepro(directory, "public-only", "8.4.13",
                List.of(new CitizenNoticeFixtures.ReproCase("list", response, 200, Map.of("/data/notice_count", 1)))));
        assertThat(directory.resolve("manifest.json")).doesNotExist();
        assertThat(directory.resolve("list.actual.json")).doesNotExist();
    }

    @Test
    void rejectsMalformedWireUtf8InsteadOfRetainingReplacementCharacters() throws Exception {
        Path directory = directory();
        byte[] wire = success().toString().replace("합성 시민 공지 😀", "##").getBytes(StandardCharsets.UTF_8);
        int marker = new String(wire, StandardCharsets.ISO_8859_1).indexOf("##");
        assertThat(marker).isGreaterThan(0); wire[marker] = (byte) 0xc3; wire[marker + 1] = 0x28;
        var item = new CitizenNoticeFixtures.ReproCase("invalid-utf8", response("GET", "/api/v1/citizen/notices", 200, wire),
                200, Map.of("/data/notice_count", 1));
        assertThatThrownBy(() -> CitizenNoticeFixtures.writeRepro(directory, "invalid-wire", "8.4.13", List.of(item)));
        assertThat(directory.resolve("invalid-utf8.actual.json")).doesNotExist();
        assertThat(directory.resolve("manifest.json")).doesNotExist();
    }

    @ParameterizedTest
    @ValueSource(strings = {"missing", "mismatch", "non-uuid", "uppercase", "duplicate"})
    void refusesErrorRequestIdsThatCannotBeLinkedToOneCanonicalResponseHeader(String defect) throws Exception {
        Path directory = directory();
        String id = defect.equals("non-uuid") ? "not-a-request-id" : defect.equals("uppercase") ? REQUEST_ID.toUpperCase(java.util.Locale.ROOT) : REQUEST_ID;
        var body = JSON.createObjectNode().put("request_id", id);
        body.putObject("error").put("code", "INVALID_REQUEST").put("message", "지원 조건 확인").put("retryable", false).putArray("field_errors");
        List<String> headers = switch (defect) {
            case "missing" -> List.of();
            case "mismatch" -> List.of("5e6a7264-d505-4b14-9134-bd71334cfd94");
            case "duplicate" -> List.of(id, id);
            default -> List.of(id);
        };
        var item = new CitizenNoticeFixtures.ReproCase("bad-request-id", response("GET", "/api/v1/citizen/notices?cost=free", 422,
                body.toString().getBytes(StandardCharsets.UTF_8), headers), 422, Map.of("/error/code", "INVALID_REQUEST"));
        assertThatThrownBy(() -> CitizenNoticeFixtures.writeRepro(directory, "error-identity", "8.4.13", List.of(item)));
        assertThat(directory.resolve("bad-request-id.actual.json")).doesNotExist();
        assertThat(directory.resolve("manifest.json")).doesNotExist();
    }

    @Test
    void acceptsDirectoryCreatedByAnotherInitializerAfterItsExistenceCheck() throws Exception {
        Path base = Path.of("").toRealPath().resolve("build");
        assertThat(base).isDirectory();
        Path created;
        try (MockedStatic<Files> files = mockStatic(Files.class, CALLS_REAL_METHODS)) {
            files.when(() -> Files.exists(base, LinkOption.NOFOLLOW_LINKS)).thenReturn(false);
            created = CitizenNoticeFixtures.createReproDirectory("racing-initializer");
        }
        assertThat(created.resolve("snapshots")).isDirectory();
        Files.delete(created.resolve("snapshots")); Files.delete(created);
    }

    @Test
    void failedManifestWriteNeverPublishesPartialCompletionOrLeavesItsTemporaryFile() throws Exception {
        Path directory = directory();
        var selected = sample("list", "/api/v1/citizen/notices", 200, success().toString(), Map.of("/data/notice_count", 1));
        try (MockedStatic<Files> files = mockStatic(Files.class, CALLS_REAL_METHODS)) {
            files.when(() -> Files.write(any(Path.class), any(byte[].class), any(OpenOption[].class))).thenAnswer(call -> {
                Path path = call.getArgument(0);
                if (path.getFileName().toString().equals("manifest.json") || path.getFileName().toString().startsWith(".manifest-")) {
                    try (var stream = new FileOutputStream(path.toFile())) { stream.write("{\"partial\":".getBytes(StandardCharsets.UTF_8)); }
                    throw new IOException("시험용 manifest 중간 쓰기 실패");
                }
                return call.callRealMethod();
            });
            assertThatThrownBy(() -> CitizenNoticeFixtures.writeRepro(directory, "manifest-failure", "8.4.13", List.of(selected)))
                    .isInstanceOf(UncheckedIOException.class);
        }
        assertThat(directory.resolve("manifest.json")).doesNotExist();
        try (var files = Files.list(directory)) { assertThat(files.map(path -> path.getFileName().toString())).noneMatch(name -> name.startsWith(".manifest-")); }
    }

    @Test
    void fingerprintsPublicSnapshotsAlongsideResponseAndKeepsExistingOutputsUnchanged() throws Exception {
        Path directory = directory();
        var canonical = (ObjectNode) success().path("data").deepCopy();
        canonical.put("schema_version", "citizen-snapshot-v1").put("snapshot_id", SNAPSHOT)
                .put("channel_key", "citizen:current").putNull("case_id");
        canonical.putArray("revision_ids").add("30000000-0000-4000-8000-000000000002");
        byte[] canonicalBytes = canonical.toString().getBytes(StandardCharsets.UTF_8);
        String name = SNAPSHOT + "-" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(canonicalBytes)) + ".json";
        Path snapshot = Files.write(directory.resolve("snapshots").resolve(name), canonicalBytes);
        byte[] snapshotBefore = Files.readAllBytes(snapshot);
        var selected = sample("list", "/api/v1/citizen/notices", 200, success().toString(), Map.of("/data/notice_count", 1));
        CitizenNoticeFixtures.writeRepro(directory, "public-snapshot", "8.4.13", List.of(selected));
        var manifest = JSON.readTree(directory.resolve("manifest.json").toFile());
        assertThat(manifest.path("artifacts")).hasSize(4).anySatisfy(file -> {
            assertThat(file.path("path").asText()).isEqualTo("snapshots/" + name);
            assertThat(file.path("size").asLong()).isEqualTo(snapshotBefore.length);
        });
        byte[] actualBefore = Files.readAllBytes(directory.resolve("list.actual.json"));
        byte[] manifestBefore = Files.readAllBytes(directory.resolve("manifest.json"));
        assertThatThrownBy(() -> CitizenNoticeFixtures.writeRepro(directory, "public-snapshot", "8.4.13", List.of(selected)));
        assertThat(Files.readAllBytes(snapshot)).isEqualTo(snapshotBefore);
        assertThat(Files.readAllBytes(directory.resolve("list.actual.json"))).isEqualTo(actualBefore);
        assertThat(Files.readAllBytes(directory.resolve("manifest.json"))).isEqualTo(manifestBefore);
    }

    @Test
    void doesNotCompleteWhenCaseOutputAlreadyExists() throws Exception {
        Path directory = directory();
        Path existing = Files.writeString(directory.resolve("list.actual.json"), "이전 결과 보존 😀");
        byte[] before = Files.readAllBytes(existing);
        assertThatThrownBy(() -> CitizenNoticeFixtures.writeRepro(directory, "existing", "8.4.13",
                List.of(sample("list", "/api/v1/citizen/notices", 200, success().toString(), Map.of("/data/notice_count", 1)))));
        assertThat(Files.readAllBytes(existing)).isEqualTo(before);
        assertThat(directory.resolve("manifest.json")).doesNotExist();
    }

    @Test
    void createsDistinctRunsInFixedBuildRootWithoutRemovingPreviousFiles() throws Exception {
        Path first = CitizenNoticeFixtures.createReproDirectory("mysql-construction_traffic");
        assertThat(first.toAbsolutePath().normalize()).startsWith(Path.of("build/repro/citizen-api-v1").toAbsolutePath().normalize());
        assertThat(first.resolve("snapshots")).isDirectory();
        Path sentinel = Files.writeString(first.resolve("previous.txt"), "이전 사용자 결과");
        Path second = CitizenNoticeFixtures.createReproDirectory("mysql-construction_traffic");
        assertThat(second).isNotEqualTo(first);
        assertThat(second.resolve("snapshots")).isDirectory();
        assertThat(Files.readString(sentinel)).isEqualTo("이전 사용자 결과");
        Files.delete(sentinel); Files.delete(first.resolve("snapshots")); Files.delete(first);
        Files.delete(second.resolve("snapshots")); Files.delete(second);
    }

    private Path directory() throws Exception { Files.createDirectory(root.resolve("snapshots")); return root; }
    private ObjectNode success() throws Exception { return (ObjectNode) JSON.readTree(Path.of("../contracts/examples/citizen-list-response.json").toFile()); }
    private CitizenNoticeFixtures.ReproCase sample(String id, String path, int status, String body, Map<String, ?> checks) {
        return new CitizenNoticeFixtures.ReproCase(id, response("GET", path, status, body), status, checks);
    }
    private CitizenNoticeFixtures.ReproCase sample(String id, String path, int status, byte[] body, Map<String, ?> checks) {
        return new CitizenNoticeFixtures.ReproCase(id, response("GET", path, status, body), status, checks);
    }
    private HttpResponse<byte[]> response(String method, String path, int status, String body) {
        return response(method, path, status, body.getBytes(StandardCharsets.UTF_8));
    }
    private HttpResponse<byte[]> response(String method, String path, int status, byte[] body) {
        return response(method, path, status, body, List.of(REQUEST_ID));
    }
    private HttpResponse<byte[]> response(String method, String path, int status, byte[] body, List<String> requestIds) {
        HttpRequest request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:49152" + path))
                .header("Authorization", "Bearer DO_NOT_EXPORT_AUTH").method(method, HttpRequest.BodyPublishers.noBody()).build();
        return new HttpResponse<>() {
            public int statusCode() { return status; }
            public HttpRequest request() { return request; }
            public Optional<HttpResponse<byte[]>> previousResponse() { return Optional.empty(); }
            public HttpHeaders headers() { return HttpHeaders.of(Map.of("Set-Cookie", List.of("DO_NOT_EXPORT_COOKIE"), "X-Request-ID", requestIds), (name, value) -> true); }
            public byte[] body() { return body; }
            public Optional<SSLSession> sslSession() { return Optional.empty(); }
            public URI uri() { return request.uri(); }
            public HttpClient.Version version() { return HttpClient.Version.HTTP_1_1; }
        };
    }
}
