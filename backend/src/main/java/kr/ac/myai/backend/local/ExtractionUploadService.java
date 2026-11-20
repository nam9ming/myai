package kr.ac.myai.backend.local;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.extraction.VerifiedExtraction;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.List;

@Service
@Profile("local-api")
public class ExtractionUploadService {
    private final LocalManagementService management;
    private final ExtractionArchiveReader archives;
    private final ExtractionUploadStore store;
    private final ReviewedImportReader json;
    private final Path extractionRoot;

    public ExtractionUploadService(LocalManagementService management, ExtractionArchiveReader archives,
                                   ExtractionUploadStore store, ReviewedImportReader json,
                                   @Value("${myai.local-api.extraction-root}") String extractionRoot) {
        this.management = management; this.archives = archives; this.store = store; this.json = json;
        this.extractionRoot = Path.of(extractionRoot);
    }

    public record Result(String schemaVersion, String runId, String expectedInputHash, String state,
                         List<ExtractionUploadStore.Artifact> receivedFiles, boolean reviewRequired) { }

    public Result initialize(byte[] control, byte[] metadata, byte[] input) {
        limit(control, 64 * 1024, false); limit(metadata, 64 * 1024, false); limit(input, 8 * 1024 * 1024, false);
        var request = management.readExtractionRequest(control);
        JsonNode meta;
        try { meta = json.parseJson(metadata); }
        catch (ImportException error) { throw invalid(); }
        if (meta == null || !meta.isObject() || !request.runId().equals(meta.path("run_id").textValue())
                || !"manual_import".equals(meta.path("execution_mode").textValue())
                || !meta.path("attempts").isIntegralNumber() || !meta.path("attempts").canConvertToInt()
                || meta.path("attempts").intValue() < 1 || meta.path("attempts").intValue() > 3
                || !request.expectedInputHash().equals(ReviewedImportReader.sha256(input))) throw invalid();
        int attempts = meta.path("attempts").intValue();
        var existing = store.find(request.runId()).orElse(null);
        var canonical = canonical(request.runId(), existing);
        if (canonical != null) {
            manual(canonical);
            if (canonical.attempts() != attempts) throw conflict();
            same(canonical, "input.json", input.length, request.expectedInputHash());
            same(canonical, "metadata.json", metadata.length, ReviewedImportReader.sha256(metadata));
        }
        return result(store.initialize(request.runId(), request.expectedInputHash(), attempts, control, metadata, input));
    }

    public Result put(String runId, int attempt, String artifact, byte[] content) {
        if (attempt < 1 || attempt > 3 || !("prompt".equals(artifact) || "output".equals(artifact))) throw invalid();
        limit(content, ("prompt".equals(artifact) ? 20 : 5) * 1024 * 1024, true);
        var staged = store.find(runId).orElseThrow(this::notFound);
        var canonical = canonical(runId, staged);
        if (canonical != null) {
            manual(canonical);
            same(canonical, "attempt-" + attempt + "." + artifact, content.length, ReviewedImportReader.sha256(content));
        }
        return result(store.put(runId, attempt, artifact, content));
    }

    public LocalManagementService.Result finalizeUpload(String runId, byte[] control) {
        limit(control, 64 * 1024, false);
        var request = management.readExtractionRequest(control);
        if (!request.runId().equals(runId)) throw invalid();
        var staged = store.find(runId).orElse(null);
        if (staged == null) {
            canonical(runId, null);
            throw notFound();
        }
        staged = store.ready(runId, request.expectedInputHash());
        var canonical = canonical(runId, staged);
        if (canonical != null) {
            manual(canonical);
            if (canonical.attempts() != staged.attempts()) throw conflict();
            for (var file : staged.artifacts()) if (!file.name().equals("control.json"))
                same(canonical, file.name(), file.sizeBytes(), file.sha256());
        }
        var pairs = new ArrayList<ExtractionArchiveReader.AttemptFiles>();
        for (int attempt = 1; attempt <= staged.attempts(); attempt++) pairs.add(new ExtractionArchiveReader.AttemptFiles(
                staged.directory().resolve("attempt-" + attempt + ".prompt"), staged.directory().resolve("attempt-" + attempt + ".output")));
        try {
            archives.importManual(runId, extractionRoot, staged.directory().resolve("input.json"), staged.directory().resolve("metadata.json"), pairs);
        } catch (ExtractionException error) { throw LocalManagementService.translated(error.code(), error.retryable()); }
        return management.extraction(control);
    }

    private VerifiedExtraction canonical(String runId, ExtractionUploadStore.Staged staged) {
        try {
            if (!extractionRoot.isAbsolute() || !extractionRoot.normalize().equals(extractionRoot)
                    || !extractionRoot.toRealPath().equals(extractionRoot)) throw archiveInvalid();
            Path directory = extractionRoot.resolve(runId);
            var attributes = attributes(directory);
            if (attributes == null) return null;
            if (!attributes.isDirectory()) throw archiveInvalid();
            if (regular(directory.resolve("receipt.json"))) return archives.read(runId, extractionRoot);
            if (staged == null) throw archiveInvalid();
            store.ready(runId, staged.expectedInputHash());
            if (regular(directory.resolve("identity.json"))) return null;
            try (var files = Files.newDirectoryStream(directory)) {
                boolean beforeIdentity = true;
                for (Path file : files) {
                    if (!file.getFileName().toString().matches("\\.[a-z0-9_]{8}\\.tmp")
                            || !Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)
                            || !Files.getPosixFilePermissions(file, LinkOption.NOFOLLOW_LINKS)
                            .equals(PosixFilePermissions.fromString("rw-------"))) {
                        beforeIdentity = false; break;
                    }
                }
                if (beforeIdentity) return null;
            }
            // 다른 finalize가 첫 identity/receipt를 설치하는 경합은 손상으로 오인하지 않는다.
            if (regular(directory.resolve("receipt.json"))) return archives.read(runId, extractionRoot);
            if (regular(directory.resolve("identity.json"))) return null;
            throw archiveInvalid();
        } catch (ExtractionException error) { throw LocalManagementService.translated(error.code(), error.retryable()); }
        catch (IOException | SecurityException error) {
            throw LocalManagementService.translated("EXTRACTION_IO_ERROR", true);
        }
    }

    private BasicFileAttributes attributes(Path path) throws IOException {
        try { return Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS); }
        catch (NoSuchFileException error) { return null; }
    }

    private boolean regular(Path path) throws IOException {
        var attributes = attributes(path);
        if (attributes != null && !attributes.isRegularFile()) throw archiveInvalid();
        return attributes != null;
    }

    private void manual(VerifiedExtraction canonical) {
        if (!canonical.receipt().path("format_version").asText().equals("extraction-archive-v1")
                || !canonical.receipt().path("execution_mode").asText().equals("manual_import")) throw conflict();
    }

    private void same(VerifiedExtraction canonical, String name, long size, String hash) {
        JsonNode file = canonical.receipt().path("artifacts").path(name);
        if (!file.path("size").isIntegralNumber() || file.path("size").longValue() != size
                || !hash.equals(file.path("sha256").textValue())) throw conflict();
    }

    private Result result(ExtractionUploadStore.Staged staged) {
        return new Result("extraction-upload-result-v1", staged.runId(), staged.expectedInputHash(), "staged", staged.artifacts(), true);
    }

    private void limit(byte[] content, int maximum, boolean emptyAllowed) {
        if (content == null || !emptyAllowed && content.length == 0) throw invalid();
        if (content.length > maximum) throw new ApiException(HttpStatus.PAYLOAD_TOO_LARGE, "EXTRACTION_UPLOAD_TOO_LARGE",
                "추출 업로드의 파일별 크기 한도를 초과했습니다.", null);
    }
    private ApiException invalid() { return new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "EXTRACTION_UPLOAD_INVALID", "추출 업로드의 입력·실행 연결을 확인해 주세요.", null); }
    private ApiException archiveInvalid() { return LocalManagementService.translated("EXTRACTION_ARCHIVE_INVALID", false); }
    private ApiException conflict() { return new ApiException(HttpStatus.CONFLICT, "EXTRACTION_UPLOAD_CONFLICT", "이미 보관한 추출 원본과 다릅니다.", null); }
    private ApiException notFound() { return new ApiException(HttpStatus.NOT_FOUND, "EXTRACTION_UPLOAD_NOT_FOUND", "추출 업로드 실행을 찾을 수 없습니다.", null); }
}
