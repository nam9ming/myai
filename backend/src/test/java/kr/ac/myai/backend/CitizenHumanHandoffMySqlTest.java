package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.importing.HumanReviewChanges;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.review.ReviewReportService;
import kr.ac.myai.backend.service.ExtractionImportService;
import kr.ac.myai.backend.service.HumanHandoffImportService;
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
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.*;

@SpringBootTest
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class CitizenHumanHandoffMySqlTest {
    @Autowired ReviewedImportReader reader;
    @Autowired ReviewedImportService importer;
    @Autowired ExtractionArchiveReader archives;
    @Autowired ExtractionImportService extraction;
    @Autowired HumanHandoffImportService handoffs;
    @Autowired PublicationService publication;
    @Autowired PublicationCommandReader commands;
    @Autowired SourceReviewService sources;
    @Autowired SnapshotExportService exporter;
    @Autowired ReviewReportService reports;
    @Autowired JdbcTemplate jdbc;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final Set<String> runs = new HashSet<>(), documents = new HashSet<>(), versions = new HashSet<>(), events = new HashSet<>(), hashes = new HashSet<>(), snapshots = new HashSet<>();
    Map<String, List<Map<String, Object>>> originalRows;

    @DynamicPropertySource
    static void isolatedDatabaseAndPython(DynamicPropertyRegistry registry) {
        String url = System.getenv("DB_URL");
        if (url == null || !url.startsWith("jdbc:mysql://")
                || !Set.of("/myai_test", "/myai_citizen_test").contains(URI.create(url.substring(5)).getRawPath())) {
            throw new IllegalStateException("시민 인계 시험은 전용 myai_test 또는 myai_citizen_test DB_URL이 필요합니다.");
        }
        registry.add("spring.datasource.url", () -> url);
        registry.add("app.calculation.workdir", () -> PythonProbe.REPO.toString());
        registry.add("app.calculation.python-executable", () -> PythonProbe.PYTHON);
        registry.add("app.extraction.timeout-ms", () -> 20_000);
    }

    @BeforeEach void recordExistingRows() {
        assertThat(jdbc.queryForObject("SELECT DATABASE()", String.class)).isIn("myai_test", "myai_citizen_test");
        originalRows = CitizenNoticeFixtures.rows(jdbc);
    }

    @AfterEach void removeOnlyOwnedRowsAndPreserveEverythingElse() throws Exception {
        try {
            if (originalRows == null) return;
            for (String id : snapshots) jdbc.update("DELETE FROM publication_audits WHERE after_snapshot_id=?", id);
            for (String id : snapshots) jdbc.update("DELETE FROM publication_heads WHERE snapshot_id=?", id);
            for (String id : snapshots) jdbc.update("DELETE FROM snapshot_revisions WHERE snapshot_id=?", id);
            for (String id : snapshots) jdbc.update("DELETE FROM snapshots WHERE snapshot_id=?", id);
            for (String id : events) {
                jdbc.update("DELETE FROM review_audits WHERE event_id=?", id);
                jdbc.update("UPDATE events SET current_review_revision_id=NULL WHERE event_id=?", id);
                jdbc.update("DELETE FROM event_revisions WHERE event_id=?", id);
                jdbc.update("DELETE FROM events WHERE event_id=?", id);
            }
            for (String id : runs) jdbc.update("DELETE FROM extraction_runs WHERE run_id=?", id);
            for (String id : versions) {
                jdbc.update("DELETE FROM source_reviews WHERE document_version_id=?", id);
                jdbc.update("DELETE FROM source_checks WHERE document_version_id=? ORDER BY checked_at DESC", id);
                jdbc.update("DELETE FROM document_versions WHERE document_version_id=?", id);
            }
            for (String id : documents) jdbc.update("DELETE FROM documents WHERE document_id=?", id);
            for (String hash : hashes) jdbc.update("DELETE FROM import_batches WHERE input_sha256=?", hash);
            assertThat(CitizenNoticeFixtures.rows(jdbc)).as("시험 소유 행만 정리하고 기존 행을 보존한다").isEqualTo(originalRows);
        } finally { ExtractionArchiveReaderTest.unseal(root); }
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void importsActualCitizenHandoffPrivatelyAndReplaysWithoutChangingParent(boolean failed) throws Exception {
        var fixture = fixture(failed, output -> { });
        var beforeParent = jdbc.queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", fixture.run());
        var beforeArchive = CitizenExtractionArchiveTest.tree(Path.of((String) beforeParent.get("raw_ref")));
        var beforePublic = publicRows();
        var imported = importHandoff(fixture);
        assertThat(imported.revisionIds()).hasSize(5);
        for (String id : imported.revisionIds()) {
            var payload = payload(id); var revision = payload.path("revision");
            assertThat(payload.path("schema_version").asText()).isEqualTo("citizen-revision-v1");
            assertThat(revision.path("origin").asText()).isEqualTo("ai_reviewed");
            assertThat(revision.path("review_status").asText()).isEqualTo("needs_review");
            assertThat(revision.path("publication_intent").asText()).isEqualTo("hidden");
            assertThat(revision.path("originating_run_ids").get(0).asText()).isEqualTo(fixture.run());
            assertThat(payload.path("human_handoffs")).hasSize(1);
            assertThat(payload.path("event").has("area_id")).isFalse();
            assertThat(revision.has("dictionary_version")).isFalse();
            var projected = new ArrayList<JsonNode>(); fixture.projection().path("events").forEach(projected::add);
            var facts = projected.stream().filter(event -> event.path("event_id").equals(revision.path("event_id"))).findFirst().orElseThrow().path("facts");
            for (String field : ReviewedImportReader.CITIZEN_FIELDS) assertThat(revision.path(field)).as(field).isEqualTo(facts.path(field));
        }
        var beforeReplay = CitizenNoticeFixtures.rows(jdbc);
        var repeated = importHandoff(fixture);
        assertThat(repeated.alreadyImported()).isTrue();
        assertThat(repeated.importId()).isEqualTo(imported.importId());
        assertThat(repeated.revisionIds()).isEqualTo(imported.revisionIds());
        assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(beforeReplay);
        assertThat(jdbc.queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", fixture.run())).isEqualTo(beforeParent);
        assertThat(CitizenExtractionArchiveTest.tree(Path.of((String) beforeParent.get("raw_ref")))).isEqualTo(beforeArchive);
        assertThat(publicRows()).isEqualTo(beforePublic);
        assertThat(jdbc.queryForObject("SELECT schema_version FROM import_batches WHERE import_id=?", String.class, imported.importId()))
                .isEqualTo("citizen-human-handoff-import-v1");
        var beforeReport = CitizenNoticeFixtures.rows(jdbc);
        var report = reports.build(UUID.fromString(version(fixture)), root, null);
        assertThat(report.path("events")).hasSize(5);
        for (var event : report.path("events")) for (var revision : event.path("revisions")) {
            assertThat(revision.path("validation").path("status").asText()).isEqualTo("valid");
            assertThat(revision.path("handoff_validation").path("status").asText()).isEqualTo("valid");
            assertThat(revision.path("handoffs").get(0).path("review").path("review").path("reviewed_by").asText())
                    .isEqualTo("PRIVATE_CITIZEN_REVIEW_DECLARATION");
        }
        assertThat(report.path("documents").get(0).path("imports").get(0).path("validation").path("status").asText()).isEqualTo("valid");
        assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(beforeReport);
    }

    @Test void emptyCitizenHandoffKeepsBatchAndProofWithoutInventingEvents() throws Exception {
        var fixture = fixture(true, output -> { output.putArray("items"); output.putArray("warnings").add("NO_EVENT_FOUND"); });
        var before = CitizenNoticeFixtures.rows(jdbc);
        var result = importHandoff(fixture);
        assertThat(result.revisionIds()).isEmpty();
        for (String table : List.of("events", "event_revisions", "review_audits", "snapshots", "publication_heads"))
            assertThat(CitizenNoticeFixtures.rows(jdbc).get(table)).isEqualTo(before.get(table));
        var refs = mapper.readTree(jdbc.queryForObject("SELECT result_refs_json FROM import_batches WHERE import_id=?", String.class, result.importId()));
        assertThat(refs.path("originating_run_id").asText()).isEqualTo(fixture.run());
        assertThat(refs.path("human_handoffs")).hasSize(1);
        assertThat(importHandoff(fixture).alreadyImported()).isTrue();
        var report = reports.build(UUID.fromString(version(fixture)), root, null);
        assertThat(report.path("events")).isEmpty();
        assertThat(report.path("documents").get(0).path("imports").get(0).path("validation").path("status").asText()).isEqualTo("valid");
    }

    @Test void staleCasAndMismatchedRequestFamilyPreserveAllRows() throws Exception {
        var fixture = fixture(false, output -> { }); importHandoff(fixture);
        var request = fixture.request().deepCopy(); request.put("reason", "다른 명시 인계 요청");
        for (var mapping : request.path("revisions")) ((ObjectNode) mapping).put("revision_id", UUID.randomUUID().toString());
        var before = CitizenNoticeFixtures.rows(jdbc);
        assertThatThrownBy(() -> importRequest(fixture, request)).isInstanceOfSatisfying(ImportException.class,
                ex -> assertThat(ex.code()).isEqualTo("IMPORT_CONFLICT"));
        assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(before);
        request.put("schema_version", "human-handoff-import-v1");
        assertThatThrownBy(() -> importRequest(fixture, request)).isInstanceOf(ImportException.class);
        assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(before);
    }

    @Test void concurrentExactReplayCommitsOneBatchAndFiveRevisions() throws Exception {
        var fixture = fixture(false, output -> { });
        byte[] request = requestBytes(fixture.request());
        var barrier = new CyclicBarrier(2);
        try (var workers = Executors.newVirtualThreadPerTaskExecutor()) {
            var futures = java.util.stream.IntStream.range(0, 2).mapToObj(index -> workers.submit(() -> {
                barrier.await(5, TimeUnit.SECONDS);
                return handoffs.importBytes(request, root, fixture.handoffRoot(), "synthetic-citizen-importer");
            })).toList();
            var first = futures.get(0).get(40, TimeUnit.SECONDS); var second = futures.get(1).get(40, TimeUnit.SECONDS);
            assertThat(first.importId()).isEqualTo(second.importId());
            assertThat(first.revisionIds()).isEqualTo(second.revisionIds());
            assertThat(List.of(first, second).stream().filter(result -> !result.alreadyImported())).hasSize(1);
        }
        for (String id : events) assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_revisions WHERE event_id=?", Long.class, id)).isEqualTo(1);
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void ordinaryImportCannotIntroduceFirstCitizenAiProofOnNewOrManualEvent(boolean existingManual) throws Exception {
        var fixture = fixture(true, output -> { });
        ObjectNode next = projectedPayload(fixture);
        if (existingManual) {
            ObjectNode human = next.deepCopy(); human.remove("human_handoffs");
            var revision = (ObjectNode) human.path("revision");
            revision.put("origin", "human").putArray("originating_run_ids");
            importer.importBatch(reader.read(requestBytes(envelope(fixture, human)), root), "synthetic-manual-importer");
            ((ObjectNode) next.path("revision")).put("revision_id", UUID.randomUUID().toString()).put("revision_no", 2);
            HumanReviewChanges.record(human, next, "synthetic-citizen-importer", Instant.now(), "합성 최초 proof 우회 시도", ReviewedImportReader.CITIZEN_FIELDS);
        }
        var input = envelope(fixture, next); byte[] bytes = requestBytes(input);
        var before = CitizenNoticeFixtures.rows(jdbc);
        assertThatThrownBy(() -> importer.importBatch(reader.read(bytes, root), "synthetic-ordinary-importer")).isInstanceOf(ImportException.class);
        assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(before);
    }

    @Test void differentCitizenHandoffsRacingAtSameCasCommitOneCompleteBatch() throws Exception {
        var first = fixture(false, output -> { });
        var second = CitizenHandoffFixture.freeze(root, first.source(), first.extraction(), output ->
                ((ObjectNode) output.path("items").get(0).path("title")).put("value", "합성 경합 수정 제목"));
        assertThat(first.eventId()).isEqualTo(second.eventId());
        byte[] firstBytes = requestBytes(first.request()), secondBytes = requestBytes(second.request());
        var barrier = new CyclicBarrier(2);
        try (var workers = Executors.newVirtualThreadPerTaskExecutor()) {
            var attempts = List.of(workers.submit(() -> raceImport(first, firstBytes, barrier)),
                    workers.submit(() -> raceImport(second, secondBytes, barrier)));
            var outcomes = List.of(attempts.get(0).get(40, TimeUnit.SECONDS), attempts.get(1).get(40, TimeUnit.SECONDS));
            assertThat(outcomes.stream().filter(value -> value instanceof ReviewedImportService.ImportResult)).hasSize(1);
            assertThat(outcomes.stream().filter(value -> value instanceof ImportException)).hasSize(1);
            for (Object value : outcomes) if (value instanceof ImportException ex) assertThat(ex.code()).isEqualTo("IMPORT_CONFLICT");
        }
        for (String id : events) {
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_revisions WHERE event_id=?", Long.class, id)).isEqualTo(1);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM review_audits WHERE event_id=?", Long.class, id)).isEqualTo(1);
        }
    }

    private Object raceImport(CitizenHandoffFixture.Handoff fixture, byte[] request, CyclicBarrier barrier) throws Exception {
        barrier.await(5, TimeUnit.SECONDS);
        try { return handoffs.importBytes(request, root, fixture.handoffRoot(), "synthetic-citizen-importer"); }
        catch (ImportException ex) { return ex; }
    }

    @Test void everyLaterCitizenFactRequiresExactAuditAndKeepsOriginalProofAndRun() throws Exception {
        var fixture = fixture(false, output -> { }); var imported = importHandoff(fixture);
        var current = (ObjectNode) payload(imported.revisionIds().getFirst());
        var originalProof = current.path("human_handoffs").deepCopy();
        var originalRuns = current.path("revision").path("originating_run_ids").deepCopy();
        for (String field : ReviewedImportReader.CITIZEN_FIELDS.subList(0, 14)) {
            ObjectNode next = current.deepCopy(); var revision = (ObjectNode) next.path("revision");
            revision.put("revision_id", UUID.randomUUID().toString()).put("revision_no", revision.path("revision_no").asLong() + 1);
            if (field.equals("title")) revision.put("title", "합성 후속 제목 수정");
            else if (field.equals("categories")) revision.putArray("categories").add("education").add("support");
            else revision.putObject(field).put("value", "합성 후속 표현 " + field).put("knowledge", "known").putNull("reason")
                    .putArray("evidence_ids").add(current.path("evidence").get(0).path("evidence_id").asText());
            byte[] unaudited = requestBytes(envelope(fixture, next));
            var before = CitizenNoticeFixtures.rows(jdbc);
            assertThatThrownBy(() -> importer.importBatch(reader.read(unaudited, root), "synthetic-editor")).isInstanceOfSatisfying(ImportException.class,
                    ex -> assertThat(ex.code()).as(field).isEqualTo("IMPORT_CONFLICT"));
            assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(before);
            HumanReviewChanges.record(current, next, "synthetic-editor", Instant.now(), "합성 원문 사실 보완", ReviewedImportReader.CITIZEN_FIELDS);
            byte[] audited = requestBytes(envelope(fixture, next));
            var result = importer.importBatch(reader.read(audited, root), "synthetic-editor");
            var saved = (ObjectNode) payload(result.revisionIds().getFirst());
            assertThat(saved.path("human_handoffs")).isEqualTo(originalProof);
            assertThat(saved.path("revision").path("originating_run_ids")).isEqualTo(originalRuns);
            var previousAudit = current.path("revision").path("human_overrides");
            var savedAudit = saved.path("revision").path("human_overrides");
            assertThat(savedAudit).hasSize(previousAudit.size() + 1);
            for (int i = 0; i < previousAudit.size(); i++) assertThat(savedAudit.get(i)).isEqualTo(previousAudit.get(i));
            assertThat(savedAudit.get(savedAudit.size() - 1).path("field_path").asText()).isEqualTo(field);
            current = saved;
        }
        ObjectNode forged = current.deepCopy(); var revision = (ObjectNode) forged.path("revision");
        revision.put("revision_id", UUID.randomUUID().toString()).put("revision_no", revision.path("revision_no").asLong() + 1);
        ((ObjectNode) revision.path("human_overrides").get(0)).put("reason", "과거 감사 변조");
        byte[] bytes = requestBytes(envelope(fixture, forged)); var before = CitizenNoticeFixtures.rows(jdbc);
        assertThatThrownBy(() -> importer.importBatch(reader.read(bytes, root), "synthetic-editor")).isInstanceOf(ImportException.class);
        assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(before);
    }

    @Test void lateAuditConstraintFailureRollsBackEntireCitizenHandoff() throws Exception {
        var fixture = fixture(false, output -> { });
        String constraint = "citizen_handoff_" + UUID.randomUUID().toString().replace("-", "");
        assertThat(fixture.eventId()).matches("[0-9a-f-]{36}");
        jdbc.execute("ALTER TABLE review_audits ADD CONSTRAINT " + constraint + " CHECK (event_id <> '" + fixture.eventId() + "')");
        try {
            byte[] request = requestBytes(fixture.request()); var before = CitizenNoticeFixtures.rows(jdbc);
            assertThatThrownBy(() -> handoffs.importBytes(request, root, fixture.handoffRoot(), "synthetic-citizen-importer"))
                    .isInstanceOfSatisfying(ImportException.class, ex -> assertThat(ex.code()).isEqualTo("IMPORT_DATABASE_UNAVAILABLE"));
            assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(before);
        } finally { jdbc.execute("ALTER TABLE review_audits DROP CHECK " + constraint); }
        assertThat(importHandoff(fixture).revisionIds()).hasSize(5);
    }

    @Test void manualCorrectionsCannotDropRunSourceOrProofHistory() throws Exception {
        var fixture = fixture(false, output -> { }); var result = importHandoff(fixture);
        var previous = (ObjectNode) payload(result.revisionIds().getFirst());
        for (String removed : List.of("originating_run_ids", "source_version_ids", "human_handoffs")) {
            ObjectNode next = previous.deepCopy(); var revision = (ObjectNode) next.path("revision");
            revision.put("revision_id", UUID.randomUUID().toString()).put("revision_no", 2);
            if (removed.equals("human_handoffs")) next.remove(removed); else revision.putArray(removed);
            HumanReviewChanges.record(previous, next, "synthetic-editor", Instant.now(), "합성 추적 정보 제거 시도", ReviewedImportReader.CITIZEN_FIELDS);
            byte[] bytes = requestBytes(envelope(fixture, next)); var before = CitizenNoticeFixtures.rows(jdbc);
            assertThatThrownBy(() -> importer.importBatch(reader.read(bytes, root), "synthetic-editor")).isInstanceOf(ImportException.class);
            assertThat(CitizenNoticeFixtures.rows(jdbc)).as(removed).isEqualTo(before);
        }
    }

    @Test void sourceRightsAndSeparateApprovalGateCitizenPublicationWhileExportsAndRollbackKeepOriginalBytes() throws Exception {
        assertThat(jdbc.queryForList("SELECT snapshot_id FROM publication_heads WHERE channel_key='citizen:current'"))
                .as("기존 시민 공개 head를 덮어쓰지 않는다").isEmpty();
        var fixture = fixture(true, output -> {
            var first = output.path("items").get(0).deepCopy(); output.putArray("items").add(first);
        });
        var imported = importHandoff(fixture); String firstRevision = imported.revisionIds().getFirst();
        var beforePending = CitizenNoticeFixtures.rows(jdbc);
        assertThatThrownBy(() -> publication.execute(decision(fixture, 1), root, "synthetic-approver"))
                .isInstanceOf(PublicationException.class);
        assertThatThrownBy(() -> publish("preview", List.of(firstRevision), null)).isInstanceOf(PublicationException.class);
        assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(beforePending);
        sourceReview(fixture, 0, "allowed", true);
        var approved = publication.execute(decision(fixture, 1), root, "synthetic-approver");
        assertThat(payload(approved.revisionId()).path("revision").path("origin").asText()).isEqualTo("ai_reviewed");
        var beforePreview = CitizenNoticeFixtures.rows(jdbc);
        var preview = publish("preview", List.of(approved.revisionId()), null);
        assertThat(preview.preview().path("notices")).hasSize(1);
        assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(beforePreview);
        var published = publish("publish", List.of(approved.revisionId()), null);
        String original = jdbc.queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id=?", String.class, published.snapshotId());
        assertThat(original).contains("citizen-snapshot-v1").doesNotContain("PRIVATE_", "human_handoffs", "human_overrides", "reviewer_id",
                "originating_run_ids", "raw_asset_path", "receipt_sha256", fixture.run(), root.toString());
        Path exported = Files.createDirectory(root.resolve("export"));
        var export = exporter.export(UUID.fromString(published.snapshotId()), exported);
        assertThat(Files.readString(exported.resolve(export.fileName()))).isEqualTo(original);
        sourceReview(fixture, 1, "restricted", false);
        var beforeRestricted = CitizenNoticeFixtures.rows(jdbc);
        assertThatThrownBy(() -> publish("preview", List.of(approved.revisionId()), 0L)).isInstanceOf(PublicationException.class);
        assertThatThrownBy(() -> publish("publish", List.of(approved.revisionId()), 0L)).isInstanceOf(PublicationException.class);
        assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(beforeRestricted);
        var empty = publish("publish", List.of(), 0L);
        assertThat(empty.headVersion()).isEqualTo(1);
        Files.delete(root.resolve(fixture.source().path("documents").get(0).path("raw_asset_path").asText()));
        var rollback = publication.execute(new PublicationCommand.CitizenRollback("citizen-publication-command-v1", "rollback", "합성 시민 이전 공개본 복구",
                UUID.fromString(published.snapshotId()), 1L), null, "synthetic-publisher");
        assertThat(rollback.snapshotId()).isEqualTo(published.snapshotId());
        assertThat(rollback.headVersion()).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id=?", String.class, published.snapshotId())).isEqualTo(original);
        assertThat(exporter.export(UUID.fromString(published.snapshotId()), exported).alreadyExported()).isTrue();
        assertThat(Files.readString(exported.resolve(export.fileName()))).isEqualTo(original);
    }

    private PublicationCommand.Decision decision(CitizenHandoffFixture.Handoff fixture, long expected) throws Exception {
        var current = mapper.readTree(jdbc.queryForObject("SELECT r.payload_json FROM events e JOIN event_revisions r ON e.current_review_revision_id=r.revision_id WHERE e.event_id=?",
                String.class, fixture.eventId()));
        var citations = new ArrayList<String>(); current.path("evidence").forEach(value -> citations.add(value.path("evidence_id").asText()));
        return new PublicationCommand.Decision("citizen-review-command-v1", "approve", "합성 원문 대조 승인", UUID.fromString(fixture.eventId()), expected, citations);
    }

    private void sourceReview(CitizenHandoffFixture.Handoff fixture, long expected, String rights, boolean check) throws Exception {
        var request = (ObjectNode) mapper.readTree(Path.of("examples/source-review.json").toFile());
        var document = fixture.source().path("documents").get(0); String hash = document.path("text_sha256").asText();
        request.put("review_id", UUID.randomUUID().toString()).put("document_version_id", version(fixture)).put("expected_review_no", expected)
                .put("expected_text_sha256", hash).put("use_review", rights);
        if (check) ((ObjectNode) request.path("check")).put("checked_at", Instant.now().toString()).put("text_sha256", hash);
        else request.putNull("check");
        Path file = Files.writeString(root.resolve(UUID.randomUUID() + "-rights.json"), request.toString());
        sources.review(file, check ? root : null, "synthetic-source-reviewer");
    }

    private PublicationService.Result publish(String action, List<String> revisions, Long expected) {
        var request = mapper.createObjectNode().put("schema_version", "citizen-publication-command-v1").put("action", action)
                .put("data_kind", "synthetic").put("reason", "합성 시민 공개 검증");
        var selected = request.putArray("revision_ids"); revisions.forEach(selected::add);
        if (expected == null) request.putNull("expected_head_version"); else request.put("expected_head_version", expected);
        var result = publication.execute(commands.read(request.toString().getBytes(StandardCharsets.UTF_8)), root, "synthetic-publisher");
        if (action.equals("publish")) snapshots.add(result.snapshotId());
        return result;
    }

    private ObjectNode projectedPayload(CitizenHandoffFixture.Handoff fixture) {
        var projected = fixture.projection().path("events").get(0);
        var payload = mapper.createObjectNode().put("schema_version", "citizen-revision-v1").put("data_kind", "synthetic");
        ObjectNode event = projected.deepCopy(); event.remove("facts"); payload.set("event", event);
        ObjectNode revision = projected.path("facts").deepCopy();
        revision.put("revision_id", fixture.request().path("revisions").get(0).path("revision_id").asText()).put("revision_no", 1)
                .put("origin", "ai_reviewed").put("review_status", "needs_review").put("publication_intent", "hidden")
                .put("reviewer_id", "synthetic-citizen-importer").put("reviewed_at", Instant.now().truncatedTo(ChronoUnit.MICROS).toString())
                .putArray("human_overrides");
        payload.set("revision", revision); payload.set("evidence", fixture.projection().path("evidence").deepCopy());
        payload.putArray("human_handoffs").addObject().put("directory", fixture.image().toString())
                .put("handoff_ref", fixture.request().path("handoff_ref").asText()).put("receipt_sha256", fixture.request().path("receipt_sha256").asText());
        return payload;
    }

    private ObjectNode envelope(CitizenHandoffFixture.Handoff fixture, ObjectNode payload) {
        var input = fixture.source().deepCopy().put("schema_version", "citizen-reviewed-import-v1");
        input.set("evidence", payload.path("evidence").deepCopy());
        if (payload.has("human_handoffs")) input.set("human_handoffs", payload.path("human_handoffs").deepCopy());
        ObjectNode event = payload.path("event").deepCopy();
        event.put("expected_revision_no", payload.path("revision").path("revision_no").asLong() - 1);
        event.set("revision", payload.path("revision").deepCopy()); input.putArray("events").add(event);
        return input;
    }

    private CitizenHandoffFixture.Handoff fixture(boolean failed, Consumer<ObjectNode> edit) throws Exception {
        Path work = Files.createTempDirectory(root, "citizen-extraction-");
        var extractionFixture = CitizenExtractionArchiveTest.fixture(work.toRealPath(), failed ? new byte[] {(byte) 0xff, 0} : null);
        var source = CitizenHandoffFixture.source(root, extractionFixture);
        var document = source.path("documents").get(0);
        String documentId = document.path("document_id").asText(), version = document.path("document_version_id").asText();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM documents WHERE document_id=?", Long.class, documentId)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM document_versions WHERE document_version_id=?", Long.class, version)).isZero();
        documents.add(documentId); versions.add(version);
        var sourceBatch = reader.read(requestBytes(source), root);
        importer.importBatch(sourceBatch, "synthetic-citizen-source-importer");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM extraction_runs WHERE run_id=?", Long.class, extractionFixture.run())).isZero();
        runs.add(extractionFixture.run());
        CitizenExtractionArchiveTest.importManual(archives, extractionFixture);
        extraction.importRun(extractionFixture.run(), extractionFixture.archive(), "synthetic-citizen-run-importer");
        var result = CitizenHandoffFixture.freeze(root, source, extractionFixture, edit);
        for (var event : result.projection().path("events")) {
            String id = event.path("event_id").asText();
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM events WHERE event_id=?", Long.class, id)).isZero();
            events.add(id);
        }
        return result;
    }

    private ReviewedImportService.ImportResult importHandoff(CitizenHandoffFixture.Handoff fixture) { return importRequest(fixture, fixture.request()); }
    private ReviewedImportService.ImportResult importRequest(CitizenHandoffFixture.Handoff fixture, ObjectNode request) {
        return handoffs.importBytes(requestBytes(request), root, fixture.handoffRoot(), "synthetic-citizen-importer");
    }
    private byte[] requestBytes(JsonNode input) {
        byte[] bytes = input.toString().getBytes(StandardCharsets.UTF_8);
        String hash = ReviewedImportReader.sha256(bytes);
        if (!hashes.contains(hash)) {
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM import_batches WHERE input_sha256=?", Long.class, hash)).isZero();
            hashes.add(hash);
        }
        return bytes;
    }
    private JsonNode payload(String revision) throws Exception {
        return mapper.readTree(jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id=?", String.class, revision));
    }
    private String version(CitizenHandoffFixture.Handoff fixture) { return fixture.source().path("documents").get(0).path("document_version_id").asText(); }
    private Map<String, List<Map<String, Object>>> publicRows() {
        var result = CitizenNoticeFixtures.rows(jdbc);
        result.keySet().retainAll(Set.of("snapshots", "snapshot_revisions", "publication_heads", "publication_audits"));
        return result;
    }
}
