package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.controller.ApiExceptionHandler;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.local.*;
import kr.ac.myai.backend.logging.PublicRequestLogFilter;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.repository.ReviewedImportRepository;
import kr.ac.myai.backend.review.ReviewReportService;
import kr.ac.myai.backend.service.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.http.converter.ByteArrayHttpMessageConverter;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockPart;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.request.MockMultipartHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.doCallRealMethod;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class SourceUploadMySqlTest {
    private static final String TOKEN = "SYNTHETIC_UPLOAD_MYSQL_TOKEN_0123456789";
    private static final String ACTOR = "synthetic-upload-mysql-manager";
    private static final List<String> NON_SOURCE_TABLES = List.of("source_checks", "source_reviews", "extraction_runs", "events",
            "event_revisions", "review_audits", "snapshots", "snapshot_revisions", "publication_heads", "publication_audits");
    @Autowired JdbcTemplate jdbc;
    @Autowired ReviewedImportReader reader;
    @Autowired ReviewedImportService imports;
    @Autowired ExtractionImportService extractions;
    @Autowired HumanHandoffImportService handoffs;
    @Autowired PublicationService publication;
    @Autowired PublicationCommandReader commands;
    @Autowired ReviewReportService reports;
    @MockitoSpyBean ReviewedImportRepository repository;
    @TempDir Path temporary;
    final ObjectMapper json = new ObjectMapper().findAndRegisterModules().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    Path sources, requests;
    SourceUploadStore store;
    MockMvc local;

    @DynamicPropertySource static void python(DynamicPropertyRegistry properties) {
        properties.add("app.calculation.workdir", () -> PythonProbe.REPO.toString());
        properties.add("app.calculation.python-executable", () -> PythonProbe.PYTHON);
    }

    @BeforeEach void setup() throws Exception {
        temporary = temporary.toRealPath();
        sources = directory(temporary.resolve("sources")); requests = directory(temporary.resolve("requests"));
        mvc();
    }

    @ParameterizedTest @ValueSource(strings = {"txt", "pdf", "json"})
    void multipartFormatsRegisterPendingD03WithExactOriginalsAndPythonProjection(String format) throws Exception {
        var meta = metadata(format); byte[] metadata = bytes(" \n" + meta.toPrettyString() + "\n ");
        byte[] raw = switch (format) {
            case "pdf" -> pdf();
            case "json" -> bytes("{\"schema_version\":\"text-body-v1\",\"text\":\"합성 공지 😀\\n문의 a@b.test\"}");
            default -> bytes(" ".repeat(210_000) + "\n합성 공지 😀\r\n문의 a@b.test\n" + " ".repeat(210_000));
        };
        var untouched = counts(NON_SOURCE_TABLES);
        var first = upload(metadata, raw, format);
        var saved = registered(meta, metadata, raw, first);
        var before = database(); var originalFiles = files();
        var replay = upload(metadata, raw, format);
        assertThat(replay.path("data").path("already_imported").asBoolean()).isTrue();
        assertThat(replay.path("data").path("import_id")).isEqualTo(first.path("data").path("import_id"));
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(originalFiles);
        assertThat(counts(NON_SOURCE_TABLES)).isEqualTo(untouched);
        assertThat(reader.parseJson(saved.sourceImport()).path("documents").get(0).path("redaction_log").toString()).doesNotContain("a@b.test");
        assertThat(first.path("text_scope").asText()).isEqualTo(format.equals("pdf") ? "embedded_text_only" : "provided_text");
        assertThat(first.path("text_review_required").asBoolean()).isEqualTo(format.equals("pdf"));
    }

    @ParameterizedTest @ValueSource(ints = {8 * 1024 * 1024 + 1, 20 * 1024 * 1024})
    void largerRawJsonKeepsSmallPreparedJsonAndTheFullS10Original(int size) throws Exception {
        var meta = metadata("json"); byte[] metadata = bytes(meta.toString());
        byte[] body = bytes("{\"schema_version\":\"text-body-v1\",\"text\":\"SYNTHETIC NOTICE\"}");
        byte[] raw = Arrays.copyOf(body, size); Arrays.fill(raw, body.length, size, (byte) ' ');
        var untouched = counts(NON_SOURCE_TABLES);
        var saved = registered(meta, metadata, raw, upload(metadata, raw, "json"));
        assertThat(saved.sourceImport().length).isLessThan(8 * 1024 * 1024);
        assertThat(saved.aiInput().length).isLessThan(8 * 1024 * 1024);
        var before = database(); var originalFiles = files();
        var report = reports.build(UUID.fromString(meta.path("document_version_id").asText()), sources, null);
        var asset = report.path("documents").get(0).path("raw_asset");
        assertThat(asset.path("validation").path("status").asText()).isEqualTo("valid");
        assertThat(asset.path("size").asInt()).isEqualTo(size);
        assertThat(asset.path("sha256").asText()).isEqualTo(sha(raw));
        assertThat(asset.path("text").asText().getBytes(StandardCharsets.UTF_8)).isEqualTo(raw);
        assertThat(report.path("events")).isEmpty(); assertThat(report.path("extractions")).isEmpty();
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(originalFiles);
        assertThat(counts(NON_SOURCE_TABLES)).isEqualTo(untouched);
    }

    @Test void changedOriginalConflictsAndOldJsonAndNewRawLimitsLeaveRowsAndFilesIntact() throws Exception {
        var meta = metadata("txt"); byte[] metadata = bytes(meta.toString()), raw = bytes("SYNTHETIC NOTICE");
        var saved = registered(meta, metadata, raw, upload(metadata, raw, "txt"));
        var before = database(); var originalFiles = files();
        local.perform(request(bytes(meta.toString() + " "), raw, "txt")).andExpect(status().isConflict());
        assertThat(database()).isEqualTo(before);
        local.perform(request(metadata, bytes("CHANGED SYNTHETIC NOTICE"), "txt")).andExpect(status().isConflict());
        assertThat(database()).isEqualTo(before);
        for (var entry : originalFiles.entrySet()) assertThat(files()).containsEntry(entry.getKey(), entry.getValue());
        byte[] padded = Arrays.copyOf(saved.sourceImport(), 8 * 1024 * 1024);
        Arrays.fill(padded, saved.sourceImport().length, padded.length, (byte) ' ');
        local.perform(auth(post("/local/documents")).contentType(MediaType.APPLICATION_JSON).content(padded)).andExpect(status().isOk());
        before = database(); originalFiles = files();
        byte[] tooMuchJson = Arrays.copyOf(padded, padded.length + 1); tooMuchJson[tooMuchJson.length - 1] = ' ';
        local.perform(auth(post("/local/documents")).contentType(MediaType.APPLICATION_JSON).content(tooMuchJson))
                .andExpect(status().isPayloadTooLarge());
        local.perform(request(metadata, new byte[20 * 1024 * 1024 + 1], "txt")).andExpect(status().isPayloadTooLarge());
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(originalFiles);
    }

    @Test void lateActualSqlFailureRollsBackD03AndLeavesTheReadyOriginalForRetry() throws Exception {
        var meta = metadata("txt"); byte[] metadata = bytes(meta.toString()), raw = bytes("SYNTHETIC SQL ROLLBACK NOTICE");
        var before = database();
        doAnswer(call -> {
            call.callRealMethod();
            var result = call.getArgument(0, ReviewedImportService.ImportResult.class);
            jdbc.update("INSERT INTO import_batches SELECT * FROM import_batches WHERE import_id=?", result.importId());
            return null;
        }).when(repository).completeBatch(any(), any());
        try {
            local.perform(request(metadata, raw, "txt")).andExpect(status().isConflict());
            assertThat(database()).isEqualTo(before);
            assertThat(store.find(meta.path("document_version_id").asText(), metadata, raw)).isNotNull();
            assertThat(Files.readAllBytes(sources.resolve("uploads/" + sha(raw) + ".txt"))).isEqualTo(raw);
        } finally { doCallRealMethod().when(repository).completeBatch(any(), any()); }
        var prepared = files();
        registered(meta, metadata, raw, upload(metadata, raw, "txt"));
        assertThat(files()).isEqualTo(prepared);
    }

    @Test void concurrentIdenticalUploadsRegisterOneCompleteD03AndOneReadyBundle() throws Exception {
        var meta = metadata("txt"); byte[] metadata = bytes(meta.toString()), raw = bytes("SYNTHETIC CONCURRENT NOTICE");
        var untouched = counts(NON_SOURCE_TABLES); var barrier = new CyclicBarrier(2);
        try (var workers = Executors.newVirtualThreadPerTaskExecutor()) {
            var calls = new ArrayList<java.util.concurrent.Future<JsonNode>>();
            for (int i = 0; i < 2; i++) calls.add(workers.submit(() -> { barrier.await(10, TimeUnit.SECONDS); return upload(metadata, raw, "txt"); }));
            var first = calls.get(0).get(30, TimeUnit.SECONDS); var second = calls.get(1).get(30, TimeUnit.SECONDS);
            assertThat(first.path("data").path("import_id")).isEqualTo(second.path("data").path("import_id"));
            assertThat(List.of(first.path("data").path("already_imported").asBoolean(), second.path("data").path("already_imported").asBoolean()))
                    .containsExactlyInAnyOrder(false, true);
            registered(meta, metadata, raw, first);
        }
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM document_versions WHERE document_version_id=?", Long.class, meta.path("document_version_id").asText())).isEqualTo(1);
        try (var bundles = Files.list(requests.resolve("uploads/bundles"))) { assertThat(bundles.toList()).hasSize(1); }
        assertThat(counts(NON_SOURCE_TABLES)).isEqualTo(untouched);
    }

    @Test void selectedSourceAndRequestFilesRestoreAtTheirOriginalPathsAndReplayWithoutNewRows() throws Exception {
        var meta = metadata("json"); byte[] metadata = bytes(meta.toString());
        byte[] raw = bytes("{\"schema_version\":\"text-body-v1\",\"text\":\"SYNTHETIC RESTORE NOTICE\"}");
        var first = upload(metadata, raw, "json"); registered(meta, metadata, raw, first);
        var before = database(); var originalFiles = files();
        Path sourceBackup = temporary.resolve("source-backup"), requestBackup = temporary.resolve("request-backup");
        copyTree(sources, sourceBackup); copyTree(requests, requestBackup);
        Path displacedSource = temporary.resolve("displaced-source"), displacedRequest = temporary.resolve("displaced-request");
        Files.move(sources, displacedSource); Files.move(requests, displacedRequest);
        local.perform(request(metadata, raw, "json")).andExpect(status().isInternalServerError());
        assertThat(database()).isEqualTo(before);
        copyTree(sourceBackup, sources); copyTree(requestBackup, requests); mvc();
        assertThat(files()).isEqualTo(originalFiles);
        assertThat(upload(metadata, raw, "json").path("data").path("already_imported").asBoolean()).isTrue();
        registered(meta, metadata, raw, first);
        var report = reports.build(UUID.fromString(meta.path("document_version_id").asText()), sources, null);
        assertThat(report.path("documents").get(0).path("raw_asset").path("text").asText().getBytes(StandardCharsets.UTF_8)).isEqualTo(raw);
        assertThat(report.path("documents").get(0).path("original").path("use_review").asText()).isEqualTo("pending");
        assertThat(database()).isEqualTo(before); assertThat(files()).isEqualTo(originalFiles);
        assertThat(fileTree(displacedSource)).isEqualTo(fileTree(sources));
        assertThat(fileTree(displacedRequest)).isEqualTo(fileTree(requests));
    }

    private SourceUploadStore.Stored registered(ObjectNode meta, byte[] metadata, byte[] raw, JsonNode response) throws Exception {
        String version = meta.path("document_version_id").asText();
        assertThat(response.path("schema_version").asText()).isEqualTo("source-upload-result-v1");
        assertThat(response.path("document_id")).isEqualTo(meta.path("document_id"));
        assertThat(response.path("document_version_id").asText()).isEqualTo(version);
        assertThat(response.path("raw_sha256").asText()).isEqualTo(sha(raw));
        var saved = store.find(version, metadata, raw); assertThat(saved).isNotNull();
        var source = reader.parseJson(saved.sourceImport()); var doc = source.path("documents").get(0);
        var row = jdbc.queryForMap("SELECT * FROM document_versions WHERE document_version_id=?", version);
        assertThat(json.readTree(row.get("metadata_json").toString()).path("document")).isEqualTo(doc);
        assertThat(row.get("private_content_ref")).isEqualTo(doc.path("raw_asset_path").asText());
        assertThat(Files.readAllBytes(sources.resolve(doc.path("raw_asset_path").asText()))).isEqualTo(raw);
        assertThat(Files.readAllBytes(requests.resolve(sha(metadata) + ".json"))).isEqualTo(metadata);
        assertThat(doc.path("use_review").asText()).isEqualTo("pending");
        assertThat(doc.path("check_result").asText()).isEqualTo("unchecked"); assertThat(doc.path("checks")).isEmpty();
        assertThat(doc.path("latest_check_attempt_at").isNull()).isTrue(); assertThat(doc.path("last_verified_at").isNull()).isTrue();
        assertThat(saved.receipt().path("metadata_sha256").asText()).isEqualTo(sha(metadata));
        assertThat(saved.receipt().path("source_import_sha256").asText()).isEqualTo(sha(saved.sourceImport()));
        assertThat(saved.receipt().path("ai_input_sha256").asText()).isEqualTo(sha(saved.aiInput()));
        assertThat(response.path("input_hash").asText()).isEqualTo(sha(saved.aiInput()));
        assertThat(jdbc.queryForObject("SELECT input_sha256 FROM import_batches WHERE import_id=?", String.class,
                response.path("data").path("import_id").asText())).isEqualTo(sha(saved.sourceImport()));
        python(saved);
        for (Path root : List.of(sources, requests)) try (var paths = Files.walk(root)) {
            for (Path path : paths.toList()) assertThat(PosixFilePermissions.toString(Files.getPosixFilePermissions(path)))
                    .isEqualTo(Files.isDirectory(path) ? "rwx------" : "rw-------");
        }
        return saved;
    }

    private void python(SourceUploadStore.Stored saved) throws Exception {
        var packet = json.createObjectNode().put("source", Base64.getEncoder().encodeToString(saved.sourceImport()))
                .put("input", Base64.getEncoder().encodeToString(saved.aiInput()));
        packet.set("receipt", saved.receipt());
        String script = """
                import sys,json,base64,hashlib
                from processing.extraction.validation import parse_input
                from processing.extraction.draft import _context,_source
                packet=json.loads(sys.stdin.buffer.read())
                source=json.loads(base64.b64decode(packet['source']))
                raw=base64.b64decode(packet['input'])
                document=parse_input(raw)
                doc=_context('11111111-1111-4111-8111-111111111111',source,
                    '22222222-2222-4222-8222-222222222222','33333333-3333-4333-8333-333333333333','synthetic-only')
                _source(source,doc,document,packet['receipt'])
                print(json.dumps(dict(input_sha256=hashlib.sha256(raw).hexdigest(),
                    text_sha256=hashlib.sha256(doc['cleaned_text'].encode('utf-8')).hexdigest())))
                """;
        var builder = new ProcessBuilder(PythonProbe.PYTHON, "-c", script).directory(PythonProbe.REPO.toFile());
        builder.environment().clear(); builder.environment().put("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin");
        builder.environment().put("PYTHONDONTWRITEBYTECODE", "1"); builder.environment().put("PYTHONNOUSERSITE", "1");
        var process = builder.start();
        try {
            try (var stdin = process.getOutputStream()) { stdin.write(bytes(packet.toString())); }
            assertThat(process.waitFor(10, TimeUnit.SECONDS)).isTrue();
            assertThat(process.exitValue()).isZero();
            var proof = json.readTree(process.getInputStream().readAllBytes());
            assertThat(proof.path("input_sha256").asText()).isEqualTo(sha(saved.aiInput()));
            assertThat(proof.path("text_sha256").asText()).isEqualTo(reader.parseJson(saved.sourceImport()).path("documents").get(0).path("text_sha256").asText());
        } finally { if (process.isAlive()) { process.destroyForcibly(); assertThat(process.waitFor(5, TimeUnit.SECONDS)).isTrue(); } }
    }

    private void mvc() {
        var env = new MockEnvironment().withProperty("myai.local-api.token", TOKEN).withProperty("myai.local-api.actor", ACTOR)
                .withProperty("myai.local-api.source-root", sources.toString()).withProperty("myai.local-api.request-root", requests.toString())
                .withProperty("myai.local-api.extraction-root", temporary.toString()).withProperty("myai.local-api.handoff-root", temporary.toString());
        var requestStore = new LocalRequestStore(requests.toString()); store = new SourceUploadStore(sources.toString(), requests.toString());
        var management = new LocalManagementService(reader, commands, imports, extractions, handoffs, publication, requestStore, env);
        String tool = Files.isExecutable(Path.of("/opt/homebrew/bin/pdftotext")) ? "/opt/homebrew/bin/pdftotext" : "/usr/bin/pdftotext";
        assertThat(Files.isExecutable(Path.of(tool))).isTrue();
        var upload = new SourceUploadService(management, reader, store, new SourceTextPreprocessor(new PdfTextExtractor(tool)), requestStore, sources.toString());
        local = MockMvcBuilders.standaloneSetup(new LocalManagementController(management, upload))
                .setControllerAdvice(new ApiExceptionHandler(), new LocalBodyLimitAdvice())
                .setMessageConverters(new ByteArrayHttpMessageConverter(), new MappingJackson2HttpMessageConverter(json))
                .addFilters(new PublicRequestLogFilter(), new LocalApiSecurityFilter(env, json)).build();
    }

    private JsonNode upload(byte[] metadata, byte[] raw, String format) throws Exception {
        var response = local.perform(request(metadata, raw, format)).andExpect(status().isOk()).andReturn().getResponse();
        assertThat(response.getContentAsString()).doesNotContain(TOKEN, sources.toString(), requests.toString(), "PRIVATE_FILENAME");
        return json.readTree(response.getContentAsByteArray());
    }

    private MockMultipartHttpServletRequestBuilder request(byte[] metadata, byte[] raw, String format) {
        String media = switch (format) { case "txt" -> "text/plain"; case "pdf" -> "application/pdf"; default -> "application/json"; };
        var meta = new MockPart("metadata", metadata); meta.getHeaders().setContentType(MediaType.APPLICATION_JSON);
        var file = new MockPart("file", "../../PRIVATE_FILENAME." + format, raw); file.getHeaders().setContentType(MediaType.parseMediaType(media));
        var request = multipart("/local/documents").part(meta, file); auth(request); return request;
    }

    private MockHttpServletRequestBuilder auth(MockHttpServletRequestBuilder request) {
        return request.header("Authorization", "Bearer " + TOKEN).header("Host", "127.0.0.1:49123").header("Origin", "http://127.0.0.1:49123")
                .with(input -> { input.setLocalAddr("127.0.0.1"); input.setRemoteAddr("127.0.0.1"); input.setLocalPort(49123); input.setServerPort(49123); return input; });
    }

    private ObjectNode metadata(String format) {
        return json.createObjectNode().put("schema_version", "source-upload-v1").put("format", format).put("data_kind", "synthetic")
                .put("document_id", UUID.randomUUID().toString()).put("document_version_id", UUID.randomUUID().toString()).put("version_no", 1)
                .put("publisher", "합성 기관").put("official_url", "https://example.invalid/notice/1").put("title", "합성 공지")
                .putNull("official_number").putNull("published_date").put("collected_at", "2026-11-02T00:00:00Z")
                .put("collection_method", "synthetic fixture").put("use_note", "synthetic only; not approved for publication");
    }

    private Path directory(Path path) throws Exception { return Files.createDirectory(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))).toRealPath(); }
    private byte[] bytes(String value) { return value.getBytes(StandardCharsets.UTF_8); }
    private String sha(byte[] value) throws Exception { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value)); }
    private Map<String, Long> counts(List<String> tables) { var result = new TreeMap<String, Long>(); for (String table : tables) result.put(table, jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Long.class)); return result; }
    private JsonNode database() {
        var out = json.createObjectNode();
        var valueOrder = Comparator.nullsFirst(Comparator.<String>naturalOrder());
        for (String table : jdbc.queryForList("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME", String.class)) {
            var rows = new ArrayList<ObjectNode>();
            // 큰 JSON 행을 MySQL 정렬 버퍼에 싣지 않고 전체 값을 Java에서 정렬한다.
            for (var row : jdbc.queryForList("SELECT * FROM `" + table + "`")) {
                var value = json.createObjectNode();
                row.forEach((key, entry) -> value.put(key, entry == null ? null : entry.toString()));
                rows.add(value);
            }
            rows.sort((left, right) -> {
                var columns = left.fieldNames();
                while (columns.hasNext()) {
                    String column = columns.next();
                    int compared = valueOrder.compare(left.path(column).textValue(), right.path(column).textValue());
                    if (compared != 0) return compared;
                }
                return 0;
            });
            out.putArray(table).addAll(rows);
        }
        return out;
    }
    private Map<String, String> files() throws Exception { var result = new TreeMap<String, String>(); fileTree(sources).forEach((name, hash) -> result.put("sources/" + name, hash)); fileTree(requests).forEach((name, hash) -> result.put("requests/" + name, hash)); return result; }
    private Map<String, String> fileTree(Path root) throws Exception { var result = new TreeMap<String, String>(); try (var files = Files.walk(root)) { for (Path path : files.toList()) result.put(root.relativize(path).toString(), PosixFilePermissions.toString(Files.getPosixFilePermissions(path)) + (Files.isRegularFile(path) ? sha(Files.readAllBytes(path)) : "")); } return result; }
    private void copyTree(Path source, Path target) throws Exception { try (var paths = Files.walk(source)) { for (Path path : paths.toList()) { Path copy = target.resolve(source.relativize(path)); if (Files.isDirectory(path)) directory(copy); else Files.copy(path, copy, StandardCopyOption.COPY_ATTRIBUTES); } } }

    private byte[] pdf() throws Exception {
        var objects = new ArrayList<>(List.of("<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
                "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"));
        String stream = "BT /F1 12 Tf 72 720 Td (SYNTHETIC NOTICE) Tj ET\n";
        objects.add("<< /Length " + stream.length() + " >>\nstream\n" + stream + "endstream");
        var output = new ByteArrayOutputStream(); output.write(bytes("%PDF-1.4\n")); var offsets = new ArrayList<Integer>();
        for (int i = 0; i < objects.size(); i++) { offsets.add(output.size()); output.write(bytes((i + 1) + " 0 obj\n" + objects.get(i) + "\nendobj\n")); }
        int xref = output.size(); output.write(bytes("xref\n0 6\n0000000000 65535 f \n"));
        for (int offset : offsets) output.write(bytes(String.format(Locale.ROOT, "%010d 00000 n \n", offset)));
        output.write(bytes("trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + xref + "\n%%EOF\n")); return output.toByteArray();
    }
}
