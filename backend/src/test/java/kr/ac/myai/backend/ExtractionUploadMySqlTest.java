package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.VerifiedExtraction;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.local.ExtractionUploadService;
import kr.ac.myai.backend.local.ExtractionUploadStore;
import kr.ac.myai.backend.local.LocalManagementService;
import kr.ac.myai.backend.local.LocalRequestStore;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.repository.ExtractionRunRepository;
import kr.ac.myai.backend.review.ReviewReportService;
import kr.ac.myai.backend.service.*;
import org.assertj.core.api.ThrowableAssert.ThrowingCallable;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static kr.ac.myai.backend.SourceReviewFixtures.document;
import static kr.ac.myai.backend.SourceReviewFixtures.version;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@SpringBootTest
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class ExtractionUploadMySqlTest {
    private static final String ACTOR = "synthetic-extraction-upload-mysql-manager";
    private static final List<String> IMMUTABLE = List.of("test_points", "place_dictionary", "documents", "document_versions",
            "source_checks", "source_reviews", "events", "event_revisions", "review_audits", "snapshots", "snapshot_revisions",
            "publication_heads", "publication_audits", "import_batches");
    private static final List<String> ALL_TABLES = new ArrayList<>(IMMUTABLE);
    static { ALL_TABLES.add("extraction_runs"); }
    @Autowired JdbcTemplate jdbc;
    @Autowired ReviewedImportReader json;
    @Autowired ReviewedImportService imports;
    @Autowired ExtractionImportService extractions;
    @Autowired HumanHandoffImportService handoffs;
    @Autowired PublicationService publication;
    @Autowired PublicationCommandReader commands;
    @Autowired ExtractionArchiveReader archives;
    @Autowired ReviewReportService reports;
    @MockitoSpyBean ExtractionRunRepository repository;
    @TempDir Path temporary;
    final ObjectMapper mapper = new ObjectMapper().findAndRegisterModules().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    final List<String> ownedCases = new ArrayList<>();
    Path sources, requests, extractionRoot;
    SourceReviewFixtures fixtures;
    ExtractionUploadStore store;
    ExtractionUploadService service;

    @DynamicPropertySource static void python(DynamicPropertyRegistry properties) {
        properties.add("app.calculation.workdir", () -> PythonProbe.REPO.toString());
        properties.add("app.calculation.python-executable", () -> PythonProbe.PYTHON);
        properties.add("app.extraction.timeout-ms", () -> 10000);
    }

    @BeforeEach void setup() throws Exception {
        temporary = temporary.toRealPath();
        sources = directory(temporary.resolve("sources")); requests = directory(temporary.resolve("requests"));
        extractionRoot = directory(temporary.resolve("extractions"));
        fixtures = new SourceReviewFixtures(sources, jdbc, json, imports);
        service = service();
    }

    @AfterEach void cleanupOnlyOwnedPublicationRowsAndFiles() throws Exception {
        try {
            doCallRealMethod().when(repository).insert(any(VerifiedExtraction.class), anyString());
            for (String caseId : ownedCases) {
                String channel = "replay:" + caseId;
                jdbc.update("DELETE FROM publication_audits WHERE channel_key=?", channel);
                jdbc.update("DELETE FROM publication_heads WHERE channel_key=?", channel);
                jdbc.update("DELETE FROM snapshot_revisions WHERE snapshot_id IN (SELECT snapshot_id FROM snapshots WHERE case_id=?)", caseId);
                jdbc.update("DELETE FROM snapshots WHERE case_id=?", caseId);
            }
        } finally { ExtractionArchiveReaderTest.unseal(temporary); }
    }

    @ParameterizedTest @ValueSource(strings = {"one", "three", "failed"})
    void actualPythonAndMysqlKeepEveryAttemptAndExactReplayWithoutCreatingReviewOrPublication(String scenario) throws Exception {
        publishCanary();
        var fixture = fixture(scenario);
        var protectedRows = database(IMMUTABLE); var protectedSourceFiles = tree(sources);
        var beforeRows = database(ALL_TABLES);
        stage(fixture);
        assertThat(database(ALL_TABLES)).isEqualTo(beforeRows);
        assertThat(extractionRoot.resolve(fixture.run())).doesNotExist();
        byte[] finalControl = bytes("\n" + mapper.readTree(fixture.control()).toPrettyString() + "\n ");
        String status = scenario.equals("failed") ? "failed" : "validated";
        registered(fixture, service.finalizeUpload(fixture.run(), finalControl), finalControl, status, false);
        var row = jdbc.queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", fixture.run());
        var originals = tree(extractionRoot); var staged = tree(requests.resolve("extraction-uploads"));
        byte[] receipt = Files.readAllBytes(extractionRoot.resolve(fixture.run()).resolve("receipt.json"));
        stage(fixture);
        registered(fixture, service.finalizeUpload(fixture.run(), finalControl), finalControl, status, true);
        assertThat(jdbc.queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", fixture.run())).isEqualTo(row);
        assertThat(Files.readAllBytes(extractionRoot.resolve(fixture.run()).resolve("receipt.json"))).isEqualTo(receipt);
        assertThat(tree(extractionRoot)).isEqualTo(originals); assertThat(tree(requests.resolve("extraction-uploads"))).isEqualTo(staged);
        var saved = database(ALL_TABLES); var files = selectedFiles();
        rejected(() -> service.initialize(fixture.control(), append(fixture.metadata(), " "), fixture.input()), 409);
        byte[] changedInput = append(fixture.input(), " ");
        rejected(() -> service.initialize(control(fixture.run(), changedInput), fixture.metadata(), changedInput), 409);
        rejected(() -> service.put(fixture.run(), 1, "output", bytes("CHANGED SYNTHETIC OUTPUT")), 409);
        rejected(() -> service.put(fixture.run(), 1, "prompt", bytes("CHANGED SYNTHETIC PROMPT")), 409);
        rejected(() -> service.put(fixture.run(), fixture.outputs().size() + 1, "output", new byte[0]),
                fixture.outputs().size() == 3 ? 422 : 409);
        assertThat(database(ALL_TABLES)).isEqualTo(saved); assertThat(selectedFiles()).isEqualTo(files);
        smallReportKeepsOriginals(fixture);
        assertThat(database(IMMUTABLE)).isEqualTo(protectedRows); assertThat(tree(sources)).isEqualTo(protectedSourceFiles);
    }

    @Test void aCompleteHttpStageResumesTheInterruptedCanonicalBeforeItsFirstMysqlRegistration() throws Exception {
        var fixture = fixture("three"); stage(fixture);
        var staged = store.ready(fixture.run(), sha(fixture.input()));
        JsonNode first = archives.importManual(fixture.run(), extractionRoot, staged.directory().resolve("input.json"),
                staged.directory().resolve("metadata.json"), pairs(staged.directory(), fixture.outputs().size()));
        Path canonical = extractionRoot.resolve(fixture.run()); byte[] identity = Files.readAllBytes(canonical.resolve("identity.json"));
        Files.delete(canonical.resolve("receipt.json")); Files.delete(canonical.resolve("attempt-3.output"));
        var before = database(ALL_TABLES); var stageBefore = tree(requests);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM extraction_runs WHERE run_id=?", Long.class, fixture.run())).isZero();
        registered(fixture, service.finalizeUpload(fixture.run(), fixture.control()), fixture.control(), "validated", false);
        assertThat(Files.readAllBytes(canonical.resolve("identity.json"))).isEqualTo(identity);
        assertThat(json.readJson(canonical.resolve("receipt.json"))).isEqualTo(first);
        // final control의 기존 flat request 보관만 추가되며 staging 원본은 바뀌지 않는다.
        for (var entry : stageBefore.entrySet()) assertThat(tree(requests)).containsEntry(entry.getKey(), entry.getValue());
        assertThat(database(IMMUTABLE)).isEqualTo(withoutExtraction(before));
    }

    @ParameterizedTest @ValueSource(strings = {"actual-sql-conflict", "unavailable"})
    void aLateInsertFailureRollsBackMysqlButKeepsReadyAndFrozenOriginalsForTheSameRetry(String failure) throws Exception {
        var fixture = fixture("failed"); stage(fixture);
        var before = database(ALL_TABLES); var stageBefore = tree(requests.resolve("extraction-uploads"));
        doAnswer(call -> {
            call.callRealMethod();
            assertThat(TransactionSynchronizationManager.isActualTransactionActive()).isTrue();
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM extraction_runs WHERE run_id=?", Long.class, fixture.run())).isEqualTo(1);
            if (failure.equals("actual-sql-conflict"))
                jdbc.update("INSERT INTO extraction_runs SELECT * FROM extraction_runs WHERE run_id=?", fixture.run());
            throw new DataAccessResourceFailureException("SYNTHETIC PRIVATE SQL FAILURE");
        }).when(repository).insert(any(VerifiedExtraction.class), eq(ACTOR));
        try {
            var error = rejected(() -> service.finalizeUpload(fixture.run(), fixture.control()), failure.equals("unavailable") ? 503 : 409);
            assertThat(error.retryable()).isEqualTo(failure.equals("unavailable"));
            assertThat(database(ALL_TABLES)).isEqualTo(before);
            assertThat(store.ready(fixture.run(), sha(fixture.input())).control()).isEqualTo(fixture.control());
            archiveOriginals(fixture, archives.read(fixture.run(), extractionRoot), "failed");
        } finally { doCallRealMethod().when(repository).insert(any(VerifiedExtraction.class), eq(ACTOR)); }
        var originals = tree(extractionRoot); var requestsBeforeRetry = tree(requests);
        registered(fixture, service.finalizeUpload(fixture.run(), fixture.control()), fixture.control(), "failed", false);
        registered(fixture, service.finalizeUpload(fixture.run(), fixture.control()), fixture.control(), "failed", true);
        assertThat(tree(extractionRoot)).isEqualTo(originals); assertThat(tree(requests)).isEqualTo(requestsBeforeRetry);
        assertThat(tree(requests.resolve("extraction-uploads"))).isEqualTo(stageBefore);
        assertThat(database(IMMUTABLE)).isEqualTo(withoutExtraction(before));
    }

    @Test void twoSimultaneousFinalizationsRegisterOneFullRunAndReuseTheSameReceipt() throws Exception {
        var fixture = fixture("three"); stage(fixture); var protectedRows = database(IMMUTABLE);
        var barrier = new CyclicBarrier(2);
        try (var workers = Executors.newVirtualThreadPerTaskExecutor()) {
            var calls = new ArrayList<java.util.concurrent.Future<LocalManagementService.Result>>();
            for (int i = 0; i < 2; i++) calls.add(workers.submit(() -> {
                barrier.await(10, TimeUnit.SECONDS); return service.finalizeUpload(fixture.run(), fixture.control());
            }));
            var responses = new ArrayList<JsonNode>();
            for (var call : calls) responses.add(mapper.valueToTree(call.get(40, TimeUnit.SECONDS)));
            assertThat(responses.stream().map(value -> value.path("data").path("already_registered").asBoolean()).toList())
                    .containsExactlyInAnyOrder(false, true);
            assertThat(responses.stream().map(value -> value.path("data").path("receipt_sha256").asText()).distinct().toList()).hasSize(1);
        }
        registered(fixture, service.finalizeUpload(fixture.run(), fixture.control()), fixture.control(), "validated", true);
        assertThat(database(IMMUTABLE)).isEqualTo(protectedRows);
        try (var bundles = Files.list(requests.resolve("extraction-uploads/bundles"))) { assertThat(bundles.toList()).hasSize(1); }
    }

    @Test void fullHttpSizedPromptAndOutputReachD05WhileTheExistingS10ArtifactLimitRemainsSeparate() throws Exception {
        var base = fixture("one"); byte[] prompt = new byte[20 * 1024 * 1024]; Arrays.fill(prompt, (byte) 'P');
        byte[] output = new byte[5 * 1024 * 1024]; Arrays.fill(output, (byte) 0xff);
        var fixture = new Fixture(base.run(), base.source(), base.control(), base.metadata(), base.input(), List.of(prompt), List.of(output));
        service.initialize(fixture.control(), fixture.metadata(), fixture.input());
        var before = database(ALL_TABLES); var initial = selectedFiles();
        rejected(() -> service.put(fixture.run(), 1, "prompt", new byte[prompt.length + 1]), 413);
        rejected(() -> service.put(fixture.run(), 1, "output", new byte[output.length + 1]), 413);
        assertThat(database(ALL_TABLES)).isEqualTo(before); assertThat(selectedFiles()).isEqualTo(initial);
        service.put(fixture.run(), 1, "prompt", prompt); service.put(fixture.run(), 1, "output", output);
        registered(fixture, service.finalizeUpload(fixture.run(), fixture.control()), fixture.control(), "failed", false);
        var saved = database(ALL_TABLES); var files = selectedFiles();
        assertThatThrownBy(() -> reports.build(UUID.fromString(version(fixture.source())), sources, null))
                .isInstanceOfSatisfying(PublicationException.class, error -> assertThat(error.code()).isEqualTo("REPORT_TOO_LARGE"));
        assertThat(database(ALL_TABLES)).isEqualTo(saved); assertThat(selectedFiles()).isEqualTo(files);
        assertThat(database(IMMUTABLE)).isEqualTo(withoutExtraction(before));
    }

    @Test void selectedSourceRequestAndExtractionRootsRestoreAtTheSamePathsAndReplayAgainstTheUnchangedDatabase() throws Exception {
        var fixture = fixture("three"); stage(fixture);
        registered(fixture, service.finalizeUpload(fixture.run(), fixture.control()), fixture.control(), "validated", false);
        var before = database(ALL_TABLES); var files = selectedFiles();
        Path backup = directory(temporary.resolve("selected-backup"));
        for (Path root : List.of(sources, requests, extractionRoot)) copyTree(root, backup.resolve(root.getFileName()));
        for (Path root : List.of(sources, requests, extractionRoot)) Files.move(root, temporary.resolve("displaced-" + root.getFileName()));
        rejected(() -> service.finalizeUpload(fixture.run(), fixture.control()), 500);
        assertThat(database(ALL_TABLES)).isEqualTo(before);
        for (Path root : List.of(sources, requests, extractionRoot)) copyTree(backup.resolve(root.getFileName()), root);
        service = service();
        assertThat(selectedFiles()).isEqualTo(files);
        stage(fixture);
        registered(fixture, service.finalizeUpload(fixture.run(), fixture.control()), fixture.control(), "validated", true);
        smallReportKeepsOriginals(fixture);
        assertThat(database(ALL_TABLES)).isEqualTo(before); assertThat(selectedFiles()).isEqualTo(files);
    }

    private ExtractionUploadService service() {
        store = new ExtractionUploadStore(requests.toString(), json);
        var environment = new MockEnvironment().withProperty("myai.local-api.actor", ACTOR)
                .withProperty("myai.local-api.source-root", sources.toString()).withProperty("myai.local-api.extraction-root", extractionRoot.toString())
                .withProperty("myai.local-api.handoff-root", sources.toString());
        var management = new LocalManagementService(json, commands, imports, extractions, handoffs, publication,
                new LocalRequestStore(requests.toString()), environment);
        return new ExtractionUploadService(management, archives, store, json, extractionRoot.toString());
    }

    private Fixture fixture(String scenario) throws Exception {
        var source = fixtures.source(true); fixtures.register(source); String run = UUID.randomUUID().toString(); var doc = document(source);
        var input = mapper.createObjectNode(); input.set("data_kind", source.path("data_kind"));
        for (String field : List.of("document_version_id", "title", "published_date")) input.set(field, doc.path(field));
        input.set("blocks", doc.path("block_index"));
        var output = (ObjectNode) mapper.readTree(PythonProbe.REPO.resolve("contracts/examples/ai-extraction.json").toFile());
        output.put("document_version_id", version(source)); var block = doc.path("block_index").get(0); String content = block.path("text").asText();
        ((ObjectNode) output.path("evidence").get(0)).put("block_id", block.path("block_id").asText()).put("quote", content)
                .put("start_char", 0).put("end_char", content.codePointCount(0, content.length())).put("text_sha256", sha(bytes(content)));
        var outputs = switch (scenario) {
            case "one" -> List.of(bytes(output.toString()));
            case "three" -> List.of(bytes("{broken"), new byte[] {(byte) 0xff, 0}, bytes(output.toString()));
            case "failed" -> List.of(bytes("{broken"), new byte[0], new byte[] {(byte) 0xff, 0});
            default -> throw new IllegalArgumentException("Unknown synthetic scenario");
        };
        var metadata = (ObjectNode) mapper.readTree(PythonProbe.REPO.resolve("processing/examples/extraction-metadata.json").toFile());
        metadata.put("run_id", run).put("document_version_id", version(source)).put("attempts", outputs.size())
                .put("preprocessing_version", doc.path("preprocessing_version").asText()).putNull("provider");
        ((ObjectNode) metadata.path("unavailable_reasons")).put("provider", "합성 시험 😀; 실제 모델 호출 없음");
        metadata.put("started_at", "2026-11-03T01:00:00.123456789Z").put("finished_at", "2026-11-03T01:00:00.123456790Z");
        String rawMetadata = mapper.writerWithDefaultPrettyPrinter().writeValueAsString(metadata)
                .replace("\"cost\" : null", "\"cost\" : 0.1234567890123456789");
        assertThat(rawMetadata).contains("0.1234567890123456789", "2026-11-03T01:00:00.123456789Z", "합성 시험 😀");
        byte[] rawInput = bytes(" \n" + input.toPrettyString() + "\n ");
        var prompts = new ArrayList<byte[]>(); for (int index = 1; index <= outputs.size(); index++) prompts.add(bytes("합성 수동 입력 " + index + " 😀\r\n"));
        return new Fixture(run, source, control(run, rawInput), bytes(" \n" + rawMetadata + "\n "), rawInput, List.copyOf(prompts), outputs);
    }

    private void stage(Fixture fixture) {
        service.initialize(fixture.control(), fixture.metadata(), fixture.input());
        for (int index = fixture.outputs().size() - 1; index >= 0; index--) {
            service.put(fixture.run(), index + 1, "output", fixture.outputs().get(index));
            service.put(fixture.run(), index + 1, "prompt", fixture.prompts().get(index));
        }
    }

    private void registered(Fixture fixture, LocalManagementService.Result response, byte[] control, String status, boolean replay) throws Exception {
        JsonNode result = mapper.valueToTree(response); JsonNode data = result.path("data");
        assertThat(result.path("schema_version").asText()).isEqualTo("local-management-result-v1");
        assertThat(result.path("request_sha256").asText()).isEqualTo(sha(control));
        assertThat(Files.readAllBytes(requests.resolve(sha(control) + ".json"))).isEqualTo(control);
        assertThat(data.path("run_id").asText()).isEqualTo(fixture.run()); assertThat(data.path("status").asText()).isEqualTo(status);
        assertThat(data.path("attempts").asInt()).isEqualTo(fixture.outputs().size());
        assertThat(data.path("already_registered").asBoolean()).isEqualTo(replay); assertThat(data.path("review_required").asBoolean()).isTrue();
        var row = jdbc.queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", fixture.run());
        assertThat(row.get("document_version_id")).isEqualTo(version(fixture.source())); assertThat(row.get("status")).isEqualTo(status);
        assertThat(row.get("execution_mode")).isEqualTo("manual_import"); assertThat(row.get("input_sha256")).isEqualTo(sha(fixture.input()));
        assertThat(row.get("output_sha256")).isEqualTo(sha(fixture.outputs().getLast()));
        assertThat(row.get("metadata_json")).isEqualTo(new String(fixture.metadata(), StandardCharsets.UTF_8));
        assertThat(row.get("metadata_sha256")).isEqualTo(sha(fixture.metadata()));
        assertThat(row.get("registered_by")).isEqualTo(ACTOR); assertThat(row.get("provider")).isNull(); assertThat(row.get("model")).isNull();
        assertThat(row.get("model_version")).isNull(); assertThat(((Number) row.get("attempts")).intValue()).isEqualTo(fixture.outputs().size());
        Path frozen = Path.of(row.get("raw_ref").toString()); assertThat(frozen).isNotEqualTo(extractionRoot.resolve(fixture.run()));
        var verified = archives.readSealed(fixture.run(), frozen.getParent()); archiveOriginals(fixture, verified, status);
        byte[] receipt = Files.readAllBytes(frozen.resolve("receipt.json"));
        assertThat(row.get("receipt_json")).isEqualTo(new String(receipt, StandardCharsets.UTF_8));
        assertThat(row.get("receipt_sha256")).isEqualTo(sha(receipt)); assertThat(data.path("receipt_sha256").asText()).isEqualTo(sha(receipt));
        assertThat(Files.readAllBytes(extractionRoot.resolve(fixture.run()).resolve("receipt.json"))).isEqualTo(receipt);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM extraction_runs WHERE run_id=?", Long.class, fixture.run())).isEqualTo(1);
        var d03 = mapper.readTree(jdbc.queryForObject("SELECT metadata_json FROM document_versions WHERE document_version_id=?", String.class, version(fixture.source())));
        assertThat(d03.path("document")).isEqualTo(document(fixture.source()));
        assertThat(d03.path("document").path("use_review").asText()).isEqualTo("pending");
        assertThat(d03.path("document").path("check_result").asText()).isEqualTo("unchecked");
    }

    private void archiveOriginals(Fixture fixture, VerifiedExtraction verified, String status) throws Exception {
        var expected = originals(fixture); assertThat(ExtractionArchiveReader.artifactNames(verified.receipt())).containsExactlyInAnyOrderElementsOf(expected.keySet());
        assertThat(verified.receipt().path("status").asText()).isEqualTo(status); assertThat(verified.receipt().path("review_required").asBoolean()).isTrue();
        var expectedStatuses = new ArrayList<String>(); for (int i = 0; i < fixture.outputs().size(); i++)
            expectedStatuses.add(status.equals("validated") && i == fixture.outputs().size() - 1 ? "validated" : "failed");
        assertThat(verified.receipt().path("attempts").findValuesAsText("status")).containsExactlyElementsOf(expectedStatuses);
        for (var entry : expected.entrySet()) {
            assertThat(Files.readAllBytes(verified.directory().resolve(entry.getKey()))).isEqualTo(entry.getValue());
            assertThat(Files.readAllBytes(extractionRoot.resolve(fixture.run()).resolve(entry.getKey()))).isEqualTo(entry.getValue());
            JsonNode artifact = verified.receipt().path("artifacts").path(entry.getKey());
            assertThat(artifact.path("size").asLong()).isEqualTo(entry.getValue().length); assertThat(artifact.path("sha256").asText()).isEqualTo(sha(entry.getValue()));
        }
        try (var paths = Files.walk(verified.directory())) {
            for (Path path : paths.toList()) assertThat(PosixFilePermissions.toString(Files.getPosixFilePermissions(path)))
                    .isEqualTo(Files.isDirectory(path) ? "r-x------" : "r--------");
        }
    }

    private void smallReportKeepsOriginals(Fixture fixture) throws Exception {
        var before = database(ALL_TABLES); var files = selectedFiles();
        JsonNode report = reports.build(UUID.fromString(version(fixture.source())), sources, null), selected = null;
        for (JsonNode run : report.path("extractions")) if (run.path("database").path("run_id").asText().equals(fixture.run())) selected = run;
        assertThat(selected).isNotNull(); assertThat(selected.path("validation").path("status").asText()).isEqualTo("valid");
        assertThat(report.path("events")).isEmpty();
        for (var entry : originals(fixture).entrySet()) {
            JsonNode artifact = selected.path("artifacts").path(entry.getKey());
            byte[] embedded = artifact.path("encoding").asText().equals("base64") ? Base64.getDecoder().decode(artifact.path("base64").asText())
                    : bytes(artifact.path("text").asText());
            assertThat(embedded).isEqualTo(entry.getValue()); assertThat(artifact.path("sha256").asText()).isEqualTo(sha(entry.getValue()));
        }
        assertThat(database(ALL_TABLES)).isEqualTo(before); assertThat(selectedFiles()).isEqualTo(files);
    }

    private void publishCanary() throws Exception {
        var input = fixtures.human(false); fixtures.register(input); String event = SourceReviewFixtures.event(input);
        String revision = jdbc.queryForObject("SELECT current_review_revision_id FROM events WHERE event_id=?", String.class, event);
        var evidence = new ArrayList<String>(); mapper.readTree(jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id=?", String.class, revision))
                .path("evidence").forEach(value -> evidence.add(value.path("evidence_id").asText()));
        var approved = publication.execute(new PublicationCommand.Decision("publication-command-v1", "approve", "합성 공개 불변 시험",
                UUID.fromString(event), 1, evidence), sources, "synthetic-upload-canary-approver");
        var command = (ObjectNode) mapper.readTree(Path.of("examples/publish.json").toFile()); String caseId = UUID.randomUUID().toString(); ownedCases.add(caseId);
        String area = input.path("events").get(0).path("area_id").asText();
        command.put("mode", "replay").put("case_id", caseId).put("anchor_date", "2026-11-03").put("reference_instant", "2026-11-03T00:00:00Z")
                .put("knowledge_cutoff", "2026-11-03T00:00:00Z").put("history_fidelity", "reconstructed").putNull("expected_head_version");
        ((ObjectNode) command.path("area")).put("area_id", area);
        for (var point : command.path("points")) ((ObjectNode) point).put("area_id", area).put("point_id", UUID.randomUUID().toString());
        command.putArray("revision_ids").add(approved.revisionId());
        Path file = Files.writeString(sources.resolve("canary-publish.json"), command.toString());
        String snapshot = publication.execute(commands.read(file), sources, "synthetic-upload-canary-publisher").snapshotId();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM snapshot_revisions WHERE snapshot_id=?", Long.class, snapshot)).isPositive();
    }

    private Map<String, byte[]> originals(Fixture fixture) {
        var files = new TreeMap<String, byte[]>(); files.put("input.json", fixture.input()); files.put("metadata.json", fixture.metadata());
        for (int i = 0; i < fixture.outputs().size(); i++) { files.put("attempt-" + (i + 1) + ".prompt", fixture.prompts().get(i)); files.put("attempt-" + (i + 1) + ".output", fixture.outputs().get(i)); }
        return files;
    }
    private List<ExtractionArchiveReader.AttemptFiles> pairs(Path directory, int attempts) {
        var pairs = new ArrayList<ExtractionArchiveReader.AttemptFiles>(); for (int i = 1; i <= attempts; i++) pairs.add(new ExtractionArchiveReader.AttemptFiles(directory.resolve("attempt-" + i + ".prompt"), directory.resolve("attempt-" + i + ".output"))); return pairs;
    }
    private Map<String, List<Map<String, String>>> database(List<String> tables) {
        var result = new LinkedHashMap<String, List<Map<String, String>>>(); var order = Comparator.nullsFirst(Comparator.<String>naturalOrder());
        for (String table : tables) {
            var rows = new ArrayList<Map<String, String>>();
            // 큰 JSON 전체 행을 DB 정렬 버퍼에 싣지 않고 모든 열/null/값을 Java에서 정렬한다.
            for (var row : jdbc.queryForList("SELECT * FROM " + table)) { var values = new LinkedHashMap<String, String>(); row.forEach((key, value) -> values.put(key, value == null ? null : value.toString())); rows.add(values); }
            rows.sort((left, right) -> { for (String column : left.keySet()) { int compared = order.compare(left.get(column), right.get(column)); if (compared != 0) return compared; } return 0; }); result.put(table, rows);
        }
        return result;
    }
    private Map<String, List<Map<String, String>>> withoutExtraction(Map<String, List<Map<String, String>>> value) { var copy = new LinkedHashMap<>(value); copy.remove("extraction_runs"); return copy; }
    private Map<String, String> selectedFiles() throws Exception { var files = new TreeMap<String, String>(); for (Path root : List.of(sources, requests, extractionRoot)) tree(root).forEach((name, hash) -> files.put(root.getFileName() + "/" + name, hash)); return files; }
    private Map<String, String> tree(Path root) throws Exception { var files = new TreeMap<String, String>(); try (var paths = Files.walk(root)) { for (Path path : paths.toList()) files.put(root.relativize(path).toString(), PosixFilePermissions.toString(Files.getPosixFilePermissions(path)) + ":" + (Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) ? sha(Files.readAllBytes(path)) : "directory")); } return files; }
    private void copyTree(Path source, Path target) throws Exception { try (var paths = Files.walk(source)) { for (Path path : paths.toList()) { Path copy = target.resolve(source.relativize(path)); if (Files.isDirectory(path)) directory(copy); else Files.copy(path, copy, StandardCopyOption.COPY_ATTRIBUTES); } } try (var paths = Files.walk(source)) { for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) Files.setPosixFilePermissions(target.resolve(source.relativize(path)), Files.getPosixFilePermissions(path)); } }
    private ApiException rejected(ThrowingCallable action, int status) { var thrown = catchThrowable(action); assertThat(thrown).isInstanceOf(ApiException.class); var error = (ApiException) thrown; assertThat(error.status().value()).isEqualTo(status); assertThat(error.getMessage()).doesNotContain(temporary.toString(), "SYNTHETIC PRIVATE SQL FAILURE", "CHANGED SYNTHETIC", "합성 수동 입력"); return error; }
    private byte[] control(String run, byte[] input) throws Exception { return bytes(" \n" + mapper.createObjectNode().put("schema_version", "extraction-import-request-v1").put("run_id", run).put("expected_input_hash", sha(input)) + "\n "); }
    private static byte[] bytes(String value) { return value.getBytes(StandardCharsets.UTF_8); }
    private byte[] append(byte[] value, String suffix) { return bytes(new String(value, StandardCharsets.UTF_8) + suffix); }
    private String sha(byte[] value) throws Exception { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value)); }
    private Path directory(Path path) throws Exception { return Files.createDirectory(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))).toRealPath(); }
    private record Fixture(String run, ObjectNode source, byte[] control, byte[] metadata, byte[] input, List<byte[]> prompts, List<byte[]> outputs) { }
}
