package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.review.ReviewReportService;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ReviewedImportService;
import kr.ac.myai.backend.service.SnapshotExportService;
import kr.ac.myai.backend.service.SourceReviewService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.*;

@SpringBootTest(properties = "app.calculation.workdir=")
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class CitizenPublicationMySqlTest {
    @Autowired ReviewedImportReader imports;
    @Autowired ReviewedImportService importer;
    @Autowired PublicationCommandReader commands;
    @Autowired PublicationService publication;
    @Autowired SourceReviewService sources;
    @Autowired SnapshotExportService exporter;
    @Autowired ReviewReportService reports;
    @Autowired JdbcTemplate jdbc;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final Set<String> ownedSnapshots = ConcurrentHashMap.newKeySet();
    boolean testDatabaseVerified;

    @DynamicPropertySource
    static void testDatabase(DynamicPropertyRegistry registry) {
        String url = System.getenv("DB_URL");
        if (url == null || !url.startsWith("jdbc:mysql://")
                || !Set.of("/myai_test", "/myai_citizen_test").contains(URI.create(url.substring(5)).getRawPath())) {
            throw new IllegalStateException("시민 공개 시험은 전용 myai_test 또는 myai_citizen_test DB_URL이 필요합니다.");
        }
        registry.add("spring.datasource.url", () -> url);
    }

    @BeforeEach
    void syntheticSourcesAndUnusedCitizenChannel() throws Exception {
        assertThat(jdbc.queryForObject("SELECT DATABASE()", String.class)).isIn("myai_test", "myai_citizen_test");
        testDatabaseVerified = true;
        assertThat(jdbc.queryForList("SELECT snapshot_id FROM publication_heads WHERE channel_key = 'citizen:current'"))
                .as("기존 시민 head는 시험이 덮어쓰거나 초기화하지 않는다").isEmpty();
        for (String name : List.of("citizen-source.txt", "synthetic-source.txt")) {
            Files.copy(Path.of("examples/" + name), root.resolve(name));
        }
    }

    @AfterEach
    void removeOnlyOwnedSnapshots() {
        if (!testDatabaseVerified) return;
        for (String id : ownedSnapshots) jdbc.update("DELETE FROM publication_audits WHERE after_snapshot_id = ?", id);
        for (String id : ownedSnapshots) jdbc.update("DELETE FROM publication_heads WHERE snapshot_id = ?", id);
        for (String id : ownedSnapshots) jdbc.update("DELETE FROM snapshot_revisions WHERE snapshot_id = ?", id);
        for (String id : ownedSnapshots) jdbc.update("DELETE FROM snapshots WHERE snapshot_id = ?", id);
        ownedSnapshots.clear();
    }

    @ParameterizedTest
    @ValueSource(strings = {"education", "support", "culture", "construction_traffic", "living"})
    void publishesEveryCitizenCategoryWithoutLegacyContext(String category) throws Exception {
        var input = fresh(true); revision(input).putArray("categories").add(category);
        String approved = approve(input, true);
        var before = databaseCounts();
        var legacyHead = jdbc.queryForList("SELECT * FROM publication_heads WHERE channel_key = 'current'");
        var preview = execute(request("preview", List.of(approved), null));
        assertThat(databaseCounts()).isEqualTo(before);
        assertThat(preview.headVersion()).isNull();
        assertThat(preview.preview().path("notices").get(0).path("categories").get(0).asText()).isEqualTo(category);
        var result = execute(request("publish", List.of(approved), null));
        assertThat(result.headVersion()).isZero();
        var frozen = mapper.readTree(canonical(result.snapshotId()));
        assertThat(frozen.path("schema_version").asText()).isEqualTo("citizen-snapshot-v1");
        assertThat(frozen.path("channel_key").asText()).isEqualTo("citizen:current");
        assertThat(frozen.path("mode").asText()).isEqualTo("current");
        assertThat(frozen.path("case_id").isNull()).isTrue();
        assertThat(frozen.has("area")).isFalse(); assertThat(frozen.has("points")).isFalse();
        assertThat(frozen.has("rules_version")).isFalse(); assertThat(frozen.has("dictionary_version")).isFalse();
        var notice = frozen.path("notices").get(0);
        assertThat(notice.path("revision_id").asText()).isEqualTo(approved);
        assertThat(notice.path("application_period").path("value").asText()).isEqualTo("2026-11-20~2026-11-25");
        assertThat(notice.path("occurrences").path("value").asText()).isEqualTo("2026-12-01~2026-12-02");
        assertThat(notice.path("cost").path("value").isNull()).isTrue();
        assertThat(canonical(result.snapshotId())).doesNotContain("raw_asset_path", "cleaned_text", "human_overrides", "reviewer_id", "originating_run_ids", "citizen-source.txt");
        assertThat(jdbc.queryForMap("SELECT schema_version, rules_version, dictionary_version FROM snapshots WHERE snapshot_id = ?", result.snapshotId()))
                .containsEntry("schema_version", "citizen-snapshot-v1").containsEntry("rules_version", null).containsEntry("dictionary_version", null);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM snapshot_revisions WHERE snapshot_id = ? AND revision_id = ?", Long.class, result.snapshotId(), approved)).isEqualTo(1);
        assertThat(jdbc.queryForList("SELECT * FROM publication_heads WHERE channel_key = 'current'")).isEqualTo(legacyHead);
    }

    @Test
    void emptyPublicationAdvancesCitizenHeadAndRollbackNeedsNoSourceFiles() throws Exception {
        var input = fresh(true); String approved = approve(input, true);
        var first = execute(request("publish", List.of(approved), null));
        String original = canonical(first.snapshotId());
        var empty = execute(request("publish", List.of(), 0L));
        assertThat(empty.headVersion()).isEqualTo(1);
        assertThat(mapper.readTree(canonical(empty.snapshotId())).path("notice_count").asInt()).isZero();
        assertThat(mapper.readTree(canonical(empty.snapshotId())).path("sources")).isEmpty();
        Files.delete(root.resolve("citizen-source.txt"));
        var result = publication.execute(command(rollback(first.snapshotId(), 1)), null, "synthetic-rollback");
        assertThat(result.headVersion()).isEqualTo(2);
        assertThat(head()).isEqualTo(first.snapshotId());
        assertThat(canonical(first.snapshotId())).isEqualTo(original);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM publication_audits WHERE channel_key = 'citizen:current'", Long.class)).isEqualTo(3);
    }

    @Test
    void previewWritesNeitherDatabaseNorSourceDirectory() throws Exception {
        var input = fresh(true); String approved = approve(input, true);
        var before = databaseCounts();
        var bytes = Files.readAllBytes(root.resolve("citizen-source.txt"));
        for (int i = 0; i < 2; i++) {
            var result = execute(request("preview", List.of(approved), null));
            assertThat(result.preview().path("notice_count").asInt()).isEqualTo(1);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM snapshots WHERE snapshot_id = ?", Long.class, result.snapshotId())).isZero();
        }
        assertThat(databaseCounts()).isEqualTo(before);
        assertThat(Files.readAllBytes(root.resolve("citizen-source.txt"))).isEqualTo(bytes);
        try (var files = Files.list(root)) {
            assertThat(files.map(path -> path.getFileName().toString()).toList()).containsExactlyInAnyOrder("citizen-source.txt", "synthetic-source.txt");
        }
    }

    @Test
    void exportPreservesRetiredCitizenBytesAfterRawDeletionAndRollback() throws Exception {
        var input = fresh(true); String approved = approve(input, true);
        var first = execute(request("publish", List.of(approved), null));
        byte[] original = canonical(first.snapshotId()).getBytes(StandardCharsets.UTF_8);
        execute(request("publish", List.of(), 0L));
        Files.delete(root.resolve("citizen-source.txt"));
        Path output = Files.createDirectory(root.resolve("exports")); var before = databaseCounts();
        var exported = exporter.export(UUID.fromString(first.snapshotId()), output);
        assertThat(Files.readAllBytes(output.resolve(exported.fileName()))).isEqualTo(original);
        assertThat(exported.checksum()).isEqualTo(first.checksum());
        assertThat(databaseCounts()).isEqualTo(before);
        publication.execute(command(rollback(first.snapshotId(), 1)), null, "synthetic-rollback");
        before = databaseCounts();
        assertThat(exporter.export(UUID.fromString(first.snapshotId()), output).alreadyExported()).isTrue();
        assertThat(Files.readAllBytes(output.resolve(exported.fileName()))).isEqualTo(original);
        assertThat(databaseCounts()).isEqualTo(before);
    }

    @Test
    void reportValidatesCitizenPublicationAndUsesCitizenHeadForExplicitPreview() throws Exception {
        var input = fresh(true); String approved = approve(input, true);
        var published = execute(request("publish", List.of(approved), null));
        var preview = request("preview", List.of(approved), 0L);
        Path file = Files.writeString(root.resolve("preview.json"), preview.toString());
        var before = databaseCounts();
        var report = reports.build(UUID.fromString(input.path("documents").get(0).path("document_version_id").asText()), root, file);
        assertThat(report.path("publication").path("snapshots")).hasSize(1);
        assertThat(report.path("publication").path("snapshots").get(0).path("validation").path("status").asText()).isEqualTo("valid");
        assertThat(report.path("preview").path("status").asText()).isEqualTo("valid");
        var summary = report.path("preview").path("summary");
        assertThat(summary.path("status").asText()).isEqualTo("available");
        assertThat(summary.path("baseline").path("channel_key").asText()).isEqualTo("citizen:current");
        assertThat(summary.path("baseline").path("snapshot_id").asText()).isEqualTo(published.snapshotId());
        assertThat(summary.path("unchanged_events").asInt()).isEqualTo(1);
        assertThat(summary.path("cancelled_events").isNull()).isTrue();
        preview.putArray("revision_ids"); Files.writeString(file, preview.toString());
        var removed = reports.build(UUID.fromString(input.path("documents").get(0).path("document_version_id").asText()), root, file).path("preview").path("summary");
        assertThat(removed.path("removed_events").asInt()).isEqualTo(1);
        assertThat(removed.path("cancelled_events").isNull()).isTrue();
        assertThat(databaseCounts()).isEqualTo(before);
        assertThat(head()).isEqualTo(published.snapshotId());
    }

    @Test
    void unrelatedCitizenDocumentCannotRequestEmptyPreviewAgainstExistingHead() throws Exception {
        var current = fresh(true); String publishedRevision = approve(current, true);
        var published = execute(request("publish", List.of(publishedRevision), null));
        var unrelated = fresh(true); approve(unrelated, true);
        Path file = Files.writeString(root.resolve("unrelated-preview.json"), request("preview", List.of(), 0L).toString());
        var before = databaseCounts();
        var headBefore = jdbc.queryForList("SELECT * FROM publication_heads WHERE channel_key = 'citizen:current'");
        String preserved = canonical(published.snapshotId());
        var report = reports.build(UUID.fromString(unrelated.path("documents").get(0).path("document_version_id").asText()), root, file);
        assertThat(report.path("preview").path("status").asText()).isEqualTo("invalid");
        assertThat(report.path("preview").path("code").asText()).isEqualTo("REPORT_PREVIEW_INVALID");
        assertThat(databaseCounts()).isEqualTo(before);
        assertThat(jdbc.queryForList("SELECT * FROM publication_heads WHERE channel_key = 'citizen:current'")).isEqualTo(headBefore);
        assertThat(canonical(published.snapshotId())).isEqualTo(preserved);
    }

    @ParameterizedTest
    @ValueSource(strings = {"pending", "old_approval", "restricted", "raw_hash", "payload_hash", "evidence", "data_kind", "future_review"})
    void changedOrUnapprovedCitizenStateCannotReplacePublishedSnapshot(String defect) throws Exception {
        var safe = execute(request("publish", List.of(), null));
        String preserved = canonical(safe.snapshotId());
        var input = fresh(true);
        String selected;
        if (defect.equals("pending")) {
            var batch = imports.read(input.toString().getBytes(StandardCharsets.UTF_8), root);
            importer.importBatch(batch, "synthetic-importer"); selected = batch.events().getFirst().revisionId();
        } else selected = approve(input, true);
        if (defect.equals("old_approval")) publication.execute(decision(input, "reject", 2, true), null, "synthetic-reviewer");
        if (defect.equals("restricted")) restrict(input);
        if (defect.equals("raw_hash")) Files.writeString(root.resolve("citizen-source.txt"), "변경한 합성 원문");
        if (defect.equals("payload_hash")) jdbc.update("UPDATE event_revisions SET payload_sha256 = ? WHERE revision_id = ?", "0".repeat(64), selected);
        if (Set.of("evidence", "data_kind", "future_review").contains(defect)) {
            var payload = (ObjectNode) mapper.readTree(jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id = ?", String.class, selected));
            if (defect.equals("evidence")) ((ObjectNode) payload.path("evidence").get(0)).put("quote", "없는 근거");
            if (defect.equals("data_kind")) payload.put("data_kind", "real");
            if (defect.equals("future_review")) ((ObjectNode) payload.path("revision")).put("reviewed_at", "2999-01-01T00:00:00Z");
            String json = payload.toString();
            jdbc.update("UPDATE event_revisions SET payload_json = ?, payload_sha256 = ? WHERE revision_id = ?", json,
                    ReviewedImportReader.sha256(json.getBytes(StandardCharsets.UTF_8)), selected);
        }
        var before = databaseCounts();
        for (String action : List.of("preview", "publish")) {
            var publicationRequest = request(action, List.of(selected), 0L);
            assertThatThrownBy(() -> execute(publicationRequest)).isInstanceOf(PublicationException.class);
        }
        assertThat(databaseCounts()).isEqualTo(before);
        assertThat(head()).isEqualTo(safe.snapshotId());
        assertThat(canonical(safe.snapshotId())).isEqualTo(preserved);
    }

    @Test
    void citizenAndLegacyPublicationRemainSeparateInSameDatabase() throws Exception {
        var legacy = fresh(false); String approved = approve(legacy, false);
        var legacyRequest = (ObjectNode) mapper.readTree(Path.of("examples/publish.json").toFile());
        String area = legacy.path("events").get(0).path("area_id").asText();
        ((ObjectNode) legacyRequest.path("area")).put("area_id", area);
        for (JsonNode point : legacyRequest.path("points")) ((ObjectNode) point).put("area_id", area).put("point_id", UUID.randomUUID().toString());
        String caseId = UUID.randomUUID().toString();
        legacyRequest.put("mode", "replay").put("case_id", caseId).put("anchor_date", "2026-11-02")
                .put("reference_instant", "2026-11-02T03:00:00Z").put("knowledge_cutoff", "2026-11-02T03:00:00Z")
                .put("history_fidelity", "reconstructed").putNull("expected_head_version");
        legacyRequest.putArray("revision_ids").add(approved);
        var old = execute(legacyRequest); String bytes = canonical(old.snapshotId());
        var citizen = execute(request("publish", List.of(), null));
        var before = databaseCounts();
        for (String action : List.of("preview", "publish")) {
            assertThatThrownBy(() -> execute(request(action, List.of(approved), 0L))).isInstanceOf(PublicationException.class);
        }
        assertThatThrownBy(() -> publication.execute(command(rollback(old.snapshotId(), 0)), null, "synthetic-reviewer"))
                .isInstanceOf(PublicationException.class);
        assertThat(databaseCounts()).isEqualTo(before); assertThat(head()).isEqualTo(citizen.snapshotId());
        assertThat(canonical(old.snapshotId())).isEqualTo(bytes);
        assertThat(jdbc.queryForObject("SELECT snapshot_id FROM publication_heads WHERE channel_key = ?", String.class, "replay:" + caseId)).isEqualTo(old.snapshotId());
        var unrelatedAudits = jdbc.queryForList("SELECT * FROM publication_audits WHERE after_snapshot_id = ?", old.snapshotId());
        ownedSnapshots.remove(old.snapshotId());
        try { removeOnlyOwnedSnapshots(); }
        finally { ownedSnapshots.add(old.snapshotId()); }
        assertThat(canonical(old.snapshotId())).isEqualTo(bytes);
        assertThat(jdbc.queryForList("SELECT * FROM publication_audits WHERE after_snapshot_id = ?", old.snapshotId())).isEqualTo(unrelatedAudits);
        assertThat(jdbc.queryForObject("SELECT snapshot_id FROM publication_heads WHERE channel_key = ?", String.class, "replay:" + caseId)).isEqualTo(old.snapshotId());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM snapshots WHERE snapshot_id = ?", Long.class, citizen.snapshotId())).isZero();
    }

    @Test
    void staleHeadAndLateAuditFailureLeaveEntirePublicationUnchanged() throws Exception {
        var first = execute(request("publish", List.of(), null));
        var input = fresh(true); String approved = approve(input, true);
        var before = databaseCounts();
        assertThatThrownBy(() -> execute(request("publish", List.of(approved), null)))
                .isInstanceOfSatisfying(PublicationException.class, ex -> assertThat(ex.code()).isEqualTo("PUBLICATION_CONFLICT"));
        String marker = "citizen-late-" + UUID.randomUUID();
        String constraint = "citizen_test_" + UUID.randomUUID().toString().replace("-", "");
        jdbc.execute("ALTER TABLE publication_audits ADD CONSTRAINT " + constraint + " CHECK (reason <> '" + marker + "')");
        try {
            var request = request("publish", List.of(approved), 0L).put("reason", marker);
            assertThatThrownBy(() -> execute(request)).isInstanceOf(PublicationException.class);
        } finally { jdbc.execute("ALTER TABLE publication_audits DROP CHECK " + constraint); }
        assertThat(databaseCounts()).isEqualTo(before); assertThat(head()).isEqualTo(first.snapshotId());
        assertThat(jdbc.queryForObject("SELECT lock_version FROM publication_heads WHERE channel_key = 'citizen:current'", Long.class)).isZero();
    }

    @Test
    void simultaneousPublicationHasExactlyOneSnapshotHeadAndAuditWinner() throws Exception {
        var input = fresh(true); String approved = approve(input, true);
        var request = request("publish", List.of(approved), null); var before = databaseCounts();
        var barrier = new CyclicBarrier(2);
        try (var pool = Executors.newFixedThreadPool(2)) {
            java.util.concurrent.Callable<String> action = () -> {
                barrier.await(10, TimeUnit.SECONDS);
                try { execute(request); return "success"; }
                catch (PublicationException ex) { return ex.code(); }
            };
            var left = pool.submit(action); var right = pool.submit(action);
            assertThat(List.of(left.get(30, TimeUnit.SECONDS), right.get(30, TimeUnit.SECONDS)))
                    .containsExactlyInAnyOrder("success", "PUBLICATION_CONFLICT");
        }
        var after = databaseCounts();
        for (int i : List.of(0, 1, 2, 3)) assertThat(after.get(i)).isEqualTo(before.get(i) + 1);
        assertThat(ownedSnapshots).containsExactly(head());
    }

    @ParameterizedTest
    @ValueSource(strings = {"checksum", "canonical_channel", "created_at", "missing_publish_audit"})
    void rollbackRejectsCorruptOrNeverPublishedCitizenSnapshot(String defect) throws Exception {
        var first = execute(request("publish", List.of(), null));
        var second = execute(request("publish", List.of(), 0L));
        if (defect.equals("checksum")) jdbc.update("UPDATE snapshots SET checksum = ? WHERE snapshot_id = ?", "0".repeat(64), first.snapshotId());
        if (defect.equals("canonical_channel")) {
            var canonical = (ObjectNode) mapper.readTree(canonical(first.snapshotId())); canonical.put("channel_key", "current");
            String json = canonical.toString(); jdbc.update("UPDATE snapshots SET canonical_json = ?, checksum = ? WHERE snapshot_id = ?", json,
                    ReviewedImportReader.sha256(json.getBytes(StandardCharsets.UTF_8)), first.snapshotId());
        }
        if (defect.equals("created_at")) jdbc.update("UPDATE snapshots SET created_at = '2020-01-01 00:00:00' WHERE snapshot_id = ?", first.snapshotId());
        if (defect.equals("missing_publish_audit")) jdbc.update("DELETE FROM publication_audits WHERE after_snapshot_id = ?", first.snapshotId());
        var before = databaseCounts();
        assertThatThrownBy(() -> publication.execute(command(rollback(first.snapshotId(), 1)), null, "synthetic-rollback"))
                .isInstanceOf(PublicationException.class);
        assertThat(databaseCounts()).isEqualTo(before); assertThat(head()).isEqualTo(second.snapshotId());
    }

    private PublicationService.Result execute(ObjectNode request) {
        var result = publication.execute(command(request), root, "synthetic-publisher");
        if (result.action().equals("publish")) ownedSnapshots.add(result.snapshotId());
        return result;
    }

    private ObjectNode request(String action, List<String> revisions, Long expected) {
        var request = mapper.createObjectNode().put("schema_version", "citizen-publication-command-v1")
                .put("action", action).put("reason", "합성 시민 공개 시험").put("data_kind", "synthetic");
        var ids = request.putArray("revision_ids"); revisions.forEach(ids::add);
        if (expected == null) request.putNull("expected_head_version"); else request.put("expected_head_version", expected);
        return request;
    }

    private ObjectNode rollback(String snapshot, long expected) {
        return mapper.createObjectNode().put("schema_version", "citizen-publication-command-v1").put("action", "rollback")
                .put("reason", "합성 시민 공개 복구").put("snapshot_id", snapshot).put("expected_head_version", expected);
    }

    private PublicationCommand command(ObjectNode request) { return commands.read(request.toString().getBytes(StandardCharsets.UTF_8)); }

    private String approve(ObjectNode input, boolean citizen) {
        importer.importBatch(imports.read(input.toString().getBytes(StandardCharsets.UTF_8), root), "synthetic-importer");
        return publication.execute(decision(input, "approve", 1, citizen), root, "synthetic-approver").revisionId();
    }

    private PublicationCommand decision(ObjectNode input, String action, long expected, boolean citizen) {
        return new PublicationCommand.Decision(citizen ? "citizen-review-command-v1" : "publication-command-v1", action,
                "합성 원문 검토", UUID.fromString(input.path("events").get(0).path("event_id").asText()), expected, List.of("heading-quote", "body-quote"));
    }

    private void restrict(ObjectNode input) throws Exception {
        JsonNode document = input.path("documents").get(0);
        var request = mapper.createObjectNode().put("schema_version", "source-review-v1").put("review_id", UUID.randomUUID().toString())
                .put("document_version_id", document.path("document_version_id").asText()).put("expected_review_no", 0)
                .put("expected_text_sha256", document.path("text_sha256").asText()).putNull("check")
                .put("use_review", "restricted").put("use_note", "합성 사용권 재검토").put("reason", "합성 사용권 변경");
        sources.review(Files.writeString(root.resolve("restriction.json"), request.toString()), null, "synthetic-reviewer");
    }

    private ObjectNode fresh(boolean citizen) throws Exception {
        String text = Files.readString(Path.of("examples/" + (citizen ? "citizen-reviewed-import" : "reviewed-import") + ".json"));
        var replacements = new HashMap<String, String>();
        return (ObjectNode) mapper.readTree(Pattern.compile("[12]0000000-0000-4000-8000-[0-9]{12}").matcher(text)
                .replaceAll(match -> replacements.computeIfAbsent(match.group(), ignored -> UUID.randomUUID().toString())));
    }

    private ObjectNode revision(ObjectNode input) { return (ObjectNode) input.path("events").get(0).path("revision"); }
    private String canonical(String id) { return jdbc.queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id = ?", String.class, id); }
    private String head() { return jdbc.queryForObject("SELECT snapshot_id FROM publication_heads WHERE channel_key = 'citizen:current'", String.class); }
    private List<Long> databaseCounts() {
        return List.of("snapshots", "snapshot_revisions", "publication_heads", "publication_audits", "event_revisions", "source_reviews", "source_checks", "extraction_runs", "test_points")
                .stream().map(table -> jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Long.class)).toList();
    }
}
