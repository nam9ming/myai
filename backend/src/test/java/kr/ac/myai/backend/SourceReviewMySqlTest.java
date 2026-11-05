package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.repository.PublicationRepository;
import kr.ac.myai.backend.repository.ExtractionRunRepository;
import kr.ac.myai.backend.repository.SourceReviewRepository;
import kr.ac.myai.backend.service.ExtractionImportService;
import kr.ac.myai.backend.service.HumanHandoffImportService;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ReviewedImportService;
import kr.ac.myai.backend.service.SnapshotExportService;
import kr.ac.myai.backend.service.SourceReviewService;
import kr.ac.myai.backend.source.SourceReviewException;
import kr.ac.myai.backend.source.SourceReviewState;
import kr.ac.myai.backend.source.SourceView;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import static kr.ac.myai.backend.SourceReviewFixtures.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@SpringBootTest
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class SourceReviewMySqlTest {
    @Autowired SourceReviewService reviews;
    @MockitoSpyBean PublicationRepository documents;
    @Autowired ReviewedImportReader reader;
    @Autowired ReviewedImportService importer;
    @Autowired ExtractionImportService extraction;
    @Autowired HumanHandoffImportService handoffs;
    @Autowired PublicationService publication;
    @Autowired PublicationCommandReader commands;
    @Autowired SnapshotExportService exporter;
    @Autowired PlatformTransactionManager manager;
    @Autowired JdbcTemplate jdbc;
    @MockitoSpyBean SourceReviewRepository sourceReviews;
    @MockitoSpyBean SourceReviewState sourceState;
    @MockitoSpyBean ExtractionRunRepository extractionRuns;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final List<String> ownedCases = new ArrayList<>();
    SourceReviewFixtures fixtures;

    @DynamicPropertySource
    static void python(DynamicPropertyRegistry properties) {
        properties.add("app.calculation.workdir", () -> PythonProbe.REPO.toString());
        properties.add("app.calculation.python-executable", () -> PythonProbe.PYTHON);
        properties.add("app.extraction.timeout-ms", () -> 10000);
    }

    @BeforeEach
    void syntheticFixture() { fixtures = new SourceReviewFixtures(root, jdbc, reader, importer); }

    @AfterEach
    void removeOwnedPublicationRowsAndUnsealTemps() throws Exception {
        for (String caseId : ownedCases) {
            String channel = "replay:" + caseId;
            jdbc.update("DELETE FROM publication_audits WHERE channel_key=?", channel);
            jdbc.update("DELETE FROM publication_heads WHERE channel_key=?", channel);
            jdbc.update("DELETE FROM snapshot_revisions WHERE snapshot_id IN (SELECT snapshot_id FROM snapshots WHERE case_id=?)", caseId);
            jdbc.update("DELETE FROM snapshots WHERE case_id=?", caseId);
        }
        ExtractionArchiveReaderTest.unseal(root);
    }

    @Test
    void pendingVersionAppendsVerifiedAllowedWithoutChangingOriginalOrFrozenRun() throws Exception {
        var source = fixtures.source(true); fixtures.register(source);
        String run = UUID.randomUUID().toString(); Path archive = fixtures.archive(source, run);
        extraction.importRun(run, archive, "synthetic-registrant");
        var original = documents.document(version(source)); var runBefore = runRow(run); var counts = businessCounts();
        var request = request(source, 0, "verified", "allowed", "합성 권한 확인");
        Instant before = Instant.now(); var result = review(request, root, "synthetic-first-reviewer");
        assertThat(result.reviewNo()).isEqualTo(1); assertThat(result.alreadyRecorded()).isFalse();
        assertThat(result.documentVersionId()).isEqualTo(version(source));
        assertThat(result.reviewId()).isEqualTo(request.path("review_id").asText());
        assertThat(documents.document(version(source))).isEqualTo(original);
        assertThat(runRow(run)).isEqualTo(runBefore); assertThat(businessCounts()).isEqualTo(counts);
        var view = view(source); var effective = metadata(view);
        assertThat(view.original()).isEqualTo(original); assertThat(view.reviewNo()).isEqualTo(1);
        assertThat(view.reviewSha256()).isEqualTo(result.recordSha256());
        assertThat(effective.path("use_review").asText()).isEqualTo("allowed");
        assertThat(effective.path("checks")).hasSize(1);
        assertThat(effective.path("last_verified_at").asText()).isEqualTo(request.path("check").path("checked_at").asText());
        var record = record(result.reviewId());
        assertThat(record.path("actor").asText()).isEqualTo("synthetic-first-reviewer");
        assertThat(Instant.parse(record.path("recorded_at").asText())).isBetween(before.minusMillis(1), Instant.now());
        assertThat(record.path("input_json").asText()).isEqualTo(request.toString());
        assertThat(view.checkRecordedAt().get(result.reviewId())).isEqualTo(Instant.parse(record.path("recorded_at").asText()));
        assertThat(extraction.importRun(run, archive, "synthetic-other-registrant").alreadyRegistered()).isTrue();
    }

    @Test
    void rightsOnlyRequiresNoRawAndDoesNotInventCheckOrSuccessTime() throws Exception {
        var source = fixtures.source(true); fixtures.register(source); var original = documents.document(version(source));
        Files.delete(root.resolve("synthetic-source.txt"));
        var result = review(request(source, 0, null, "restricted", "합성 사용 중단"), null, "synthetic-rights-reviewer");
        var effective = metadata(view(source));
        assertThat(result.reviewNo()).isEqualTo(1); assertThat(effective.path("use_review").asText()).isEqualTo("restricted");
        assertThat(effective.path("checks")).isEmpty();
        assertThat(effective.path("latest_check_attempt_at").isNull()).isTrue();
        assertThat(effective.path("last_verified_at").isNull()).isTrue();
        assertThat(effective.path("check_result").asText()).isEqualTo("unchecked");
        assertThat(checkCount(source)).isZero(); assertThat(documents.document(version(source))).isEqualTo(original);
    }

    @ParameterizedTest
    @ValueSource(strings = {"changed", "unreachable", "uncertain"})
    void failedCheckWithoutRawPreservesPreviousSuccessAndSqlLink(String result) throws Exception {
        var source = fixtures.source(false); fixtures.register(source);
        String success = document(source).path("checks").get(0).path("check_id").asText();
        String verifiedAt = document(source).path("last_verified_at").asText();
        Files.delete(root.resolve("synthetic-source.txt"));
        var request = request(source, 0, result, "allowed", "합성 실패 뒤 사용권 유지");
        var appended = review(request, null, "synthetic-failure-reviewer"); var effective = metadata(view(source));
        assertThat(effective.path("checks")).hasSize(2);
        assertThat(effective.path("last_verified_at").asText()).isEqualTo(verifiedAt);
        assertThat(effective.path("check_result").asText()).isEqualTo(result);
        var row = checkRow(appended.reviewId());
        assertThat(row.get("last_success_ref")).isEqualTo(success);
        assertThat(row.get("result")).isEqualTo(result); assertThat(row.get("note")).isEqualTo("합성 원문 확인 시험");
        assertThat(row.get("document_version_id")).isEqualTo(version(source));
        Instant checkedAt = jdbc.queryForObject("SELECT checked_at FROM source_checks WHERE check_id=?", (sql, index) -> sql.getTimestamp(1).toInstant(), appended.reviewId());
        assertThat(checkedAt).isEqualTo(Instant.parse(request.path("check").path("checked_at").asText()));
    }

    @Test
    void verifiedCheckRequiresOriginalRootAndRawHashBeforeAnyWrite() throws Exception {
        var source = fixtures.source(true); fixtures.register(source); var request = request(source, 0, "verified", "allowed", "합성 권한");
        sourceError("SOURCE_REVIEW_VALIDATION_ERROR", () -> review(request, null, "synthetic-reviewer"));
        Files.writeString(root.resolve("synthetic-source.txt"), "PRIVATE_TAMPERED_SOURCE");
        sourceError("SOURCE_REVIEW_VALIDATION_ERROR", () -> review(request, root, "synthetic-reviewer"));
        assertThat(reviewCount(source)).isZero(); assertThat(checkCount(source)).isZero();
    }

    @Test
    void newOperationalSuccessRemainsLastSuccessOfLaterFailedCheck() throws Exception {
        var source = fixtures.source(true); fixtures.register(source);
        var first = review(request(source, 0, "verified", "allowed", "합성 성공"), root, "synthetic-first");
        var failure = request(source, 1, "unreachable", "allowed", "합성 실패 뒤 유지");
        ((ObjectNode) failure.path("check")).put("checked_at", "2026-11-03T02:00:00Z");
        Files.delete(root.resolve("synthetic-source.txt"));
        var second = review(failure, null, "synthetic-second");
        assertThat(checkRow(second.reviewId()).get("last_success_ref")).isEqualTo(first.reviewId());
        assertThat(metadata(view(source)).path("last_verified_at").asText()).isEqualTo("2026-11-03T01:00:00.123456Z");
        assertThat(metadata(view(source)).path("checks")).hasSize(2);
    }

    @Test
    void exactOldBytesReplayPrecedesCasAndRawIoAndPreservesFirstActorTime() throws Exception {
        var source = fixtures.source(true); fixtures.register(source);
        var request = request(source, 0, "verified", "allowed", "합성 사용권");
        Path file = write(request); var first = reviews.review(file, root, "synthetic-first"); String record = record(first.reviewId()).toString();
        review(request(source, 1, null, "restricted", "합성 사용 중지"), null, "synthetic-second");
        Files.delete(root.resolve("synthetic-source.txt"));
        var replay = reviews.review(file, null, "synthetic-replay-actor");
        assertThat(replay.alreadyRecorded()).isTrue(); assertThat(replay.reviewNo()).isEqualTo(1);
        assertThat(replay.reviewId()).isEqualTo(first.reviewId()); assertThat(replay.recordSha256()).isEqualTo(first.recordSha256());
        assertThat(record(first.reviewId()).toString()).isEqualTo(record);
        assertThat(view(source).reviewNo()).isEqualTo(2); assertThat(reviewCount(source)).isEqualTo(2); assertThat(checkCount(source)).isEqualTo(1);
        Files.writeString(file, request + "\n");
        sourceError("SOURCE_REVIEW_CONFLICT", () -> reviews.review(file, null, "synthetic-replay-actor"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"no-op", "bad-review-id", "bad-version-id", "wrong-hash", "missing-expected", "null-expected", "negative-expected", "stale-expected"})
    void invalidOrStaleRequestCannotAutofillOrWrite(String invalid) throws Exception {
        var source = fixtures.source(true); fixtures.register(source);
        var request = request(source, 0, null, "restricted", "합성 권한 변경");
        switch (invalid) {
            case "no-op" -> request.put("use_review", "pending").put("use_note", "합성 미검토");
            case "bad-review-id" -> request.put("review_id", "not-a-uuid");
            case "bad-version-id" -> request.put("document_version_id", "not-a-uuid");
            case "wrong-hash" -> request.put("expected_text_sha256", "0".repeat(64));
            case "missing-expected" -> request.remove("expected_review_no");
            case "null-expected" -> request.putNull("expected_review_no");
            case "negative-expected" -> request.put("expected_review_no", -1);
            case "stale-expected" -> request.put("expected_review_no", 1);
        }
        assertThatThrownBy(() -> review(request, null, "synthetic-reviewer")).isInstanceOf(SourceReviewException.class);
        assertThat(reviewCount(source)).isZero(); assertThat(checkCount(source)).isZero();
    }

    @ParameterizedTest
    @ValueSource(booleans = {true, false})
    void simultaneousFirstAppendSerializesSameIdReplayAndDifferentIdConflict(boolean sameId) throws Exception {
        var source = fixtures.source(true); fixtures.register(source);
        var first = request(source, 0, null, "restricted", "합성 동시 결정");
        var second = first.deepCopy(); if (!sameId) second.put("review_id", UUID.randomUUID().toString());
        var files = List.of(write(first), write(second)); var barrier = new CyclicBarrier(2);
        try (var workers = Executors.newVirtualThreadPerTaskExecutor()) {
            var futures = files.stream().map(file -> workers.submit(() -> {
                barrier.await(5, TimeUnit.SECONDS);
                try { return reviews.review(file, null, "synthetic-concurrent").alreadyRecorded() ? "replay" : "insert"; }
                catch (SourceReviewException ex) { return ex.code(); }
            })).toList();
            assertThat(List.of(futures.getFirst().get(30, TimeUnit.SECONDS), futures.getLast().get(30, TimeUnit.SECONDS)))
                    .containsExactlyInAnyOrder("insert", sameId ? "replay" : "SOURCE_REVIEW_CONFLICT");
        }
        assertThat(reviewCount(source)).isEqualTo(1); assertThat(view(source).reviewNo()).isEqualTo(1); assertThat(checkCount(source)).isZero();
    }

    @ParameterizedTest
    @CsvSource({"true,note", "true,time", "true,result", "true,missing", "true,extra", "true,last-success",
            "false,note", "false,time", "false,result", "false,missing", "false,extra", "false,last-success"})
    void viewRejectsEveryOriginalPrefixAndOperationalSqlCheckMismatch(boolean originalPrefix, String alteration) throws Exception {
        var source = fixtures.source(!originalPrefix); fixtures.register(source);
        String id = originalPrefix ? document(source).path("checks").get(0).path("check_id").asText()
                : review(request(source, 0, "verified", "allowed", "합성 권한"), root, "synthetic-reviewer").reviewId();
        var row = checkRow(id); String extra = UUID.randomUUID().toString();
        try {
            switch (alteration) {
                case "note" -> jdbc.update("UPDATE source_checks SET note='PRIVATE_TAMPER' WHERE check_id=?", id);
                case "time" -> jdbc.update("UPDATE source_checks SET checked_at=TIMESTAMPADD(MICROSECOND,1,checked_at) WHERE check_id=?", id);
                case "result" -> jdbc.update("UPDATE source_checks SET result='uncertain' WHERE check_id=?", id);
                case "missing" -> jdbc.update("DELETE FROM source_checks WHERE check_id=?", id);
                case "extra" -> jdbc.update("INSERT INTO source_checks(check_id,document_version_id,checked_at,result,note) VALUES (?,?,?,'uncertain','합성 추가 행')",
                        extra, version(source), Timestamp.from(Instant.parse("2026-11-03T02:00:00Z")));
                case "last-success" -> jdbc.update("UPDATE source_checks SET last_success_ref=? WHERE check_id=?", id, id);
            }
            assertThatThrownBy(() -> view(source)).isInstanceOf(SourceReviewException.class).hasMessageNotContaining("PRIVATE_TAMPER");
        } finally {
            jdbc.update("DELETE FROM source_checks WHERE check_id=?", extra);
            if (alteration.equals("missing")) jdbc.update("INSERT INTO source_checks(check_id,document_version_id,checked_at,result,last_success_ref,note) VALUES (?,?,?,?,?,?)",
                    row.get("check_id"), row.get("document_version_id"), row.get("checked_at"), row.get("result"), row.get("last_success_ref"), row.get("note"));
            else jdbc.update("UPDATE source_checks SET checked_at=?,result=?,last_success_ref=?,note=? WHERE check_id=?",
                    row.get("checked_at"), row.get("result"), row.get("last_success_ref"), row.get("note"), id);
        }
        assertThat(view(source).reviewNo()).isEqualTo(originalPrefix ? 0 : 1);
    }

    @ParameterizedTest
    @ValueSource(strings = {"row-hash", "chain", "original"})
    void exactReplayStillRejectsRecordChainOrOriginalFingerprintTampering(String alteration) throws Exception {
        var source = fixtures.source(true); fixtures.register(source);
        Path file = write(request(source, 0, "verified", "allowed", "합성 권한"));
        var first = reviews.review(file, root, "synthetic-first");
        review(request(source, 1, null, "restricted", "합성 중단"), null, "synthetic-second");
        String record = jdbc.queryForObject("SELECT record_json FROM source_reviews WHERE review_id=?", String.class, first.reviewId());
        String original = documents.document(version(source)).metadata();
        try {
            if (alteration.equals("row-hash")) jdbc.update("UPDATE source_reviews SET record_sha256=REPEAT('0',64) WHERE review_id=?", first.reviewId());
            else if (alteration.equals("chain")) {
                var modified = (ObjectNode) mapper.readTree(record); modified.put("actor", "synthetic-forged");
                jdbc.update("UPDATE source_reviews SET record_json=?,record_sha256=? WHERE review_id=?", modified.toString(), sha(modified.toString()), first.reviewId());
            } else {
                var modified = (ObjectNode) mapper.readTree(original); ((ObjectNode) modified.path("document")).put("title", "합성 변조 원본");
                jdbc.update("UPDATE document_versions SET metadata_json=? WHERE document_version_id=?", modified.toString(), version(source));
            }
            assertThatThrownBy(() -> reviews.review(file, null, "synthetic-replayer")).isInstanceOf(SourceReviewException.class);
        } finally {
            jdbc.update("UPDATE source_reviews SET record_json=?,record_sha256=? WHERE review_id=?", record, first.recordSha256(), first.reviewId());
            jdbc.update("UPDATE document_versions SET metadata_json=? WHERE document_version_id=?", original, version(source));
        }
        assertThat(reviews.review(file, null, "synthetic-replayer").alreadyRecorded()).isTrue();
    }

    @ParameterizedTest
    @ValueSource(ints = {0, 1})
    void missingRightsOnlyTailBlocksReadReplayAppendAndNewPublication(int preceding) throws Exception {
        var input = fixtures.human(false); importInput(input);
        var original = documents.document(version(input));
        var approved = publication.execute(decision(event(input), "approve", 1), root, "synthetic-approver");
        if (preceding == 1) review(request(input, 0, null, "allowed", "합성 추가 사용권 선언"), null, "synthetic-first");
        Path file = write(request(input, preceding, null, "restricted", "합성 사용 제한"));
        var restricted = reviews.review(file, null, "synthetic-rights-reviewer");
        var before = view(input); long checks = checkCount(input);
        var row = jdbc.queryForMap("SELECT * FROM source_reviews WHERE review_id=?", restricted.reviewId());
        jdbc.update("DELETE FROM source_reviews WHERE review_id=?", restricted.reviewId());
        try {
            assertThat(checkCount(input)).isEqualTo(checks);
            assertThat(documents.document(version(input))).isEqualTo(original);
            assertThatThrownBy(() -> view(input)).isInstanceOf(SourceReviewException.class);
            assertThatThrownBy(() -> new TransactionTemplate(manager).execute(status -> {
                sourceReviews.lockView(before); return null;
            })).isInstanceOf(SourceReviewException.class);
            assertThatThrownBy(() -> reviews.review(file, null, "synthetic-replay")).isInstanceOf(SourceReviewException.class);
            assertThatThrownBy(() -> review(request(input, preceding, null, "allowed", "합성 새 요청"), null, "synthetic-new"))
                    .isInstanceOf(SourceReviewException.class);
            var publish = publish(input, List.of(approved.revisionId()));
            publish.put("action", "preview");
            publicationError("PUBLICATION_CONFLICT", () -> publication.execute(command(publish), root, "synthetic-publisher"));
            publish.put("action", "publish");
            publicationError("PUBLICATION_CONFLICT", () -> publication.execute(command(publish), root, "synthetic-publisher"));
            publication.execute(decision(event(input), "reject", 2), null, "synthetic-reviewer");
            publicationError("PUBLICATION_CONFLICT", () -> publication.execute(decision(event(input), "approve", 3), root, "synthetic-approver"));
            assertThat(reviewCount(input)).isEqualTo(preceding);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM snapshots WHERE case_id=?", Long.class, publish.path("case_id").asText())).isZero();
        } finally {
            jdbc.update("INSERT INTO source_reviews(review_id,document_version_id,review_no,input_sha256,record_json,record_sha256) VALUES (?,?,?,?,?,?)",
                    row.get("review_id"), row.get("document_version_id"), row.get("review_no"), row.get("input_sha256"), row.get("record_json"), row.get("record_sha256"));
        }
        assertThat(view(input).reviewNo()).isEqualTo(preceding + 1);
    }

    @ParameterizedTest
    @ValueSource(strings = {"source_reviews", "document_versions"})
    void lateSqlInsertOrAnchorFailureRollsBackReviewCheckAndAnchor(String table) throws Exception {
        var source = fixtures.source(true); fixtures.register(source); var original = documents.document(version(source));
        String constraint = "source_review_test_" + UUID.randomUUID().toString().replace("-", "");
        jdbc.execute("ALTER TABLE " + table + " ADD CONSTRAINT " + constraint + " CHECK(document_version_id <> '" + version(source) + "'"
                + (table.equals("document_versions") ? " OR source_review_no=0" : "") + ")");
        try {
            assertThatThrownBy(() -> review(request(source, 0, "verified", "allowed", "합성 권한"), root, "synthetic-reviewer"))
                    .isInstanceOf(SourceReviewException.class).hasMessageNotContaining(constraint).hasMessageNotContaining(version(source));
            assertThat(reviewCount(source)).isZero(); assertThat(checkCount(source)).isZero();
            assertThat(documents.document(version(source))).isEqualTo(original);
            assertThat(view(source).reviewNo()).isZero(); assertThat(view(source).reviewSha256()).isNull();
        } finally { jdbc.execute("ALTER TABLE " + table + " DROP CHECK " + constraint); }
        assertThat(review(request(source, 0, "verified", "allowed", "합성 권한"), root, "synthetic-reviewer").reviewNo()).isEqualTo(1);
    }

    @ParameterizedTest
    @ValueSource(strings = {"source_review_no=source_review_no+1", "source_review_sha256=REPEAT('0',64)"})
    void changedParentAnchorRejectsOtherwiseCompleteHistory(String alteration) throws Exception {
        var source = fixtures.source(false); fixtures.register(source);
        var first = review(request(source, 0, null, "restricted", "합성 사용 제한"), null, "synthetic-reviewer");
        try {
            jdbc.update("UPDATE document_versions SET " + alteration + " WHERE document_version_id=?", version(source));
            assertThatThrownBy(() -> view(source)).isInstanceOf(SourceReviewException.class);
        } finally {
            jdbc.update("UPDATE document_versions SET source_review_no=?,source_review_sha256=? WHERE document_version_id=?",
                    first.reviewNo(), first.recordSha256(), version(source));
        }
        assertThat(view(source).reviewSha256()).isEqualTo(first.recordSha256());
    }

    @Test
    void d05AndHumanHandoffKeepFullOriginalMetadataAfterOperationalUpdates() throws Exception {
        var source = fixtures.source(false); fixtures.register(source);
        String run = UUID.randomUUID().toString(); Path archive = fixtures.archive(source, run);
        extraction.importRun(run, archive, "synthetic-registrant");
        var handoff = fixtures.handoff(source, run, archive);
        var imported = handoffs.importFile(handoff.file(), root, handoff.directory(), "synthetic-handoff-importer");
        var reference = ArgumentCaptor.forClass(ExtractionRunRepository.Reference.class);
        verify(extractionRuns, atLeastOnce()).checkReference(reference.capture());
        assertThat(reference.getValue().documentRowSha256()).isNotNull();
        var original = documents.document(version(source)); var runBefore = runRow(run);
        var filesBefore = fileHashes(archive); var handoffBefore = fileHashes(handoff.image());
        var rights = review(request(source, 0, null, "allowed", "합성 운영 사용권 보완"), null, "synthetic-rights-reviewer");
        review(request(source, 1, "unreachable", "allowed", "합성 확인 실패 뒤 유지"), null, "synthetic-check-reviewer");
        assertThat(rights.reviewNo()).isEqualTo(1); assertThat(view(source).reviewNo()).isEqualTo(2);
        new TransactionTemplate(manager).execute(status -> { extractionRuns.checkReference(reference.getValue()); return null; });
        assertThat(extraction.importRun(run, archive, "synthetic-replay").alreadyRegistered()).isTrue();
        var replay = handoffs.importFile(handoff.file(), root, handoff.directory(), "synthetic-replay");
        assertThat(replay.alreadyImported()).isTrue(); assertThat(replay.revisionIds()).isEqualTo(imported.revisionIds());
        assertThat(documents.document(version(source))).isEqualTo(original); assertThat(runRow(run)).isEqualTo(runBefore);
        assertThat(fileHashes(archive)).isEqualTo(filesBefore); assertThat(fileHashes(handoff.image())).isEqualTo(handoffBefore);
        String event = jdbc.queryForObject("SELECT event_id FROM event_revisions WHERE revision_id=?", String.class, imported.revisionIds().getFirst());
        var approved = publication.execute(decision(event, "approve", 1), root, "synthetic-approver");
        assertThat(jdbc.queryForObject("SELECT review_status FROM event_revisions WHERE revision_id=?", String.class, approved.revisionId())).isEqualTo("approved");
    }

    @Test
    void pendingOriginalHumanRevisionApprovesOnlyAfterDeclaredVerifiedAllowedOperation() throws Exception {
        var input = fixtures.human(true); importInput(input); String original = payloadForEvent(event(input));
        publicationError("PUBLICATION_VALIDATION_ERROR", () -> publication.execute(decision(event(input), "approve", 1), root, "synthetic-approver"));
        review(request(input, 0, "verified", "allowed", "합성 원문·권한 확인"), root, "synthetic-source-reviewer");
        var approved = publication.execute(decision(event(input), "approve", 1), root, "synthetic-approver");
        assertThat(jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE event_id=? AND revision_no=1", String.class, event(input))).isEqualTo(original);
        assertThat(jdbc.queryForObject("SELECT review_status FROM event_revisions WHERE revision_id=?", String.class, approved.revisionId())).isEqualTo("approved");
        assertThat(mapper.readTree(documents.document(version(input)).metadata()).path("document").path("use_review").asText()).isEqualTo("pending");
    }

    @Test
    void sourceVerificationNeverPromotesRawAiDraftToDirectApproval() throws Exception {
        var source = fixtures.source(false); fixtures.register(source);
        String run = UUID.randomUUID().toString(); Path archive = fixtures.archive(source, run);
        extraction.importRun(run, archive, "synthetic-registrant");
        var imported = importer.importBatch(reader.read(fixtures.extraction.draft(source, run, archive), root), "synthetic-draft-importer");
        review(request(source, 0, "verified", "allowed", "합성 운영 확인"), root, "synthetic-source-reviewer");
        String event = jdbc.queryForObject("SELECT event_id FROM event_revisions WHERE revision_id=?", String.class, imported.revisionIds().getFirst());
        publicationError("PUBLICATION_VALIDATION_ERROR", () -> publication.execute(decision(event, "approve", 1), root, "synthetic-approver"));
        assertThat(jdbc.queryForObject("SELECT review_status FROM event_revisions WHERE revision_id=?", String.class, imported.revisionIds().getFirst())).isEqualTo("draft");
    }

    @Test
    void restrictedOperationalRightsBlockNewApprovalPreviewAndPublication() throws Exception {
        var input = fixtures.human(false); importInput(input);
        var approved = publication.execute(decision(event(input), "approve", 1), root, "synthetic-approver");
        review(request(input, 0, null, "restricted", "합성 권한 제한"), null, "synthetic-rights-reviewer");
        publication.execute(decision(event(input), "reject", 2), null, "synthetic-reviewer");
        publicationError("PUBLICATION_VALIDATION_ERROR", () -> publication.execute(decision(event(input), "approve", 3), root, "synthetic-approver"));
        // 승인본의 현재성 제약과 분리하여 운영 권한 자체가 새 공개를 막는지 확인한다.
        var other = fixtures.human(false); importInput(other);
        var otherApproved = publication.execute(decision(event(other), "approve", 1), root, "synthetic-approver");
        var request = publish(other, List.of(otherApproved.revisionId()));
        review(request(other, 0, null, "restricted", "합성 권한 제한"), null, "synthetic-rights-reviewer");
        publicationError("PUBLICATION_VALIDATION_ERROR", () -> publication.execute(command(request), root, "synthetic-publisher"));
        request.put("action", "preview");
        publicationError("PUBLICATION_VALIDATION_ERROR", () -> publication.execute(command(request), root, "synthetic-publisher"));
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM snapshots WHERE case_id=?", Long.class, request.path("case_id").asText())).isZero();
    }

    @Test
    void lateBackdatedCheckIsCurrentStateButCannotVerifyHistoricalReplay() throws Exception {
        var input = fixtures.human(true); importInput(input);
        var request = request(input, 0, "verified", "allowed", "합성 뒤늦은 확인 등록");
        ((ObjectNode) request.path("check")).put("checked_at", "2026-11-02T03:00:00Z");
        var append = review(request, root, "synthetic-source-reviewer");
        assertThat(Instant.parse(record(append.reviewId()).path("recorded_at").asText())).isAfter(Instant.parse("2026-11-03T00:00:00Z"));
        var approved = publication.execute(decision(event(input), "approve", 1), root, "synthetic-approver");
        var historical = publish(input, List.of(approved.revisionId()));
        historical.put("history_fidelity", "verified_snapshot");
        publicationError("PUBLICATION_VALIDATION_ERROR", () -> publication.execute(command(historical), root, "synthetic-publisher"));
        historical.put("history_fidelity", "reconstructed");
        var published = publication.execute(command(historical), root, "synthetic-publisher");
        var snapshot = mapper.readTree(canonical(published.snapshotId())); var source = snapshot.path("sources").get(0);
        assertThat(source.path("checks")).isEmpty(); assertThat(source.path("last_verified_at").isNull()).isTrue();
        assertThat(source.path("check_result").asText()).isEqualTo("unchecked");
        assertThat(source.path("current_last_verified_at").asText()).isEqualTo("2026-11-02T03:00:00Z");
        assertThat(source.path("current_check_result").asText()).isEqualTo("verified");
    }

    @Test
    void failedCurrentCheckKeepsSuccessAndOldSnapshotExportRollbackBytes() throws Exception {
        var input = fixtures.human(false); importInput(input);
        var approved = publication.execute(decision(event(input), "approve", 1), root, "synthetic-approver");
        var request = publish(input, List.of(approved.revisionId()));
        var first = publication.execute(command(request), root, "synthetic-publisher"); String canonical = canonical(first.snapshotId());
        Path exports = Files.createDirectory(root.resolve("exports"));
        var export = exporter.export(UUID.fromString(first.snapshotId()), exports); byte[] bytes = Files.readAllBytes(exports.resolve(export.fileName()));
        review(request(input, 0, "unreachable", "allowed", "합성 후속 확인 실패"), null, "synthetic-source-reviewer");
        request.put("expected_head_version", 0); var second = publication.execute(command(request), root, "synthetic-publisher");
        var current = mapper.readTree(canonical(second.snapshotId())).path("sources").get(0);
        assertThat(current.path("current_last_verified_at").asText()).isEqualTo(document(input).path("last_verified_at").asText());
        assertThat(current.path("current_check_result").asText()).isEqualTo("unreachable");
        review(request(input, 1, null, "restricted", "합성 사용 중지"), null, "synthetic-rights-reviewer");
        var rollback = new PublicationCommand.Rollback("publication-command-v1", "rollback", "합성 원본 복구", "replay",
                UUID.fromString(request.path("case_id").asText()), UUID.fromString(first.snapshotId()), 1L);
        assertThat(publication.execute(rollback, null, "synthetic-publisher").snapshotId()).isEqualTo(first.snapshotId());
        assertThat(canonical(first.snapshotId())).isEqualTo(canonical);
        assertThat(exporter.export(UUID.fromString(first.snapshotId()), exports).alreadyExported()).isTrue();
        assertThat(Files.readAllBytes(exports.resolve(export.fileName()))).isEqualTo(bytes);
    }

    @Test
    void multipleEventsSharingVersionUseOneSourceViewForValidationAndSnapshot() throws Exception {
        var input = fixtures.human(false);
        var second = ((ObjectNode) input.path("events").get(0)).deepCopy(); String secondId = UUID.randomUUID().toString();
        second.put("event_id", secondId); ((ObjectNode) second.path("revision")).put("event_id", secondId).put("revision_id", UUID.randomUUID().toString());
        input.withArray("events").add(second); importInput(input);
        var firstApproved = publication.execute(decision(event(input), "approve", 1), root, "synthetic-approver");
        var secondApproved = publication.execute(decision(secondId, "approve", 1), root, "synthetic-approver");
        review(request(input, 0, null, "allowed", "합성 공통 사용권"), null, "synthetic-rights-reviewer");
        clearInvocations(sourceReviews);
        var published = publication.execute(command(publish(input, List.of(firstApproved.revisionId(), secondApproved.revisionId()))), root, "synthetic-publisher");
        verify(sourceReviews, times(1)).view(argThat(doc -> doc.versionId().equals(version(input))));
        verify(sourceReviews, times(1)).lockView(argThat(view -> view.original().versionId().equals(version(input)) && view.reviewNo() == 1));
        var snapshot = mapper.readTree(canonical(published.snapshotId()));
        assertThat(snapshot.path("event_public_payloads")).hasSize(2); assertThat(snapshot.path("sources")).hasSize(1);
    }

    @ParameterizedTest
    @ValueSource(strings = {"approve", "publish", "preview"})
    void sourceWriterBetweenValidationAndFinalLockRejectsStaleOperation(String action) throws Exception {
        var input = fixtures.human(false); importInput(input);
        PublicationCommand operation;
        if (action.equals("approve")) operation = decision(event(input), "approve", 1);
        else {
            var approved = publication.execute(decision(event(input), "approve", 1), root, "synthetic-approver");
            var request = publish(input, List.of(approved.revisionId())); request.put("action", action); operation = command(request);
        }
        var counts = businessCounts(); var changed = new AtomicBoolean();
        org.mockito.stubbing.Answer<Object> appendBeforeLock = invocation -> {
            if (changed.compareAndSet(false, true)) review(request(input, 0, null, "restricted", "합성 경합 중 사용 중지"), null, "synthetic-concurrent-source-writer");
            return invocation.callRealMethod();
        };
        if (action.equals("preview")) doAnswer(appendBeforeLock).when(sourceReviews).lockView(any(SourceView.class));
        else doAnswer(appendBeforeLock).when(documents).lockDocument(any(PublicationRepository.Document.class));
        publicationError("PUBLICATION_CONFLICT", () -> publication.execute(operation, root, "synthetic-publisher"));
        assertThat(changed).isTrue(); assertThat(businessCounts()).isEqualTo(counts);
        assertThat(view(input).reviewNo()).isEqualTo(1); assertThat(metadata(view(input)).path("use_review").asText()).isEqualTo("restricted");
    }

    @Test
    void finalLockUsesCurrentReadForFirstRightsOnlyAppendDespiteRrSnapshot() throws Exception {
        var source = fixtures.source(true); fixtures.register(source); var oldView = view(source);
        var transaction = new TransactionTemplate(manager);
        transaction.executeWithoutResult(status -> {
            jdbc.queryForObject("SELECT COUNT(*) FROM source_reviews WHERE document_version_id=?", Long.class, version(source));
            try (var worker = Executors.newVirtualThreadPerTaskExecutor()) {
                worker.submit(() -> review(request(source, 0, null, "restricted", "합성 현재 읽기 경합"), null, "synthetic-concurrent-source-writer")).get(20, TimeUnit.SECONDS);
            } catch (Exception ex) { throw new AssertionError(ex); }
            assertThatThrownBy(() -> sourceReviews.lockView(oldView)).isInstanceOf(SourceReviewException.class);
        });
        assertThat(view(source).reviewNo()).isEqualTo(1);
    }

    @Test
    void readOnlyViewKeepsRecordsAndChecksInOneSnapshotDuringConcurrentAppend() throws Exception {
        var source = fixtures.source(true); fixtures.register(source); var changed = new AtomicBoolean();
        doAnswer(invocation -> {
            var captured = invocation.callRealMethod();
            PublicationRepository.Document original = invocation.getArgument(0);
            if (original.versionId().equals(version(source)) && changed.compareAndSet(false, true)) {
                try (var worker = Executors.newVirtualThreadPerTaskExecutor()) {
                    worker.submit(() -> review(request(source, 0, "verified", "allowed", "합성 동시 확인"), root, "synthetic-concurrent-source-writer")).get(20, TimeUnit.SECONDS);
                }
            }
            return captured;
        }).when(sourceState).view(any(PublicationRepository.Document.class), anyList());
        var consistent = view(source);
        assertThat(changed).isTrue(); assertThat(consistent.reviewNo()).isZero();
        assertThat(metadata(consistent).path("checks")).isEmpty();
        assertThat(view(source).reviewNo()).isEqualTo(1); assertThat(checkCount(source)).isEqualTo(1);
    }

    private void importInput(ObjectNode input) throws Exception { importer.importBatch(reader.read(write(input), root), "synthetic-importer"); }
    private String payloadForEvent(String event) { return jdbc.queryForObject("SELECT r.payload_json FROM events e JOIN event_revisions r ON r.revision_id=e.current_review_revision_id WHERE e.event_id=?", String.class, event); }
    private PublicationCommand.Decision decision(String event, String action, long expected) throws Exception {
        var evidence = new ArrayList<String>(); mapper.readTree(payloadForEvent(event)).path("evidence").forEach(item -> evidence.add(item.path("evidence_id").asText()));
        return new PublicationCommand.Decision("publication-command-v1", action, "합성 원문 대조 결정", UUID.fromString(event), expected, evidence);
    }
    private ObjectNode publish(ObjectNode input, List<String> revisions) throws Exception {
        var request = (ObjectNode) mapper.readTree(Path.of("examples/publish.json").toFile()); String caseId = UUID.randomUUID().toString(); ownedCases.add(caseId);
        request.put("mode", "replay").put("case_id", caseId).put("anchor_date", "2026-11-03")
                .put("reference_instant", "2026-11-03T00:00:00Z").put("knowledge_cutoff", "2026-11-03T00:00:00Z").put("history_fidelity", "reconstructed");
        String area = input.path("events").get(0).path("area_id").asText(); ((ObjectNode) request.path("area")).put("area_id", area);
        for (var point : request.path("points")) ((ObjectNode) point).put("point_id", UUID.randomUUID().toString()).put("area_id", area);
        var ids = request.putArray("revision_ids"); revisions.forEach(ids::add); request.putNull("expected_head_version"); return request;
    }
    private PublicationCommand command(ObjectNode input) throws Exception { return commands.read(write(input)); }
    private String canonical(String id) { return jdbc.queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id=?", String.class, id); }
    private Map<String, String> fileHashes(Path directory) throws Exception {
        var files = new LinkedHashMap<String, String>();
        try (var stream = Files.walk(directory)) {
            for (Path path : stream.filter(Files::isRegularFile).sorted().toList())
                files.put(directory.relativize(path).toString(), ReviewedImportReader.sha256(Files.readAllBytes(path)));
        }
        return files;
    }
    private void publicationError(String code, org.assertj.core.api.ThrowableAssert.ThrowingCallable action) {
        assertThatThrownBy(action).isInstanceOfSatisfying(PublicationException.class, ex -> assertThat(ex.code()).isEqualTo(code));
    }

    private ObjectNode request(ObjectNode source, long expected, String check, String rights, String note) {
        var request = mapper.createObjectNode().put("schema_version", "source-review-v1").put("review_id", UUID.randomUUID().toString())
                .put("document_version_id", version(source)).put("expected_review_no", expected)
                .put("expected_text_sha256", document(source).path("text_sha256").asText());
        if (check == null) request.putNull("check");
        else request.putObject("check").put("checked_at", "2026-11-03T01:00:00.123456Z").put("result", check)
                .put("text_sha256", document(source).path("text_sha256").asText()).put("note", "합성 원문 확인 시험");
        return request.put("use_review", rights).put("use_note", note).put("reason", "합성 확인·권한 결정");
    }

    private Path write(ObjectNode request) throws Exception { return Files.writeString(root.resolve(UUID.randomUUID() + ".json"), request.toString()); }
    private SourceReviewService.Result review(ObjectNode request, Path rawRoot, String actor) throws Exception { return reviews.review(write(request), rawRoot, actor); }
    private SourceView view(ObjectNode source) { return sourceReviews.view(documents.document(version(source))); }
    private JsonNode metadata(SourceView view) throws Exception { return mapper.readTree(view.effectiveMetadata()).path("document"); }
    private JsonNode record(String id) throws Exception { return mapper.readTree(jdbc.queryForObject("SELECT record_json FROM source_reviews WHERE review_id=?", String.class, id)); }
    private Map<String, Object> checkRow(String id) { return jdbc.queryForMap("SELECT * FROM source_checks WHERE check_id=?", id); }
    private Map<String, Object> runRow(String id) { return jdbc.queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", id); }
    private long reviewCount(ObjectNode source) { return jdbc.queryForObject("SELECT COUNT(*) FROM source_reviews WHERE document_version_id=?", Long.class, version(source)); }
    private long checkCount(ObjectNode source) { return jdbc.queryForObject("SELECT COUNT(*) FROM source_checks WHERE document_version_id=?", Long.class, version(source)); }
    private List<Long> businessCounts() { return List.of("events", "event_revisions", "snapshots", "publication_heads").stream()
            .map(table -> jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Long.class)).toList(); }
    private String sha(String json) { return ReviewedImportReader.sha256(json.getBytes(StandardCharsets.UTF_8)); }
    private void sourceError(String code, org.assertj.core.api.ThrowableAssert.ThrowingCallable action) {
        assertThatThrownBy(action).isInstanceOfSatisfying(SourceReviewException.class, ex -> assertThat(ex.code()).isEqualTo(code));
    }
}
