package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.core.JsonParser;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.springframework.jdbc.core.JdbcTemplate;

import java.nio.charset.StandardCharsets;
import java.nio.charset.CodingErrorAction;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.LinkOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.FileAlreadyExistsException;
import java.net.http.HttpResponse;
import java.io.IOException;
import java.io.UncheckedIOException;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.UUID;
import java.util.regex.Pattern;

final class CitizenNoticeFixtures {
    final Path root;
    final JdbcTemplate jdbc;
    final ReviewedImportReader imports;
    final ReviewedImportService importer;
    final PublicationCommandReader commands;
    final PublicationService publication;
    final Set<String> ownedSnapshots;
    final ObjectMapper mapper = new ObjectMapper();

    CitizenNoticeFixtures(Path root, JdbcTemplate jdbc, ReviewedImportReader imports, ReviewedImportService importer,
                          PublicationCommandReader commands, PublicationService publication, Set<String> ownedSnapshots) {
        this.root = root; this.jdbc = jdbc; this.imports = imports; this.importer = importer;
        this.commands = commands; this.publication = publication; this.ownedSnapshots = ownedSnapshots;
    }

    ObjectNode citizen(String category, boolean knownCost) throws Exception {
        var input = fresh(true);
        revision(input).putArray("categories").add(category);
        if (knownCost) recordKnownCost(input, "5,000원");
        return input;
    }

    void recordKnownCost(ObjectNode input, String value) throws IOException {
        replaceCostText(input, "참가비 " + value);
        knownBodyFact(input, "cost", value);
    }

    void recordConflictingCost(ObjectNode input) throws IOException {
        replaceCostText(input, "신청 안내는 참가비 무료, 세부 안내는 참가비 2,000원");
        ((ObjectNode) revision(input).path("cost")).putNull("value").put("knowledge", "ambiguous")
                .put("reason", "원문의 참가비 안내가 서로 다름").putArray("evidence_ids").add("body-quote");
    }

    private void replaceCostText(ObjectNode input, String quote) throws IOException {
        String text = input.path("documents").get(0).path("cleaned_text").asText();
        replaceCitizenText(input, text.replace("비용·자격", quote + ". 자격"));
    }

    void recordScheduleStatus(ObjectNode input, String applicationPeriod, String occurrences,
                              String recruitment, String lifecycle) throws IOException {
        var revision = revision(input);
        String text = input.path("documents").get(0).path("cleaned_text").asText().stripTrailing()
                .replace("신청: " + revision.path("application_period").path("value").asText(), "당초 신청: " + applicationPeriod)
                .replace("진행: " + revision.path("occurrences").path("value").asText(), "당초 진행: " + occurrences);
        if (recruitment != null) {
            text = text.replace("·모집 상태 미기재.", " 미기재.") + " " + recruitment + ".";
            knownBodyFact(input, "recruitment", recruitment);
        }
        replaceCitizenText(input, text + " " + lifecycle + ".\n");
        knownBodyFact(input, "application_period", applicationPeriod);
        knownBodyFact(input, "occurrences", occurrences);
        knownBodyFact(input, "lifecycle", lifecycle);
    }

    private void replaceCitizenText(ObjectNode input, String text) throws IOException {
        var document = (ObjectNode) input.path("documents").get(0);
        String body = text.substring(text.indexOf('\n') + 1).stripTrailing();
        String hash = ReviewedImportReader.sha256(text.getBytes(StandardCharsets.UTF_8));
        document.put("cleaned_text", text).put("raw_sha256", hash).put("text_sha256", hash);
        ((ObjectNode) document.path("block_index").get(1)).put("text", body);
        ((ObjectNode) document.path("checks").get(0)).put("text_sha256", hash);
        for (var evidence : input.path("evidence")) ((ObjectNode) evidence).put("text_sha256", hash);
        ((ObjectNode) input.path("evidence").get(1)).put("quote", body).put("end_char", body.codePointCount(0, body.length()));
        Files.writeString(root.resolve(document.path("raw_asset_path").asText()), text);
    }

    private void knownBodyFact(ObjectNode input, String field, String value) {
        ((ObjectNode) revision(input).path(field)).put("value", value).put("knowledge", "known")
                .putNull("reason").putArray("evidence_ids").add("body-quote");
    }

    ObjectNode legacy() throws Exception { return fresh(false); }

    private ObjectNode fresh(boolean citizen) throws Exception {
        String text = Files.readString(Path.of("examples/" + (citizen ? "citizen-reviewed-import" : "reviewed-import") + ".json"));
        var ids = new HashMap<String, String>();
        var input = (ObjectNode) mapper.readTree(Pattern.compile("[12]0000000-0000-4000-8000-[0-9]{12}").matcher(text)
                .replaceAll(match -> ids.computeIfAbsent(match.group(), ignored -> UUID.randomUUID().toString())));
        var document = (ObjectNode) input.path("documents").get(0);
        String name = document.path("document_version_id").asText() + ".txt";
        Files.copy(Path.of("examples/" + (citizen ? "citizen-source" : "synthetic-source") + ".txt"), root.resolve(name));
        document.put("raw_asset_path", name);
        return input;
    }

    String approve(ObjectNode input, boolean citizen) {
        importer.importBatch(imports.read(input.toString().getBytes(StandardCharsets.UTF_8), root), "synthetic-importer");
        return decide(input, "approve", revision(input).path("revision_no").asLong(), citizen).revisionId();
    }

    PublicationService.Result decide(ObjectNode input, String action, long expected, boolean citizen) {
        return publication.execute(new PublicationCommand.Decision(citizen ? "citizen-review-command-v1" : "publication-command-v1",
                action, "합성 공지 검토", UUID.fromString(event(input)), expected, List.of("heading-quote", "body-quote")), root, "synthetic-reviewer");
    }

    String editTitleAndApprove(ObjectNode input, String title) {
        var original = jdbc.queryForMap("SELECT r.revision_no, r.payload_json FROM event_revisions r JOIN events e ON e.current_review_revision_id=r.revision_id WHERE e.event_id=?", event(input));
        long number = ((Number) original.get("revision_no")).longValue();
        String at = Instant.now().truncatedTo(ChronoUnit.MICROS).toString();
        ((ObjectNode) input.path("events").get(0)).put("expected_revision_no", number);
        var revision = revision(input);
        String before = revision.path("title").asText();
        revision.put("revision_id", UUID.randomUUID().toString()).put("revision_no", number + 1).put("title", title)
                .put("review_status", "needs_review").put("publication_intent", "hidden").put("reviewer_id", "synthetic-reviewer").put("reviewed_at", at);
        var change = revision.withArray("human_overrides").addObject().put("field_path", "title").put("before", before).put("after", title)
                .put("reason", "합성 제목 재검토").put("reviewer", "synthetic-reviewer").put("time", at);
        change.putArray("evidence_ids").add("heading-quote");
        importer.importBatch(imports.read(input.toString().getBytes(StandardCharsets.UTF_8), root), "synthetic-editor");
        return decide(input, "approve", number + 1, true).revisionId();
    }

    PublicationService.Result publish(List<String> revisions, Long expected) {
        var request = mapper.createObjectNode().put("schema_version", "citizen-publication-command-v1").put("action", "publish")
                .put("reason", "합성 시민 공개").put("data_kind", "synthetic");
        var selected = request.putArray("revision_ids"); revisions.forEach(selected::add);
        if (expected == null) request.putNull("expected_head_version"); else request.put("expected_head_version", expected);
        return execute(request, root);
    }

    PublicationService.Result rollback(String id, long expected) {
        return execute(mapper.createObjectNode().put("schema_version", "citizen-publication-command-v1").put("action", "rollback")
                .put("reason", "합성 시민 공개 복구").put("snapshot_id", id).put("expected_head_version", expected), null);
    }

    PublicationService.Result publishLegacy(ObjectNode input, String revisionId) throws Exception {
        var request = (ObjectNode) mapper.readTree(Path.of("examples/publish.json").toFile());
        String area = input.path("events").get(0).path("area_id").asText();
        ((ObjectNode) request.path("area")).put("area_id", area);
        for (var point : request.path("points")) ((ObjectNode) point).put("area_id", area).put("point_id", UUID.randomUUID().toString());
        request.putArray("revision_ids").add(revisionId);
        request.putNull("expected_head_version");
        return execute(request, root);
    }

    private PublicationService.Result execute(ObjectNode request, Path sourceRoot) {
        var result = publication.execute(commands.read(request.toString().getBytes(StandardCharsets.UTF_8)), sourceRoot, "synthetic-publisher");
        if (result.action().equals("publish")) ownedSnapshots.add(result.snapshotId());
        return result;
    }

    JsonNode canonical(String id) throws Exception { return mapper.readTree(canonicalText(id)); }
    String canonicalText(String id) { return jdbc.queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id=?", String.class, id); }
    void replaceCanonical(String id, JsonNode canonical) {
        String text = canonical.toString();
        jdbc.update("UPDATE snapshots SET canonical_json=?, checksum=? WHERE snapshot_id=?", text,
                ReviewedImportReader.sha256(text.getBytes(StandardCharsets.UTF_8)), id);
    }

    static ObjectNode revision(ObjectNode input) { return (ObjectNode) input.path("events").get(0).path("revision"); }
    static String event(ObjectNode input) { return input.path("events").get(0).path("event_id").asText(); }

    record ReproCase(String id, HttpResponse<byte[]> response, int expectedStatus, Map<String, ?> checks) { }

    static Path createReproDirectory(String scenario) {
        reproCheck(scenario != null && scenario.matches("[a-z][a-z0-9_-]{0,63}"));
        try {
            Path base = Path.of("").toRealPath();
            for (String part : List.of("build", "repro", "citizen-api-v1")) {
                base = base.resolve(part);
                try { Files.createDirectory(base); }
                catch (FileAlreadyExistsException ignored) { /* 병렬 시험이 먼저 만든 폴더도 아래에서 확인한다. */ }
                reproCheck(Files.isDirectory(base, LinkOption.NOFOLLOW_LINKS));
            }
            Path directory = Files.createTempDirectory(base, scenario + "-");
            Files.createDirectory(directory.resolve("snapshots")); return directory;
        } catch (IOException ex) { throw new UncheckedIOException("합성 재현 출력 디렉터리를 만들지 못했습니다.", ex); }
    }

    private static final ObjectMapper REPRO_JSON = new ObjectMapper().enable(JsonParser.Feature.STRICT_DUPLICATE_DETECTION)
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);
    private static final Set<String> PRIVATE_REPRO_FIELDS = Set.of("raw_asset_path", "cleaned_text", "block_index", "raw_ref",
            "private_content_ref", "metadata_json", "payload_json", "human_overrides", "human_handoffs", "originating_run_ids",
            "reviewer_id", "reviewed_at", "source_review_no", "source_review_sha256", "receipt", "prompt", "authorization",
            "token", "password", "secret", "webhook", "access_token");

    // 두 공개 합성 HTTP 시험에서만 호출한다. snapshot은 기존 exporter가 검증한 파일이다.
    static void writeRepro(Path directory, String scenario, String mysqlVersion, List<ReproCase> cases) {
        reproCheck(scenario != null && scenario.matches("[a-z][a-z0-9_-]{0,63}") && mysqlVersion != null
                && mysqlVersion.matches("[0-9]+\\.[0-9]+\\.[0-9]+(?:[-+][a-zA-Z0-9._-]+)?") && cases != null && !cases.isEmpty());
        try {
            reproCheck(Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS));
            directory = directory.toRealPath(); Path snapshots = directory.resolve("snapshots");
            reproCheck(Files.isDirectory(snapshots, LinkOption.NOFOLLOW_LINKS));
            try (var entries = Files.list(directory)) { reproCheck(entries.allMatch(path -> path.equals(snapshots))); }
            var output = new LinkedHashMap<String, byte[]>();
            var manifest = REPRO_JSON.createObjectNode().put("schema_version", "citizen-api-repro-v1")
                    .put("api_schema", "citizen-api-v1").put("snapshot_schema", "citizen-snapshot-v1")
                    .put("data_kind", "synthetic").put("scenario", scenario).put("response_checks", "passed");
            var runtime = manifest.putObject("runtime").put("java", System.getProperty("java.version"))
                    .put("spring_boot", org.springframework.boot.SpringBootVersion.getVersion()).put("mysql", mysqlVersion)
                    .put("jar_sha256", reproHash(Path.of("build/libs/myai-backend-0.1.0.jar")));
            String checkout = System.getenv("GITHUB_SHA");
            if ("true".equals(System.getenv("GITHUB_ACTIONS")) && checkout != null && checkout.matches("[0-9a-f]{40}")) runtime.put("ci_checkout_sha", checkout);
            else runtime.putNull("ci_checkout_sha");
            var recorded = manifest.putArray("cases"); var ids = new HashSet<String>();
            var snapshotIds = new TreeSet<String>(); var eventIds = new TreeSet<String>(); var revisionIds = new TreeSet<String>();
            for (var item : cases) {
                reproCheck(item != null && item.id() != null && item.id().matches("[a-z][a-z0-9-]{0,63}") && ids.add(item.id())
                        && item.response() != null && item.checks() != null && !item.checks().isEmpty());
                var response = item.response(); var uri = response.request().uri();
                reproCheck(response.request().method().equals("GET") && response.uri().equals(uri) && uri.getRawUserInfo() == null
                        && uri.getRawFragment() == null && uri.getRawPath().matches("/api/v1/citizen/notices(?:/[0-9a-f-]{36})?"));
                String query = uri.getRawQuery();
                reproCheck(query == null || query.matches("(?:snapshot_id=[0-9a-f-]{36}|history_(?:before_version|limit)=[0-9]+|cost=free)(?:&(?:snapshot_id=[0-9a-f-]{36}|history_(?:before_version|limit)=[0-9]+|cost=free))*"));
                byte[] actualBytes = reproUtf8(response.body()); JsonNode actual = REPRO_JSON.readTree(actualBytes);
                reproExpectation(response.statusCode() == item.expectedStatus(), item, "/status");
                reproPublicResponse(actual, response);
                var expected = REPRO_JSON.createObjectNode().put("status", item.expectedStatus());
                var checks = expected.putObject("checks");
                for (var check : item.checks().entrySet()) {
                    reproCheck(check.getKey() != null && check.getKey().startsWith("/"));
                    JsonNode value = reproValue(check.getValue());
                    value = REPRO_JSON.readTree(REPRO_JSON.writeValueAsBytes(value));
                    JsonNode found = actual.at(check.getKey());
                    reproExpectation(!found.isMissingNode() && found.equals(value), item, check.getKey()); checks.set(check.getKey(), value);
                }
                String requestName = item.id() + ".request.json", actualName = item.id() + ".actual.json", expectedName = item.id() + ".expected.json";
                var request = REPRO_JSON.createObjectNode().put("method", "GET").put("path_query", uri.getRawPath() + (query == null ? "" : "?" + query)).putNull("body");
                output.put(requestName, REPRO_JSON.writeValueAsBytes(request)); output.put(actualName, actualBytes);
                output.put(expectedName, REPRO_JSON.writeValueAsBytes(expected));
                recorded.addObject().put("id", item.id()).put("actual_status", response.statusCode()).put("expected_status", item.expectedStatus())
                        .put("request", requestName).put("actual", actualName).put("expected", expectedName);
                reproIds(actual, snapshotIds, eventIds, revisionIds);
            }
            try (var files = Files.list(snapshots)) {
                for (Path file : files.sorted().toList()) {
                    reproCheck(Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS) && file.getFileName().toString().matches("[0-9a-f-]{36}-[0-9a-f]{64}\\.json") && Files.size(file) <= 8L * 1024 * 1024);
                    byte[] bytes = Files.readAllBytes(file); JsonNode snapshot = REPRO_JSON.readTree(bytes);
                    reproShape(snapshot, "schema_version snapshot_id created_at data_kind mode case_id channel_key timezone revision_ids notices sources notice_count");
                    reproCheck(snapshot.path("schema_version").asText().equals("citizen-snapshot-v1") && snapshot.path("data_kind").asText().equals("synthetic")
                            && file.getFileName().toString().equals(snapshot.path("snapshot_id").asText() + "-" + ReviewedImportReader.sha256(bytes) + ".json"));
                    reproNoPrivate(snapshot); reproIds(snapshot, snapshotIds, eventIds, revisionIds);
                    output.put("snapshots/" + file.getFileName(), bytes);
                }
            }
            manifest.set("snapshot_ids", REPRO_JSON.valueToTree(snapshotIds)); manifest.set("event_ids", REPRO_JSON.valueToTree(eventIds));
            manifest.set("revision_ids", REPRO_JSON.valueToTree(revisionIds)); var artifacts = manifest.putArray("artifacts");
            for (var entry : output.entrySet()) artifacts.addObject().put("path", entry.getKey()).put("size", entry.getValue().length).put("sha256", ReviewedImportReader.sha256(entry.getValue()));
            for (var entry : output.entrySet()) if (!entry.getKey().startsWith("snapshots/"))
                Files.write(directory.resolve(entry.getKey()), entry.getValue(), StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
            for (var entry : output.entrySet()) reproCheck(MessageDigest.isEqual(Files.readAllBytes(directory.resolve(entry.getKey())), entry.getValue()));
            Path temporary = Files.createTempFile(directory, ".manifest-", ".tmp");
            try {
                Files.write(temporary, REPRO_JSON.writeValueAsBytes(manifest), StandardOpenOption.WRITE);
                Files.createLink(directory.resolve("manifest.json"), temporary);
            } finally { Files.deleteIfExists(temporary); }
        } catch (IOException ex) { throw new UncheckedIOException("합성 공개 재현 파일 저장에 실패했습니다.", ex); }
    }

    private static void reproPublicResponse(JsonNode value, HttpResponse<byte[]> response) {
        int status = response.statusCode();
        reproNoPrivate(value);
        if (status == 200) {
            reproShape(value, "schema_version snapshot_id generated_at data");
            reproCheck(value.path("schema_version").asText().equals("citizen-api-v1") && value.path("data").path("data_kind").asText().equals("synthetic"));
            reproShape(value.path("data"), value.path("data").has("notices")
                    ? "created_at data_kind mode timezone notice_count notices sources" : "created_at data_kind mode timezone notice sources history");
        } else {
            reproCheck(status >= 400 && status <= 599);
            reproShape(value, value.has("current_snapshot_id") ? "error request_id current_snapshot_id" : "error request_id");
            reproShape(value.path("error"), "code message field_errors retryable");
            reproCheck(value.path("error").path("field_errors").isArray());
            value.path("error").path("field_errors").forEach(field -> reproShape(field, "field message"));
            String requestId = value.path("request_id").textValue();
            var headerIds = response.headers().allValues("X-Request-ID");
            reproCheck(requestId != null && requestId.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
                    && headerIds.size() == 1 && requestId.equals(headerIds.getFirst()));
        }
    }

    private static void reproNoPrivate(JsonNode value) {
        if (value.isObject()) value.fields().forEachRemaining(field -> { reproCheck(!PRIVATE_REPRO_FIELDS.contains(field.getKey())); reproNoPrivate(field.getValue()); });
        else if (value.isArray()) value.forEach(CitizenNoticeFixtures::reproNoPrivate);
        else if (value.isFloatingPointNumber()) reproCheck(Double.isFinite(value.doubleValue()));
    }

    private static void reproShape(JsonNode value, String fields) {
        var names = new HashSet<String>(); value.fieldNames().forEachRemaining(names::add);
        reproCheck(value.isObject() && names.equals(Set.of(fields.split(" "))));
    }

    private static JsonNode reproValue(Object value) {
        if (value == null) return REPRO_JSON.nullNode();
        if (value instanceof JsonNode node) { reproNoPrivate(node); return node; }
        if (value instanceof List<?> list) { var result = REPRO_JSON.createArrayNode(); list.forEach(item -> result.add(reproValue(item))); return result; }
        if (value instanceof Map<?, ?> map) {
            var result = REPRO_JSON.createObjectNode(); map.forEach((key, item) -> { reproCheck(key instanceof String); result.set((String) key, reproValue(item)); }); return result;
        }
        reproCheck(value instanceof String || value instanceof Boolean || value instanceof Number);
        var result = REPRO_JSON.valueToTree(value); reproNoPrivate(result); return result;
    }

    private static void reproIds(JsonNode value, Set<String> snapshots, Set<String> events, Set<String> revisions) {
        if (value.isObject()) value.fields().forEachRemaining(field -> {
            Set<String> selected = switch (field.getKey()) { case "snapshot_id", "current_snapshot_id" -> snapshots; case "event_id" -> events; case "revision_id" -> revisions; default -> null; };
            if (selected != null && field.getValue().isTextual()) { String id = field.getValue().asText(); reproCheck(id.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")); selected.add(id); }
            reproIds(field.getValue(), snapshots, events, revisions);
        });
        else if (value.isArray()) value.forEach(item -> reproIds(item, snapshots, events, revisions));
    }

    private static byte[] reproUtf8(byte[] value) throws IOException {
        reproCheck(value != null);
        byte[] bytes = value.clone();
        StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes));
        return bytes;
    }

    private static String reproHash(Path file) throws IOException {
        try (var input = Files.newInputStream(file)) {
            var digest = MessageDigest.getInstance("SHA-256"); byte[] buffer = new byte[64 * 1024]; int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
            return HexFormat.of().formatHex(digest.digest());
        } catch (java.security.NoSuchAlgorithmException ex) { throw new IllegalStateException(ex); }
    }

    private static void reproCheck(boolean valid) { if (!valid) throw new IllegalArgumentException("합성 공개 재현의 경로·응답·기대값·파일 보존 조건을 확인해 주세요."); }

    private static void reproExpectation(boolean valid, ReproCase item, String pointer) {
        if (!valid) throw new IllegalArgumentException("재현 기대값 불일치: case=" + item.id() + ", pointer=" + pointer
                + ", expected_status=" + item.expectedStatus() + ", actual_status=" + item.response().statusCode());
    }

    static Map<String, List<Map<String, Object>>> rows(JdbcTemplate jdbc) {
        var result = new LinkedHashMap<String, List<Map<String, Object>>>();
        for (String table : jdbc.queryForList("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME", String.class)) {
            if (!table.matches("[a-z_]+")) throw new IllegalStateException("합성 시험 테이블 이름을 확인할 수 없습니다.");
            result.put(table, jdbc.queryForList("SELECT * FROM `" + table + "` ORDER BY 1"));
        }
        return result;
    }
}
