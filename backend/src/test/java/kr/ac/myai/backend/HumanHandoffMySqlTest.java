package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedBatch;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.ReviewedImportRepository;
import kr.ac.myai.backend.repository.ExtractionRunRepository;
import kr.ac.myai.backend.service.ExtractionImportService;
import kr.ac.myai.backend.service.HumanHandoffImportService;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.SnapshotExportService;
import kr.ac.myai.backend.service.ReviewedImportService;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.publication.PublicationException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class HumanHandoffMySqlTest {
    @Autowired JdbcTemplate jdbc;
    @Autowired ReviewedImportReader reader;
    @Autowired ReviewedImportService importer;
    @Autowired ExtractionImportService extraction;
    @Autowired HumanHandoffImportService handoffs;
    @Autowired PublicationService publication;
    @Autowired PublicationCommandReader commands;
    @Autowired SnapshotExportService exporter;
    @Autowired MockMvc mvc;
    final java.util.List<String> ownedCases = new java.util.ArrayList<>();
    @MockitoSpyBean ReviewedImportRepository repository;
    @MockitoSpyBean ExtractionRunRepository runs;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();

    @DynamicPropertySource
    static void python(DynamicPropertyRegistry properties) {
        properties.add("app.calculation.workdir", () -> PythonProbe.REPO.toString());
        properties.add("app.calculation.python-executable", () -> PythonProbe.PYTHON);
        properties.add("app.extraction.timeout-ms", () -> 10000);
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void importsActualManualHandoffPrivatelyWithoutChangingParentStatus(boolean failed) throws Exception {
        var fixture = fixture(failed, output -> { });
        String parentBefore = parentRow(fixture.run());
        var before = counts();
        Instant started = Instant.now();
        var result = importHandoff(fixture);
        var payload = payload(result.revisionIds().getFirst());
        var revision = payload.path("revision");
        assertThat(revision.path("origin").asText()).isEqualTo("ai_reviewed");
        assertThat(revision.path("review_status").asText()).isEqualTo("needs_review");
        assertThat(revision.path("publication_intent").asText()).isEqualTo("hidden");
        assertThat(revision.path("reviewer_id").asText()).isEqualTo("synthetic-handoff-importer");
        assertThat(Instant.parse(revision.path("reviewed_at").asText())).isBetween(started.minusMillis(1), Instant.now());
        assertThat(payload.path("human_handoffs")).hasSize(1);
        assertThat(payload.path("human_handoffs").get(0).path("handoff_ref")).isEqualTo(fixture.request().path("handoff_ref"));
        assertThat(parentRow(fixture.run())).isEqualTo(parentBefore);
        assertThat(jdbc.queryForObject("SELECT status FROM extraction_runs WHERE run_id=?", String.class, fixture.run()))
                .isEqualTo(failed ? "failed" : "validated");
        assertThat(jdbc.queryForObject("SELECT execution_mode FROM extraction_runs WHERE run_id=?", String.class, fixture.run())).isEqualTo("manual_import");
        assertThat(counts().subList(3, 5)).isEqualTo(before.subList(3, 5));
        assertThat(jdbc.queryForObject("SELECT actor FROM review_audits WHERE revision_id=?", String.class, result.revisionIds().getFirst()))
                .isEqualTo("synthetic-handoff-importer");
        assertThat(Files.readString(fixture.image().resolve("review").resolve(fixture.projection().path("review").path("review_ref").asText()).resolve("review.json")))
                .contains("PRIVATE_HUMAN_DECLARATION", "123Z");
    }

    @Test
    void exactReplayReturnsSameBatchWithoutAnotherRevision() throws Exception {
        var fixture = fixture(false, output -> { });
        var first = importHandoff(fixture);
        var before = counts();
        var repeated = importHandoff(fixture);
        assertThat(repeated.alreadyImported()).isTrue();
        assertThat(repeated.importId()).isEqualTo(first.importId());
        assertThat(repeated.revisionIds()).isEqualTo(first.revisionIds());
        assertThat(counts()).isEqualTo(before);
    }

    @Test
    void emptyHandoffRecordsProofWithoutDeletingExistingEvent() throws Exception {
        var fixture = fixture(false, output -> { });
        var first = importHandoff(fixture);
        var empty = handoff(fixture.source(), fixture.run(), fixture.archive(), output -> {
            output.putArray("items"); output.putArray("warnings").add("NO_EVENT_FOUND");
        });
        var before = counts();
        var result = importHandoff(empty);
        assertThat(result.revisionIds()).isEmpty();
        assertThat(counts().subList(0, 5)).isEqualTo(before.subList(0, 5));
        assertThat(jdbc.queryForObject("SELECT current_review_revision_id FROM events WHERE event_id=?", String.class, fixture.eventId()))
                .isEqualTo(first.revisionIds().getFirst());
        var refs = mapper.readTree(jdbc.queryForObject("SELECT result_refs_json FROM import_batches WHERE import_id=?", String.class, result.importId()));
        assertThat(refs.path("originating_run_id").asText()).isEqualTo(fixture.run());
        assertThat(refs.path("human_handoffs")).hasSize(1);
        assertThat(refs.path("human_handoffs").get(0).path("handoff_ref")).isEqualTo(empty.request().path("handoff_ref"));
        assertThat(importHandoff(empty).alreadyImported()).isTrue();
    }

    @Test
    void staleExpectedRevisionConflictsWithoutChangingStoredFacts() throws Exception {
        var fixture = fixture(false, output -> { });
        var imported = importHandoff(fixture);
        var changed = handoff(fixture.source(), fixture.run(), fixture.archive(), output ->
                ((ObjectNode) output.path("items").get(0).path("title")).put("value", "합성 변경 제목"));
        var before = counts();
        conflict(() -> importHandoff(changed));
        assertThat(counts()).isEqualTo(before);
        assertThat(jdbc.queryForObject("SELECT current_review_revision_id FROM events WHERE event_id=?", String.class, fixture.eventId()))
                .isEqualTo(imported.revisionIds().getFirst());
    }

    @Test
    void concurrentExactInputCommitsOneBatchAndOneRevision() throws Exception {
        var fixture = fixture(false, output -> { });
        var barrier = new CyclicBarrier(2);
        try (var workers = Executors.newVirtualThreadPerTaskExecutor()) {
            var futures = java.util.stream.IntStream.range(0, 2).mapToObj(i -> workers.submit(() -> {
                barrier.await(5, TimeUnit.SECONDS);
                return importHandoff(fixture);
            })).toList();
            var results = List.of(futures.get(0).get(30, TimeUnit.SECONDS), futures.get(1).get(30, TimeUnit.SECONDS));
            assertThat(results.stream().filter(result -> !result.alreadyImported())).hasSize(1);
            assertThat(results.getFirst().importId()).isEqualTo(results.getLast().importId());
            assertThat(results.getFirst().revisionIds()).isEqualTo(results.getLast().revisionIds());
        }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_revisions WHERE event_id=?", Long.class, fixture.eventId())).isEqualTo(1);
    }

    @Test
    void concurrentDifferentHandoffsWithSameExpectedRevisionCommitOnlyOne() throws Exception {
        var fixture = fixture(true, output -> { }); var original = importHandoff(fixture);
        String originalPayload = jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id=?", String.class, original.revisionIds().getFirst());
        var left = handoff(fixture.source(), fixture.run(), fixture.archive(), output ->
                ((ObjectNode) output.path("items").get(0).path("title")).put("value", "합성 동시 수정 왼쪽"));
        var right = handoff(fixture.source(), fixture.run(), fixture.archive(), output ->
                ((ObjectNode) output.path("items").get(0).path("title")).put("value", "합성 동시 수정 오른쪽"));
        expected(left, 1); expected(right, 1); var barrier = new CyclicBarrier(2);
        try (var workers = Executors.newVirtualThreadPerTaskExecutor()) {
            var futures = List.of(left, right).stream().map(candidate -> workers.submit(() -> {
                barrier.await(5, TimeUnit.SECONDS);
                try { importHandoff(candidate); return "success"; }
                catch (ImportException exception) { return exception.code(); }
            })).toList();
            assertThat(List.of(futures.getFirst().get(30, TimeUnit.SECONDS), futures.getLast().get(30, TimeUnit.SECONDS)))
                    .containsExactlyInAnyOrder("success", "IMPORT_CONFLICT");
        }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_revisions WHERE event_id=?", Long.class, fixture.eventId())).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id=?", String.class, original.revisionIds().getFirst()))
                .isEqualTo(originalPayload);
        var current = mapper.readTree(jdbc.queryForObject("SELECT r.payload_json FROM events e JOIN event_revisions r ON r.revision_id=e.current_review_revision_id WHERE e.event_id=?",
                String.class, fixture.eventId()));
        assertThat(current.path("revision").path("title").asText()).isIn("합성 동시 수정 왼쪽", "합성 동시 수정 오른쪽");
        assertThat(current.path("human_handoffs")).hasSize(2);
    }

    @Test
    void revisionMappingRequiresExactExplicitEventIdentityAndIntegerVersion() throws Exception {
        var fixture = fixture(false, output -> { }); ObjectNode valid = fixture.request().deepCopy(); var before = counts();
        for (String defect : List.of("extra", "missing", "duplicate", "event", "negative", "fractional")) {
            var request = valid.deepCopy(); var revision = (ObjectNode) request.path("revisions").get(0);
            switch (defect) {
                case "extra" -> request.put("PRIVATE_EXTRA", "PRIVATE_VALUE");
                case "missing" -> request.putArray("revisions");
                case "duplicate" -> request.withArray("revisions").add(revision.deepCopy());
                case "event" -> revision.put("event_id", UUID.randomUUID().toString());
                case "negative" -> revision.put("expected_revision_no", -1);
                case "fractional" -> revision.put("expected_revision_no", 0.5);
                default -> throw new AssertionError(defect);
            }
            Files.writeString(fixture.file(), request.toString());
            assertThatThrownBy(() -> importHandoff(fixture)).as(defect).isInstanceOf(ImportException.class).hasMessageNotContaining("PRIVATE_VALUE");
            assertThat(counts()).isEqualTo(before);
        }
        Files.writeString(fixture.file(), valid.toString());
        for (String actor : new String[]{null, "", "PRIVATE_VALUE\n", "x".repeat(129)}) {
            assertThatThrownBy(() -> handoffs.importFile(fixture.file(), root, fixture.handoffRoot(), actor))
                    .isInstanceOf(ImportException.class).hasMessageNotContaining("PRIVATE_VALUE");
        }
        assertThat(counts()).isEqualTo(before);
    }

    @Test
    void lateSqlFailureRollsBackBatchEventRevisionAndAudit() throws Exception {
        var fixture = fixture(true, output -> { });
        var before = counts();
        doAnswer(invocation -> {
            invocation.callRealMethod();
            throw new org.springframework.dao.DataIntegrityViolationException("PRIVATE_VALUE late SQL failure");
        }).when(repository).appendEvent(any(ReviewedBatch.Event.class), eq("synthetic"), eq("late-failure-test"), eq(true));
        assertThatThrownBy(() -> handoffs.importFile(fixture.file(), root, fixture.handoffRoot(), "late-failure-test"))
                .isInstanceOf(ImportException.class).hasMessageNotContaining("PRIVATE_VALUE");
        verify(repository).appendEvent(any(ReviewedBatch.Event.class), eq("synthetic"), eq("late-failure-test"), eq(true));
        assertThat(counts()).isEqualTo(before);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM events WHERE event_id=?", Long.class, fixture.eventId())).isZero();
        assertThat(jdbc.queryForObject("SELECT status FROM extraction_runs WHERE run_id=?", String.class, fixture.run())).isEqualTo("failed");
    }

    @Test
    void rawDraftPromotionKeepsOriginalAndRecordsDatabaseFieldChanges() throws Exception {
        var fixture = fixture(false, output -> ((ObjectNode) output.path("items").get(0).path("title"))
                .put("value", "합성 사람이 수정한 제목"));
        var raw = reader.read(fixtures().draft(fixture.source(), fixture.run(), fixture.archive()), root);
        importer.importBatch(raw, "synthetic-draft-importer");
        var original = raw.events().getFirst();
        expected(fixture, 1);
        var result = importHandoff(fixture);
        var current = payload(result.revisionIds().getFirst());
        assertThat(jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id=?", String.class, original.revisionId()))
                .isEqualTo(original.payloadJson());
        var title = current.path("revision").path("human_overrides").findParents("field_path").stream()
                .filter(change -> change.path("field_path").asText().equals("title")).findFirst().orElseThrow();
        assertThat(title.path("before")).isEqualTo(mapper.readTree(original.payloadJson()).path("revision").path("title"));
        assertThat(title.path("after").asText()).isEqualTo("합성 사람이 수정한 제목");
        assertThat(title.path("reviewer").asText()).isEqualTo("synthetic-handoff-importer");
        assertThat(current.path("revision").path("human_overrides").toString()).doesNotContain("output.items");
    }

    @Test
    void unknownTitleTypeDuplicatesPartialTimeAndMissingBindingStayPrivate() throws Exception {
        var fixture = fixture(false, output -> {
            var item = (ObjectNode) output.path("items").get(0);
            unknown((ObjectNode) item.path("title"), "not_stated");
            unknown((ObjectNode) item.path("types"), "ambiguous");
            var directions = (ObjectNode) item.path("directions");
            directions.put("knowledge", "known").putNull("reason");
            directions.putArray("value").add("상행").add("상행"); directions.putArray("evidence_ids").add("e1");
            var occurrence = (ObjectNode) item.path("occurrences").get(0);
            unknown((ObjectNode) occurrence.path("time_end"), "not_stated");
            occurrence.putArray("location_refs"); output.withArray("warnings").add("LOCATION_BINDING_UNKNOWN");
        });
        var result = importHandoff(fixture); var revision = payload(result.revisionIds().getFirst()).path("revision");
        assertThat(revision.path("title").isNull()).isTrue();
        assertThat(revision.path("types")).isEmpty();
        assertThat(revision.path("directions").path("value").toString()).isEqualTo("[\"상행\",\"상행\"]");
        assertThat(revision.path("occurrences").get(0).path("time_end").isNull()).isTrue();
        assertThat(revision.path("occurrences").get(0).path("precision").asText()).isEqualTo("unknown");
        assertThat(revision.path("locations")).hasSize(2);
        assertThatThrownBy(() -> publication.execute(decision(fixture, "approve", 1), root, "synthetic-approver"))
                .isInstanceOf(PublicationException.class);
        assertThat(jdbc.queryForObject("SELECT current_review_revision_id FROM events WHERE event_id=?", String.class, fixture.eventId()))
                .isEqualTo(result.revisionIds().getFirst());
    }

    @Test
    void noEvidenceHandoffKeepsUnknownFactsAndCanBeRejectedAfterSourceRemoval() throws Exception {
        var fixture = fixture(true, output -> {
            ExtractionRunMySqlTest.unknownFields(output); output.putArray("evidence");
            for (var item : output.path("items")) ((ObjectNode) item.path("types")).put("knowledge", "ambiguous");
        });
        var result = importHandoff(fixture);
        assertThat(payload(result.revisionIds().getFirst()).path("evidence")).isEmpty();
        Files.delete(root.resolve("synthetic-source.txt"));
        var rejected = publication.execute(decision(fixture, "reject", 1), null, "synthetic-rejector");
        assertThat(jdbc.queryForObject("SELECT review_status FROM event_revisions WHERE revision_id=?", String.class, rejected.revisionId()))
                .isEqualTo("rejected");
        assertThat(payload(rejected.revisionId()).path("human_handoffs"))
                .isEqualTo(payload(result.revisionIds().getFirst()).path("human_handoffs"));
    }

    @Test
    void laterHandoffPreservesEarlierProofAndAuditPrefix() throws Exception {
        var fixture = fixture(false, output -> { });
        var raw = reader.read(fixtures().draft(fixture.source(), fixture.run(), fixture.archive()), root);
        importer.importBatch(raw, "synthetic-draft-importer"); expected(fixture, 1);
        var first = importHandoff(fixture); var firstPayload = payload(first.revisionIds().getFirst());
        var second = handoff(fixture.source(), fixture.run(), fixture.archive(), output -> { }); expected(second, 2);
        var next = importHandoff(second); var nextPayload = payload(next.revisionIds().getFirst());
        assertThat(nextPayload.path("human_handoffs")).hasSize(2);
        assertThat(nextPayload.path("human_handoffs").get(0)).isEqualTo(firstPayload.path("human_handoffs").get(0));
        var oldAudit = firstPayload.path("revision").path("human_overrides");
        for (int i = 0; i < oldAudit.size(); i++) assertThat(nextPayload.path("revision").path("human_overrides").get(i)).isEqualTo(oldAudit.get(i));
    }

    @Test
    void removedCurrentEvidenceKeepsExactHistoricalCitationsOnLaterManualRevision() throws Exception {
        var fixture = fixture(false, output -> { });
        var raw = reader.read(fixtures().draft(fixture.source(), fixture.run(), fixture.archive()), root);
        importer.importBatch(raw, "synthetic-draft-importer"); expected(fixture, 1);
        var first = importHandoff(fixture); var firstPayload = payload(first.revisionIds().getFirst());
        assertThat(firstPayload.path("revision").path("human_overrides")).isNotEmpty();
        var removed = manualUpdate(fixture, first.revisionIds().getFirst(), next -> {
            ((ObjectNode) next).putArray("evidence");
            clearCitations((ObjectNode) next.path("event"));
            var revision = (ObjectNode) next.path("revision");
            for (String field : List.of("occurrences", "locations", "applicability", "exceptions", "route_names", "stop_names", "directions")) {
                clearCitations(revision.path(field)); ExtractionRunMySqlTest.unknownFields(revision.path(field));
            }
            for (var occurrence : revision.path("occurrences")) ((ObjectNode) occurrence).put("precision", "unknown").put("knowledge", "ambiguous");
            revision.put("lifecycle", "uncertain").putArray("lifecycle_evidence_ids");
        });
        var removedPayload = payload(removed.revisionIds().getFirst());
        assertThat(removedPayload.path("evidence")).isEmpty();
        var next = manualUpdate(fixture, removed.revisionIds().getFirst(), payload -> { });
        var nextPayload = payload(next.revisionIds().getFirst());
        assertThat(nextPayload.path("revision").path("human_overrides"))
                .isEqualTo(removedPayload.path("revision").path("human_overrides"));
        for (int i = 0; i < firstPayload.path("revision").path("human_overrides").size(); i++)
            assertThat(nextPayload.path("revision").path("human_overrides").get(i))
                    .isEqualTo(firstPayload.path("revision").path("human_overrides").get(i));
        assertThat(nextPayload.path("human_handoffs")).isEqualTo(firstPayload.path("human_handoffs"));
    }

    @Test
    void handoffNeverOverwritesHumanCorrectedGeometry() throws Exception {
        var fixture = fixture(false, output -> { });
        var first = importHandoff(fixture);
        var corrected = manualUpdate(fixture, first.revisionIds().getFirst(), next -> {
            var location = (ObjectNode) next.path("revision").path("locations").get(0);
            location.put("kind", "point").put("status", "verified").put("coverage", "complete").put("source", "합성 좌표 수동 대조")
                    .put("checked_by", "synthetic-editor").put("checked_at", "2026-11-03T02:00:00Z");
            location.putObject("geometry").put("type", "Point").putArray("coordinates").add(127.27).add(37.01);
        });
        var before = counts();
        var another = handoff(fixture.source(), fixture.run(), fixture.archive(), output -> { }); expected(another, 2);
        conflict(() -> importHandoff(another));
        assertThat(counts()).isEqualTo(before);
        assertThat(jdbc.queryForObject("SELECT current_review_revision_id FROM events WHERE event_id=?", String.class, fixture.eventId()))
                .isEqualTo(corrected.revisionIds().getFirst());
        assertThat(payload(corrected.revisionIds().getFirst()).path("revision").path("locations").get(0).path("geometry").isObject()).isTrue();
    }

    @ParameterizedTest
    @ValueSource(strings = {"approve", "reject"})
    void handoffPreservesApprovedOrRejectedCurrentRevision(String action) throws Exception {
        var fixture = fixture(false, output -> { }); importHandoff(fixture);
        var decided = publication.execute(decision(fixture, action, 1), root, "synthetic-reviewer");
        var another = handoff(fixture.source(), fixture.run(), fixture.archive(), output -> { }); expected(another, 2);
        var before = counts(); conflict(() -> importHandoff(another));
        assertThat(counts()).isEqualTo(before);
        assertThat(jdbc.queryForObject("SELECT current_review_revision_id FROM events WHERE event_id=?", String.class, fixture.eventId()))
                .isEqualTo(decided.revisionId());
    }

    @Test
    void manualCompletionPreservesProofThroughApprovalPreviewPublicationExportAndRestore() throws Exception {
        var fixture = fixture(true, output -> {
            var item = (ObjectNode) output.path("items").get(0);
            unknown((ObjectNode) item.path("title"), "not_stated");
            unknown((ObjectNode) item.path("types"), "ambiguous");
            unknown((ObjectNode) item.path("occurrences").get(0).path("time_end"), "not_stated");
        });
        var first = importHandoff(fixture); var firstPayload = payload(first.revisionIds().getFirst());
        assertThatThrownBy(() -> publication.execute(decision(fixture, "approve", 1), root, "synthetic-approver"))
                .isInstanceOf(PublicationException.class);
        var completed = manualUpdate(fixture, first.revisionIds().getFirst(), next -> {
            var revision = (ObjectNode) next.path("revision"); revision.put("title", "합성 수동 보완 제목"); revision.putArray("types").add("construction");
            var occurrence = (ObjectNode) revision.path("occurrences").get(0);
            occurrence.put("time_end", "12:00").put("precision", "exact_time").put("knowledge", "known");
        });
        var completedPayload = payload(completed.revisionIds().getFirst());
        assertThat(completedPayload.path("human_handoffs")).isEqualTo(firstPayload.path("human_handoffs"));
        var approved = publication.execute(decision(fixture, "approve", 2), root, "PRIVATE_APPROVER");
        assertThat(payload(approved.revisionId()).path("human_handoffs")).isEqualTo(firstPayload.path("human_handoffs"));
        assertThat(payload(approved.revisionId()).path("revision").path("human_overrides"))
                .isEqualTo(completedPayload.path("revision").path("human_overrides"));
        var publish = publishRequest(fixture, approved.revisionId());
        publish.put("action", "preview"); var before = counts();
        var preview = publication.execute(command(publish), root, "PRIVATE_PUBLISHER");
        assertThat(preview.preview().path("event_count").asInt()).isEqualTo(1); assertThat(counts()).isEqualTo(before);
        publish.put("action", "publish");
        var published = publication.execute(command(publish), root, "PRIVATE_PUBLISHER");
        String canonical = jdbc.queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id=?", String.class, published.snapshotId());
        assertPublic(canonical);
        var exported = exporter.export(UUID.fromString(published.snapshotId()), root);
        assertThat(Files.readString(root.resolve(exported.fileName()))).isEqualTo(canonical);
        var detail = mvc.perform(get("/api/v1/events/" + fixture.eventId()).param("snapshot_id", published.snapshotId()))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString(StandardCharsets.UTF_8);
        assertPublic(detail);
        var image = fixture.image().resolve("projection.json"); var permissions = Files.getPosixFilePermissions(image);
        byte[] bytes = Files.readAllBytes(image);
        try {
            image.toFile().setWritable(true, true); Files.writeString(image, "PRIVATE_VALUE changed after approval");
            for (String action : List.of("preview", "publish")) {
                publish.put("action", action).put("expected_head_version", 0);
                assertThatThrownBy(() -> publication.execute(command(publish), root, "synthetic-publisher")).isInstanceOf(PublicationException.class);
            }
        } finally { Files.write(image, bytes); Files.setPosixFilePermissions(image, permissions); }
        publish.put("action", "publish").put("expected_head_version", 0).putArray("revision_ids");
        var empty = publication.execute(command(publish), root, "synthetic-publisher");
        Files.delete(root.resolve("synthetic-source.txt"));
        var rollback = new PublicationCommand.Rollback("publication-command-v1", "rollback", "합성 불변 공개본 복구", "replay",
                UUID.fromString(publish.path("case_id").asText()), UUID.fromString(published.snapshotId()), empty.headVersion());
        publication.execute(rollback, null, "synthetic-publisher");
        assertThat(jdbc.queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id=?", String.class, published.snapshotId())).isEqualTo(canonical);
        var rejected = publication.execute(decision(fixture, "reject", 3), null, "synthetic-rejector");
        assertThat(payload(rejected.revisionId()).path("human_handoffs")).isEqualTo(firstPayload.path("human_handoffs"));
        assertThatThrownBy(() -> publication.execute(decision(fixture, "approve", 4), root, "synthetic-approver")).isInstanceOf(PublicationException.class);
    }

    @Test
    void missingProofBlocksLaterManualImportAndApproval() throws Exception {
        var fixture = fixture(true, output -> { }); var imported = importHandoff(fixture);
        var path = fixture.image().resolve("projection.json"); var permissions = Files.getPosixFilePermissions(path.getParent());
        var removed = path.resolveSibling("removed-projection.json");
        try {
            path.getParent().toFile().setWritable(true, true); Files.move(path, removed);
            var before = counts();
            assertThatThrownBy(() -> manualUpdate(fixture, imported.revisionIds().getFirst(), next -> { })).isInstanceOf(ImportException.class);
            assertThatThrownBy(() -> publication.execute(decision(fixture, "approve", 1), root, "synthetic-approver")).isInstanceOf(PublicationException.class);
            assertThat(counts()).isEqualTo(before);
        } finally { Files.move(removed, path); Files.setPosixFilePermissions(path.getParent(), permissions); }
    }

    @Test
    void changedD03RowsAndD05StatusCannotReuseCommittedBatch() throws Exception {
        var fixture = fixture(true, output -> { }); importHandoff(fixture);
        String version = fixture.source().path("documents").get(0).path("document_version_id").asText();
        var before = counts();
        for (String column : List.of("metadata_json", "text_sha256", "private_content_ref")) {
            String original = jdbc.queryForObject("SELECT " + column + " FROM document_versions WHERE document_version_id=?", String.class, version);
            String altered = column.equals("metadata_json") ? original.replace("합성 기관", "합성 변조 기관")
                    : column.equals("text_sha256") ? "0".repeat(64) : "PRIVATE_CHANGED_SOURCE";
            try {
                jdbc.update("UPDATE document_versions SET " + column + "=? WHERE document_version_id=?", altered, version);
                assertThatThrownBy(() -> importHandoff(fixture)).isInstanceOf(ImportException.class);
                assertThat(counts()).isEqualTo(before);
            } finally { jdbc.update("UPDATE document_versions SET " + column + "=? WHERE document_version_id=?", original, version); }
        }
        try {
            jdbc.update("UPDATE extraction_runs SET status='validated' WHERE run_id=?", fixture.run());
            assertThatThrownBy(() -> importHandoff(fixture)).isInstanceOf(ImportException.class);
            assertThat(counts()).isEqualTo(before);
        } finally { jdbc.update("UPDATE extraction_runs SET status='failed' WHERE run_id=?", fixture.run()); }
        assertThat(importHandoff(fixture).alreadyImported()).isTrue();
    }

    @Test
    void replayRechecksFullD03AndD05FingerprintInsideTransaction() throws Exception {
        var fixture = fixture(true, output -> { }); importHandoff(fixture);
        String version = fixture.source().path("documents").get(0).path("document_version_id").asText();
        String metadata = jdbc.queryForObject("SELECT metadata_json FROM document_versions WHERE document_version_id=?", String.class, version);
        String originalParent = parentRow(fixture.run()); var before = counts();
        for (String target : List.of("document", "run")) {
            var changed = new java.util.concurrent.atomic.AtomicBoolean();
            doAnswer(invocation -> {
                if (changed.compareAndSet(false, true)) {
                    if (target.equals("document")) jdbc.update("UPDATE document_versions SET metadata_json=? WHERE document_version_id=?",
                            metadata.replace("합성 공지", "합성 경합 변경 공지"), version);
                    else jdbc.update("UPDATE extraction_runs SET registered_by='PRIVATE_CHANGED_ACTOR' WHERE run_id=?", fixture.run());
                }
                return invocation.callRealMethod();
            }).when(runs).checkReference(any(ExtractionRunRepository.Reference.class));
            try {
                assertThatThrownBy(() -> importHandoff(fixture)).isInstanceOf(ImportException.class);
                assertThat(changed).isTrue(); assertThat(counts()).isEqualTo(before);
                assertThat(jdbc.queryForObject("SELECT metadata_json FROM document_versions WHERE document_version_id=?", String.class, version)).isEqualTo(metadata);
                assertThat(parentRow(fixture.run())).isEqualTo(originalParent);
            } finally { reset(runs); }
        }
        assertThat(importHandoff(fixture).alreadyImported()).isTrue();
    }

    @Test
    void failedParentProofCannotAuthorizeAnotherEventSharingSameRun() throws Exception {
        var fixture = fixture(true, output -> { }); var first = importHandoff(fixture);
        ObjectNode authorized = (ObjectNode) payload(first.revisionIds().getFirst());
        var revision = (ObjectNode) authorized.path("revision");
        revision.put("revision_id", UUID.randomUUID().toString()).put("revision_no", 2);
        ObjectNode other = authorized.deepCopy(); String unauthorized = UUID.randomUUID().toString();
        other.remove("human_handoffs"); ((ObjectNode) other.path("event")).put("event_id", unauthorized);
        ((ObjectNode) other.path("revision")).put("event_id", unauthorized).put("revision_id", UUID.randomUUID().toString()).put("revision_no", 1);
        Path sourceFile = Files.writeString(root.resolve("proof-source.json"), fixture.source().toString());
        var source = reader.read(sourceFile, root);
        var batch = new ReviewedBatch("reviewed-import-v1", ReviewedImportReader.sha256(UUID.randomUUID().toString().getBytes(StandardCharsets.UTF_8)),
                "synthetic", source.documents(), List.of(event(authorized, 1), event(other, 0)), fixture.run(), null,
                authorized.path("human_handoffs").toString());
        var before = counts();
        assertThatThrownBy(() -> importer.importBatch(batch, "synthetic-editor")).isInstanceOfSatisfying(ImportException.class,
                exception -> assertThat(exception.code()).isEqualTo("IMPORT_VALIDATION_ERROR"));
        assertThat(counts()).isEqualTo(before);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM events WHERE event_id=?", Long.class, unauthorized)).isZero();
    }

    @Test
    void alteredOrMissingOriginalArchivesAndSourceBlockReplayDespiteNestedCopies() throws Exception {
        for (String target : List.of("handoff", "parent", "source")) {
            var fixture = fixture(true, output -> { }); importHandoff(fixture);
            Path path = target.equals("handoff") ? fixture.image().resolve("projection.json")
                    : target.equals("parent") ? stored(fixture.run()).resolve("attempt-1.output") : root.resolve("synthetic-source.txt");
            byte[] original = Files.readAllBytes(path); var permissions = Files.getPosixFilePermissions(path);
            try {
                path.toFile().setWritable(true, true); Files.writeString(path, "PRIVATE_VALUE tampered");
                var before = counts();
                assertThatThrownBy(() -> importHandoff(fixture)).isInstanceOf(ImportException.class).hasMessageNotContaining("PRIVATE_VALUE");
                assertThat(counts()).isEqualTo(before);
            } finally { Files.write(path, original); Files.setPosixFilePermissions(path, permissions); }
            Path missing = path.resolveSibling("removed-" + path.getFileName());
            var parentPermissions = Files.getPosixFilePermissions(path.getParent());
            try {
                path.getParent().toFile().setWritable(true, true); Files.move(path, missing);
                assertThatThrownBy(() -> importHandoff(fixture)).isInstanceOf(ImportException.class);
            } finally { Files.move(missing, path); Files.setPosixFilePermissions(path.getParent(), parentPermissions); }
            assertThat(importHandoff(fixture).alreadyImported()).isTrue();
        }
    }

    @Test
    void wrongReceiptUnsealedImageAndRestrictedSourceAreRejectedBeforeWriting() throws Exception {
        var fixture = fixture(false, output -> { }); var before = counts();
        String hash = fixture.request().path("receipt_sha256").asText();
        fixture.request().put("receipt_sha256", "0".repeat(64)); writeRequest(fixture);
        assertThatThrownBy(() -> importHandoff(fixture)).isInstanceOf(ImportException.class);
        fixture.request().put("receipt_sha256", hash); writeRequest(fixture);
        var permissions = Files.getPosixFilePermissions(fixture.image());
        try {
            fixture.image().toFile().setWritable(true, true);
            assertThatThrownBy(() -> importHandoff(fixture)).isInstanceOf(ImportException.class);
        } finally { Files.setPosixFilePermissions(fixture.image(), permissions); }
        String version = fixture.source().path("documents").get(0).path("document_version_id").asText();
        String metadata = jdbc.queryForObject("SELECT metadata_json FROM document_versions WHERE document_version_id=?", String.class, version);
        var changed = (ObjectNode) mapper.readTree(metadata);
        ((ObjectNode) changed.path("document")).put("use_review", "restricted");
        try {
            jdbc.update("UPDATE document_versions SET metadata_json=? WHERE document_version_id=?", changed.toString(), version);
            assertThatThrownBy(() -> importHandoff(fixture)).isInstanceOf(ImportException.class);
        } finally { jdbc.update("UPDATE document_versions SET metadata_json=? WHERE document_version_id=?", metadata, version); }
        assertThat(counts()).isEqualTo(before);
    }

    private Fixture fixture(boolean failed, Consumer<ObjectNode> edit) throws Exception {
        var helpers = fixtures();
        var source = helpers.source(); helpers.registerSource(source);
        String run = UUID.randomUUID().toString();
        Path archive = helpers.archive(source, run, failed);
        extraction.importRun(run, archive, "synthetic-registrant");
        return handoff(source, run, archive, edit);
    }

    private Fixture handoff(ObjectNode source, String run, Path archive, Consumer<ObjectNode> edit) throws Exception {
        Path work = Files.createTempDirectory(root, "handoff-").toRealPath();
        Path sourceFile = Files.writeString(work.resolve("source.json"), source.toString());
        var output = (ObjectNode) mapper.readTree(PythonProbe.REPO.resolve("contracts/examples/ai-extraction.json").toFile());
        var doc = source.path("documents").get(0);
        output.put("document_version_id", doc.path("document_version_id").asText());
        var block = doc.path("block_index").get(0); String text = block.path("text").asText();
        ((ObjectNode) output.path("evidence").get(0)).put("block_id", block.path("block_id").asText()).put("quote", text)
                .put("start_char", 0).put("end_char", text.codePointCount(0, text.length()))
                .put("text_sha256", ReviewedImportReader.sha256(text.getBytes(StandardCharsets.UTF_8)));
        edit.accept(output);
        Path outputFile = Files.writeString(work.resolve("review-output.json"), output.toString());
        Path handoffRoot = work.resolve("handoffs");
        String script = """
                import hashlib, json, sys, uuid
                from datetime import datetime, timezone
                from pathlib import Path
                from processing.extraction.archive import freeze_run, _json
                from processing.evaluation.reviews import freeze_review
                from processing.evaluation.handoff_storage import freeze_handoff
                source_path, output_path, run_root, run, work_path, handoff_root = sys.argv[1:]
                work, run_root = Path(work_path), Path(run_root)
                frozen = freeze_run(run, run_root)
                parent = run_root / frozen['snapshot_ref']
                receipt = frozen['receipt']
                output = json.loads(Path(output_path).read_bytes())
                before = json.loads((parent / f"attempt-{len(receipt['attempts'])}.output").read_bytes()) if receipt['status'] == 'validated' else None
                at = datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', '123Z')
                review = dict(schema_version='human-review-v1', review_id=str(uuid.uuid4()),
                    source=dict(run_id=run, snapshot_ref=frozen['snapshot_ref'], receipt_sha256=hashlib.sha256((parent / 'receipt.json').read_bytes()).hexdigest()),
                    review=dict(reviewed_by='PRIVATE_HUMAN_DECLARATION', started_at=at, finished_at=at, basis='source_only', note='합성 시험; 실제 사람 검토 선언 아님'),
                    output=output, changes=[])
                if before != output:
                    review['changes'].append(dict(field_path='output', before=before, after=output, reason='합성 원문 대조 수정',
                        evidence_ids=[e['evidence_id'] for e in output['evidence']], reviewer=review['review']['reviewed_by'], time=at))
                review_path = work / 'review.json'; review_path.write_bytes(_json(review))
                review_root = work / 'reviews'; selected = freeze_review(review_path, review_root, run_root)
                request = dict(schema_version='human-handoff-v1', handoff_id=str(uuid.uuid4()), review_ref=selected['review_ref'],
                    review_receipt_sha256=hashlib.sha256((review_root / selected['review_ref'] / 'receipt.json').read_bytes()).hexdigest(),
                    source=json.loads(Path(source_path).read_bytes()), area_id='10000000-0000-4000-8000-000000000005',
                    split_group_id='10000000-0000-4000-8000-000000000006', dictionary_version='synthetic-dictionary-v1')
                request_path = work / 'handoff.json'; request_path.write_bytes(_json(request))
                result = freeze_handoff(request_path, Path(handoff_root), review_root)
                print(json.dumps(result, ensure_ascii=False))
                """;
        var process = new ProcessBuilder(PythonProbe.PYTHON, "-c", script, sourceFile.toString(), outputFile.toString(), archive.toString(), run,
                work.toString(), handoffRoot.toString()).directory(PythonProbe.REPO.toFile()).start();
        assertThat(process.waitFor(15, TimeUnit.SECONDS)).isTrue();
        assertThat(process.exitValue()).as(new String(process.getErrorStream().readAllBytes(), StandardCharsets.UTF_8)).isZero();
        var receipt = mapper.readTree(process.getInputStream().readAllBytes());
        Path image = handoffRoot.resolve(receipt.path("handoff_ref").asText());
        var projection = mapper.readTree(image.resolve("projection.json").toFile());
        var request = mapper.createObjectNode().put("schema_version", "human-handoff-import-v1")
                .put("handoff_ref", receipt.path("handoff_ref").asText())
                .put("receipt_sha256", ReviewedImportReader.sha256(Files.readAllBytes(image.resolve("receipt.json"))))
                .put("reason", "합성 사람 수정 인계");
        var revisions = request.putArray("revisions");
        for (var event : projection.path("events")) revisions.addObject().put("event_id", event.path("event_id").asText())
                .put("revision_id", UUID.randomUUID().toString()).put("expected_revision_no", 0);
        Path file = Files.writeString(work.resolve("import.json"), request.toString());
        return new Fixture(source, run, archive, handoffRoot, image, request, projection, file);
    }

    private ReviewedBatch.Event event(JsonNode payload, long expected) {
        var revision = payload.path("revision"); String json = payload.toString();
        var runs = new java.util.ArrayList<String>(); revision.path("originating_run_ids").forEach(value -> runs.add(value.asText()));
        var versions = new java.util.ArrayList<String>(); revision.path("source_version_ids").forEach(value -> versions.add(value.asText()));
        return new ReviewedBatch.Event(payload.path("event").path("event_id").asText(), revision.path("revision_id").asText(), revision.path("revision_no").asLong(),
                expected, json, ReviewedImportReader.sha256(json.getBytes(StandardCharsets.UTF_8)), revision.path("review_status").asText(),
                revision.path("publication_intent").asText(), revision.path("reviewer_id").asText(), Instant.parse(revision.path("reviewed_at").asText()),
                runs, versions, List.of());
    }

    private ObjectNode publishRequest(Fixture fixture, String revision) throws Exception {
        var request = (ObjectNode) mapper.readTree(Path.of("examples/publish.json").toFile());
        String caseId = UUID.randomUUID().toString(); ownedCases.add(caseId);
        request.put("mode", "replay").put("case_id", caseId).put("anchor_date", "2026-11-03")
                .put("reference_instant", "2026-11-03T00:00:00Z").put("knowledge_cutoff", "2026-11-03T00:00:00Z").put("history_fidelity", "reconstructed");
        for (var point : request.path("points")) ((ObjectNode) point).put("point_id", UUID.randomUUID().toString());
        request.putArray("revision_ids").add(revision); request.putNull("expected_head_version");
        return request;
    }

    private PublicationCommand command(ObjectNode request) throws Exception {
        return commands.read(Files.writeString(root.resolve(UUID.randomUUID() + "-command.json"), request.toString()));
    }

    private void assertPublic(String json) {
        assertThat(json).doesNotContain("PRIVATE_", "human_handoffs", "human_overrides", "handoff_ref", "receipt_sha256", "reviewer_id",
                "raw_output", "raw_ref", "raw_asset_path", root.toString());
    }

    private static void clearCitations(JsonNode node) {
        if (node.isObject()) {
            if (node.has("evidence_ids")) ((ObjectNode) node).putArray("evidence_ids");
            node.forEach(HumanHandoffMySqlTest::clearCitations);
        } else if (node.isArray()) node.forEach(HumanHandoffMySqlTest::clearCitations);
    }

    private static void unknown(ObjectNode field, String knowledge) {
        field.putNull("value").put("knowledge", knowledge).put("reason", "합성 원문 미기재"); field.putArray("evidence_ids");
    }

    private void writeRequest(Fixture fixture) throws Exception { Files.writeString(fixture.file(), fixture.request().toString()); }

    private void expected(Fixture fixture, long revision) throws Exception {
        for (var item : fixture.request().path("revisions")) ((ObjectNode) item).put("expected_revision_no", revision);
        writeRequest(fixture);
    }

    private Path stored(String run) {
        return Path.of(jdbc.queryForObject("SELECT raw_ref FROM extraction_runs WHERE run_id=?", String.class, run));
    }

    private PublicationCommand.Decision decision(Fixture fixture, String action, long expected) throws Exception {
        var current = mapper.readTree(jdbc.queryForObject("SELECT r.payload_json FROM events e JOIN event_revisions r ON r.revision_id=e.current_review_revision_id WHERE e.event_id=?",
                String.class, fixture.eventId()));
        var evidence = new java.util.ArrayList<String>(); current.path("evidence").forEach(item -> evidence.add(item.path("evidence_id").asText()));
        return new PublicationCommand.Decision("publication-command-v1", action, "합성 원문 대조 결정", UUID.fromString(fixture.eventId()), expected, evidence);
    }

    private ReviewedImportService.ImportResult manualUpdate(Fixture fixture, String previousId, Consumer<ObjectNode> edit) throws Exception {
        JsonNode previous = payload(previousId); ObjectNode next = previous.deepCopy(); edit.accept(next);
        var revision = (ObjectNode) next.path("revision");
        revision.put("revision_id", UUID.randomUUID().toString()).put("revision_no", previous.path("revision").path("revision_no").asLong() + 1)
                .put("review_status", "needs_review").put("publication_intent", "hidden").put("reviewer_id", "synthetic-editor")
                .put("reviewed_at", Instant.now().toString());
        var evidenceIds = new java.util.LinkedHashSet<String>();
        for (var p : List.of(previous, next)) p.path("evidence").forEach(e -> evidenceIds.add(e.path("evidence_id").asText()));
        for (String field : ("title types occurrences locations applicability exceptions route_names stop_names directions lifecycle lifecycle_evidence_ids "
                + "source_version_ids originating_run_ids rules_version dictionary_version event evidence").split(" ")) {
            JsonNode before = field.equals("event") || field.equals("evidence") ? previous.path(field) : previous.path("revision").path(field);
            JsonNode after = field.equals("event") || field.equals("evidence") ? next.path(field) : revision.path(field);
            if (before.equals(after)) continue;
            var record = revision.withArray("human_overrides").addObject().put("field_path", field).put("reason", "합성 수동 보완")
                    .put("reviewer", "synthetic-editor").put("time", revision.path("reviewed_at").asText());
            record.set("before", before.deepCopy()); record.set("after", after.deepCopy());
            var citations = record.putArray("evidence_ids"); evidenceIds.forEach(citations::add);
        }
        var envelope = fixture.source().deepCopy(); envelope.put("schema_version", "reviewed-import-v1");
        envelope.set("evidence", next.path("evidence")); envelope.set("human_handoffs", next.path("human_handoffs"));
        var event = (ObjectNode) next.path("event"); event.put("expected_revision_no", previous.path("revision").path("revision_no").asLong());
        event.set("revision", revision); envelope.putArray("events").add(event);
        Path file = Files.writeString(root.resolve(UUID.randomUUID() + "-manual.json"), envelope.toString());
        return importer.importBatch(reader.read(file, root), "synthetic-editor");
    }

    private ExtractionRunMySqlTest fixtures() {
        var helpers = new ExtractionRunMySqlTest();
        helpers.root = root; helpers.jdbc = jdbc; helpers.reader = reader; helpers.importer = importer;
        return helpers;
    }

    private ReviewedImportService.ImportResult importHandoff(Fixture fixture) {
        return handoffs.importFile(fixture.file(), root, fixture.handoffRoot(), "synthetic-handoff-importer");
    }

    private JsonNode payload(String revision) throws Exception {
        return mapper.readTree(jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id=?", String.class, revision));
    }

    private String parentRow(String run) {
        return jdbc.queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", run).toString();
    }

    private List<Long> counts() {
        return List.of("events", "event_revisions", "review_audits", "snapshots", "publication_heads", "import_batches").stream()
                .map(table -> jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Long.class)).toList();
    }

    private void conflict(org.assertj.core.api.ThrowableAssert.ThrowingCallable action) {
        assertThatThrownBy(action).isInstanceOfSatisfying(ImportException.class,
                exception -> assertThat(exception.code()).isEqualTo("IMPORT_CONFLICT"));
    }

    @AfterEach
    void makeOwnedTempsRemovable() throws Exception {
        for (String id : ownedCases) {
            jdbc.update("DELETE FROM publication_audits WHERE channel_key=?", "replay:" + id);
            jdbc.update("DELETE FROM publication_heads WHERE channel_key=?", "replay:" + id);
            for (String snapshot : jdbc.queryForList("SELECT snapshot_id FROM snapshots WHERE case_id=?", String.class, id)) {
                jdbc.update("DELETE FROM snapshot_revisions WHERE snapshot_id=?", snapshot);
                jdbc.update("DELETE FROM snapshots WHERE snapshot_id=?", snapshot);
            }
        }
        ExtractionArchiveReaderTest.unseal(root);
    }

    private record Fixture(ObjectNode source, String run, Path archive, Path handoffRoot, Path image,
                           ObjectNode request, JsonNode projection, Path file) {
        String eventId() { return projection.path("events").get(0).path("event_id").asText(); }
    }
}
