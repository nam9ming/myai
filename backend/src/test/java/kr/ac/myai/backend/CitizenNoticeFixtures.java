package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.springframework.jdbc.core.JdbcTemplate;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
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
        if (knownCost) {
            var document = (ObjectNode) input.path("documents").get(0);
            String text = document.path("cleaned_text").asText().replace("비용·자격·준비사항·신청 방법·모집 상태 미기재.", "참가비 5,000원. 자격·준비사항·신청 방법·모집 상태 미기재.");
            String body = text.substring(text.indexOf('\n') + 1).stripTrailing();
            String hash = ReviewedImportReader.sha256(text.getBytes(StandardCharsets.UTF_8));
            document.put("cleaned_text", text).put("raw_sha256", hash).put("text_sha256", hash);
            ((ObjectNode) document.path("block_index").get(1)).put("text", body);
            ((ObjectNode) document.path("checks").get(0)).put("text_sha256", hash);
            for (var evidence : input.path("evidence")) ((ObjectNode) evidence).put("text_sha256", hash);
            ((ObjectNode) input.path("evidence").get(1)).put("quote", body).put("end_char", body.codePointCount(0, body.length()));
            ((ObjectNode) revision(input).path("cost")).put("value", "5,000원").put("knowledge", "known").putNull("reason").putArray("evidence_ids").add("body-quote");
            Files.writeString(root.resolve(document.path("raw_asset_path").asText()), text);
        }
        return input;
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

    static Map<String, List<Map<String, Object>>> rows(JdbcTemplate jdbc) {
        var result = new LinkedHashMap<String, List<Map<String, Object>>>();
        for (String table : jdbc.queryForList("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME", String.class)) {
            if (!table.matches("[a-z_]+")) throw new IllegalStateException("합성 시험 테이블 이름을 확인할 수 없습니다.");
            result.put(table, jdbc.queryForList("SELECT * FROM `" + table + "` ORDER BY 1"));
        }
        return result;
    }
}
