package kr.ac.myai.backend.local;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermission;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

@Component
@Profile("local-api")
public class SourceUploadStore {
    private static final int JSON_LIMIT = 8 * 1024 * 1024;
    private static final int METADATA_LIMIT = 64 * 1024;
    private static final Set<PosixFilePermission> DIRECTORY_MODE = PosixFilePermissions.fromString("rwx------");
    private static final Set<PosixFilePermission> FILE_MODE = PosixFilePermissions.fromString("rw-------");
    private static final Set<String> BUNDLE_FILES = Set.of("metadata.json", "source-import.json", "input.json", "receipt.json");
    private static final Set<String> RECEIPT_FIELDS = Set.of("schema_version", "document_version_id", "metadata_sha256", "raw_sha256",
            "format", "source_import_sha256", "ai_input_sha256", "preprocessing_version", "text_scope", "text_review_required");
    private final String sourceRoot;
    private final String requestRoot;
    private final ReviewedImportReader json = new ReviewedImportReader();

    public SourceUploadStore(@Value("${myai.local-api.source-root}") String sourceRoot,
                             @Value("${myai.local-api.request-root}") String requestRoot) {
        this.sourceRoot = sourceRoot;
        this.requestRoot = requestRoot;
    }

    public record Stored(byte[] sourceImport, byte[] aiInput, JsonNode receipt) { }

    public Path retainRaw(byte[] bytes, String format) {
        content(bytes, ReviewedImportReader.RAW_ASSET_LIMIT);
        if (!format(format)) throw invalid();
        try {
            Path uploads = createDirectory(root(sourceRoot).resolve("uploads"));
            Path target = uploads.resolve(ReviewedImportReader.sha256(bytes) + "." + format);
            if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) return matching(target, bytes);
            Path temporary = Files.createTempFile(uploads, ".raw-", ".tmp", PosixFilePermissions.asFileAttribute(FILE_MODE));
            try {
                Files.write(temporary, bytes, StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS);
                try { Files.createLink(target, temporary); }
                catch (FileAlreadyExistsException ex) { return matching(target, bytes); }
                return matching(target, bytes);
            } finally { Files.deleteIfExists(temporary); }
        } catch (IOException | IllegalArgumentException | UnsupportedOperationException | SecurityException ex) { throw ioError(); }
    }

    public Stored find(String versionId, byte[] metadata, byte[] raw) {
        version(versionId); content(metadata, METADATA_LIMIT); content(raw, ReviewedImportReader.RAW_ASSET_LIMIT);
        try {
            Path sources = root(sourceRoot), uploads = root(requestRoot).resolve("uploads");
            if (!Files.exists(uploads, LinkOption.NOFOLLOW_LINKS)) return null;
            directory(uploads);
            Path index = uploads.resolve(versionId + ".json");
            return Files.exists(index, LinkOption.NOFOLLOW_LINKS)
                    ? load(index, sources, versionId, metadata, ReviewedImportReader.sha256(raw), null) : null;
        } catch (IOException | IllegalArgumentException | UnsupportedOperationException | SecurityException ex) { throw ioError(); }
    }

    public Stored commit(String versionId, byte[] metadata, byte[] sourceImport, byte[] aiInput, JsonNode receipt) {
        version(versionId); content(metadata, METADATA_LIMIT); content(sourceImport, JSON_LIMIT); content(aiInput, JSON_LIMIT);
        byte[] receiptBytes;
        try { receiptBytes = receipt == null ? null : receipt.toString().getBytes(StandardCharsets.UTF_8); }
        catch (IllegalArgumentException ex) { throw invalid(); }
        content(receiptBytes, JSON_LIMIT);
        JsonNode checkedReceipt;
        try { checkedReceipt = json.parseJson(receiptBytes); }
        catch (ImportException ex) { throw invalid(); }
        if (!validReceipt(checkedReceipt, versionId, metadata, sourceImport, aiInput)) throw invalid();
        String rawHash = checkedReceipt.path("raw_sha256").asText(), format = checkedReceipt.path("format").asText();
        try {
            Path sources = root(sourceRoot), uploads = createDirectory(root(requestRoot).resolve("uploads"));
            Path index = uploads.resolve(versionId + ".json");
            if (Files.exists(index, LinkOption.NOFOLLOW_LINKS)) return load(index, sources, versionId, metadata, rawHash, format);
            verifyRaw(sources, checkedReceipt);
            Path bundles = createDirectory(uploads.resolve("bundles"));
            String bundleId = UUID.randomUUID().toString();
            Path bundle = Files.createDirectory(bundles.resolve(bundleId), PosixFilePermissions.asFileAttribute(DIRECTORY_MODE));
            Path temporary = null;
            boolean installed = false;
            try {
                write(bundle.resolve("metadata.json"), metadata);
                write(bundle.resolve("source-import.json"), sourceImport);
                write(bundle.resolve("input.json"), aiInput);
                write(bundle.resolve("receipt.json"), receiptBytes);
                loadBundle(bundle, sources, versionId, metadata, rawHash, format);
                temporary = Files.createTempFile(uploads, ".index-", ".tmp", PosixFilePermissions.asFileAttribute(FILE_MODE));
                Files.writeString(temporary, "{\"bundle_id\":\"" + bundleId + "\"}", StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS);
                try { Files.createLink(index, temporary); installed = true; }
                catch (FileAlreadyExistsException ex) { return load(index, sources, versionId, metadata, rawHash, format); }
                return load(index, sources, versionId, metadata, rawHash, format);
            } finally {
                if (temporary != null) Files.deleteIfExists(temporary);
                if (!installed) {
                    for (String name : BUNDLE_FILES) Files.deleteIfExists(bundle.resolve(name));
                    Files.deleteIfExists(bundle);
                }
            }
        } catch (IOException | IllegalArgumentException | UnsupportedOperationException | SecurityException ex) { throw ioError(); }
    }

    private Stored load(Path index, Path sources, String versionId, byte[] metadata, String rawHash, String format) throws IOException {
        JsonNode value = storedJson(read(index, 1024));
        if (!fields(value, Set.of("bundle_id")) || !uuid(value.path("bundle_id").textValue())) throw conflict();
        Path bundles = index.getParent().resolve("bundles"); directory(bundles);
        return loadBundle(bundles.resolve(value.path("bundle_id").textValue()), sources, versionId, metadata, rawHash, format);
    }

    private Stored loadBundle(Path bundle, Path sources, String versionId, byte[] metadata, String rawHash, String format) throws IOException {
        directory(bundle);
        var names = new HashSet<String>();
        try (var files = Files.newDirectoryStream(bundle)) { for (Path file : files) names.add(file.getFileName().toString()); }
        if (!names.equals(BUNDLE_FILES)) throw conflict();
        byte[] storedMetadata = read(bundle.resolve("metadata.json"), METADATA_LIMIT);
        byte[] source = read(bundle.resolve("source-import.json"), JSON_LIMIT), input = read(bundle.resolve("input.json"), JSON_LIMIT);
        JsonNode receipt = storedJson(read(bundle.resolve("receipt.json"), JSON_LIMIT));
        if (!Arrays.equals(metadata, storedMetadata) || !validReceipt(receipt, versionId, storedMetadata, source, input)
                || !rawHash.equals(receipt.path("raw_sha256").asText())
                || (format != null && !format.equals(receipt.path("format").asText()))) throw conflict();
        verifyRaw(sources, receipt);
        return new Stored(source, input, receipt);
    }

    private boolean validReceipt(JsonNode receipt, String versionId, byte[] metadata, byte[] source, byte[] input) {
        return fields(receipt, RECEIPT_FIELDS)
                && receipt.path("schema_version").asText().equals("source-upload-receipt-v1")
                && receipt.path("document_version_id").asText().equals(versionId)
                && receipt.path("metadata_sha256").asText().equals(ReviewedImportReader.sha256(metadata))
                && receipt.path("source_import_sha256").asText().equals(ReviewedImportReader.sha256(source))
                && receipt.path("ai_input_sha256").asText().equals(ReviewedImportReader.sha256(input))
                && receipt.path("raw_sha256").isTextual() && receipt.path("raw_sha256").textValue().matches("[0-9a-f]{64}")
                && format(receipt.path("format").textValue())
                && receipt.path("preprocessing_version").isTextual() && !receipt.path("preprocessing_version").textValue().isBlank()
                && receipt.path("text_scope").isTextual() && !receipt.path("text_scope").textValue().isBlank()
                && receipt.path("text_review_required").isBoolean();
    }

    private void verifyRaw(Path sources, JsonNode receipt) throws IOException {
        Path uploads = sources.resolve("uploads"); directory(uploads);
        byte[] raw = read(uploads.resolve(receipt.path("raw_sha256").asText() + "." + receipt.path("format").asText()),
                ReviewedImportReader.RAW_ASSET_LIMIT);
        if (!ReviewedImportReader.sha256(raw).equals(receipt.path("raw_sha256").asText())) throw conflict();
    }

    private Path matching(Path target, byte[] expected) throws IOException {
        if (!Arrays.equals(read(target, ReviewedImportReader.RAW_ASSET_LIMIT), expected)) throw conflict();
        return target;
    }

    private byte[] read(Path file, int limit) throws IOException {
        if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)
                || !Files.getPosixFilePermissions(file, LinkOption.NOFOLLOW_LINKS).equals(FILE_MODE)) throw conflict();
        var before = Files.readAttributes(file, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        try (var stream = Files.newInputStream(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = stream.readNBytes(limit + 1);
            var after = Files.readAttributes(file, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (bytes.length == 0 || bytes.length > limit || !after.isRegularFile()
                    || !Objects.equals(before.fileKey(), after.fileKey()) || before.size() != after.size()
                    || !before.lastModifiedTime().equals(after.lastModifiedTime())
                    || !Files.getPosixFilePermissions(file, LinkOption.NOFOLLOW_LINKS).equals(FILE_MODE)) throw conflict();
            return bytes;
        }
    }

    private void write(Path file, byte[] bytes) throws IOException {
        try (var channel = Files.newByteChannel(file, Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE),
                PosixFilePermissions.asFileAttribute(FILE_MODE))) {
            var buffer = ByteBuffer.wrap(bytes);
            while (buffer.hasRemaining()) channel.write(buffer);
        }
    }

    private Path root(String configured) throws IOException {
        if (configured == null || configured.isBlank()) throw ioError();
        Path stated = Path.of(configured);
        if (!stated.isAbsolute() || !stated.normalize().equals(stated)) throw ioError();
        Path current = stated.getRoot();
        for (Path part : stated) {
            current = current.resolve(part);
            if (!Files.isDirectory(current, LinkOption.NOFOLLOW_LINKS)) throw ioError();
        }
        if (!Files.getPosixFilePermissions(stated, LinkOption.NOFOLLOW_LINKS).equals(DIRECTORY_MODE)) throw ioError();
        return stated;
    }

    private Path createDirectory(Path path) throws IOException {
        try { Files.createDirectory(path, PosixFilePermissions.asFileAttribute(DIRECTORY_MODE)); }
        catch (FileAlreadyExistsException ignored) { }
        directory(path); return path;
    }

    private void directory(Path path) throws IOException {
        if (!Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)
                || !Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS).equals(DIRECTORY_MODE)) throw conflict();
    }

    private JsonNode storedJson(byte[] bytes) {
        try { return json.parseJson(bytes); }
        catch (ImportException ex) { throw conflict(); }
    }

    private boolean fields(JsonNode node, Set<String> expected) {
        if (!node.isObject()) return false;
        var actual = new HashSet<String>(); node.fieldNames().forEachRemaining(actual::add);
        return actual.equals(expected);
    }

    private void content(byte[] bytes, int limit) {
        if (bytes == null || bytes.length == 0) throw invalid();
        if (bytes.length > limit) throw new ApiException(HttpStatus.PAYLOAD_TOO_LARGE, "SOURCE_UPLOAD_TOO_LARGE",
                "업로드 크기 한도를 초과했습니다. 파일을 나누거나 별도 검토해 주세요.", null);
    }

    private void version(String value) { if (!uuid(value)) throw invalid(); }
    private boolean uuid(String value) { return value != null && value.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"); }
    private boolean format(String value) { return value != null && Set.of("txt", "pdf", "json").contains(value); }
    private ApiException invalid() { return new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "SOURCE_UPLOAD_INVALID", "업로드 보관 요청의 형식·크기·해시를 확인해 주세요.", null); }
    private ApiException conflict() { return new ApiException(HttpStatus.CONFLICT, "SOURCE_UPLOAD_CONFLICT", "업로드 원본 또는 준비본의 내용·링크·권한이 다릅니다. 기존 항목을 보존했습니다.", null); }
    private ApiException ioError() { return new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "SOURCE_UPLOAD_IO_ERROR", "업로드 원본·준비본을 보관하지 못했습니다. 비공개 디렉터리와 접근 권한을 확인해 주세요.", null); }
}
