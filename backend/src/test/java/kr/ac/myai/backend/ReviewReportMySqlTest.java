package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.review.ReviewReportService;
import kr.ac.myai.backend.service.*;
import org.junit.jupiter.api.*;
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

import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

@SpringBootTest
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class ReviewReportMySqlTest {
    @Autowired ReviewReportService reports;
    @Autowired ReviewedImportReader reader;
    @Autowired ReviewedImportService importer;
    @Autowired ExtractionImportService extractions;
    @Autowired PublicationService publication;
    @Autowired PublicationCommandReader commands;
    @Autowired HumanHandoffImportService handoffs;
    @Autowired SourceReviewService sourceReviews;
    @Autowired JdbcTemplate jdbc;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    SourceReviewFixtures fixtures;

    @DynamicPropertySource
    static void python(DynamicPropertyRegistry registry) {
        registry.add("app.calculation.workdir", () -> PythonProbe.REPO.toString());
        registry.add("app.calculation.python-executable", () -> PythonProbe.PYTHON);
    }

    @BeforeEach void setup() { fixtures = new SourceReviewFixtures(root, jdbc, reader, importer); }
    @AfterEach void cleanup() throws Exception { ExtractionArchiveReaderTest.unseal(root); }

    @Test
    void chunkedCyclesRegisterAndExposeEverySubrequestThroughHumanHandoffReport() throws Exception {
        var source = fixtures.source(false);
        ChunkedArchiveFixtures.enlarge(SourceReviewFixtures.document(source), "block_index");
        fixtures.register(source); String run = UUID.randomUUID().toString();
        Path prepared = fixtures.archive(source, run);
        Path archive = ChunkedArchiveFixtures.archive(root.resolve("chunked"), prepared.resolve(run).resolve("input.json"), run,
                SourceReviewFixtures.document(source).path("preprocessing_version").asText(), "retry");
        var first = extractions.importRun(run, archive, "synthetic-registrant");
        var reused = extractions.importRun(run, archive, "synthetic-registrant");
        assertThat(first.alreadyRegistered()).isFalse(); assertThat(reused.alreadyRegistered()).isTrue();
        assertThat(reused.receiptSha256()).isEqualTo(first.receiptSha256());
        var handoff = fixtures.handoff(source, run, archive);
        handoffs.importFile(handoff.file(), root, handoff.directory(), "synthetic-reviewer");
        var before = database(); var files = files();
        var report = reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null);
        var extraction = byRun(report, run); var receipt = extraction.path("receipt"); var artifacts = extraction.path("artifacts");
        assertThat(extraction.path("validation").path("status").asText()).isEqualTo("valid");
        assertThat(extraction.path("database").path("attempts").asInt()).isEqualTo(2);
        assertThat(extraction.path("database").path("output_sha256").asText()).isEqualTo(artifacts.path("attempt-2.output").path("sha256").asText());
        assertThat(artifacts.size()).isEqualTo(3 + 2 * 2 + 4 * receipt.path("total_calls").asInt());
        for (String name : List.of("chunk-plan.json", "attempt-1.prompt", "attempt-1.output", "attempt-2.output",
                "attempt-1-chunk-000001.prompt", "attempt-1-chunk-000001.output", "attempt-1-chunk-000001.response", "attempt-1-chunk-000001.exchange",
                "attempt-2-chunk-000002.prompt", "attempt-2-chunk-000002.output", "attempt-2-chunk-000002.response", "attempt-2-chunk-000002.exchange"))
            assertThat(artifacts.path(name).path("validation").path("status").asText()).as(name).isEqualTo("valid");
        assertThat(artifacts.path("attempt-1.output").path("size").asInt(-1)).isZero();
        assertThat(report.path("events")).hasSize(1);
        assertThat(report.path("events").get(0).path("revisions").get(0).path("handoff_validation").path("status").asText()).isEqualTo("valid");
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
    }

    @Test
    void oversizedChunkPlanAndSubrequestFailBeforePythonVerificationWithoutWrites() throws Exception {
        for (String name : List.of("chunk-plan.json", "attempt-1-chunk-000001.response")) {
            var source = fixtures.source(false); ChunkedArchiveFixtures.enlarge(SourceReviewFixtures.document(source), "block_index");
            fixtures.register(source); String run = UUID.randomUUID().toString(); Path prepared = fixtures.archive(source, run);
            Path archive = ChunkedArchiveFixtures.archive(root.resolve(run), prepared.resolve(run).resolve("input.json"), run,
                    SourceReviewFixtures.document(source).path("preprocessing_version").asText(), "success");
            extractions.importRun(run, archive, "synthetic-registrant");
            Path directory = Path.of(jdbc.queryForObject("SELECT raw_ref FROM extraction_runs WHERE run_id=?", String.class, run));
            Path file = directory.resolve(name); file.toFile().setWritable(true, true);
            Files.writeString(file, "x".repeat(8 * 1024 * 1024 + 1)); file.toFile().setWritable(false, false);
            var before = database(); var files = files();
            assertThatThrownBy(() -> reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null))
                    .isInstanceOfSatisfying(PublicationException.class, ex -> assertThat(ex.code()).isEqualTo("REPORT_TOO_LARGE"));
            assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
        }
    }

    @Test
    void missingChunkSubrequestIsInvalidAndPreservesDatabaseAndRemainingFiles() throws Exception {
        var source = fixtures.source(false); ChunkedArchiveFixtures.enlarge(SourceReviewFixtures.document(source), "block_index");
        fixtures.register(source); String run = UUID.randomUUID().toString(); Path prepared = fixtures.archive(source, run);
        Path archive = ChunkedArchiveFixtures.archive(root.resolve("missing-chunk"), prepared.resolve(run).resolve("input.json"), run,
                SourceReviewFixtures.document(source).path("preprocessing_version").asText(), "success");
        extractions.importRun(run, archive, "synthetic-registrant");
        Path directory = Path.of(jdbc.queryForObject("SELECT raw_ref FROM extraction_runs WHERE run_id=?", String.class, run));
        directory.toFile().setWritable(true, true); Files.delete(directory.resolve("attempt-1-chunk-000001.response")); directory.toFile().setWritable(false, false);
        var before = database(); var files = files();
        var extraction = byRun(reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null), run);
        assertThat(extraction.path("archive_validation").path("status").asText()).isEqualTo("invalid");
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
    }

    @Test
    void sourceOnlyPreservesPendingOriginalAndSeparatesInspectionFromCapture() throws Exception {
        var source = fixtures.source(true); fixtures.register(source);
        var before = database(); var files = files();
        var report = reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null);
        assertThat(report.path("format_version").asText()).isEqualTo("local-review-report-v1");
        assertThat(report.path("documents")).hasSize(1);
        var doc = report.path("documents").get(0);
        assertThat(doc.path("original").path("use_review").asText()).isEqualTo("pending");
        assertThat(doc.path("raw_asset").path("text").asText()).contains("공사");
        assertThat(doc.path("validation").path("status").asText()).isEqualTo("valid");
        assertThat(report.path("capture").path("isolation").asText()).isEqualTo("REPEATABLE_READ");
        assertThat(report.path("capture").path("validation_same_snapshot").asBoolean(true)).isFalse();
        assertThat(report.path("preview").path("status").asText()).isEqualTo("not_requested");
        assertThat(report.path("events")).isEmpty(); assertThat(report.path("extractions")).isEmpty();
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void twentyMiBRawAssetIsFullyEmbeddedAsTextOrBase64WithoutWrites(boolean binary) throws Exception {
        var source = fixtures.source(true);
        byte[] bytes = new byte[20 * 1024 * 1024]; Arrays.fill(bytes, binary ? (byte) 0xff : (byte) 'x');
        Files.write(root.resolve("synthetic-source.txt"), bytes);
        SourceReviewFixtures.document(source).put("raw_sha256", ReviewedImportReader.sha256(bytes));
        fixtures.register(source); var before = database(); var files = files();
        var document = reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null).path("documents").get(0);
        var raw = document.path("raw_asset");
        assertThat(document.path("validation").path("status").asText()).isEqualTo("valid");
        assertThat(raw.path("validation").path("status").asText()).isEqualTo("valid");
        assertThat(raw.path("size").asInt()).isEqualTo(20 * 1024 * 1024);
        assertThat(raw.path("encoding").asText()).isEqualTo(binary ? "base64" : "utf-8");
        byte[] embedded = binary ? Base64.getDecoder().decode(raw.path("base64").asText())
                : raw.path("text").asText().getBytes(java.nio.charset.StandardCharsets.UTF_8);
        assertThat(embedded).isEqualTo(bytes);
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
    }

    @Test
    void largerRawAssetSurvivesSourceReviewApprovalPreviewPublicationAndReport() throws Exception {
        var input = fixtures.human(true);
        byte[] bytes = new byte[8 * 1024 * 1024 + 1]; Arrays.fill(bytes, (byte) 'x');
        Files.write(root.resolve("synthetic-source.txt"), bytes);
        var document = SourceReviewFixtures.document(input); document.put("raw_sha256", ReviewedImportReader.sha256(bytes));
        importInput(input);
        var review = mapper.createObjectNode().put("schema_version", "source-review-v1").put("review_id", UUID.randomUUID().toString())
                .put("document_version_id", SourceReviewFixtures.version(input)).put("expected_review_no", 0)
                .put("expected_text_sha256", document.path("text_sha256").asText())
                .put("use_review", "allowed").put("use_note", "합성 원문 크기 경계 시험").put("reason", "합성 확인·권한 결정");
        review.putObject("check").put("checked_at", "2026-11-02T02:00:00Z").put("result", "verified")
                .put("text_sha256", document.path("text_sha256").asText()).put("note", "합성 원문 확인 시험");
        assertThat(sourceReviews.review(write(review), root, "synthetic-source-reviewer").reviewNo()).isEqualTo(1);
        var approved = approve(input, 1);
        var request = publish(input, approved.revisionId()); request.put("action", "preview");
        Path preview = write(request); var beforePreview = database();
        var previewReport = reports.build(UUID.fromString(SourceReviewFixtures.version(input)), root, preview);
        assertThat(previewReport.path("preview").path("status").asText()).isEqualTo("valid");
        assertThat(database()).isEqualTo(beforePreview);
        request.put("action", "publish");
        var published = publication.execute(commands.read(write(request)), root, "synthetic-publisher");
        var before = database(); var files = files();
        var report = reports.build(UUID.fromString(SourceReviewFixtures.version(input)), root, null);
        var savedDocument = report.path("documents").get(0);
        assertThat(savedDocument.path("original").path("use_review").asText()).isEqualTo("pending");
        assertThat(savedDocument.path("source_reviews")).hasSize(1);
        assertThat(savedDocument.path("raw_asset").path("text").asText().getBytes(java.nio.charset.StandardCharsets.UTF_8)).isEqualTo(bytes);
        assertThat(report.path("publication").path("memberships").get(0).path("snapshot_id").asText()).isEqualTo(published.snapshotId());
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
    }

    @Test
    void allFailedAndLegacyRunsRemainVisibleWithExactBinaryOutputAndNoFreezeWrites() throws Exception {
        var source = fixtures.source(false); fixtures.register(source);
        String good = UUID.randomUUID().toString(), failed = UUID.randomUUID().toString(), legacy = UUID.randomUUID().toString();
        extractions.importRun(good, fixtures.archive(source, good), "synthetic-report-registrant");
        extractions.importRun(failed, fixtures.extraction.archive(source, failed, true), "synthetic-report-registrant");
        jdbc.update("INSERT INTO extraction_runs(run_id,document_version_id,input_sha256,provider,model,prompt_version,status) VALUES (?,?,?,'legacy','legacy','legacy','failed')",
                legacy, SourceReviewFixtures.version(source), "1".repeat(64));
        var before = database(); var files = files();
        var report = reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null);
        assertThat(report.path("extractions")).hasSize(3);
        var bad = byRun(report, failed);
        assertThat(bad.path("database").path("status").asText()).isEqualTo("failed");
        assertThat(bad.path("validation").path("status").asText()).isEqualTo("valid");
        assertThat(bad.path("artifacts").path("attempt-1.output").path("base64").asText()).isEqualTo("/w==");
        assertThat(bad.path("artifacts").path("attempt-1.output").path("size").asInt()).isEqualTo(1);
        assertThat(byRun(report, legacy).path("validation").path("status").asText()).isEqualTo("invalid");
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
    }

    @Test
    void everyManualAttemptAndApiWireArtifactIsDisplayed() throws Exception {
        var source = fixtures.source(false); fixtures.register(source);
        String failed = UUID.randomUUID().toString(), api = UUID.randomUUID().toString();
        Path initial = fixtures.extraction.archive(source, failed, true), work = initial.getParent();
        var metadata = (ObjectNode) mapper.readTree(work.resolve("metadata.json").toFile()); metadata.put("attempts", 2);
        Path info = Files.writeString(work.resolve("multiple-metadata.json"), metadata.toString()), multiple = work.resolve("multiple-archive");
        var process = new ProcessBuilder(PythonProbe.PYTHON, "-m", "processing.extraction", "import", "--input", work.resolve("input.json").toString(), "--metadata", info.toString(),
                "--attempt", work.resolve("prompt.txt").toString(), work.resolve("output.json").toString(),
                "--attempt", work.resolve("prompt.txt").toString(), work.resolve("output.json").toString(), "--root", multiple.toString())
                .directory(PythonProbe.REPO.toFile()).start();
        assertThat(process.waitFor(10, TimeUnit.SECONDS)).isTrue(); assertThat(process.exitValue()).isEqualTo(4);
        extractions.importRun(failed, multiple, "synthetic-registrant");
        var prepared = fixtures.archive(source, api);
        var apiArchive = ExtractionArchiveReaderTest.apiArchive(root.resolve("api"), prepared.resolve(api).resolve("input.json"), api,
                SourceReviewFixtures.document(source).path("preprocessing_version").asText());
        extractions.importRun(api, apiArchive, "synthetic-registrant");
        var before = files(); var report = reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null);
        assertThat(byRun(report, failed).path("artifacts").path("attempt-2.output").path("base64").asText()).isEqualTo("/w==");
        assertThat(byRun(report, failed).path("artifacts").has("attempt-2.prompt")).isTrue();
        assertThat(byRun(report, api).path("artifacts").has("attempt-1.response")).isTrue();
        assertThat(byRun(report, api).path("artifacts").has("attempt-1.exchange")).isTrue();
        assertThat(files()).isEqualTo(before);
    }

    @Test
    void registeredRowMismatchKeepsEveryIndependentlyVerifiedArchiveArtifact() throws Exception {
        for (boolean api : List.of(false, true)) {
            var source = fixtures.source(false); fixtures.register(source); String run = UUID.randomUUID().toString();
            Path archive = fixtures.archive(source, run);
            if (api) archive = ExtractionArchiveReaderTest.apiArchive(root.resolve("mismatched-api"), archive.resolve(run).resolve("input.json"), run,
                    SourceReviewFixtures.document(source).path("preprocessing_version").asText());
            extractions.importRun(run, archive, "synthetic-registrant");
            Path registered = Path.of(jdbc.queryForObject("SELECT raw_ref FROM extraction_runs WHERE run_id=?", String.class, run));
            if (api) {
                var receipt = (ObjectNode) mapper.readTree(jdbc.queryForObject("SELECT receipt_json FROM extraction_runs WHERE run_id=?", String.class, run));
                ((ObjectNode) receipt.path("artifacts").path("attempt-1.output")).put("size", 8 * 1024 * 1024 + 1);
                jdbc.update("UPDATE extraction_runs SET receipt_json=? WHERE run_id=?", receipt.toString(), run);
            } else jdbc.update("UPDATE extraction_runs SET status='failed',output_sha256=? WHERE run_id=?", "0".repeat(64), run);
            var before = database(); var files = files();
            var extraction = byRun(reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null), run);
            assertThat(extraction.path("validation").path("status").asText()).isEqualTo("invalid");
            assertThat(extraction.path("archive_validation").path("status").asText()).isEqualTo("valid");
            assertThat(extraction.path("database_validation").path("status").asText()).isEqualTo("invalid");
            for (String artifact : api ? List.of("attempt-1.prompt", "attempt-1.output", "attempt-1.response", "attempt-1.exchange") : List.of("attempt-1.prompt", "attempt-1.output")) {
                var value = extraction.path("artifacts").path(artifact);
                assertThat(value.path("validation").path("status").asText()).isEqualTo("valid");
                assertThat(value.path("text").asText()).isEqualTo(Files.readString(registered.resolve(artifact)));
            }
            assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
        }
    }

    @Test
    void oversizedRegisteredArtifactFailsBeforeReadingOrRepairingTheArchive() throws Exception {
        var source = fixtures.source(false); fixtures.register(source); String run = UUID.randomUUID().toString();
        extractions.importRun(run, fixtures.archive(source, run), "synthetic-registrant");
        Path registered = Path.of(jdbc.queryForObject("SELECT raw_ref FROM extraction_runs WHERE run_id=?", String.class, run));
        Path output = registered.resolve("attempt-1.output");
        Files.setPosixFilePermissions(output, java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));
        Files.writeString(output, "x".repeat(8 * 1024 * 1024 + 1));
        var before = database(); var files = files();
        assertThatThrownBy(() -> reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null))
                .isInstanceOfSatisfying(PublicationException.class, ex -> assertThat(ex.code()).isEqualTo("REPORT_TOO_LARGE"));
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
    }

    @Test
    void mutableRegisteredParentIsRejectedWithoutCreatingAnotherFrozenArchiveInPreview() throws Exception {
        var source = fixtures.source(false); fixtures.register(source); String run = UUID.randomUUID().toString();
        extractions.importRun(run, fixtures.archive(source, run), "synthetic-registrant");
        var batch = fixtures.extraction.review(source, run); importer.importBatch(batch, "synthetic-reviewer");
        var event = batch.events().getFirst(); var payload = mapper.readTree(event.payloadJson());
        var evidence = new ArrayList<String>(); payload.path("evidence").forEach(value -> evidence.add(value.path("evidence_id").asText()));
        var approved = publication.execute(new PublicationCommand.Decision("publication-command-v1", "approve", "합성 승인", UUID.fromString(event.id()), 1, evidence), root, "synthetic-approver");
        var input = mapper.createObjectNode(); input.putArray("events").add(payload.path("event"));
        var request = publish(input, approved.revisionId()); request.put("action", "preview"); Path preview = write(request);
        Path registered = fixtures.extraction.stored(run); var permissions = Files.getPosixFilePermissions(registered);
        var writable = new HashSet<>(permissions); writable.add(java.nio.file.attribute.PosixFilePermission.OWNER_WRITE); Files.setPosixFilePermissions(registered, writable);
        try {
            var before = database(); var files = files(); var report = reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, preview);
            assertThat(byRun(report, run).path("validation").path("status").asText()).isEqualTo("invalid");
            assertThat(report.path("preview").path("status").asText()).isEqualTo("invalid");
            assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
        } finally { Files.setPosixFilePermissions(registered, permissions); }
    }

    @Test
    void historicalSourceConnectionRetainsCurrentOtherSourceAndRemovalPublicationTransitions() throws Exception {
        var first = fixtures.human(false); importInput(first);
        String originalVersion = SourceReviewFixtures.version(first), event = SourceReviewFixtures.event(first);
        var second = (ObjectNode) mapper.readTree(first.toString()
                .replace(SourceReviewFixtures.document(first).path("document_id").asText(), UUID.randomUUID().toString())
                .replace(originalVersion, UUID.randomUUID().toString()));
        for (var check : second.path("documents").get(0).path("checks")) ((ObjectNode) check).put("check_id", UUID.randomUUID().toString());
        var item = (ObjectNode) second.path("events").get(0); item.put("expected_revision_no", 1);
        ((ObjectNode) item.path("revision")).put("revision_id", UUID.randomUUID().toString()).put("revision_no", 2);
        importInput(second);
        String otherSourceRun = UUID.randomUUID().toString();
        jdbc.update("INSERT INTO extraction_runs(run_id,document_version_id,input_sha256,provider,model,prompt_version,status) VALUES (?,?,?,'legacy','legacy','legacy','failed')",
                otherSourceRun, SourceReviewFixtures.version(second), "2".repeat(64));
        var evidence = new ArrayList<String>(); second.path("evidence").forEach(e -> evidence.add(e.path("evidence_id").asText()));
        var approved = publication.execute(new PublicationCommand.Decision("publication-command-v1", "approve", "합성 검토", UUID.fromString(event), 2, evidence), root, "synthetic-approver");
        var request = publish(second, approved.revisionId());
        var published = publication.execute(commands.read(write(request)), root, "synthetic-publisher");
        request.put("expected_head_version", 0).putArray("revision_ids");
        var empty = publication.execute(commands.read(write(request)), root, "synthetic-publisher");
        publication.execute(new PublicationCommand.Rollback("publication-command-v1", "rollback", "합성 복구", "replay", UUID.fromString(request.path("case_id").asText()), UUID.fromString(published.snapshotId()), empty.headVersion()), null, "synthetic-publisher");
        publication.execute(new PublicationCommand.Decision("publication-command-v1", "reject", "합성 반려", UUID.fromString(event), 3, evidence), null, "synthetic-reviewer");
        var before = database(); var report = reports.build(UUID.fromString(originalVersion), root, null);
        assertThat(report.path("documents")).hasSize(2);
        assertThat(byRun(report, otherSourceRun).path("database").path("document_version_id").asText()).isEqualTo(SourceReviewFixtures.version(second));
        assertThat(report.path("events")).hasSize(1);
        assertThat(report.path("events").get(0).path("revisions")).hasSize(4);
        assertThat(report.path("review_audits")).hasSize(4);
        assertThat(report.path("publication").path("audits")).hasSize(3);
        assertThat(report.path("publication").toString()).contains(empty.snapshotId(), "rollback");
        assertThat(database()).isEqualTo(before);
    }

    @Test
    void laterNonmemberSnapshotStillIdentifiesCurrentHeadAfterEventRemoval() throws Exception {
        var input = fixtures.human(false); importInput(input); String event = SourceReviewFixtures.event(input);
        var evidence = new ArrayList<String>(); input.path("evidence").forEach(item -> evidence.add(item.path("evidence_id").asText()));
        var approved = publication.execute(new PublicationCommand.Decision("publication-command-v1", "approve", "합성 승인", UUID.fromString(event), 1, evidence), root, "synthetic-reviewer");
        var request = publish(input, approved.revisionId());
        var first = publication.execute(commands.read(write(request)), root, "synthetic-publisher");
        request.put("expected_head_version", 0).putArray("revision_ids");
        publication.execute(commands.read(write(request)), root, "synthetic-publisher");
        request.put("expected_head_version", 1);
        var current = publication.execute(commands.read(write(request)), root, "synthetic-publisher");
        var before = database(); var report = reports.build(UUID.fromString(SourceReviewFixtures.version(input)), root, null);
        var published = report.path("publication");
        assertThat(published.path("audits")).hasSize(2);
        assertThat(published.path("heads").get(0).path("snapshot_id").asText()).isEqualTo(current.snapshotId());
        assertThat(published.path("snapshots").toString()).contains(current.snapshotId());
        assertThat(published.path("memberships")).hasSize(1);
        assertThat(published.path("memberships").get(0).path("snapshot_id").asText()).isEqualTo(first.snapshotId());
        assertThat(database()).isEqualTo(before);
    }

    @Test
    void handoffPreservesHumanOutputChangesAndEverySourceProof() throws Exception {
        var source = fixtures.source(false); fixtures.register(source); String run = UUID.randomUUID().toString();
        var archive = fixtures.archive(source, run); extractions.importRun(run, archive, "synthetic-registrant");
        var image = fixtures.handoff(source, run, archive);
        handoffs.importFile(image.file(), root, image.directory(), "synthetic-reviewer");
        var before = database(); var files = files();
        var report = reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null);
        var proof = report.path("events").get(0).path("revisions").get(0).path("handoffs").get(0);
        assertThat(proof.path("validation").path("status").asText()).isEqualTo("valid");
        assertThat(proof.path("review").path("output").path("items")).hasSize(1);
        assertThat(proof.path("review").has("changes")).isTrue();
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
    }

    @Test
    void previewNeverDispatchesPublishAndPreservesUnapprovedGateFailure() throws Exception {
        var input = fixtures.human(true); var imported = importInput(input);
        var request = publish(input, imported.events().getFirst().revisionId());
        var publishFile = write(request); var before = database();
        var rejected = reports.build(UUID.fromString(SourceReviewFixtures.version(input)), root, publishFile);
        assertThat(rejected.path("preview").path("status").asText()).isEqualTo("invalid");
        assertThat(rejected.path("preview").path("code").asText()).isEqualTo("REPORT_PREVIEW_INVALID");
        request.put("action", "preview");
        var preview = reports.build(UUID.fromString(SourceReviewFixtures.version(input)), root, write(request));
        assertThat(preview.path("preview").path("status").asText()).isEqualTo("invalid");
        assertThat(preview.path("preview").path("code").asText()).isEqualTo("PUBLICATION_CONFLICT");
        assertThat(database()).isEqualTo(before);
    }

    @Test
    void emptyHumanHandoffRemainsVisibleBeforeAndAfterAnExistingEvent() throws Exception {
        for (boolean existing : List.of(false, true)) {
            var source = fixtures.source(false); fixtures.register(source); String run = UUID.randomUUID().toString();
            var archive = fixtures.archive(source, run); extractions.importRun(run, archive, "synthetic-registrant");
            if (existing) {
                var first = fixtures.handoff(source, run, archive);
                handoffs.importFile(first.file(), root, first.directory(), "synthetic-reviewer");
            }
            var empty = fixtures.handoff(source, run, archive, output -> {
                output.putArray("items"); output.putArray("warnings").add("NO_EVENT_FOUND");
            });
            var imported = handoffs.importFile(empty.file(), root, empty.directory(), "synthetic-reviewer");
            assertThat(imported.revisionIds()).isEmpty();
            var before = database(); var files = files();
            var report = reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null);
            var imports = report.path("documents").get(0).path("imports");
            assertThat(imports).hasSize(existing ? 2 : 1);
            JsonNode selected = null;
            for (var item : imports) if (item.path("database").path("import_id").asText().equals(imported.importId())) selected = item;
            assertThat(selected).isNotNull();
            assertThat(selected.path("validation").path("status").asText()).isEqualTo("valid");
            var proof = selected.path("handoffs").get(0);
            assertThat(proof.path("review").path("output").path("items")).isEmpty();
            assertThat(proof.path("review").path("output").path("warnings").toString()).contains("NO_EVENT_FOUND");
            assertThat(proof.path("review").path("changes")).isNotEmpty();
            assertThat(report.path("events")).hasSize(existing ? 1 : 0);
            assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
            var refs = (ObjectNode) mapper.readTree(jdbc.queryForObject("SELECT result_refs_json FROM import_batches WHERE import_id=?", String.class, imported.importId()));
            refs.put("originating_run_id", UUID.randomUUID().toString());
            jdbc.update("UPDATE import_batches SET result_refs_json=? WHERE import_id=?", refs.toString(), imported.importId());
            before = database();
            var invalid = reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null).path("documents").get(0).path("imports");
            for (var item : invalid) if (item.path("database").path("import_id").asText().equals(imported.importId()))
                assertThat(item.path("validation").path("status").asText()).isEqualTo("invalid");
            assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
        }
    }

    @Test
    void rejectedPartialHandoffPreservesUnknownsWithoutWeakeningApproval() throws Exception {
        var source = fixtures.source(false); fixtures.register(source); String run = UUID.randomUUID().toString();
        var archive = fixtures.archive(source, run); extractions.importRun(run, archive, "synthetic-registrant");
        var image = fixtures.handoff(source, run, archive, output -> {
            var item = (ObjectNode) output.path("items").get(0);
            for (String field : List.of("title", "types")) {
                var value = (ObjectNode) item.path(field);
                value.putNull("value").put("knowledge", field.equals("types") ? "ambiguous" : "not_stated").put("reason", "합성 미기재").putArray("evidence_ids");
            }
        });
        var imported = handoffs.importFile(image.file(), root, image.directory(), "synthetic-reviewer");
        String event = jdbc.queryForObject("SELECT event_id FROM event_revisions WHERE revision_id=?", String.class, imported.revisionIds().getFirst());
        assertThatThrownBy(() -> publication.execute(new PublicationCommand.Decision("publication-command-v1", "approve", "합성 승인 거부", UUID.fromString(event), 1, List.of("e1")), root, "synthetic-approver"))
                .isInstanceOf(PublicationException.class);
        publication.execute(new PublicationCommand.Decision("publication-command-v1", "reject", "합성 반려", UUID.fromString(event), 1, List.of()), null, "synthetic-rejector");
        var before = database(); var files = files();
        var report = reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null);
        var revisions = report.path("events").get(0).path("revisions");
        assertThat(revisions).hasSize(2);
        assertThat(revisions.get(1).path("payload").path("revision").path("review_status").asText()).isEqualTo("rejected");
        assertThat(revisions.get(1).path("payload").path("revision").path("title").isNull()).isTrue();
        assertThat(revisions.get(1).path("payload").path("revision").path("types")).isEmpty();
        assertThat(revisions.get(1).path("validation").path("status").asText()).isEqualTo("valid");
        assertThatThrownBy(() -> publication.execute(new PublicationCommand.Decision("publication-command-v1", "approve", "합성 재승인 거부", UUID.fromString(event), 2, List.of("e1")), root, "synthetic-approver"))
                .isInstanceOf(PublicationException.class);
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
    }

    @Test
    void mixedBundlePreviewCountsNewChangedRemovedUnchangedAndCancelledAgainstExactHead() throws Exception {
        var first = fixtures.human(false); importInput(first);
        String firstEvent = SourceReviewFixtures.event(first), area = first.path("events").get(0).path("area_id").asText();
        var firstApproved = approve(first, 1);
        var other = fixtures.human(false); ((ObjectNode) other.path("events").get(0)).put("area_id", area);
        var cancellation = (ObjectNode) other.path("events").get(0).path("revision");
        cancellation.put("lifecycle", "cancelled").putArray("lifecycle_evidence_ids").add(other.path("evidence").get(0).path("evidence_id").asText());
        importInput(other); var otherApproved = approve(other, 1);
        var request = publish(first, firstApproved.revisionId());
        var firstSnapshot = publication.execute(commands.read(write(request)), root, "synthetic-publisher");
        request.put("action", "preview").put("expected_head_version", 0);
        request.putArray("revision_ids").add(firstApproved.revisionId()).add(otherApproved.revisionId());
        Path mixedRequest = write(request); var before = database(); var files = files();
        var mixed = reports.build(UUID.fromString(SourceReviewFixtures.version(first)), root, mixedRequest).path("preview");
        assertThat(mixed.path("status").asText()).isEqualTo("valid");
        assertThat(mixed.path("summary").path("status").asText()).isEqualTo("available");
        assertThat(mixed.path("summary").path("baseline").path("snapshot_id").asText()).isEqualTo(firstSnapshot.snapshotId());
        assertThat(mixed.path("summary").path("new_events").asInt(-1)).isEqualTo(1);
        assertThat(mixed.path("summary").path("revision_changed").asInt(-1)).isZero();
        assertThat(mixed.path("summary").path("removed_events").asInt(-1)).isZero();
        assertThat(mixed.path("summary").path("unchanged_events").asInt(-1)).isEqualTo(1);
        assertThat(mixed.path("summary").path("cancelled_events").asInt(-1)).isEqualTo(1);
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
        request.put("action", "publish"); publication.execute(commands.read(write(request)), root, "synthetic-publisher");
        var changed = first.deepCopy(); var item = (ObjectNode) changed.path("events").get(0); item.put("expected_revision_no", 2);
        ((ObjectNode) item.path("revision")).put("revision_id", UUID.randomUUID().toString()).put("revision_no", 3).put("title", "합성 제목 수정");
        importInput(changed); var changedApproved = approve(changed, 3);
        request.put("action", "preview").put("expected_head_version", 1); request.putArray("revision_ids").add(changedApproved.revisionId());
        Path changedRequest = write(request); before = database();
        var summary = reports.build(UUID.fromString(SourceReviewFixtures.version(first)), root, changedRequest).path("preview").path("summary");
        assertThat(summary.path("new_events").asInt(-1)).isZero(); assertThat(summary.path("revision_changed").asInt(-1)).isEqualTo(1);
        assertThat(summary.path("removed_events").asInt(-1)).isEqualTo(1); assertThat(summary.path("unchanged_events").asInt(-1)).isZero();
        assertThat(summary.path("cancelled_events").asInt(-1)).isZero(); assertThat(database()).isEqualTo(before);
    }

    @Test
    void previewWithoutHeadShowsNewCardsAndDamagedBaselineRemainsUnknown() throws Exception {
        var input = fixtures.human(false); importInput(input); var approved = approve(input, 1);
        var request = publish(input, approved.revisionId()); request.put("action", "preview");
        Path previewRequest = write(request); var before = database();
        var first = reports.build(UUID.fromString(SourceReviewFixtures.version(input)), root, previewRequest).path("preview");
        assertThat(first.path("summary").path("baseline").path("status").asText()).isEqualTo("none");
        assertThat(first.path("summary").path("new_events").asInt(-1)).isEqualTo(1); assertThat(database()).isEqualTo(before);
        request.put("action", "publish"); var published = publication.execute(commands.read(write(request)), root, "synthetic-publisher");
        jdbc.update("UPDATE snapshots SET checksum=? WHERE snapshot_id=?", "0".repeat(64), published.snapshotId());
        before = database(); var damaged = reports.build(UUID.fromString(SourceReviewFixtures.version(input)), root, previewRequest).path("preview");
        assertThat(damaged.path("status").asText()).isEqualTo("valid");
        assertThat(damaged.path("summary").path("status").asText()).isEqualTo("unknown");
        assertThat(damaged.path("summary").path("new_events").isNull()).isTrue();
        assertThat(damaged.path("summary").path("baseline").path("validation").path("status").asText()).isEqualTo("invalid");
        assertThat(database()).isEqualTo(before);
    }

    @Test
    void missingSourceFileIsRecordedWhileUnknownVersionAndExcessRowsFailExplicitly() throws Exception {
        var source = fixtures.source(true); fixtures.register(source); Files.delete(root.resolve("synthetic-source.txt"));
        var report = reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null);
        assertThat(report.path("documents").get(0).path("raw_asset").path("validation").path("status").asText()).isEqualTo("invalid");
        assertThatThrownBy(() -> reports.build(UUID.randomUUID(), root, null)).isInstanceOfSatisfying(PublicationException.class, e -> assertThat(e.code()).isEqualTo("REPORT_NOT_FOUND"));
        for (int i = 0; i < 1001; i++) jdbc.update("INSERT INTO extraction_runs(run_id,document_version_id,input_sha256,provider,model,prompt_version,status) VALUES (?,?,?,'legacy','legacy','legacy','failed')", UUID.randomUUID().toString(), SourceReviewFixtures.version(source), "1".repeat(64));
        assertThatThrownBy(() -> reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null)).isInstanceOfSatisfying(PublicationException.class, e -> assertThat(e.code()).isEqualTo("REPORT_TOO_LARGE"));
    }

    @Test
    void overflowingBaselineEventCountIsUnknownRatherThanWrappedToValidCount() throws Exception {
        var input = fixtures.human(false); importInput(input); var approved = approve(input, 1);
        var request = publish(input, approved.revisionId());
        var published = publication.execute(commands.read(write(request)), root, "synthetic-publisher");
        var canonical = (ObjectNode) mapper.readTree(jdbc.queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id=?", String.class, published.snapshotId()));
        canonical.put("event_count", 4294967297L); String text = canonical.toString();
        jdbc.update("UPDATE snapshots SET canonical_json=?, checksum=? WHERE snapshot_id=?", text,
                ReviewedImportReader.sha256(text.getBytes(java.nio.charset.StandardCharsets.UTF_8)), published.snapshotId());
        request.put("action", "preview"); Path preview = write(request); var before = database();
        var summary = reports.build(UUID.fromString(SourceReviewFixtures.version(input)), root, preview).path("preview").path("summary");
        assertThat(summary.path("status").asText()).isEqualTo("unknown");
        assertThat(summary.path("new_events").isNull()).isTrue(); assertThat(database()).isEqualTo(before);
    }

    @Test
    void binarySourceAndDamagedStoredHashKeepOriginalBytesAndDatabaseValues() throws Exception {
        var source = fixtures.human(false); byte[] binary = {(byte) 0xff, 0};
        Files.write(root.resolve("synthetic-source.txt"), binary);
        SourceReviewFixtures.document(source).put("raw_sha256", ReviewedImportReader.sha256(binary));
        var batch = importInput(source); String revision = batch.events().getFirst().revisionId();
        jdbc.update("UPDATE event_revisions SET payload_sha256=? WHERE revision_id=?", "0".repeat(64), revision);
        var before = database(); var report = reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null);
        assertThat(report.path("documents").get(0).path("raw_asset").path("base64").asText()).isEqualTo("/wA=");
        var damaged = report.path("events").get(0).path("revisions").get(0);
        assertThat(damaged.path("database").path("payload_json").asText()).contains("human_overrides");
        assertThat(damaged.path("validation").path("code").asText()).isEqualTo("PUBLICATION_VALIDATION_ERROR");
        assertThat(database()).isEqualTo(before);
    }

    @Test
    void oversizedSourceFailsInsteadOfReturningTruncatedText() throws Exception {
        var source = fixtures.source(true); fixtures.register(source);
        byte[] bytes = new byte[20 * 1024 * 1024 + 1]; Arrays.fill(bytes, (byte) 'x');
        Files.write(root.resolve("synthetic-source.txt"), bytes);
        var metadata = (ObjectNode) mapper.readTree(jdbc.queryForObject("SELECT metadata_json FROM document_versions WHERE document_version_id=?",
                String.class, SourceReviewFixtures.version(source)));
        ((ObjectNode) metadata.path("document")).put("raw_sha256", ReviewedImportReader.sha256(bytes));
        jdbc.update("UPDATE document_versions SET metadata_json=? WHERE document_version_id=?", metadata.toString(), SourceReviewFixtures.version(source));
        var before = database(); var files = files();
        assertThatThrownBy(() -> reports.build(UUID.fromString(SourceReviewFixtures.version(source)), root, null))
                .isInstanceOfSatisfying(PublicationException.class, e -> assertThat(e.code()).isEqualTo("REPORT_TOO_LARGE"));
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
    }

    @Test
    void individuallyAllowedRawAssetsStillRejectReportAboveSixtyFourMiBWithoutWrites() throws Exception {
        var first = fixtures.human(false);
        byte[] bytes = new byte[20 * 1024 * 1024]; Arrays.fill(bytes, (byte) 0xff);
        Files.write(root.resolve("synthetic-source.txt"), bytes);
        SourceReviewFixtures.document(first).put("raw_sha256", ReviewedImportReader.sha256(bytes));
        importInput(first);
        for (int revision = 2; revision <= 3; revision++) {
            var next = (ObjectNode) mapper.readTree(first.toString()
                    .replace(SourceReviewFixtures.document(first).path("document_id").asText(), UUID.randomUUID().toString())
                    .replace(SourceReviewFixtures.version(first), UUID.randomUUID().toString()));
            for (var check : SourceReviewFixtures.document(next).path("checks")) ((ObjectNode) check).put("check_id", UUID.randomUUID().toString());
            ((ObjectNode) next.path("events").get(0)).put("expected_revision_no", revision - 1);
            ((ObjectNode) next.path("events").get(0).path("revision")).put("revision_id", UUID.randomUUID().toString()).put("revision_no", revision);
            importInput(next);
        }
        var before = database(); var files = files();
        assertThatThrownBy(() -> reports.build(UUID.fromString(SourceReviewFixtures.version(first)), root, null))
                .isInstanceOfSatisfying(PublicationException.class, error -> {
                    assertThat(error.code()).isEqualTo("REPORT_TOO_LARGE");
                    assertThat(error.field()).isEqualTo("report");
                });
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(files);
    }

    private JsonNode byRun(JsonNode report, String id) { for (var run : report.path("extractions")) if (run.path("database").path("run_id").asText().equals(id)) return run; throw new AssertionError(id); }
    private kr.ac.myai.backend.importing.ReviewedBatch importInput(ObjectNode input) throws Exception { var batch = reader.read(write(input), root); importer.importBatch(batch, "synthetic-importer"); return batch; }
    private PublicationService.Result approve(ObjectNode input, long expected) {
        var evidence = new ArrayList<String>(); input.path("evidence").forEach(item -> evidence.add(item.path("evidence_id").asText()));
        return publication.execute(new PublicationCommand.Decision("publication-command-v1", "approve", "합성 검토", UUID.fromString(SourceReviewFixtures.event(input)), expected, evidence), root, "synthetic-approver");
    }
    private Path write(JsonNode value) throws Exception { return Files.writeString(root.resolve(UUID.randomUUID() + ".json"), value.toString()); }
    private ObjectNode publish(ObjectNode input, String revision) throws Exception {
        var request = (ObjectNode) mapper.readTree(Path.of("examples/publish.json").toFile());
        request.put("mode", "replay").put("case_id", UUID.randomUUID().toString()).put("anchor_date", "2026-11-03").put("reference_instant", "2026-11-03T00:00:00Z").put("knowledge_cutoff", "2026-11-03T00:00:00Z").put("history_fidelity", "reconstructed");
        String area = input.path("events").get(0).path("area_id").asText(); ((ObjectNode) request.path("area")).put("area_id", area);
        for (var point : request.path("points")) ((ObjectNode) point).put("point_id", UUID.randomUUID().toString()).put("area_id", area);
        request.putArray("revision_ids").add(revision); return request;
    }
    private JsonNode database() { var result = mapper.createObjectNode(); for (String table : jdbc.queryForList("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME", String.class)) { var rows = result.putArray(table); for (var row : jdbc.queryForList("SELECT * FROM `" + table + "` ORDER BY 1")) { var out = rows.addObject(); row.forEach((k, v) -> out.put(k, v == null ? null : v.toString())); } } return result; }
    private Map<String,String> files() throws Exception { var result = new TreeMap<String,String>(); try (var paths = Files.walk(root)) { for (Path path : paths.toList()) result.put(root.relativize(path).toString(), Files.getPosixFilePermissions(path).toString() + (Files.isRegularFile(path) ? ReviewedImportReader.sha256(Files.readAllBytes(path)) : "")); } return result; }
}
