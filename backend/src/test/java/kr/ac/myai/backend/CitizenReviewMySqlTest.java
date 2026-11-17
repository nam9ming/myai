package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedBatch;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
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
import java.util.HashSet;
import java.util.Set;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.*;

@SpringBootTest
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class CitizenReviewMySqlTest {
    @Autowired ReviewedImportReader reader;
    @Autowired ReviewedImportService importer;
    @Autowired PublicationCommandReader commands;
    @Autowired PublicationService publication;
    @Autowired JdbcTemplate jdbc;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final Set<String> ownedSnapshots = new HashSet<>();
    boolean testDatabaseVerified;

    @DynamicPropertySource
    static void testDatabase(DynamicPropertyRegistry registry) {
        String url = System.getenv("DB_URL");
        if (url == null || !url.startsWith("jdbc:mysql://")
                || !Set.of("/myai_test", "/myai_citizen_test").contains(URI.create(url.substring(5)).getRawPath())) {
            throw new IllegalStateException("시민 검토 시험은 전용 myai_test 또는 myai_citizen_test DB_URL이 필요합니다.");
        }
        registry.add("spring.datasource.url", () -> url);
    }

    @BeforeEach
    void sources() throws Exception {
        assertThat(jdbc.queryForObject("SELECT DATABASE()", String.class)).isIn("myai_test", "myai_citizen_test");
        testDatabaseVerified = true;
        for (String name : List.of("citizen-source.txt", "synthetic-source.txt")) {
            Files.copy(Path.of("examples/" + name), root.resolve(name));
        }
    }

    @AfterEach
    void clearPublishedData() {
        if (!testDatabaseVerified) return;
        for (String id : ownedSnapshots) {
            jdbc.update("DELETE FROM publication_audits WHERE after_snapshot_id = ?", id);
            jdbc.update("DELETE FROM publication_heads WHERE snapshot_id = ?", id);
            jdbc.update("DELETE FROM snapshot_revisions WHERE snapshot_id = ?", id);
            jdbc.update("DELETE FROM snapshots WHERE snapshot_id = ?", id);
        }
        ownedSnapshots.clear();
    }

    @Test
    void cleanupDeletesOnlyOwnedSnapshotAndPreservesAnotherPublishedChannel() throws Exception {
        var unrelated = publishReplayFixture();
        var owned = publishReplayFixture();
        var canonical = jdbc.queryForList("SELECT canonical_json, checksum FROM snapshots WHERE snapshot_id = ?", unrelated.snapshotId());
        var head = jdbc.queryForList("SELECT * FROM publication_heads WHERE snapshot_id = ?", unrelated.snapshotId());
        var audits = jdbc.queryForList("SELECT * FROM publication_audits WHERE after_snapshot_id = ?", unrelated.snapshotId());
        var revisions = jdbc.queryForList("SELECT * FROM snapshot_revisions WHERE snapshot_id = ?", unrelated.snapshotId());
        assertThat(revisions).hasSize(1);
        assertThat(canonical).hasSize(1); assertThat(head).hasSize(1); assertThat(audits).hasSize(1);
        ownedSnapshots.remove(unrelated.snapshotId());
        clearPublishedData();
        ownedSnapshots.add(unrelated.snapshotId());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM snapshots WHERE snapshot_id = ?", Long.class, owned.snapshotId())).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM publication_heads WHERE snapshot_id = ?", Long.class, owned.snapshotId())).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM publication_audits WHERE after_snapshot_id = ?", Long.class, owned.snapshotId())).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM snapshot_revisions WHERE snapshot_id = ?", Long.class, owned.snapshotId())).isZero();
        assertThat(jdbc.queryForList("SELECT canonical_json, checksum FROM snapshots WHERE snapshot_id = ?", unrelated.snapshotId())).isEqualTo(canonical);
        assertThat(jdbc.queryForList("SELECT * FROM publication_heads WHERE snapshot_id = ?", unrelated.snapshotId())).isEqualTo(head);
        assertThat(jdbc.queryForList("SELECT * FROM publication_audits WHERE after_snapshot_id = ?", unrelated.snapshotId())).isEqualTo(audits);
        assertThat(jdbc.queryForList("SELECT * FROM snapshot_revisions WHERE snapshot_id = ?", unrelated.snapshotId())).isEqualTo(revisions);
    }

    @ParameterizedTest
    @ValueSource(strings = {"education", "support", "culture", "construction_traffic", "living"})
    void importsEditsApprovesAndRejectsEveryCategoryWithoutPublishing(String category) throws Exception {
        var input = fresh(true);
        revision(input).putArray("categories").add(category);
        var first = read(input);
        long snapshots = count("snapshots"), heads = count("publication_heads");
        var imported = importer.importBatch(first, "importer");
        assertThat(importer.importBatch(first, "retry").importId()).isEqualTo(imported.importId());
        assertThat(importer.importBatch(first, "retry").alreadyImported()).isTrue();
        var before = input.deepCopy();
        next(input);
        ((ObjectNode) revision(input).path("cost")).put("knowledge", "ambiguous").put("reason", "비용 확인 필요");
        audit(before, input, "cost");
        importer.importBatch(read(input), "editor");
        var approved = publication.execute(decision(input, "approve", 2, true), root, "approver");
        var facts = mapper.readTree(payload(approved.revisionId())).path("revision");
        assertThat(facts.path("categories").get(0).asText()).isEqualTo(category);
        assertThat(facts.path("application_period").path("value").asText()).isEqualTo("2026-11-20~2026-11-25");
        assertThat(facts.path("occurrences").path("value").asText()).isEqualTo("2026-12-01~2026-12-02");
        assertThat(facts.path("cost").path("value").isNull()).isTrue();
        assertThat(facts.path("cost").path("knowledge").asText()).isEqualTo("ambiguous");
        assertThat(facts.path("review_status").asText()).isEqualTo("approved");
        assertThat(facts.path("publication_intent").asText()).isEqualTo("public");
        var rejected = publication.execute(decision(input, "reject", 3, true), null, "reviewer");
        assertThat(mapper.readTree(payload(rejected.revisionId())).path("revision").path("review_status").asText()).isEqualTo("rejected");
        assertThat(payload(first.events().getFirst().revisionId())).isEqualTo(first.events().getFirst().payloadJson());
        assertThat(count("snapshots")).isEqualTo(snapshots);
        assertThat(count("publication_heads")).isEqualTo(heads);
        assertThat(countEvent("event_revisions", eventId(input))).isEqualTo(4);
        assertThat(countEvent("review_audits", eventId(input))).isEqualTo(4);
    }

    @ParameterizedTest
    @ValueSource(strings = {"title", "categories", "application_period", "occurrences", "regions", "locations", "residency_requirement", "target", "eligibility", "application_method", "preparation", "cost", "recruitment", "lifecycle"})
    void refusesEveryUnauditedCitizenFactChange(String field) throws Exception {
        var input = fresh(true); var original = read(input); importer.importBatch(original, "importer");
        next(input);
        if (field.equals("title")) revision(input).put("title", "합성 수정 제목");
        else if (field.equals("categories")) revision(input).putArray("categories").add("support");
        else {
            var value = revision(input).putObject(field).putNull("value").put("knowledge", "ambiguous").put("reason", "원문 재확인 필요");
            value.putArray("evidence_ids");
        }
        var changed = read(input);
        importConflict(() -> importer.importBatch(changed, "editor"));
        assertThat(countEvent("event_revisions", eventId(input))).isEqualTo(1);
        assertThat(payload(original.events().getFirst().revisionId())).isEqualTo(original.events().getFirst().payloadJson());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM import_batches WHERE input_sha256 = ?", Long.class, changed.inputSha256())).isZero();
    }

    @Test
    void preservesAuditPrefixAndRejectsForgedHistoricalChanges() throws Exception {
        var input = fresh(true); importer.importBatch(read(input), "importer");
        var before = input.deepCopy(); next(input); revision(input).putArray("categories").add("support"); audit(before, input, "categories");
        var second = read(input); importer.importBatch(second, "editor");
        next(input);
        ((ObjectNode) revision(input).path("human_overrides").get(0)).put("reason", "과거 감사 변조");
        importConflict(() -> importer.importBatch(read(input), "editor"));
        assertThat(countEvent("event_revisions", eventId(input))).isEqualTo(2);
        assertThat(payload(second.events().getFirst().revisionId())).isEqualTo(second.events().getFirst().payloadJson());
    }

    @Test
    void removedEvidenceRemainsAuditableButInventedEvidenceCannotEnterNewHistory() throws Exception {
        var input = fresh(true); var first = read(input); importer.importBatch(first, "importer");
        var original = mapper.readTree(first.events().getFirst().payloadJson());
        next(input);
        input.withArray("evidence").remove(0);
        ((ObjectNode) input.path("events").get(0).path("document_links").get(0)).putArray("evidence_ids").add("body-quote");
        revision(input).put("reviewer_id", "editor").put("reviewed_at", "2026-11-03T01:00:00Z");
        var changed = mapper.readTree(read(input).events().getFirst().payloadJson());
        for (String field : List.of("event", "evidence")) {
            var change = revision(input).withArray("human_overrides").addObject().put("field_path", field)
                    .put("reason", "합성 근거 연결 정리").put("reviewer", "editor").put("time", "2026-11-03T01:00:00Z");
            change.set("before", original.path(field).deepCopy()); change.set("after", changed.path(field).deepCopy());
            change.putArray("evidence_ids").add("heading-quote").add("body-quote");
        }
        var second = read(input); importer.importBatch(second, "editor");
        var stored = mapper.readTree(payload(second.events().getFirst().revisionId()));
        assertThat(stored.path("evidence").findValuesAsText("evidence_id")).containsExactly("body-quote");
        var history = stored.path("revision").path("human_overrides");
        assertThat(history).hasSize(2);
        for (JsonNode change : history) {
            assertThat(change.path("reviewer").asText()).isEqualTo(stored.path("revision").path("reviewer_id").asText());
            assertThat(change.path("time").asText()).isEqualTo(stored.path("revision").path("reviewed_at").asText());
            assertThat(change.path("evidence_ids").get(0).asText()).isEqualTo("heading-quote");
        }
        var before = input.deepCopy(); next(input); revision(input).putArray("categories").add("support");
        audit(before, input, "categories");
        ((ObjectNode) revision(input).path("human_overrides").get(2)).putArray("evidence_ids").add("body-quote").add("invented");
        importConflict(() -> importer.importBatch(read(input), "editor"));
        assertThat(countEvent("event_revisions", eventId(input))).isEqualTo(2);
        assertThat(payload(second.events().getFirst().revisionId())).isEqualTo(second.events().getFirst().payloadJson());
        assertThat(mapper.readTree(payload(second.events().getFirst().revisionId())).path("revision").path("human_overrides")).isEqualTo(history);
    }

    @ParameterizedTest
    @ValueSource(booleans = {true, false})
    void cannotReplaceAnExistingEventsPayloadFamily(boolean citizenFirst) throws Exception {
        var original = fresh(citizenFirst); var first = read(original); importer.importBatch(first, "importer");
        var candidate = fresh(!citizenFirst);
        ((ObjectNode) candidate.path("events").get(0)).put("event_id", eventId(original));
        revision(candidate).put("event_id", eventId(original)); next(candidate);
        var batch = read(candidate);
        importConflict(() -> importer.importBatch(batch, "editor"));
        assertThat(countEvent("event_revisions", eventId(original))).isEqualTo(1);
        assertThat(payload(first.events().getFirst().revisionId())).isEqualTo(first.events().getFirst().payloadJson());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM documents WHERE document_id = ?", Long.class, candidate.path("documents").get(0).path("document_id").asText())).isZero();
    }

    @ParameterizedTest
    @ValueSource(strings = {"approve", "reject"})
    void decisionsRejectBothCrossFamilyDirectionsBeforeAnyWrite(String action) throws Exception {
        for (boolean citizen : List.of(true, false)) {
            var input = fresh(citizen); var batch = read(input); importer.importBatch(batch, "importer");
            assertThatThrownBy(() -> publication.execute(decision(input, action, 1, !citizen), root, "reviewer"))
                    .isInstanceOfSatisfying(PublicationException.class, ex -> assertThat(ex.code()).isEqualTo("PUBLICATION_VALIDATION_ERROR"));
            assertThat(countEvent("event_revisions", eventId(input))).isEqualTo(1);
            assertThat(payload(batch.events().getFirst().revisionId())).isEqualTo(batch.events().getFirst().payloadJson());
        }
    }

    @ParameterizedTest
    @ValueSource(strings = {"pending", "restricted", "raw_hash", "future_check"})
    void approvalRechecksPermissionRawHashAndFutureSourceTimes(String defect) throws Exception {
        var input = fresh(true); var document = (ObjectNode) input.path("documents").get(0);
        if (defect.equals("pending") || defect.equals("restricted")) document.put("use_review", defect);
        if (defect.equals("future_check")) {
            document.put("latest_check_attempt_at", "2999-01-01T00:00:00Z").put("last_verified_at", "2999-01-01T00:00:00Z");
            ((ObjectNode) document.path("checks").get(0)).put("checked_at", "2999-01-01T00:00:00Z");
        }
        importer.importBatch(read(input), "importer");
        if (defect.equals("raw_hash")) Files.writeString(root.resolve("citizen-source.txt"), "변경된 합성 원문");
        assertThatThrownBy(() -> publication.execute(decision(input, "approve", 1, true), root, "approver"))
                .isInstanceOf(PublicationException.class);
        assertThat(countEvent("event_revisions", eventId(input))).isEqualTo(1);
        var rejected = publication.execute(decision(input, "reject", 1, true), null, "reviewer");
        assertThat(mapper.readTree(payload(rejected.revisionId())).path("revision").path("publication_intent").asText()).isEqualTo("hidden");
    }

    @Test
    void staleAndConcurrentDecisionsLeaveExactlyOneWinner() throws Exception {
        var input = fresh(true); importer.importBatch(read(input), "importer");
        var command = decision(input, "approve", 1, true); var barrier = new CyclicBarrier(2);
        try (var pool = Executors.newFixedThreadPool(2)) {
            java.util.concurrent.Callable<String> call = () -> {
                barrier.await(10, TimeUnit.SECONDS);
                try { publication.execute(command, root, "approver"); return "success"; }
                catch (PublicationException ex) { return ex.code(); }
            };
            var left = pool.submit(call); var right = pool.submit(call);
            assertThat(List.of(left.get(20, TimeUnit.SECONDS), right.get(20, TimeUnit.SECONDS)))
                    .containsExactlyInAnyOrder("success", "PUBLICATION_CONFLICT");
        }
        assertThatThrownBy(() -> publication.execute(command, root, "retry"))
                .isInstanceOfSatisfying(PublicationException.class, ex -> assertThat(ex.code()).isEqualTo("PUBLICATION_CONFLICT"));
        assertThat(countEvent("event_revisions", eventId(input))).isEqualTo(2);
        assertThat(countEvent("review_audits", eventId(input))).isEqualTo(2);
    }

    @Test
    void concurrentCitizenEditsCommitOnlyOneRevisionAndAudit() throws Exception {
        var input = fresh(true); importer.importBatch(read(input), "importer");
        var a = input.deepCopy(); next(a); revision(a).putArray("categories").add("support"); audit(input, a, "categories");
        var b = input.deepCopy(); next(b); revision(b).putArray("categories").add("living"); audit(input, b, "categories");
        var first = read(a); var second = read(b); var barrier = new CyclicBarrier(2);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var left = pool.submit(() -> importAttempt(first, barrier)); var right = pool.submit(() -> importAttempt(second, barrier));
            assertThat(List.of(left.get(20, TimeUnit.SECONDS), right.get(20, TimeUnit.SECONDS)))
                    .containsExactlyInAnyOrder("success", "IMPORT_CONFLICT");
        }
        assertThat(countEvent("event_revisions", eventId(input))).isEqualTo(2);
        assertThat(countEvent("review_audits", eventId(input))).isEqualTo(2);
    }

    @Test
    void laterConflictRollsBackEarlierCitizenEventDocumentAndBatch() throws Exception {
        var existing = fresh(true); importer.importBatch(read(existing), "importer");
        var candidate = fresh(true); candidate.withArray("documents").add(existing.path("documents").get(0));
        for (JsonNode evidence : existing.path("evidence")) {
            candidate.withArray("evidence").add(mapper.readTree(evidence.toString().replace("heading-quote", "old-heading").replace("body-quote", "old-body")));
        }
        var conflicting = (ObjectNode) mapper.readTree(existing.path("events").get(0).toString().replace("heading-quote", "old-heading").replace("body-quote", "old-body"));
        ((ObjectNode) conflicting.path("revision")).put("revision_id", UUID.randomUUID().toString());
        candidate.withArray("events").add(conflicting);
        var batch = read(candidate);
        importConflict(() -> importer.importBatch(batch, "importer"));
        assertThat(countEvent("event_revisions", eventId(candidate))).isZero();
        assertThat(countEvent("review_audits", eventId(candidate))).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM documents WHERE document_id = ?", Long.class, candidate.path("documents").get(0).path("document_id").asText())).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM import_batches WHERE input_sha256 = ?", Long.class, batch.inputSha256())).isZero();
        assertThat(countEvent("event_revisions", eventId(existing))).isEqualTo(1);
    }

    @Test
    void legacyPublishAndPreviewRejectCitizenRevisionWithoutChangingLegacyBytes() throws Exception {
        var legacy = fresh(false); var old = read(legacy); importer.importBatch(old, "importer");
        var legacyApproval = publication.execute(decision(legacy, "approve", 1, false), root, "approver");
        var request = replayRequest(legacy, legacyApproval.revisionId());
        var published = publication.execute(commands.read(request.toString().getBytes(StandardCharsets.UTF_8)), root, "publisher");
        ownedSnapshots.add(published.snapshotId());
        String oldSnapshot = jdbc.queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id = ?", String.class, published.snapshotId());
        var input = fresh(true); importer.importBatch(read(input), "importer");
        var approved = publication.execute(decision(input, "approve", 1, true), root, "approver");
        request.put("expected_head_version", published.headVersion()).putArray("revision_ids").add(approved.revisionId());
        long snapshots = count("snapshots"), heads = count("publication_heads");
        for (String action : List.of("publish", "preview")) {
            request.put("action", action);
            var command = commands.read(request.toString().getBytes(StandardCharsets.UTF_8));
            assertThatThrownBy(() -> publication.execute(command, root, "publisher"))
                    .isInstanceOfSatisfying(PublicationException.class, ex -> {
                        assertThat(ex.code()).isEqualTo("PUBLICATION_VALIDATION_ERROR");
                        assertThat(ex.field()).isEqualTo("revision_ids");
                    });
        }
        assertThat(count("snapshots")).isEqualTo(snapshots); assertThat(count("publication_heads")).isEqualTo(heads);
        assertThat(payload(old.events().getFirst().revisionId())).isEqualTo(old.events().getFirst().payloadJson());
        assertThat(mapper.readTree(payload(old.events().getFirst().revisionId())).has("schema_version")).isFalse();
        assertThat(jdbc.queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id = ?", String.class, published.snapshotId())).isEqualTo(oldSnapshot);
        assertThat(jdbc.queryForObject("SELECT snapshot_id FROM publication_heads WHERE channel_key = ?", String.class,
                "replay:" + request.path("case_id").asText())).isEqualTo(published.snapshotId());
    }

    private PublicationService.Result publishReplayFixture() throws Exception {
        var input = fresh(false); importer.importBatch(read(input), "importer");
        var approved = publication.execute(decision(input, "approve", 1, false), root, "approver");
        var request = replayRequest(input, approved.revisionId());
        var published = publication.execute(commands.read(request.toString().getBytes(StandardCharsets.UTF_8)), root, "publisher");
        ownedSnapshots.add(published.snapshotId());
        return published;
    }

    private ObjectNode replayRequest(ObjectNode input, String revision) throws Exception {
        var request = (ObjectNode) mapper.readTree(Path.of("examples/publish.json").toFile());
        String area = input.path("events").get(0).path("area_id").asText();
        ((ObjectNode) request.path("area")).put("area_id", area);
        for (JsonNode point : request.path("points")) ((ObjectNode) point).put("area_id", area).put("point_id", UUID.randomUUID().toString());
        request.put("mode", "replay").put("case_id", UUID.randomUUID().toString()).put("anchor_date", "2026-11-02")
                .put("reference_instant", "2026-11-02T03:00:00Z").put("knowledge_cutoff", "2026-11-02T03:00:00Z")
                .put("history_fidelity", "reconstructed").putNull("expected_head_version");
        request.putArray("revision_ids").add(revision);
        return request;
    }

    private String importAttempt(ReviewedBatch batch, CyclicBarrier barrier) throws Exception {
        barrier.await(10, TimeUnit.SECONDS);
        try { importer.importBatch(batch, "editor"); return "success"; }
        catch (ImportException ex) { return ex.code(); }
    }

    private void audit(ObjectNode before, ObjectNode after, String field) {
        var next = revision(after);
        next.put("reviewer_id", "editor").put("reviewed_at", "2026-11-03T01:00:00Z");
        var change = next.withArray("human_overrides").addObject().put("field_path", field)
                .put("reason", "합성 원문 재검토").put("reviewer", "editor").put("time", "2026-11-03T01:00:00Z");
        change.set("before", revision(before).path(field).deepCopy()); change.set("after", next.path(field).deepCopy());
        change.putArray("evidence_ids").add("heading-quote").add("body-quote");
    }

    private PublicationCommand decision(ObjectNode input, String action, long expected, boolean citizen) {
        return new PublicationCommand.Decision(citizen ? "citizen-review-command-v1" : "publication-command-v1", action,
                "합성 원문 검토", UUID.fromString(eventId(input)), expected, List.of("heading-quote", "body-quote"));
    }

    private ObjectNode fresh(boolean citizen) throws Exception {
        String text = Files.readString(Path.of("examples/" + (citizen ? "citizen-reviewed-import" : "reviewed-import") + ".json"));
        var replacements = new HashMap<String, String>();
        return (ObjectNode) mapper.readTree(Pattern.compile("[12]0000000-0000-4000-8000-[0-9]{12}").matcher(text)
                .replaceAll(match -> replacements.computeIfAbsent(match.group(), ignored -> UUID.randomUUID().toString())));
    }

    private ReviewedBatch read(ObjectNode input) { return reader.read(input.toString().getBytes(StandardCharsets.UTF_8), root); }
    private ObjectNode revision(ObjectNode input) { return (ObjectNode) input.path("events").get(0).path("revision"); }
    private String eventId(ObjectNode input) { return input.path("events").get(0).path("event_id").asText(); }
    private void next(ObjectNode input) {
        var revision = revision(input); long number = revision.path("revision_no").asLong();
        ((ObjectNode) input.path("events").get(0)).put("expected_revision_no", number);
        revision.put("revision_no", number + 1).put("revision_id", UUID.randomUUID().toString());
    }
    private long count(String table) { return jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Long.class); }
    private long countEvent(String table, String event) { return jdbc.queryForObject("SELECT COUNT(*) FROM " + table + " WHERE event_id = ?", Long.class, event); }
    private String payload(String revision) { return jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id = ?", String.class, revision); }
    private void importConflict(org.assertj.core.api.ThrowableAssert.ThrowingCallable call) {
        assertThatThrownBy(call).isInstanceOfSatisfying(ImportException.class, ex -> assertThat(ex.code()).isEqualTo("IMPORT_CONFLICT"));
    }
}
