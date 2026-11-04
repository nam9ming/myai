package kr.ac.myai.backend.extraction;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.process.PythonProcess;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFileAttributeView;
import java.nio.file.attribute.PosixFilePermission;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

@Component
@Profile("!fixture")
public class ExtractionArchiveReader {
    private static final int LIMIT = 8 * 1024 * 1024;
    private static final String HASH = "[0-9a-f]{64}";
    private static final String UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
    private final ReviewedImportReader json;
    private final String executable;
    private final String workdir;
    private final long timeout;

    public ExtractionArchiveReader(ReviewedImportReader json,
                                   @Value("${app.calculation.python-executable:python3.13}") String executable,
                                   @Value("${app.calculation.workdir:}") String workdir,
                                   @Value("${app.extraction.timeout-ms:60000}") long timeout) {
        this.json = json; this.executable = executable; this.workdir = workdir; this.timeout = timeout;
    }

    public VerifiedExtraction read(String runId, Path root) {
        return read(runId, root, false);
    }

    public VerifiedExtraction readSealed(String runId, Path root) {
        return read(runId, root, true);
    }

    private VerifiedExtraction read(String runId, Path root, boolean readOnly) {
        validate(runId != null && runId.matches(UUID), "run_id");
        validate(root != null && root.isAbsolute() && !Files.isSymbolicLink(root), "archive_root");
        try {
            Path base = root.toRealPath();
            Path directory = base.resolve(runId);
            validate(Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS), "archive_root");
            var arguments = readOnly ? List.of("-B", "-m", "processing.extraction", "verify-sealed", runId, "--root", base.toString())
                    : List.of("-m", "processing.extraction", "freeze", runId, "--root", base.toString());
            var process = PythonProcess.execute(executable, workdir, arguments, new byte[0], timeout);
            if (process.exitCode() != 0 && process.exitCode() != 4) {
                throw new ExtractionException(switch (process.exitCode()) {
                    case 2 -> "EXTRACTION_VALIDATION_ERROR";
                    case 3 -> "EXTRACTION_ARCHIVE_INVALID";
                    case 5 -> "EXTRACTION_IO_ERROR";
                    default -> "EXTRACTION_PROTOCOL_ERROR";
                }, null, false);
            }
            JsonNode packet = json.parseJson(process.stdout());
            require(keys(packet).equals(Set.of("protocol_version", "snapshot_ref", "receipt"))
                    && packet.path("protocol_version").asText().equals("extraction-registration-v1"));
            String snapshot = packet.path("snapshot_ref").asText();
            require(snapshot.equals(runId) || snapshot.matches("registered/[0-9a-f]{64}/" + runId));
            require(!readOnly || snapshot.equals(runId));
            directory = base.resolve(snapshot);
            require(Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS) && directory.toRealPath().equals(directory));
            JsonNode receipt = packet.path("receipt");
            Set<String> names = artifactNames(receipt);
            require(receipt.path("run_id").asText().equals(runId));
            require(receipt.path("status").asText().equals(process.exitCode() == 0 ? "validated" : "failed"));
            byte[] savedReceipt = read(directory.resolve("receipt.json"));
            require(json.parseJson(savedReceipt).equals(receipt));
            if (!snapshot.equals(runId)) require(snapshot.split("/")[1].equals(ReviewedImportReader.sha256(savedReceipt)));
            byte[] input = checked(directory, "input.json", receipt);
            byte[] metadata = checked(directory, "metadata.json", receipt);
            checkFingerprint(directory, "attempt-" + receipt.path("attempts").size() + ".output", receipt);
            require(receipt.path("input_sha256").asText().equals(ReviewedImportReader.sha256(input))
                    && receipt.path("metadata_sha256").asText().equals(ReviewedImportReader.sha256(metadata)));
            JsonNode source = json.parseJson(input), info = json.parseJson(metadata);
            require(info.path("run_id").asText().equals(runId) && info.path("document_version_id").equals(receipt.path("document_version_id"))
                    && source.path("document_version_id").equals(receipt.path("document_version_id"))
                    && source.path("data_kind").equals(receipt.path("data_kind"))
                    && info.path("execution_mode").equals(receipt.path("execution_mode"))
                    && info.path("schema_version").asText().equals("extract-schema-v1"));
            require(info.path("attempts").isIntegralNumber() && info.path("attempts").asInt() == receipt.path("attempts").size());
            sealed(directory);
            for (String name : names) sealed(directory.resolve(name));
            sealed(directory.resolve("identity.json")); sealed(directory.resolve("receipt.json"));
            return new VerifiedExtraction(directory, source, info, receipt, new String(metadata, StandardCharsets.UTF_8),
                    new String(savedReceipt, StandardCharsets.UTF_8), ReviewedImportReader.sha256(savedReceipt));
        } catch (PythonProcess.Failure ex) {
            throw new ExtractionException("EXTRACTION_RUNTIME_UNAVAILABLE", null, ex.retryable());
        } catch (ImportException ex) {
            throw new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false);
        } catch (IOException ex) {
            throw new ExtractionException("EXTRACTION_IO_ERROR", null, true);
        }
    }

    /** 버전별 정확한 파일 집합만 반환해 동적 파일 경로도 원본 계약 안에서 읽는다. */
    public static Set<String> artifactNames(JsonNode receipt) {
        require(receipt != null && receipt.isObject());
        String version = receipt.path("format_version").asText();
        boolean chunked = version.equals("extraction-archive-v2");
        require(chunked || version.equals("extraction-archive-v1"));
        var fields = new HashSet<>(Set.of("format_version", "run_id", "document_version_id", "data_kind", "execution_mode",
                "recorded_at", "status", "review_required", "input_sha256", "metadata_sha256", "artifacts", "attempts"));
        if (chunked) fields.addAll(Set.of("chunk_plan_sha256", "total_calls"));
        require(keys(receipt).equals(fields));
        require(receipt.path("run_id").asText().matches(UUID) && receipt.path("document_version_id").asText().matches(UUID));
        require(Set.of("synthetic", "real").contains(receipt.path("data_kind").asText()));
        String mode = receipt.path("execution_mode").asText();
        require(Set.of("manual_import", "api").contains(mode) && (!chunked || mode.equals("api")));
        require(Set.of("validated", "failed").contains(receipt.path("status").asText())
                && receipt.path("review_required").isBoolean() && receipt.path("review_required").booleanValue());
        require(receipt.path("recorded_at").isTextual() && !receipt.path("recorded_at").textValue().isBlank());
        require(receipt.path("input_sha256").isTextual() && receipt.path("input_sha256").textValue().matches(HASH)
                && receipt.path("metadata_sha256").isTextual() && receipt.path("metadata_sha256").textValue().matches(HASH));
        JsonNode attempts = receipt.path("attempts"), artifacts = receipt.path("artifacts");
        require(attempts.isArray() && attempts.size() >= 1 && attempts.size() <= 3 && artifacts.isObject());
        var names = new LinkedHashSet<>(List.of("input.json", "metadata.json"));
        if (chunked) names.add("chunk-plan.json");
        int chunkCount = -1; long calls = 0;
        for (int index = 0; index < attempts.size(); index++) {
            JsonNode attempt = attempts.get(index);
            require(attempt.isObject() && keys(attempt).equals(chunked
                    ? Set.of("attempt", "status", "error_code", "error_path", "failure_kind", "retryable", "chunks")
                    : Set.of("attempt", "status", "error_code", "error_path", "failure_kind", "retryable")));
            require(attempt.path("attempt").isIntegralNumber() && attempt.path("attempt").canConvertToInt()
                    && attempt.path("attempt").intValue() == index + 1);
            result(attempt);
            String prefix = "attempt-" + (index + 1);
            names.add(prefix + ".prompt"); names.add(prefix + ".output");
            if (!chunked) {
                if (mode.equals("api")) { names.add(prefix + ".response"); names.add(prefix + ".exchange"); }
                continue;
            }
            JsonNode chunks = attempt.path("chunks");
            require(chunks.isArray() && !chunks.isEmpty() && chunks.size() <= 999999);
            require(chunkCount == -1 || chunkCount == chunks.size()); chunkCount = chunks.size();
            boolean allValidated = true;
            for (int chunkIndex = 0; chunkIndex < chunks.size(); chunkIndex++) {
                JsonNode chunk = chunks.get(chunkIndex);
                require(chunk.isObject() && keys(chunk).equals(Set.of("chunk_id", "attempted", "status", "error_code", "error_path", "failure_kind", "retryable")));
                String id = "chunk-" + String.format(java.util.Locale.ROOT, "%06d", chunkIndex + 1);
                require(chunk.path("chunk_id").asText().equals(id) && chunk.path("attempted").isBoolean());
                if (chunk.path("attempted").booleanValue()) {
                    result(chunk); calls++;
                    for (String suffix : List.of("prompt", "output", "response", "exchange")) names.add(prefix + "-" + id + "." + suffix);
                } else {
                    require(chunk.path("status").asText().equals("not_attempted")
                            && Set.of("CHUNK_REQUEST_LIMIT", "CHUNK_NOT_ATTEMPTED").contains(chunk.path("error_code").asText())
                            && chunk.path("error_path").isNull() && chunk.path("failure_kind").asText().equals("review")
                            && chunk.path("retryable").isBoolean() && !chunk.path("retryable").booleanValue());
                }
                allValidated &= chunk.path("status").asText().equals("validated");
            }
            require(!attempt.path("status").asText().equals("validated") || allValidated);
        }
        require(attempts.get(attempts.size() - 1).path("status").equals(receipt.path("status")) && keys(artifacts).equals(names));
        for (JsonNode artifact : artifacts) {
            require(artifact.isObject() && keys(artifact).equals(Set.of("size", "sha256"))
                    && artifact.path("size").isIntegralNumber() && artifact.path("size").canConvertToLong() && artifact.path("size").longValue() >= 0
                    && artifact.path("sha256").isTextual() && artifact.path("sha256").textValue().matches(HASH));
        }
        require(receipt.path("input_sha256").equals(artifacts.path("input.json").path("sha256"))
                && receipt.path("metadata_sha256").equals(artifacts.path("metadata.json").path("sha256")));
        if (chunked) require(receipt.path("total_calls").isIntegralNumber() && receipt.path("total_calls").canConvertToLong()
                && receipt.path("total_calls").longValue() == calls
                && receipt.path("chunk_plan_sha256").isTextual() && receipt.path("chunk_plan_sha256").textValue().matches(HASH)
                && receipt.path("chunk_plan_sha256").equals(artifacts.path("chunk-plan.json").path("sha256")));
        return names;
    }

    private static void result(JsonNode result) {
        String status = result.path("status").asText();
        require(Set.of("validated", "failed").contains(status) && result.path("retryable").isBoolean());
        if (status.equals("validated")) require(result.path("error_code").isNull() && result.path("error_path").isNull()
                && result.path("failure_kind").isNull() && !result.path("retryable").booleanValue());
        else require(result.path("error_code").isTextual() && !result.path("error_code").textValue().isBlank()
                && (result.path("error_path").isNull() || result.path("error_path").isTextual())
                && result.path("failure_kind").isTextual() && !result.path("failure_kind").textValue().isBlank());
    }

    public void checkDraft(String runId, Path root, String draftJson) {
        validate(runId != null && runId.matches(UUID) && draftJson != null, "run_id");
        validate(root != null && root.isAbsolute() && !Files.isSymbolicLink(root), "archive_root");
        byte[] input = draftJson.getBytes(StandardCharsets.UTF_8);
        validate(input.length <= LIMIT, "events");
        try {
            var process = PythonProcess.execute(executable, workdir, List.of("-m", "processing.extraction", "check-draft",
                    runId, "--root", root.toString()), input, timeout);
            validate(process.exitCode() == 0, "events");
            JsonNode packet = json.parseJson(process.stdout());
            require(keys(packet).equals(Set.of("protocol_version", "status", "run_id", "input_sha256"))
                    && packet.path("protocol_version").asText().equals("ai-draft-check-v1")
                    && packet.path("status").asText().equals("validated")
                    && packet.path("run_id").asText().equals(runId)
                    && packet.path("input_sha256").asText().equals(ReviewedImportReader.sha256(input)));
        } catch (PythonProcess.Failure ex) {
            throw new ExtractionException("EXTRACTION_RUNTIME_UNAVAILABLE", null, ex.retryable());
        } catch (ImportException ex) {
            throw new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false);
        }
    }

    private byte[] checked(Path directory, String name, JsonNode receipt) throws IOException {
        byte[] bytes = read(directory.resolve(name));
        JsonNode artifact = receipt.path("artifacts").path(name);
        require(artifact.path("size").isIntegralNumber() && artifact.path("size").longValue() == bytes.length
                && artifact.path("sha256").asText().equals(ReviewedImportReader.sha256(bytes)));
        return bytes;
    }

    /** 큰 실패 원출력도 보존하며 전체 size/SHA를 고정 크기 버퍼로 대조한다. */
    private void checkFingerprint(Path directory, String name, JsonNode receipt) throws IOException {
        Path file = directory.resolve(name); require(Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS));
        try (var stream = Files.newInputStream(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            var digest = MessageDigest.getInstance("SHA-256");
            byte[] buffer = new byte[64 * 1024]; long size = 0; int count;
            while ((count = stream.read(buffer)) != -1) { digest.update(buffer, 0, count); size += count; }
            JsonNode artifact = receipt.path("artifacts").path(name);
            require(artifact.path("size").longValue() == size
                    && artifact.path("sha256").textValue().equals(HexFormat.of().formatHex(digest.digest())));
        } catch (NoSuchAlgorithmException ex) { throw new IllegalStateException(ex); }
    }

    private byte[] read(Path file) throws IOException {
        require(Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS));
        try (var stream = Files.newInputStream(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = stream.readNBytes(LIMIT + 1); require(bytes.length <= LIMIT); return bytes;
        }
    }

    private void sealed(Path path) throws IOException {
        var view = Files.getFileAttributeView(path, PosixFileAttributeView.class, LinkOption.NOFOLLOW_LINKS);
        if (view == null) throw new IOException("SNAPSHOT_POSIX_REQUIRED");
        var permissions = view.readAttributes().permissions();
        require(java.util.Collections.disjoint(permissions, Set.of(PosixFilePermission.OWNER_WRITE,
                PosixFilePermission.GROUP_WRITE, PosixFilePermission.OTHERS_WRITE)));
    }

    private static Set<String> keys(JsonNode node) {
        var result = new HashSet<String>(); node.fieldNames().forEachRemaining(result::add); return result;
    }

    private static void require(boolean condition) {
        if (!condition) throw new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false);
    }

    private static void validate(boolean condition, String field) {
        if (!condition) throw new ExtractionException("EXTRACTION_VALIDATION_ERROR", field, false);
    }
}
