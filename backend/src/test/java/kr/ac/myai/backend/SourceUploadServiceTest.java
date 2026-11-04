package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.local.*;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.http.HttpStatus;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

class SourceUploadServiceTest {
    private static final String DOCUMENT = "44444444-4444-4444-8444-444444444444";
    private static final String VERSION = "55555555-5555-4555-8555-555555555555";
    private static final ObjectMapper JSON = new ObjectMapper();
    @TempDir Path temporary;
    private Path sources, requests;
    private ReviewedImportReader reader;
    private LocalManagementService management;
    private SourceUploadStore store;
    private SourceUploadService service;
    private final List<JsonNode> imported = new ArrayList<>();

    @BeforeEach void setup() throws Exception {
        sources = Files.createDirectory(temporary.resolve("sources"), PosixFilePermissions.asFileAttribute(
                PosixFilePermissions.fromString("rwx------"))).toRealPath();
        requests = Files.createDirectory(temporary.resolve("requests"), PosixFilePermissions.asFileAttribute(
                PosixFilePermissions.fromString("rwx------"))).toRealPath();
        reader = new ReviewedImportReader();
        management = mock(LocalManagementService.class);
        doAnswer(call -> {
            byte[] bytes = call.getArgument(0);
            var batch = reader.read(bytes, sources);
            assertThat(batch.events()).isEmpty();
            imported.add(reader.parseJson(bytes));
            var result = new kr.ac.myai.backend.service.ReviewedImportService.ImportResult(
                    "77777777-7777-4777-8777-777777777777", List.of(), List.of(VERSION), imported.size() > 1);
            return new LocalManagementService.Result("local-management-result-v1", sha(bytes), result);
        }).when(management).documents(any());
        store = new SourceUploadStore(sources.toString(), requests.toString());
        service = create(new SourceTextPreprocessor(new PdfTextExtractor("")));
    }

    @Test void registersTextAsPendingSourceAndPreservesOriginalAndProjectedBytes() throws Exception {
        byte[] metadata = bytes(metadata("txt").toString());
        byte[] raw = bytes("합성 공지\r\n문의 a@b.test\n다음 줄");
        JsonNode result = JSON.valueToTree(service.upload(metadata, raw, "text/plain;charset=UTF-8"));
        assertThat(result.path("schemaVersion").asText()).isEqualTo("source-upload-result-v1");
        assertThat(result.path("documentId").asText()).isEqualTo(DOCUMENT);
        assertThat(result.path("documentVersionId").asText()).isEqualTo(VERSION);
        assertThat(imported).hasSize(1);
        JsonNode doc = imported.getFirst().path("documents").get(0);
        assertThat(doc.path("use_review").asText()).isEqualTo("pending");
        assertThat(doc.path("check_result").asText()).isEqualTo("unchecked");
        assertThat(doc.path("checks").isEmpty()).isTrue();
        assertThat(doc.path("last_verified_at").isNull()).isTrue();
        assertThat(doc.path("cleaned_text").asText()).isEqualTo("합성 공지\n문의 [EMAIL]\n다음 줄");
        assertThat(Files.readAllBytes(sources.resolve(doc.path("raw_asset_path").asText()))).isEqualTo(raw);
        var saved = store.find(VERSION, metadata, raw);
        assertThat(saved.sourceImport()).isEqualTo(bytes(imported.getFirst().toString()));
        JsonNode input = reader.parseJson(saved.aiInput());
        assertThat(input.size()).isEqualTo(5);
        assertThat(input.path("document_version_id").asText()).isEqualTo(VERSION);
        assertThat(input.path("blocks")).isEqualTo(doc.path("block_index"));
        assertThat(input.path("published_date").isNull()).isTrue();
        assertThat(doc.path("redaction_log").toString()).doesNotContain("a@b.test");
    }

    @Test void jsonFileUsesExplicitTextShapeAndDoesNotTurnAnAiInputIntoSourceText() throws Exception {
        byte[] metadata = bytes(metadata("json").toString());
        service.upload(metadata, bytes("{\"schema_version\":\"text-body-v1\",\"text\":\"합성 본문\"}"), "application/json");
        assertThat(imported.getFirst().path("documents").get(0).path("cleaned_text").asText()).isEqualTo("합성 본문");
        var other = metadata("json").put("document_version_id", "66666666-6666-4666-8666-666666666666");
        rejected(() -> service.upload(bytes(other.toString()), bytes("{\"data_kind\":\"synthetic\",\"blocks\":[]}"), "application/json"), 422);
        assertThat(imported).hasSize(1);
    }

    @Test void exactReplayUsesTheFirstPreparedBundleWithoutRunningTheConverterAgain() throws Exception {
        byte[] metadata = bytes(metadata("txt").toString()), raw = bytes("합성 본문");
        JsonNode first = JSON.valueToTree(service.upload(metadata, raw, "text/plain"));
        var unavailable = mock(SourceTextPreprocessor.class);
        when(unavailable.prepare(anyString(), any())).thenThrow(new AssertionError("must reuse original preparation"));
        JsonNode again = JSON.valueToTree(create(unavailable).upload(metadata, raw, "text/plain"));
        var firstIdentity = (ObjectNode) first.deepCopy(); firstIdentity.remove("data");
        var nextIdentity = (ObjectNode) again.deepCopy(); nextIdentity.remove("data");
        assertThat(nextIdentity).isEqualTo(firstIdentity);
        assertThat(first.path("data").path("alreadyImported").asBoolean()).isFalse();
        assertThat(again.path("data").path("alreadyImported").asBoolean()).isTrue();
        assertThat(imported).hasSize(2);
        assertThat(imported.get(0)).isEqualTo(imported.get(1));
        rejected(() -> service.upload(bytes(new String(metadata, StandardCharsets.UTF_8) + " "), raw, "text/plain"), 409);
        rejected(() -> service.upload(metadata, bytes("다른 본문"), "text/plain"), 409);
        assertThat(imported).hasSize(2);
    }

    @Test void databaseFailureRetainsTheReadyOriginalForAnExactLaterRetry() throws Exception {
        byte[] metadata = bytes(metadata("txt").toString()), raw = bytes("합성 본문");
        doThrow(new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "DATABASE_UNAVAILABLE", "unavailable", null))
                .when(management).documents(any());
        rejected(() -> service.upload(metadata, raw, "text/plain"), 503);
        var saved = store.find(VERSION, metadata, raw);
        assertThat(saved).isNotNull();
        assertThat(reader.read(saved.sourceImport(), sources).documents()).hasSize(1);
        assertThat(Files.readAllBytes(sources.resolve("uploads/" + sha(raw) + ".txt"))).isEqualTo(raw);
    }

    @Test void malformedUnknownMetadataAndSizeOrMediaFailuresDoNotWriteFilesOrImport() throws Exception {
        var extra = metadata("txt").put("use_review", "allowed");
        for (byte[] invalid : List.of(bytes("{}"), bytes(extra.toString()), bytes(metadata("txt").put("schema_version", "other").toString()),
                bytes("{\"schema_version\":\"source-upload-v1\",\"schema_version\":\"source-upload-v1\"}"))) {
            rejected(() -> service.upload(invalid, bytes("본문"), "text/plain"), 422);
        }
        rejected(() -> service.upload(new byte[64 * 1024 + 1], bytes("본문"), "text/plain"), 413);
        rejected(() -> service.upload(bytes(metadata("txt").toString()), new byte[20 * 1024 * 1024 + 1], "text/plain"), 413);
        rejected(() -> service.upload(bytes(metadata("txt").toString()), bytes("본문"), "application/octet-stream"), 415);
        assertThat(imported).isEmpty();
        try (var src = Files.list(sources); var req = Files.list(requests)) {
            assertThat(src.toList()).isEmpty(); assertThat(req.toList()).isEmpty();
        }
    }

    @Test void invalidTitleOrSourceMetadataCannotCreateAReadyDocument() throws Exception {
        var invalidTitle = metadata("txt").put("title", "e\u0301");
        rejected(() -> service.upload(bytes(invalidTitle.toString()), bytes("본문"), "text/plain"), 422);
        assertThat(imported).isEmpty();
        var invalidSource = metadata("txt").put("official_url", "file:///private/source");
        byte[] metadata = bytes(invalidSource.toString());
        rejected(() -> service.upload(metadata, bytes("본문"), "text/plain"), 422);
        assertThat(store.find(VERSION, metadata, bytes("본문"))).isNull();
        assertThat(imported).isEmpty();
    }

    private SourceUploadService create(SourceTextPreprocessor texts) {
        return new SourceUploadService(management, reader, store, texts, new LocalRequestStore(requests.toString()), sources.toString());
    }

    private ObjectNode metadata(String format) {
        return JSON.createObjectNode().put("schema_version", "source-upload-v1").put("format", format)
                .put("data_kind", "synthetic").put("document_id", DOCUMENT).put("document_version_id", VERSION)
                .put("version_no", 1).put("publisher", "합성 기관").put("official_url", "https://example.invalid/notice/1")
                .put("title", "합성 공지").putNull("official_number").putNull("published_date")
                .put("collected_at", "2026-11-02T00:00:00Z").put("collection_method", "synthetic fixture")
                .put("use_note", "synthetic only; not approved for publication");
    }

    private byte[] bytes(String text) { return text.getBytes(StandardCharsets.UTF_8); }
    private String sha(byte[] bytes) throws Exception { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
    private void rejected(org.assertj.core.api.ThrowableAssert.ThrowingCallable action, int status) {
        assertThatThrownBy(action).isInstanceOfSatisfying(ApiException.class, ex -> assertThat(ex.status().value()).isEqualTo(status));
    }
}
