package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.service.ReviewedImportService;
import kr.ac.myai.backend.service.ExtractionImportService;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.extraction.VerifiedExtraction;
import kr.ac.myai.backend.repository.ExtractionRunRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.*;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

@SpringBootTest
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class ExtractionRunMySqlTest {
    @Autowired JdbcTemplate jdbc;
    @MockitoSpyBean ReviewedImportReader reader;
    @Autowired ReviewedImportService importer;
    @Autowired ExtractionImportService extraction;
    @Autowired kr.ac.myai.backend.service.PublicationService publication;
    @Autowired kr.ac.myai.backend.publication.PublicationCommandReader commands;
    @MockitoSpyBean ExtractionArchiveReader archives;
    @MockitoSpyBean ExtractionRunRepository runs;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();

    @DynamicPropertySource
    static void python(DynamicPropertyRegistry properties) {
        properties.add("app.calculation.workdir", () -> PythonProbe.REPO.toString());
        properties.add("app.calculation.python-executable", () -> PythonProbe.PYTHON);
        properties.add("app.extraction.timeout-ms", () -> 10000);
    }

    @Test
    void registrationKeepsExactlyVerifiedBytesWhenOriginalChangesAfterPython() throws Exception {
        var source = source(); registerSource(source);
        String id = UUID.randomUUID().toString(); Path archive = archive(source, id, false);
        Path original = archive.resolve(id).resolve("attempt-1.output");
        byte[] verified = Files.readAllBytes(original);
        var changed = new java.util.concurrent.atomic.AtomicBoolean();
        doAnswer(invocation -> {
            var parsed = (com.fasterxml.jackson.databind.JsonNode) invocation.callRealMethod();
            if ((parsed.path("format_version").asText().equals("extraction-archive-v1")
                    || parsed.path("protocol_version").asText().equals("extraction-registration-v1")) && changed.compareAndSet(false, true)) {
                Files.writeString(original, "PRIVATE_VALUE changed after Python returned");
            }
            return parsed;
        }).when(reader).parseJson(any(byte[].class));
        extraction.importRun(id, archive, "synthetic-registrant");
        assertThat(changed).isTrue();
        var row = jdbc.queryForMap("SELECT raw_ref,output_sha256 FROM extraction_runs WHERE run_id=?", id);
        Path registered = Path.of((String) row.get("raw_ref")).resolve("attempt-1.output");
        assertThat(registered).isNotEqualTo(original);
        assertThat(Files.readAllBytes(registered)).isEqualTo(verified);
        assertThat(ReviewedImportReader.sha256(Files.readAllBytes(registered))).isEqualTo(row.get("output_sha256"));
        assertThat(importer.importBatch(review(source, id), "synthetic-reviewer").revisionIds()).hasSize(1);
    }

    @Test
    void rejectsDeletedOrAlteredArchiveBeforeD06Reference() throws Exception {
        var source = source(); registerSource(source); var before = counts();
        for (String artifact : List.of("attempt-1.output", "metadata.json", "receipt.json")) {
            String id = UUID.randomUUID().toString(); Path archive = archive(source, id, false);
            extraction.importRun(id, archive, "synthetic-registrant");
            Path stored = stored(id); ExtractionArchiveReaderTest.unseal(stored);
            Files.writeString(stored.resolve(artifact), "PRIVATE_VALUE changed");
            var reviewed = review(source, id);
            assertThatThrownBy(() -> importer.importBatch(reviewed, "synthetic-reviewer"))
                    .isInstanceOf(kr.ac.myai.backend.importing.ImportException.class).hasMessageNotContaining("PRIVATE_VALUE");
            assertThat(counts()).isEqualTo(before);
        }
        String id = UUID.randomUUID().toString(); Path archive = archive(source, id, false);
        extraction.importRun(id, archive, "synthetic-registrant");
        Path stored = stored(id); ExtractionArchiveReaderTest.unseal(stored);
        Files.delete(stored.resolve("attempt-1.output"));
        var reviewed = review(source, id);
        assertThatThrownBy(() -> importer.importBatch(reviewed, "synthetic-reviewer"))
                .isInstanceOf(kr.ac.myai.backend.importing.ImportException.class);
        assertThat(counts()).isEqualTo(before);
    }

    @Test
    void rechecksChangedRegistrationUnderTheWriteTransaction() throws Exception {
        var source = source(); registerSource(source); var before = counts();
        String id = UUID.randomUUID().toString(); Path archive = archive(source, id, false);
        extraction.importRun(id, archive, "synthetic-registrant");
        var batch = review(source, id);
        String original = jdbc.queryForObject("SELECT receipt_json FROM extraction_runs WHERE run_id=?", String.class, id);
        doAnswer(invocation -> {
            CompletableFuture.runAsync(() -> jdbc.update("UPDATE extraction_runs SET receipt_json=JSON_SET(receipt_json,'$.review_required',false) WHERE run_id=?", id))
                    .get(5, TimeUnit.SECONDS);
            return invocation.callRealMethod();
        }).when(runs).checkReference(any(ExtractionRunRepository.Reference.class));
        try {
            assertThatThrownBy(() -> importer.importBatch(batch, "synthetic-reviewer"))
                    .isInstanceOfSatisfying(kr.ac.myai.backend.importing.ImportException.class, ex -> assertThat(ex.code()).isEqualTo("IMPORT_CONFLICT"));
            assertThat(counts()).isEqualTo(before);
        } finally { jdbc.update("UPDATE extraction_runs SET receipt_json=? WHERE run_id=?", original, id); }
    }

    @Test
    void cachedRunStillMustMatchEachEventsOwnSourceVersions() throws Exception {
        var first = source(); registerSource(first); var second = source(); registerSource(second);
        String id = UUID.randomUUID().toString(); Path archive = archive(first, id, false);
        extraction.importRun(id, archive, "synthetic-registrant");
        var one = review(first, id); var two = review(second, id);
        var documents = new java.util.ArrayList<>(one.documents()); documents.addAll(two.documents());
        var events = new java.util.ArrayList<>(one.events()); events.addAll(two.events());
        var batch = new kr.ac.myai.backend.importing.ReviewedBatch("reviewed-import-v1", "7".repeat(64), "synthetic", documents, events);
        var before = counts();
        assertThatThrownBy(() -> importer.importBatch(batch, "synthetic-reviewer"))
                .isInstanceOf(kr.ac.myai.backend.importing.ImportException.class);
        assertThat(counts()).isEqualTo(before);
    }

    @Test
    void approvalAndPreviewReverifyAiOriginOutsideTransactions() throws Exception {
        var source = source(); registerSource(source);
        String id = UUID.randomUUID().toString(); Path archive = archive(source, id, false);
        extraction.importRun(id, archive, "synthetic-registrant");
        var batch = review(source, id);
        doAnswer(invocation -> {
            assertThat(TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
            return invocation.callRealMethod();
        }).when(archives).read(eq(id), any(Path.class));
        importer.importBatch(batch, "synthetic-reviewer");
        var event = batch.events().getFirst();
        var decision = new kr.ac.myai.backend.publication.PublicationCommand.Decision("publication-command-v1", "approve", "합성 교차 검토",
                UUID.fromString(event.id()), 1, List.of("heading-quote"));
        Path stored = stored(id); ExtractionArchiveReaderTest.unseal(stored);
        Path output = stored.resolve("attempt-1.output"); byte[] original = Files.readAllBytes(output);
        Files.delete(output);
        assertThatThrownBy(() -> publication.execute(decision, root, "synthetic-approver"))
                .isInstanceOf(kr.ac.myai.backend.publication.PublicationException.class);
        assertThat(jdbc.queryForObject("SELECT current_review_revision_id FROM events WHERE event_id=?", String.class, event.id())).isEqualTo(event.revisionId());
        Files.write(output, original);
        seal(stored);
        var approved = publication.execute(decision, root, "synthetic-approver");
        var preview = (ObjectNode) mapper.readTree(Path.of("examples/publish.json").toFile());
        preview.put("action", "preview"); preview.putArray("revision_ids").add(approved.revisionId());
        var command = commands.read(Files.writeString(root.resolve("preview.json"), preview.toString()));
        var before = counts(); ExtractionArchiveReaderTest.unseal(stored); Files.delete(output);
        assertThatThrownBy(() -> publication.execute(command, root, "synthetic-publisher"))
                .isInstanceOf(kr.ac.myai.backend.publication.PublicationException.class);
        assertThat(counts()).isEqualTo(before);
        Files.write(output, original);
        seal(stored);
        assertThat(publication.execute(command, root, "synthetic-publisher").action()).isEqualTo("preview");
    }

    @Test
    void registersExactRunOnceWithNullableModelsOutsideTransactionAndNoPublication() throws Exception {
        var source = source(); registerSource(source); var before = counts();
        String id = UUID.randomUUID().toString(); Path archive = archive(source, id, false);
        doAnswer(invocation -> {
            assertThat(TransactionSynchronizationManager.isActualTransactionActive()).isFalse();
            return invocation.callRealMethod();
        }).when(archives).read(id, archive);
        var first = extraction.importRun(id, archive, "synthetic-registrant");
        var repeated = extraction.importRun(id, archive, "another-registrant");
        assertThat(first.alreadyRegistered()).isFalse(); assertThat(repeated.alreadyRegistered()).isTrue();
        assertThat(first.runId()).isEqualTo(repeated.runId()); assertThat(first.reviewRequired()).isTrue();
        var row = jdbc.queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", id);
        assertThat(row.get("provider")).isNull(); assertThat(row.get("model")).isNull();
        assertThat(row.get("registered_by")).isEqualTo("synthetic-registrant");
        assertThat(row.get("metadata_json")).isEqualTo(Files.readString(archive.resolve(id).resolve("metadata.json")));
        assertThat((String) row.get("metadata_json")).contains("0.1234567890123456789", "123456789Z", "123456790Z");
        assertThat(row.get("receipt_json")).isEqualTo(Files.readString(archive.resolve(id).resolve("receipt.json")));
        assertThat(row.get("status")).isEqualTo("validated"); assertThat(row.get("attempts")).isEqualTo(1);
        assertThat(counts()).isEqualTo(before);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM extraction_runs WHERE run_id=?", Long.class, id)).isEqualTo(1);
    }

    @Test
    void rejectsEverySourceProjectionMismatchAndChangedIdentityWithoutOverwriting() throws Exception {
        var source = source(); registerSource(source);
        for (String field : List.of("title", "published_date", "block_index", "preprocessing_version", "data_kind", "document_version_id")) {
            var changed = source.deepCopy(); var doc = (ObjectNode) changed.path("documents").get(0);
            switch (field) {
                case "block_index" -> ((ObjectNode) doc.path("block_index").get(0)).put("text", "다른 합성 원문");
                case "data_kind" -> changed.put("data_kind", "real");
                case "published_date" -> doc.put(field, "2026-11-01");
                case "document_version_id" -> doc.put(field, UUID.randomUUID().toString());
                default -> doc.put(field, "다른 합성 값");
            }
            String id = UUID.randomUUID().toString(); Path archive = archive(changed, id, false);
            assertThatThrownBy(() -> extraction.importRun(id, archive, "synthetic-registrant")).isInstanceOf(ExtractionException.class);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM extraction_runs WHERE run_id=?", Long.class, id)).isZero();
        }
        String id = UUID.randomUUID().toString(); Path archive = archive(source, id, false);
        extraction.importRun(id, archive, "synthetic-registrant");
        String old = jdbc.queryForObject("SELECT receipt_json FROM extraction_runs WHERE run_id=?", String.class, id);
        Path changed = archive(source, id, false);
        assertThatThrownBy(() -> extraction.importRun(id, changed, "synthetic-registrant")).isInstanceOfSatisfying(ExtractionException.class,
                ex -> assertThat(ex.code()).isEqualTo("EXTRACTION_CONFLICT"));
        assertThat(jdbc.queryForObject("SELECT receipt_json FROM extraction_runs WHERE run_id=?", String.class, id)).isEqualTo(old);
    }

    @Test
    void preservesFailedRunAndOnlyVerifiedSuccessCanEnterReviewedOrigin() throws Exception {
        var source = source(); registerSource(source); var before = counts();
        String failed = UUID.randomUUID().toString(); Path archive = archive(source, failed, true);
        assertThat(extraction.importRun(failed, archive, "synthetic-registrant").status()).isEqualTo("failed");
        assertThat(counts()).isEqualTo(before);
        assertThatThrownBy(() -> importer.importBatch(review(source, failed), "synthetic-reviewer")).isInstanceOfSatisfying(kr.ac.myai.backend.importing.ImportException.class,
                ex -> assertThat(ex.code()).isEqualTo("IMPORT_VALIDATION_ERROR"));
        assertThat(counts()).isEqualTo(before);
        String legacy = UUID.randomUUID().toString();
        jdbc.update("INSERT INTO extraction_runs(run_id,document_version_id,input_sha256,provider,model,prompt_version,status) VALUES (?,?,?,'legacy','legacy','legacy','validated')",
                legacy, source.path("documents").get(0).path("document_version_id").asText(), "0".repeat(64));
        assertThatThrownBy(() -> importer.importBatch(review(source, legacy), "synthetic-reviewer")).isInstanceOf(kr.ac.myai.backend.importing.ImportException.class);
        Path legacyArchive = archive(source, legacy, false);
        assertThatThrownBy(() -> extraction.importRun(legacy, legacyArchive, "synthetic-registrant")).isInstanceOf(ExtractionException.class);
        String validated = UUID.randomUUID().toString(); Path good = archive(source, validated, false);
        extraction.importRun(validated, good, "synthetic-registrant");
        var reviewed = importer.importBatch(review(source, validated), "synthetic-reviewer");
        assertThat(reviewed.revisionIds()).hasSize(1);
        assertThat(jdbc.queryForObject("SELECT review_status FROM event_revisions WHERE revision_id=?", String.class, reviewed.revisionIds().getFirst())).isEqualTo("needs_review");
        assertThat(jdbc.queryForObject("SELECT publication_intent FROM event_revisions WHERE revision_id=?", String.class, reviewed.revisionIds().getFirst())).isEqualTo("hidden");
        assertThat(counts().subList(2, 4)).isEqualTo(before.subList(2, 4));
    }

    @Test
    void concurrentSameRunCreatesOneRowAndLateFailureRollsBack() throws Exception {
        var source = source(); registerSource(source);
        String id = UUID.randomUUID().toString(); Path archive = archive(source, id, false);
        var barrier = new CyclicBarrier(4);
        try (var workers = Executors.newVirtualThreadPerTaskExecutor()) {
            var futures = java.util.stream.IntStream.range(0, 4).mapToObj(i -> workers.submit(() -> {
                barrier.await(5, TimeUnit.SECONDS); return extraction.importRun(id, archive, "synthetic-registrant");
            })).toList();
            int created = 0;
            for (var future : futures) if (!future.get(15, TimeUnit.SECONDS).alreadyRegistered()) created++;
            assertThat(created).isEqualTo(1);
        }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM extraction_runs WHERE run_id=?", Long.class, id)).isEqualTo(1);
        String failed = UUID.randomUUID().toString(); Path failedArchive = archive(source, failed, false);
        doAnswer(invocation -> {
            invocation.callRealMethod();
            throw new org.springframework.dao.DataIntegrityViolationException("PRIVATE_VALUE late failure");
        }).when(runs).insert(any(VerifiedExtraction.class), eq("late-failure-test"));
        assertThatThrownBy(() -> extraction.importRun(failed, failedArchive, "late-failure-test"))
                .isInstanceOf(ExtractionException.class).hasMessageNotContaining("PRIVATE_VALUE");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM extraction_runs WHERE run_id=?", Long.class, failed)).isZero();
        assertThat(Files.isRegularFile(failedArchive.resolve(failed).resolve("receipt.json"))).isTrue();
    }

    @Test
    void invalidActorStopsBeforePythonAndDatabaseErrorsKeepSafeClassification() throws Exception {
        for (String actor : new String[]{null, "", "x".repeat(129), "PRIVATE_VALUE\n"}) {
            assertThatThrownBy(() -> extraction.importRun(UUID.randomUUID().toString(), root, actor))
                    .isInstanceOfSatisfying(ExtractionException.class, ex -> assertThat(ex.code()).isEqualTo("EXTRACTION_VALIDATION_ERROR"));
        }
        verifyNoInteractions(archives, runs);
        var source = source(); registerSource(source);
        String id = UUID.randomUUID().toString(); Path archive = archive(source, id, false);
        var failures = List.of(new org.springframework.dao.DataAccessResourceFailureException("PRIVATE_VALUE"),
                new org.springframework.jdbc.BadSqlGrammarException("PRIVATE_VALUE", "PRIVATE_SQL", new java.sql.SQLException("PRIVATE_VALUE")));
        String[] codes = {"EXTRACTION_DATABASE_UNAVAILABLE", "EXTRACTION_INTERNAL_ERROR"};
        for (int i = 0; i < failures.size(); i++) {
            doThrow(failures.get(i)).when(runs).checkDocument(any(VerifiedExtraction.class));
            final String code = codes[i];
            assertThatThrownBy(() -> extraction.importRun(id, archive, "synthetic-registrant"))
                    .isInstanceOfSatisfying(ExtractionException.class, ex -> assertThat(ex.code()).isEqualTo(code)).hasMessageNotContaining("PRIVATE_VALUE");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM extraction_runs WHERE run_id=?", Long.class, id)).isZero();
        }
    }

    @Test
    void sourceOnlyImportIsIdempotentAndNeverCreatesAnEventOrPublication() throws Exception {
        var input = source();
        var batch = reader.read(Files.writeString(root.resolve("source.json"), input.toString()), root);
        var before = counts();
        var first = importer.importBatch(batch, "synthetic-source-collector");
        var repeated = importer.importBatch(batch, "another-collector");
        assertThat(first.revisionIds()).isEmpty(); assertThat(repeated.alreadyImported()).isTrue();
        assertThat(repeated.importId()).isEqualTo(first.importId()); assertThat(counts()).isEqualTo(before);
        assertThat(jdbc.queryForObject("SELECT source_kind FROM import_batches WHERE import_id = ?", String.class, first.importId())).isEqualTo("source");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM document_versions WHERE document_version_id = ?", Long.class, batch.documents().getFirst().versionId())).isEqualTo(1);
    }

    @Test
    void migrationPreservesLegacyRowsAndAcceptsNullableExactMetadata() throws Exception {
        var input = source();
        var batch = reader.read(Files.writeString(root.resolve("source.json"), input.toString()), root);
        importer.importBatch(batch, "synthetic-source-collector");
        String table = "legacy_run_" + UUID.randomUUID().toString().replace("-", "");
        String v1 = Files.readString(Path.of("src/main/resources/db/migration/V1__create_review_and_publication_schema.sql"));
        String ddl = v1.substring(v1.indexOf("CREATE TABLE extraction_runs"), v1.indexOf("CREATE TABLE events"));
        jdbc.execute(ddl.replace("extraction_runs", table).strip());
        String id = UUID.randomUUID().toString();
        try {
            jdbc.update("INSERT INTO " + table + "(run_id,document_version_id,input_sha256,provider,model,prompt_version,status) VALUES (?,?,?,'legacy-provider','legacy-model','legacy-prompt','validated')",
                    id, batch.documents().getFirst().versionId(), "1".repeat(64));
            String migration = Files.readString(Path.of("src/main/resources/db/migration/V3__extend_extraction_run_metadata.sql"));
            for (String statement : migration.replace("extraction_runs", table).split(";")) if (!statement.isBlank()) jdbc.execute(statement);
            var row = jdbc.queryForMap("SELECT * FROM " + table + " WHERE run_id = ?", id);
            assertThat(row.get("provider")).isEqualTo("legacy-provider"); assertThat(row.get("model")).isEqualTo("legacy-model");
            assertThat(row.get("metadata_json")).isNull(); assertThat(row.get("receipt_json")).isNull();
            String raw = "{\"cost\":0.1234567890123456789,\"finished_at\":\"2026-11-03T01:00:00.123456789Z\",\"unknown\":null,\"한글\":\"😀\"}";
            jdbc.update("UPDATE " + table + " SET provider=NULL, model=NULL, metadata_json=?, metadata_sha256=? WHERE run_id=?", raw, ReviewedImportReader.sha256(raw.getBytes(java.nio.charset.StandardCharsets.UTF_8)), id);
            assertThat(jdbc.queryForObject("SELECT metadata_json FROM " + table + " WHERE run_id=?", String.class, id)).isEqualTo(raw);
        } finally { jdbc.execute("DROP TABLE " + table); }
    }

    private List<Long> counts() {
        return List.of("events", "event_revisions", "snapshots", "publication_heads").stream()
                .map(table -> jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Long.class)).toList();
    }

    ObjectNode source() throws Exception {
        Files.copy(Path.of("examples/synthetic-source.txt"), root.resolve("synthetic-source.txt"), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        var input = (ObjectNode) mapper.readTree(Path.of("examples/reviewed-import.json").toFile());
        input.put("schema_version", "source-import-v1"); input.putArray("evidence"); input.putArray("events");
        var doc = (ObjectNode) input.path("documents").get(0);
        doc.put("document_id", UUID.randomUUID().toString()).put("document_version_id", UUID.randomUUID().toString());
        for (var check : doc.path("checks")) ((ObjectNode) check).put("check_id", UUID.randomUUID().toString());
        return input;
    }

    void registerSource(ObjectNode input) throws Exception {
        importer.importBatch(reader.read(Files.writeString(root.resolve("source.json"), input.toString()), root), "synthetic-source-collector");
    }

    Path stored(String id) { return Path.of(jdbc.queryForObject("SELECT raw_ref FROM extraction_runs WHERE run_id=?", String.class, id)); }

    static void seal(Path directory) throws Exception {
        try (var files = Files.list(directory)) {
            for (Path file : files.toList()) file.toFile().setWritable(false, false);
        }
        directory.toFile().setWritable(false, false);
    }

    @AfterEach
    void makeOwnedTempsRemovable() throws Exception { ExtractionArchiveReaderTest.unseal(root); }

    Path archive(ObjectNode source, String id, boolean failed) throws Exception {
        Path work = Files.createTempDirectory(root, "run-"); var doc = source.path("documents").get(0);
        var input = mapper.createObjectNode().put("data_kind", source.path("data_kind").asText())
                .put("document_version_id", doc.path("document_version_id").asText()).put("title", doc.path("title").asText());
        input.set("published_date", doc.path("published_date")); input.set("blocks", doc.path("block_index"));
        var meta = (ObjectNode) mapper.readTree(PythonProbe.REPO.resolve("processing/examples/extraction-metadata.json").toFile());
        meta.put("run_id", id).put("document_version_id", doc.path("document_version_id").asText())
                .put("preprocessing_version", doc.path("preprocessing_version").asText()).putNull("provider");
        ((ObjectNode) meta.path("unavailable_reasons")).put("provider", "합성 시험, 실제 모델 호출 없음");
        meta.put("started_at", "2026-11-03T01:00:00.123456789Z").put("finished_at", "2026-11-03T01:00:00.123456790Z");
        String metadata = mapper.writerWithDefaultPrettyPrinter().writeValueAsString(meta).replace("\"cost\" : null", "\"cost\" : 0.1234567890123456789");
        var output = (ObjectNode) mapper.readTree(PythonProbe.REPO.resolve("contracts/examples/ai-extraction.json").toFile());
        output.put("document_version_id", doc.path("document_version_id").asText());
        var block = doc.path("block_index").get(0); String content = block.path("text").asText();
        var evidence = (ObjectNode) output.path("evidence").get(0);
        evidence.put("block_id", block.path("block_id").asText()).put("quote", content).put("start_char", 0)
                .put("end_char", content.codePointCount(0, content.length())).put("text_sha256", ReviewedImportReader.sha256(content.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        Path in = Files.writeString(work.resolve("input.json"), input.toString());
        Path info = Files.writeString(work.resolve("metadata.json"), metadata);
        Path prompt = Files.writeString(work.resolve("prompt.txt"), "합성 수동 입력, 실제 AI 실행 아님");
        Path out = work.resolve("output.json"); Files.write(out, failed ? new byte[]{(byte) 0xff} : output.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        Path archive = work.resolve("archive");
        var process = new ProcessBuilder(PythonProbe.PYTHON, "-m", "processing.extraction", "import", "--input", in.toString(), "--metadata", info.toString(),
                "--attempt", prompt.toString(), out.toString(), "--root", archive.toString()).directory(PythonProbe.REPO.toFile()).start();
        assertThat(process.waitFor(10, TimeUnit.SECONDS)).isTrue(); assertThat(process.exitValue()).isEqualTo(failed ? 4 : 0);
        return archive;
    }

    kr.ac.myai.backend.importing.ReviewedBatch review(ObjectNode source, String runId) throws Exception {
        var input = (ObjectNode) mapper.readTree(Path.of("examples/reviewed-import.json").toFile());
        input.set("documents", source.path("documents")); var doc = source.path("documents").get(0);
        for (var evidence : input.path("evidence")) ((ObjectNode) evidence).put("document_version_id", doc.path("document_version_id").asText());
        var event = (ObjectNode) input.path("events").get(0); String id = UUID.randomUUID().toString(); event.put("event_id", id);
        for (var link : event.path("document_links")) ((ObjectNode) link).put("document_id", doc.path("document_id").asText());
        var revision = (ObjectNode) event.path("revision"); revision.put("event_id", id).put("revision_id", UUID.randomUUID().toString()).put("origin", "ai_reviewed");
        revision.putArray("originating_run_ids").add(runId); revision.putArray("source_version_ids").add(doc.path("document_version_id").asText());
        return reader.read(Files.writeString(root.resolve("review.json"), input.toString()), root);
    }
}
