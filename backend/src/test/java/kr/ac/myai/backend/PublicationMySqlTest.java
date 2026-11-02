package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.publication.LocalPublicationCommand;
import kr.ac.myai.backend.importing.LocalImportCommand;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.web.context.WebApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class PublicationMySqlTest {
    @Autowired PublicationService publication;
    @Autowired PublicationCommandReader commands;
    @Autowired ReviewedImportService importer;
    @Autowired ReviewedImportReader imports;
    @Autowired JdbcTemplate jdbc;
    @Autowired MockMvc mvc;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();

    @BeforeEach
    void isolatePublicationTables() throws Exception {
        Files.copy(Path.of("examples/synthetic-source.txt"), root.resolve("synthetic-source.txt"));
        clearPublishedData();
    }

    @AfterEach
    void clearPublishedData() {
        jdbc.update("DELETE FROM publication_audits");
        jdbc.update("DELETE FROM publication_heads");
        jdbc.update("DELETE FROM snapshot_revisions");
        jdbc.update("DELETE FROM snapshots");
    }

    @Test
    void approvalCreatesNewRevisionAndLeavesPublicDataUntouched() throws Exception {
        ObjectNode input = fresh();
        var batch = importBatch(input);
        var original = batch.events().getFirst();
        var result = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        assertThat(result.revisionId()).isNotEqualTo(original.revisionId());
        assertThat(jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id = ?", String.class, original.revisionId())).isEqualTo(original.payloadJson());
        assertThat(jdbc.queryForObject("SELECT review_status FROM event_revisions WHERE revision_id = ?", String.class, result.revisionId())).isEqualTo("approved");
        assertThat(jdbc.queryForObject("SELECT publication_intent FROM event_revisions WHERE revision_id = ?", String.class, result.revisionId())).isEqualTo("public");
        assertThat(jdbc.queryForObject("SELECT revision_no FROM event_revisions WHERE revision_id = ?", Long.class, result.revisionId())).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT actor FROM review_audits WHERE revision_id = ?", String.class, result.revisionId())).isEqualTo("synthetic-approver");
        assertThat(count("publication_heads")).isZero();
        conflict(() -> publication.execute(decision(input, "reject", 1), root, "another-reviewer"));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM event_revisions WHERE event_id = ?", Long.class, original.id())).isEqualTo(2);
    }

    @Test
    void rejectsUnreviewedSourcesAndAllowsRejectionWithoutRawFile() throws Exception {
        var input = fresh();
        ((ObjectNode) input.path("documents").get(0)).put("use_review", "restricted");
        importBatch(input);
        assertThatThrownBy(() -> publication.execute(decision(input, "approve", 1), root, "synthetic-approver")).isInstanceOf(PublicationException.class);
        Files.delete(root.resolve("synthetic-source.txt"));
        var rejected = publication.execute(decision(input, "reject", 1), null, "synthetic-reviewer");
        assertThat(jdbc.queryForObject("SELECT review_status FROM event_revisions WHERE revision_id = ?", String.class, rejected.revisionId())).isEqualTo("rejected");
        assertThat(jdbc.queryForObject("SELECT publication_intent FROM event_revisions WHERE revision_id = ?", String.class, rejected.revisionId())).isEqualTo("hidden");
    }

    @Test
    void storedValidationCannotBypassOrdinaryImportApprovalGate() throws Exception {
        var input = fresh();
        ((ObjectNode) input.path("events").get(0).path("revision")).put("review_status", "approved").put("publication_intent", "public");
        var approved = imports.validateStored(input, root);
        assertThatThrownBy(() -> importer.importBatch(approved, "synthetic-importer")).isInstanceOf(kr.ac.myai.backend.importing.ImportException.class);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM events WHERE event_id = ?", Long.class, approved.events().getFirst().id())).isZero();
    }

    @Test
    void blocksChangedRawSourceAndUnapprovedPublication() throws Exception {
        var input = fresh();
        var batch = importBatch(input);
        var pending = publishInput(input, batch.events().getFirst().revisionId(), null);
        assertThatThrownBy(() -> publication.execute(command(pending), root, "synthetic-publisher")).isInstanceOf(PublicationException.class);
        Files.writeString(root.resolve("synthetic-source.txt"), "원문 변경 시험");
        assertThatThrownBy(() -> publication.execute(decision(input, "approve", 1), root, "synthetic-approver")).isInstanceOf(PublicationException.class);
        assertThat(count("snapshots")).isZero();
        assertThat(count("publication_heads")).isZero();
    }

    @Test
    void freezesWhitelistedContentAndRestoresPreviousSnapshot() throws Exception {
        var input = fresh();
        var revision = (ObjectNode) input.path("events").get(0).path("revision");
        var change = revision.withArray("human_overrides").addObject().put("field_path", "title").put("after", "합성 공지")
                .put("reason", "합성 수정").put("reviewer", "DO_NOT_PUBLISH_REVIEWER").put("time", "2026-11-02T02:00:00Z");
        change.putObject("before").put("private_path", "/DO_NOT_PUBLISH_PATH");
        change.putArray("evidence_ids").add("heading-quote");
        importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "DO_NOT_PUBLISH_APPROVER");
        var publish = publishInput(input, approved.revisionId(), null);
        var first = publication.execute(command(publish), root, "synthetic-publisher");
        assertThat(first.headVersion()).isZero();
        String canonical = canonical(first.snapshotId());
        assertThat(canonical).doesNotContain("DO_NOT_PUBLISH", "cleaned_text", "raw_asset_path", "synthetic-source.txt", "human_overrides", "reviewer_id", "checked_by", "raw_output");
        String expectedHash = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(canonical.getBytes(StandardCharsets.UTF_8)));
        assertThat(first.checksum()).isEqualTo(expectedHash);
        var content = mapper.readTree(canonical);
        assertThat(content.path("event_public_payloads")).hasSize(1);
        assertThat(content.path("points")).hasSize(5);
        assertThat(content.path("event_public_payloads").get(0).path("exceptions").path("value").isNull()).isTrue();
        publish.put("expected_head_version", 0).putArray("revision_ids");
        var second = publication.execute(command(publish), root, "synthetic-publisher");
        assertThat(second.headVersion()).isEqualTo(1);
        assertThat(mapper.readTree(canonical(second.snapshotId())).path("event_count").asInt()).isZero();
        var restored = publication.execute(rollback(first.snapshotId(), 1), null, "synthetic-publisher");
        assertThat(restored.headVersion()).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT snapshot_id FROM publication_heads WHERE channel_key = 'current'", String.class)).isEqualTo(first.snapshotId());
        assertThat(canonical(first.snapshotId())).isEqualTo(canonical);
        assertThat(count("publication_audits")).isEqualTo(3);
        mvc.perform(get("/api/v1/config")).andExpect(status().isOk());
        mvc.perform(get("/local/publication")).andExpect(status().isNotFound());
    }

    @Test
    void previewReturnsPublicContentWithoutCreatingSnapshotOrHead() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var request = publishInput(input, approved.revisionId(), null); request.put("action", "preview");
        var preview = publication.execute(command(request), root, "synthetic-publisher");
        assertThat(preview.action()).isEqualTo("preview");
        assertThat(mapper.valueToTree(preview).path("preview").path("event_count").asInt()).isEqualTo(1);
        assertThat(count("snapshots")).isZero();
        assertThat(count("publication_heads")).isZero();
        assertThat(count("publication_audits")).isZero();
    }

    @Test
    void rollsBackSnapshotPointsAndHeadWhenAuditInsertFails() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var publish = publishInput(input, approved.revisionId(), null);
        var first = publication.execute(command(publish), root, "synthetic-publisher");
        var point = (ObjectNode) publish.path("points").get(0);
        String pointId = point.path("point_id").asText();
        point.put("lat", 37.02).put("version", 2);
        publish.put("expected_head_version", 0).put("reason", "synthetic-late-failure");
        jdbc.execute("ALTER TABLE publication_audits ADD CONSTRAINT chk_test_publish_failure CHECK (reason <> 'synthetic-late-failure')");
        try {
            assertThatThrownBy(() -> publication.execute(command(publish), root, "synthetic-publisher")).isInstanceOf(PublicationException.class);
        } finally { jdbc.execute("ALTER TABLE publication_audits DROP CHECK chk_test_publish_failure"); }
        assertThat(count("snapshots")).isEqualTo(1);
        assertThat(count("publication_audits")).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT snapshot_id FROM publication_heads WHERE channel_key = 'current'", String.class)).isEqualTo(first.snapshotId());
        assertThat(jdbc.queryForObject("SELECT latitude FROM test_points WHERE point_id = ?", java.math.BigDecimal.class, pointId)).isEqualByComparingTo("37.01");
    }

    @Test
    void concurrentApprovalAndPublicationEachAllowOneWinner() throws Exception {
        var input = fresh(); importBatch(input);
        var review = decision(input, "approve", 1);
        assertThat(compete(review)).containsExactlyInAnyOrder("success", "PUBLICATION_CONFLICT");
        String approved = jdbc.queryForObject("SELECT current_review_revision_id FROM events WHERE event_id = ?", String.class, input.path("events").get(0).path("event_id").asText());
        assertThat(compete(command(publishInput(input, approved, null)))).containsExactlyInAnyOrder("success", "PUBLICATION_CONFLICT");
        assertThat(count("snapshots")).isEqualTo(1);
        assertThat(count("publication_audits")).isEqualTo(1);
    }

    @Test
    void checksReplayCutoffAndRejectsCrossChannelOrCorruptRollback() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var publish = publishInput(input, approved.revisionId(), null);
        var first = publication.execute(command(publish), root, "synthetic-publisher");
        var replay = publish.deepCopy();
        replay.put("mode", "replay").put("case_id", UUID.randomUUID().toString()).put("anchor_date", "2026-11-02")
                .put("reference_instant", "2026-11-02T03:00:00Z").put("knowledge_cutoff", "2026-11-02T03:00:00Z").put("history_fidelity", "verified_snapshot");
        var other = publication.execute(command(replay), root, "synthetic-publisher");
        assertThatThrownBy(() -> publication.execute(rollback(other.snapshotId(), 0), null, "synthetic-publisher")).isInstanceOf(PublicationException.class);
        jdbc.update("UPDATE snapshots SET canonical_json = '{}' WHERE snapshot_id = ?", first.snapshotId());
        assertThatThrownBy(() -> publication.execute(rollback(first.snapshotId(), 0), null, "synthetic-publisher")).isInstanceOf(PublicationException.class);
        assertThat(jdbc.queryForObject("SELECT lock_version FROM publication_heads WHERE channel_key = 'current'", Long.class)).isZero();
        replay.put("reference_instant", "2026-11-02T00:00:00Z").put("knowledge_cutoff", "2026-11-02T00:00:00Z").put("expected_head_version", 0);
        assertThatThrownBy(() -> publication.execute(command(replay), root, "synthetic-publisher")).isInstanceOf(PublicationException.class);
    }

    @Test
    void verifiedReplayRequiresSuccessfulCheckBeforeCutoff() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var replay = publishInput(input, approved.revisionId(), null);
        replay.put("mode", "replay").put("case_id", UUID.randomUUID().toString()).put("anchor_date", "2026-11-02")
                .put("reference_instant", "2026-11-02T03:00:00Z").put("knowledge_cutoff", "2026-11-02T01:30:00Z").put("history_fidelity", "verified_snapshot");
        assertThatThrownBy(() -> publication.execute(command(replay), root, "synthetic-publisher")).isInstanceOf(PublicationException.class);
        replay.put("history_fidelity", "reconstructed");
        var result = publication.execute(command(replay), root, "synthetic-publisher");
        var content = mapper.readTree(canonical(result.snapshotId()));
        assertThat(content.path("sources").get(0).path("last_verified_at").isNull()).isTrue();
        assertThat(content.path("sources").get(0).path("current_last_verified_at").asText()).isEqualTo("2026-11-02T02:00:00Z");
    }

    @Test
    void replayDoesNotTreatPublicationDateAsVersionAvailability() throws Exception {
        var input = fresh(); var document = (ObjectNode) input.path("documents").get(0);
        document.put("collected_at", "2026-11-02T04:00:00Z").put("last_verified_at", "2026-11-02T04:30:00Z").put("latest_check_attempt_at", "2026-11-02T04:30:00Z");
        ((ObjectNode) document.path("checks").get(0)).put("checked_at", "2026-11-02T04:30:00Z");
        importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var replay = publishInput(input, approved.revisionId(), null);
        replay.put("mode", "replay").put("case_id", UUID.randomUUID().toString()).put("anchor_date", "2026-11-02")
                .put("reference_instant", "2026-11-02T03:00:00Z").put("knowledge_cutoff", "2026-11-02T03:00:00Z").put("history_fidelity", "reconstructed");
        assertThatThrownBy(() -> publication.execute(command(replay), root, "synthetic-publisher")).isInstanceOf(PublicationException.class);
        assertThat(count("publication_heads")).isZero();
    }

    @Test
    void refusesFutureHumanVerificationBeforeApproval() throws Exception {
        var input = fresh();
        ((ObjectNode) input.path("events").get(0).path("revision").path("locations").get(0)).put("checked_at", "2100-01-01T00:00:00Z");
        importBatch(input);
        assertThatThrownBy(() -> publication.execute(decision(input, "approve", 1), root, "synthetic-approver")).isInstanceOf(PublicationException.class);
        var overrides = fresh();
        var change = ((ObjectNode) overrides.path("events").get(0).path("revision")).withArray("human_overrides").addObject()
                .put("field_path", "title").put("before", "합성 공지").put("after", "수정 공지").put("reason", "합성 변경")
                .put("reviewer", "synthetic-reviewer").put("time", "2100-01-01T00:00:00Z");
        change.putArray("evidence_ids").add("heading-quote");
        importBatch(overrides);
        assertThatThrownBy(() -> publication.execute(decision(overrides, "approve", 1), root, "synthetic-approver")).isInstanceOf(PublicationException.class);
    }

    @Test
    void localCommandRunsWithoutHttpAndMixedProfilesWriteNothing() throws Exception {
        var input = fresh(); importBatch(input);
        var request = fixture("approve");
        request.put("event_id", input.path("events").get(0).path("event_id").asText());
        Path file = Files.writeString(root.resolve("approve.json"), request.toString());
        try (var context = new SpringApplicationBuilder(MyaiBackendApplication.class).profiles("local-publication")
                .run("--myai.publication.file=" + file, "--myai.publication.source-root=" + root, "--myai.publication.actor=synthetic-approver")) {
            assertThat(context).isNotInstanceOf(WebApplicationContext.class);
            assertThat(context.getBean(LocalPublicationCommand.class).getExitCode()).isZero();
        }
        var unimported = fresh();
        Path importFile = Files.writeString(root.resolve("import.json"), unimported.toString());
        try (var context = new SpringApplicationBuilder(MyaiBackendApplication.class).profiles("local-import", "local-publication")
                .run("--myai.import.file=" + importFile, "--myai.import.source-root=" + root, "--myai.import.actor=synthetic-importer",
                        "--myai.publication.file=" + file, "--myai.publication.source-root=" + root, "--myai.publication.actor=synthetic-approver")) {
            assertThat(context.getBean(LocalImportCommand.class).getExitCode()).isEqualTo(2);
            assertThat(context.getBean(LocalPublicationCommand.class).getExitCode()).isEqualTo(2);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM events WHERE event_id = ?", Long.class, unimported.path("events").get(0).path("event_id").asText())).isZero();
        }
    }

    @Test
    void publicApiReadsFrozenFactsAndPreservesUnknownValues() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "PRIVATE_APPROVER");
        var request = publishInput(input, approved.revisionId(), null);
        var published = publication.execute(command(request), root, "PRIVATE_PUBLISHER");
        String eventId = input.path("events").get(0).path("event_id").asText();
        String pointId = request.path("points").get(0).path("point_id").asText();
        jdbc.update("UPDATE test_points SET label = 'PRIVATE_WORK_LABEL' WHERE point_id = ?", pointId);
        var draft = (ObjectNode) input.path("events").get(0).path("revision");
        draft.put("revision_id", UUID.randomUUID().toString()).put("revision_no", 3).put("title", "PRIVATE_DRAFT");
        ((ObjectNode) input.path("events").get(0)).put("expected_revision_no", 2);
        importBatch(input);
        var requestStarted = java.time.Instant.now();
        var config = body("/api/v1/config");
        assertThat(config.path("snapshot_id").asText()).isEqualTo(published.snapshotId());
        assertThat(config.path("data").path("created_at").asText()).isEqualTo(mapper.readTree(canonical(published.snapshotId())).path("created_at").asText());
        assertThat(body("/api/v1/config").path("data").path("created_at")).isEqualTo(config.path("data").path("created_at"));
        assertThat(config.path("data").path("points")).hasSize(5);
        assertThat(config.path("data").path("document_count").asInt()).isEqualTo(1);
        assertThat(config.path("data").path("event_count").asInt()).isEqualTo(1);
        assertThat(config.path("data").path("data_kind").asText()).isEqualTo("synthetic");
        assertThat(java.time.Instant.parse(config.path("data").path("server_now").asText())).isBetween(requestStarted, java.time.Instant.now());
        var detail = body("/api/v1/events/" + eventId + "?snapshot_id=" + published.snapshotId());
        var event = detail.path("data").path("event");
        assertThat(event.path("title").asText()).isEqualTo("합성 공지 😀");
        assertThat(event.path("revision_id").asText()).isEqualTo(approved.revisionId());
        assertThat(event.path("applicability").asText()).isEqualTo("차량");
        assertThat(event.path("exceptions").isNull()).isTrue();
        assertThat(event.path("field_values").path("exceptions").path("knowledge").asText()).isEqualTo("not_stated");
        assertThat(event.path("evidence").get(0).path("quote").asText()).isEqualTo("합성 공지 😀");
        assertThat(event.path("source_refs").get(0).path("is_fixture").asBoolean()).isTrue();
        assertThat(event.has("classification") || event.has("distance_m") || event.has("time_overlap_minutes")).isFalse();
        assertThat(config.toString() + detail).doesNotContain("PRIVATE_", "reviewer_id", "cleaned_text", "raw_asset_path", "human_overrides", "checked_by");
        mvc.perform(get("/api/v1/events/" + UUID.randomUUID()).param("snapshot_id", published.snapshotId()))
                .andExpect(status().isNotFound()).andExpect(jsonPath("$.error.code").value("EVENT_NOT_FOUND"));
    }

    @Test
    void supersededSnapshotsRetireAndRollbackReactivatesFrozenPoints() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var request = publishInput(input, approved.revisionId(), null);
        var first = publication.execute(command(request), root, "synthetic-publisher");
        String event = input.path("events").get(0).path("event_id").asText();
        var changedPoint = (ObjectNode) request.path("points").get(0);
        changedPoint.put("version", 2).put("label", "새 공개 지점");
        request.put("expected_head_version", 0).putArray("revision_ids");
        var second = publication.execute(command(request), root, "synthetic-publisher");
        mvc.perform(get("/api/v1/events/" + event).param("snapshot_id", first.snapshotId()))
                .andExpect(status().isConflict()).andExpect(jsonPath("$.error.code").value("SNAPSHOT_RETIRED"))
                .andExpect(jsonPath("$.current_snapshot_id").value(second.snapshotId()));
        assertThat(body("/api/v1/config").path("data").path("event_count").asInt()).isZero();
        publication.execute(rollback(first.snapshotId(), 1), null, "synthetic-publisher");
        var restored = body("/api/v1/config");
        assertThat(restored.path("snapshot_id").asText()).isEqualTo(first.snapshotId());
        assertThat(restored.toString()).doesNotContain("새 공개 지점");
        body("/api/v1/events/" + event + "?snapshot_id=" + first.snapshotId());
        mvc.perform(get("/api/v1/events/" + event).param("snapshot_id", second.snapshotId())).andExpect(status().isConflict());
    }

    @Test
    void neverPublishedAndCorruptSnapshotsFailWithoutLeakingContent() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var published = publication.execute(command(publishInput(input, approved.revisionId(), null)), root, "synthetic-publisher");
        String event = input.path("events").get(0).path("event_id").asText();
        mvc.perform(get("/api/v1/events/" + event).param("snapshot_id", UUID.randomUUID().toString())).andExpect(status().isNotFound());
        jdbc.update("UPDATE snapshots SET checksum = REPEAT('0', 64) WHERE snapshot_id = ?", published.snapshotId());
        mvc.perform(get("/api/v1/config")).andExpect(status().isInternalServerError()).andExpect(jsonPath("$.error.code").value("SNAPSHOT_INVALID"));
        jdbc.update("DELETE FROM publication_audits");
        mvc.perform(get("/api/v1/events/" + event).param("snapshot_id", published.snapshotId())).andExpect(status().isNotFound());
    }

    @Test
    void matchesValidatesSnapshotAndPointBeforeReportingMissingCalculator() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var request = publishInput(input, approved.revisionId(), null);
        var published = publication.execute(command(request), root, "synthetic-publisher");
        ObjectNode query = (ObjectNode) mapper.readTree(Path.of("../contracts/examples/matches-request.json").toFile());
        query.put("point_id", request.path("points").get(0).path("point_id").asText()).put("snapshot_id", published.snapshotId());
        mvc.perform(post("/api/v1/matches").contentType("application/json").content(query.toString()))
                .andExpect(status().isServiceUnavailable()).andExpect(jsonPath("$.error.code").value("CALCULATOR_NOT_READY"));
        query.put("point_id", UUID.randomUUID().toString());
        mvc.perform(post("/api/v1/matches").contentType("application/json").content(query.toString()))
                .andExpect(status().isUnprocessableEntity()).andExpect(jsonPath("$.error.code").value("INVALID_POINT"));
        query.put("snapshot_id", UUID.randomUUID().toString());
        mvc.perform(post("/api/v1/matches").contentType("application/json").content(query.toString())).andExpect(status().isNotFound());
    }

    @Test
    void replayConfigKeepsCaseAndHistoricalSourceContextSeparate() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var request = publishInput(input, approved.revisionId(), null);
        var current = publication.execute(command(request), root, "synthetic-publisher");
        String caseId = UUID.randomUUID().toString();
        request.put("mode", "replay").put("case_id", caseId).put("anchor_date", "2026-11-02")
                .put("reference_instant", "2026-11-02T03:00:00Z").put("knowledge_cutoff", "2026-11-02T01:30:00Z")
                .put("history_fidelity", "reconstructed");
        var replay = publication.execute(command(request), root, "synthetic-publisher");
        var config = body("/api/v1/config?mode=replay&case_id=" + caseId);
        assertThat(config.path("snapshot_id").asText()).isEqualTo(replay.snapshotId());
        assertThat(config.path("data").path("knowledge_cutoff").asText()).isEqualTo("2026-11-02T01:30:00Z");
        assertThat(config.path("data").path("cases")).hasSize(1);
        assertThat(body("/api/v1/config").path("snapshot_id").asText()).isEqualTo(current.snapshotId());
        var detail = body("/api/v1/events/" + input.path("events").get(0).path("event_id").asText() + "?snapshot_id=" + replay.snapshotId());
        var source = detail.path("data").path("event").path("source_refs").get(0);
        assertThat(source.path("last_verified_at").isNull()).isTrue();
        assertThat(source.path("check_result").asText()).isEqualTo("unchecked");
        assertThat(source.path("current_check_result").asText()).isEqualTo("verified");
        mvc.perform(get("/api/v1/config").param("mode", "replay").param("case_id", UUID.randomUUID().toString()))
                .andExpect(status().isNotFound()).andExpect(jsonPath("$.error.code").value("CASE_NOT_FOUND"));
        jdbc.update("UPDATE publication_heads SET snapshot_id = ? WHERE channel_key = 'current'", replay.snapshotId());
        mvc.perform(get("/api/v1/config")).andExpect(status().isInternalServerError()).andExpect(jsonPath("$.error.code").value("SNAPSHOT_INVALID"));
    }

    @Test
    void historyIncludesOnlyEarlierPublishedFactsAndRollbackHidesLaterChanges() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "PRIVATE_APPROVER");
        var request = publishInput(input, approved.revisionId(), null);
        var first = publication.execute(command(request), root, "synthetic-publisher");
        var doc = (ObjectNode) input.path("documents").get(0);
        String beforeVersion = doc.path("document_version_id").asText();
        String afterVersion = UUID.randomUUID().toString();
        doc.put("document_version_id", afterVersion).put("version_no", 2);
        for (var check : doc.path("checks")) ((ObjectNode) check).put("check_id", UUID.randomUUID().toString());
        for (var evidence : input.path("evidence")) ((ObjectNode) evidence).put("document_version_id", afterVersion);
        var draft = (ObjectNode) input.path("events").get(0).path("revision");
        draft.putArray("source_version_ids").add(afterVersion);
        draft.put("revision_id", UUID.randomUUID().toString()).put("revision_no", 3).put("title", "합성 변경 제목");
        ((ObjectNode) input.path("events").get(0)).put("expected_revision_no", 2).put("area_membership", "uncertain");
        importBatch(input);
        var secondRevision = publication.execute(decision(input, "approve", 3), root, "PRIVATE_SECOND_APPROVER");
        request.put("expected_head_version", 0).putArray("revision_ids").add(secondRevision.revisionId());
        var second = publication.execute(command(request), root, "synthetic-publisher");
        String url = "/api/v1/events/" + input.path("events").get(0).path("event_id").asText() + "?snapshot_id=";
        var history = body(url + second.snapshotId()).path("data").path("event").path("history");
        assertThat(history).hasSize(1);
        assertThat(history.get(0).path("changes").get(0).path("field").asText()).isEqualTo("title");
        assertThat(history.get(0).path("changes").get(0).path("before").asText()).isEqualTo("합성 공지 😀");
        assertThat(history.get(0).path("changes").get(0).path("after").asText()).isEqualTo("합성 변경 제목");
        assertThat(history.get(0).path("changes").findValuesAsText("field")).contains("source_refs", "area_membership");
        assertThat(history.get(0).path("before_source_refs").get(0).path("document_version_id").asText()).isEqualTo(beforeVersion);
        assertThat(history.get(0).path("source_refs").get(0).path("document_version_id").asText()).isEqualTo(afterVersion);
        assertThat(history.toString()).doesNotContain("PRIVATE_", "human_overrides", "reviewer");
        publication.execute(rollback(first.snapshotId(), 1), null, "synthetic-publisher");
        assertThat(body(url + first.snapshotId()).path("data").path("event").path("history")).isEmpty();
    }

    @Test
    void replayHistoryDoesNotImportFactsFromDifferentHistoricalContext() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var request = publishInput(input, approved.revisionId(), null);
        String caseId = UUID.randomUUID().toString();
        request.put("mode", "replay").put("case_id", caseId).put("anchor_date", "2026-11-02")
                .put("reference_instant", "2026-11-02T03:00:00Z").put("knowledge_cutoff", "2026-11-02T03:00:00Z")
                .put("history_fidelity", "reconstructed");
        var otherContext = publication.execute(command(request), root, "synthetic-publisher");
        var draft = (ObjectNode) input.path("events").get(0).path("revision");
        draft.put("revision_id", UUID.randomUUID().toString()).put("revision_no", 3).put("title", "합성 변경 제목");
        ((ObjectNode) input.path("events").get(0)).put("expected_revision_no", 2);
        importBatch(input);
        var changed = publication.execute(decision(input, "approve", 3), root, "synthetic-approver");
        request.put("expected_head_version", 0).put("knowledge_cutoff", "2026-11-02T01:30:00Z").putArray("revision_ids").add(changed.revisionId());
        var replay = publication.execute(command(request), root, "synthetic-publisher");
        jdbc.update("UPDATE snapshots SET checksum = REPEAT('0', 64) WHERE snapshot_id = ?", otherContext.snapshotId());
        var detail = body("/api/v1/events/" + input.path("events").get(0).path("event_id").asText() + "?snapshot_id=" + replay.snapshotId());
        assertThat(detail.path("data").path("event").path("history")).isEmpty();
    }

    @Test
    void historyKeepsRollbackTransitionsBeforeLaterPublication() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var request = publishInput(input, approved.revisionId(), null);
        var first = publication.execute(command(request), root, "synthetic-publisher");
        var draft = (ObjectNode) input.path("events").get(0).path("revision");
        draft.put("revision_id", UUID.randomUUID().toString()).put("revision_no", 3).put("title", "합성 변경 제목");
        ((ObjectNode) input.path("events").get(0)).put("expected_revision_no", 2);
        importBatch(input);
        var changed = publication.execute(decision(input, "approve", 3), root, "synthetic-approver");
        request.put("expected_head_version", 0).putArray("revision_ids").add(changed.revisionId());
        publication.execute(command(request), root, "synthetic-publisher");
        publication.execute(rollback(first.snapshotId(), 1), null, "synthetic-publisher");
        request.put("expected_head_version", 2);
        var current = publication.execute(command(request), root, "synthetic-publisher");
        String url = "/api/v1/events/" + input.path("events").get(0).path("event_id").asText() + "?snapshot_id=";
        var history = body(url + current.snapshotId()).path("data").path("event").path("history");
        assertThat(history).hasSize(3);
        assertThat(history.get(0).path("changes").get(0).path("after").asText()).isEqualTo("합성 변경 제목");
        assertThat(history.get(1).path("changes").get(0).path("before").asText()).isEqualTo("합성 변경 제목");
        assertThat(history.get(1).path("changes").get(0).path("after").asText()).isEqualTo("합성 공지 😀");
        assertThat(history.get(1).path("action").asText()).isEqualTo("rollback");
        assertThat(history.get(2).path("changes").get(0).path("after").asText()).isEqualTo("합성 변경 제목");
        request.put("expected_head_version", 3);
        var repeated = publication.execute(command(request), root, "synthetic-publisher");
        assertThat(body(url + repeated.snapshotId()).path("data").path("event").path("history")).hasSize(3);
    }

    @Test
    void historyUsesPublicationOrderWhenAuditTimeDiffersFromSnapshotCreation() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var request = publishInput(input, approved.revisionId(), null);
        var first = publication.execute(command(request), root, "synthetic-publisher");
        var draft = (ObjectNode) input.path("events").get(0).path("revision");
        draft.put("revision_id", UUID.randomUUID().toString()).put("revision_no", 3).put("title", "합성 변경 제목");
        ((ObjectNode) input.path("events").get(0)).put("expected_revision_no", 2);
        importBatch(input);
        var changed = publication.execute(decision(input, "approve", 3), root, "synthetic-approver");
        request.put("expected_head_version", 0).putArray("revision_ids").add(changed.revisionId());
        var second = publication.execute(command(request), root, "synthetic-publisher");
        jdbc.update("UPDATE publication_audits SET happened_at = TIMESTAMPADD(SECOND, 1, happened_at) WHERE after_snapshot_id = ?", second.snapshotId());
        String url = "/api/v1/events/" + input.path("events").get(0).path("event_id").asText() + "?snapshot_id=";
        assertThat(body(url + second.snapshotId()).path("data").path("event").path("history")).hasSize(1);
        publication.execute(rollback(first.snapshotId(), 1), null, "synthetic-publisher");
        assertThat(body(url + first.snapshotId()).path("data").path("event").path("history")).isEmpty();
    }

    @Test
    void corruptReplayOutsideCurrentAreaOrDataKindDoesNotBreakConfig() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var current = publication.execute(command(publishInput(input, approved.revisionId(), null)), root, "synthetic-publisher");
        String brokenCase = null;
        for (boolean otherArea : List.of(true, false)) {
            var replay = publishInput(otherArea ? fresh() : input, approved.revisionId(), null);
            replay.putArray("revision_ids");
            brokenCase = UUID.randomUUID().toString();
            replay.put("mode", "replay").put("case_id", brokenCase).put("anchor_date", "2026-11-02")
                    .put("reference_instant", "2026-11-02T03:00:00Z").put("knowledge_cutoff", "2026-11-02T03:00:00Z")
                    .put("history_fidelity", "reconstructed");
            if (!otherArea) replay.put("data_kind", "real");
            var published = publication.execute(command(replay), root, "synthetic-publisher");
            jdbc.update("UPDATE snapshots SET checksum = REPEAT('0', 64) WHERE snapshot_id = ?", published.snapshotId());
        }
        var response = body("/api/v1/config");
        assertThat(response.path("snapshot_id").asText()).isEqualTo(current.snapshotId());
        assertThat(response.path("data").path("cases")).isEmpty();
        mvc.perform(get("/api/v1/config").param("mode", "replay").param("case_id", brokenCase))
                .andExpect(status().isInternalServerError()).andExpect(jsonPath("$.error.code").value("SNAPSHOT_INVALID"));
    }

    @Test
    void outsideEventCannotBecomePublicSnapshot() throws Exception {
        var input = fresh();
        ((ObjectNode) input.path("events").get(0)).put("area_membership", "outside");
        importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        assertThatThrownBy(() -> publication.execute(command(publishInput(input, approved.revisionId(), null)), root, "synthetic-publisher"))
                .isInstanceOfSatisfying(PublicationException.class, error -> assertThat(error.code()).isEqualTo("PUBLICATION_VALIDATION_ERROR"));
        assertThat(count("snapshots")).isZero();
        assertThat(count("publication_heads")).isZero();
    }

    @Test
    void legacyOutsideSnapshotCannotBeReadOrRestored() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var request = publishInput(input, approved.revisionId(), null);
        var legacy = publication.execute(command(request), root, "synthetic-publisher");
        var legacyContent = (ObjectNode) mapper.readTree(canonical(legacy.snapshotId()));
        ((ObjectNode) legacyContent.path("event_public_payloads").get(0)).put("area_membership", "outside");
        String json = legacyContent.toString();
        jdbc.update("UPDATE snapshots SET canonical_json = ?, checksum = ? WHERE snapshot_id = ?", json, ReviewedImportReader.sha256(json.getBytes(StandardCharsets.UTF_8)), legacy.snapshotId());
        mvc.perform(get("/api/v1/config")).andExpect(status().isInternalServerError()).andExpect(jsonPath("$.error.code").value("SNAPSHOT_INVALID"));
        mvc.perform(get("/api/v1/events/" + input.path("events").get(0).path("event_id").asText()).param("snapshot_id", legacy.snapshotId()))
                .andExpect(status().isInternalServerError()).andExpect(jsonPath("$.error.code").value("SNAPSHOT_INVALID"));
        request.put("expected_head_version", 0).putArray("revision_ids");
        var current = publication.execute(command(request), root, "synthetic-publisher");
        assertThatThrownBy(() -> publication.execute(rollback(legacy.snapshotId(), 1), null, "synthetic-publisher")).isInstanceOf(PublicationException.class);
        assertThat(body("/api/v1/config").path("snapshot_id").asText()).isEqualTo(current.snapshotId());
    }

    @Test
    void databaseDetailMatchesPublishedFactOnlyExample() throws Exception {
        var ids = new HashMap<String, String>();
        String original = Files.readString(Path.of("examples/reviewed-import.json"));
        ObjectNode input = (ObjectNode) mapper.readTree(Pattern.compile("10000000-0000-4000-8000-[0-9]{12}").matcher(original)
                .replaceAll(match -> ids.computeIfAbsent(match.group(), ignored -> UUID.randomUUID().toString())));
        importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var published = publication.execute(command(publishInput(input, approved.revisionId(), null)), root, "synthetic-publisher");
        var started = java.time.Instant.now();
        ObjectNode actual = (ObjectNode) body("/api/v1/events/" + input.path("events").get(0).path("event_id").asText() + "?snapshot_id=" + published.snapshotId());
        assertThat(actual.path("snapshot_id").asText()).isEqualTo(published.snapshotId());
        assertThat(actual.path("data").path("event").path("revision_id").asText()).isEqualTo(approved.revisionId());
        assertThat(java.time.Instant.parse(actual.path("generated_at").asText())).isBetween(started, java.time.Instant.now());
        String normalized = actual.toString();
        for (var entry : ids.entrySet()) normalized = normalized.replace(entry.getValue(), entry.getKey());
        actual = (ObjectNode) mapper.readTree(normalized);
        var expected = mapper.readTree(Path.of("../contracts/examples/event-facts-response.json").toFile());
        actual.set("snapshot_id", expected.path("snapshot_id"));
        actual.set("generated_at", expected.path("generated_at"));
        ((ObjectNode) actual.path("data").path("event")).set("revision_id", expected.path("data").path("event").path("revision_id"));
        assertThat(actual).isEqualTo(expected);
    }

    @Test
    void concurrentHeadChangesNeverMixSnapshotCountsAndPointLabels() throws Exception {
        var input = fresh(); importBatch(input);
        var approved = publication.execute(decision(input, "approve", 1), root, "synthetic-approver");
        var request = publishInput(input, approved.revisionId(), null);
        var first = publication.execute(command(request), root, "synthetic-publisher");
        String pointId = request.path("points").get(0).path("point_id").asText();
        String oldLabel = request.path("points").get(0).path("label").asText();
        ((ObjectNode) request.path("points").get(0)).put("version", 2).put("label", "동시 공개 지점");
        request.put("expected_head_version", 0).putArray("revision_ids");
        var second = publication.execute(command(request), root, "synthetic-publisher");
        var start = new CyclicBarrier(2);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var writer = pool.submit(() -> {
                start.await(10, TimeUnit.SECONDS);
                for (long version = 1; version < 21; version++) publication.execute(rollback(version % 2 == 1 ? first.snapshotId() : second.snapshotId(), version), null, "synthetic-publisher");
                return true;
            });
            var reader = pool.submit(() -> {
                start.await(10, TimeUnit.SECONDS);
                for (int i = 0; i < 40; i++) {
                    var response = body("/api/v1/config");
                    boolean original = response.path("snapshot_id").asText().equals(first.snapshotId());
                    assertThat(response.path("data").path("event_count").asInt()).isEqualTo(original ? 1 : 0);
                    for (var point : response.path("data").path("points")) if (point.path("point_id").asText().equals(pointId)) {
                        assertThat(point.path("label").asText()).isEqualTo(original ? oldLabel : "동시 공개 지점");
                    }
                }
                return true;
            });
            assertThat(writer.get(30, TimeUnit.SECONDS)).isTrue();
            assertThat(reader.get(30, TimeUnit.SECONDS)).isTrue();
        }
    }

    private com.fasterxml.jackson.databind.JsonNode body(String url) throws Exception {
        return mapper.readTree(mvc.perform(get(url)).andExpect(status().isOk()).andReturn().getResponse().getContentAsString(StandardCharsets.UTF_8));
    }

    private List<String> compete(PublicationCommand command) throws Exception {
        var barrier = new CyclicBarrier(2);
        try (var pool = Executors.newFixedThreadPool(2)) {
            java.util.concurrent.Callable<String> action = () -> {
                barrier.await(10, TimeUnit.SECONDS);
                try { publication.execute(command, root, "synthetic-concurrent"); return "success"; }
                catch (PublicationException ex) { return ex.code(); }
            };
            var a = pool.submit(action); var b = pool.submit(action);
            return List.of(a.get(20, TimeUnit.SECONDS), b.get(20, TimeUnit.SECONDS));
        }
    }

    private PublicationCommand decision(ObjectNode input, String action, long expected) throws Exception {
        var command = fixture("approve");
        command.put("event_id", input.path("events").get(0).path("event_id").asText()).put("action", action).put("expected_revision_no", expected);
        return command(command);
    }

    private ObjectNode publishInput(ObjectNode input, String revision, Long expected) throws Exception {
        var command = fixture("publish");
        String area = input.path("events").get(0).path("area_id").asText();
        ((ObjectNode) command.path("area")).put("area_id", area);
        for (var point : command.path("points")) ((ObjectNode) point).put("area_id", area).put("point_id", UUID.randomUUID().toString());
        command.putArray("revision_ids").add(revision);
        if (expected == null) command.putNull("expected_head_version"); else command.put("expected_head_version", expected);
        return command;
    }

    private PublicationCommand rollback(String snapshot, long expected) throws Exception {
        var command = fixture("rollback");
        command.put("snapshot_id", snapshot).put("expected_head_version", expected);
        return command(command);
    }

    private PublicationCommand command(ObjectNode input) throws Exception {
        Path file = Files.writeString(root.resolve(UUID.randomUUID() + ".json"), input.toString());
        return commands.read(file);
    }

    private kr.ac.myai.backend.importing.ReviewedBatch importBatch(ObjectNode input) throws Exception {
        Path file = Files.writeString(root.resolve(UUID.randomUUID() + ".json"), input.toString());
        var batch = imports.read(file, root);
        importer.importBatch(batch, "synthetic-importer");
        return batch;
    }

    private ObjectNode fresh() throws Exception {
        String json = Files.readString(Path.of("examples/reviewed-import.json"));
        var ids = new HashMap<String, String>();
        return (ObjectNode) mapper.readTree(Pattern.compile("10000000-0000-4000-8000-[0-9]{12}").matcher(json)
                .replaceAll(match -> ids.computeIfAbsent(match.group(), ignored -> UUID.randomUUID().toString())));
    }

    private ObjectNode fixture(String name) throws Exception { return (ObjectNode) mapper.readTree(Path.of("examples/" + name + ".json").toFile()); }
    private long count(String table) { return jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Long.class); }
    private String canonical(String id) { return jdbc.queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id = ?", String.class, id); }
    private void conflict(org.assertj.core.api.ThrowableAssert.ThrowingCallable action) {
        assertThatThrownBy(action).isInstanceOfSatisfying(PublicationException.class, ex -> assertThat(ex.code()).isEqualTo("PUBLICATION_CONFLICT"));
    }
}
