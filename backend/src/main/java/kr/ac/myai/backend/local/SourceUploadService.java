package kr.ac.myai.backend.local;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.text.Normalizer;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

@Service
@Profile("local-api")
public class SourceUploadService {
    private static final List<String> FIELDS = List.of("schema_version", "format", "data_kind", "document_id",
            "document_version_id", "version_no", "publisher", "official_url", "title", "official_number",
            "published_date", "collected_at", "collection_method", "use_note");
    private static final Set<String> FIELD_SET = Set.copyOf(FIELDS);
    private static final ObjectMapper JSON = new ObjectMapper();
    private final LocalManagementService management;
    private final ReviewedImportReader reader;
    private final SourceUploadStore uploads;
    private final SourceTextPreprocessor texts;
    private final LocalRequestStore requests;
    private final Path sourceRoot;

    public SourceUploadService(LocalManagementService management, ReviewedImportReader reader, SourceUploadStore uploads,
                               SourceTextPreprocessor texts, LocalRequestStore requests,
                               @Value("${myai.local-api.source-root}") String sourceRoot) {
        this.management = management; this.reader = reader; this.uploads = uploads;
        this.texts = texts; this.requests = requests; this.sourceRoot = Path.of(sourceRoot);
    }

    public record Result(String schemaVersion, String uploadSha256, String documentId, String documentVersionId,
                         long versionNo, String useReview, String checkResult, String rawSha256, String textSha256,
                         String inputHash, String preprocessingVersion, String textScope, boolean textReviewRequired,
                         Object data) { }

    public Result upload(byte[] metadata, byte[] raw, String fileMediaType) {
        limit(metadata, 64 * 1024); limit(raw, ReviewedImportReader.RAW_ASSET_LIMIT);
        try {
            JsonNode meta = reader.parseJson(metadata);
            validate(meta);
            String format = meta.path("format").asText(), version = meta.path("document_version_id").asText();
            media(format, fileMediaType);
            requests.retain(metadata);
            var stored = uploads.find(version, metadata, raw);
            if (stored == null) {
                uploads.retainRaw(raw, format);
                var prepared = texts.prepare(format, raw);
                ObjectNode source = source(meta, raw, prepared);
                byte[] sourceBytes = bytes(source);
                reader.read(sourceBytes, sourceRoot);
                byte[] input = bytes(input(meta, source.path("documents").get(0).path("block_index")));
                var receipt = JSON.createObjectNode().put("schema_version", "source-upload-receipt-v1")
                        .put("document_version_id", version).put("metadata_sha256", sha(metadata)).put("raw_sha256", sha(raw))
                        .put("format", format).put("source_import_sha256", sha(sourceBytes)).put("ai_input_sha256", sha(input))
                        .put("preprocessing_version", prepared.preprocessingVersion()).put("text_scope", prepared.textScope())
                        .put("text_review_required", prepared.textReviewRequired());
                stored = uploads.commit(version, metadata, sourceBytes, input, receipt);
            }
            var registered = management.documents(stored.sourceImport());
            JsonNode doc = reader.parseJson(stored.sourceImport()).path("documents").get(0);
            JsonNode receipt = stored.receipt();
            String uploadHash = sha(("source-upload-v1\n" + sha(metadata) + "\n" + sha(raw)).getBytes(StandardCharsets.US_ASCII));
            return new Result("source-upload-result-v1", uploadHash, doc.path("document_id").asText(), version,
                    doc.path("version_no").asLong(), "pending", "unchecked", doc.path("raw_sha256").asText(),
                    doc.path("text_sha256").asText(), sha(stored.aiInput()), receipt.path("preprocessing_version").asText(),
                    receipt.path("text_scope").asText(), receipt.path("text_review_required").asBoolean(), registered.data());
        } catch (ImportException ex) {
            throw invalid();
        }
    }

    private void validate(JsonNode meta) {
        if (!meta.isObject()) throw invalid();
        var keys = new HashSet<String>(); meta.fieldNames().forEachRemaining(keys::add);
        if (!keys.equals(FIELD_SET) || !meta.path("schema_version").asText().equals("source-upload-v1")) throw invalid();
        for (String key : FIELDS) {
            JsonNode value = meta.path(key);
            if (key.equals("version_no")) {
                if (!value.isIntegralNumber() || !value.canConvertToLong() || value.asLong() < 1) throw invalid();
            } else if ((key.equals("official_number") || key.equals("published_date")) && value.isNull()) {
                continue;
            } else if (!value.isTextual() || value.asText().isBlank()) throw invalid();
        }
        if (!Set.of("txt", "pdf", "json").contains(meta.path("format").asText())
                || !Set.of("synthetic", "real").contains(meta.path("data_kind").asText())) throw invalid();
        for (String key : Set.of("document_id", "document_version_id")) {
            if (!meta.path(key).asText().matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")) throw invalid();
        }
        String title = meta.path("title").asText();
        if (title.contains("\r") || !Normalizer.isNormalized(title, Normalizer.Form.NFC)) throw invalid();
    }

    private ObjectNode source(JsonNode meta, byte[] raw, SourceTextPreprocessor.Prepared prepared) {
        var doc = JSON.createObjectNode();
        for (String key : FIELDS) {
            if (!Set.of("schema_version", "format", "data_kind").contains(key)) doc.set(key, meta.path(key));
        }
        doc.put("raw_asset_path", "uploads/" + sha(raw) + "." + meta.path("format").asText());
        doc.put("raw_sha256", sha(raw)).put("cleaned_text", prepared.cleanedText())
                .put("text_sha256", sha(prepared.cleanedText().getBytes(StandardCharsets.UTF_8)))
                .put("preprocessing_version", prepared.preprocessingVersion()).put("use_review", "pending")
                .putNull("latest_check_attempt_at").putNull("last_verified_at").put("check_result", "unchecked");
        var blocks = doc.putArray("block_index");
        for (var block : prepared.blocks()) {
            var item = blocks.addObject().put("block_id", block.blockId()).put("text", block.text());
            if (block.page() == null) item.putNull("page"); else item.put("page", block.page());
        }
        var redactions = doc.putArray("redaction_log");
        for (var redaction : prepared.redactionLog()) redactions.addObject()
                .put("category", redaction.category()).put("location", redaction.location());
        doc.putArray("checks");
        var source = JSON.createObjectNode().put("schema_version", "source-import-v1").put("data_kind", meta.path("data_kind").asText());
        source.putArray("documents").add(doc); source.putArray("evidence"); source.putArray("events");
        return source;
    }

    private ObjectNode input(JsonNode meta, JsonNode blocks) {
        var input = JSON.createObjectNode();
        for (String key : List.of("data_kind", "document_version_id", "title", "published_date")) input.set(key, meta.path(key));
        input.set("blocks", blocks);
        return input;
    }

    private void media(String format, String declared) {
        try {
            MediaType type = MediaType.parseMediaType(declared == null ? "" : declared);
            String expected = switch (format) { case "txt" -> "text/plain"; case "pdf" -> "application/pdf"; default -> "application/json"; };
            if (!(type.getType() + "/" + type.getSubtype()).equalsIgnoreCase(expected)
                    || type.getCharset() != null && !type.getCharset().equals(StandardCharsets.UTF_8)) throw unsupported();
        } catch (IllegalArgumentException ex) { throw unsupported(); }
    }

    private void limit(byte[] content, int limit) {
        if (content == null || content.length == 0) throw invalid();
        if (content.length > limit) throw new ApiException(HttpStatus.PAYLOAD_TOO_LARGE, "SOURCE_UPLOAD_TOO_LARGE",
                "업로드 크기 한도를 초과했습니다. 파일을 나누거나 별도 검토해 주세요.", null);
    }

    private byte[] bytes(JsonNode node) { return node.toString().getBytes(StandardCharsets.UTF_8); }
    private String sha(byte[] bytes) { return ReviewedImportReader.sha256(bytes); }
    private ApiException invalid() { return new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "SOURCE_UPLOAD_INVALID", "업로드 메타데이터·원문·식별자와 버전을 확인해 주세요.", null); }
    private ApiException unsupported() { return new ApiException(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "UNSUPPORTED_MEDIA_TYPE", "파일 형식에 맞는 text/plain·application/pdf·application/json을 사용해 주세요.", "file"); }
}
