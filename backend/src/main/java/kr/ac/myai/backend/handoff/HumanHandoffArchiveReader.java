package kr.ac.myai.backend.handoff;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.extraction.ExtractionException;
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
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFileAttributeView;
import java.nio.file.attribute.PosixFilePermission;
import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;

@Component
@Profile("!fixture")
public class HumanHandoffArchiveReader {
    private static final int LIMIT = 8 * 1024 * 1024;
    private static final String HASH = "[0-9a-f]{64}";
    private static final String UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
    private final ReviewedImportReader json;
    private final String executable;
    private final String workdir;
    private final long timeout;

    public HumanHandoffArchiveReader(ReviewedImportReader json,
                                    @Value("${app.calculation.python-executable:python3.13}") String executable,
                                    @Value("${app.calculation.workdir:}") String workdir,
                                    @Value("${app.extraction.timeout-ms:60000}") long timeout) {
        this.json = json; this.executable = executable; this.workdir = workdir; this.timeout = timeout;
    }

    public VerifiedHandoff read(HandoffReference reference) {
        validate(reference != null, "human_handoffs");
        return read(reference.handoffRef(), reference.receiptSha256(), Path.of(reference.directory()).getParent());
    }

    public VerifiedHandoff read(String ref, String receiptHash, Path root) {
        validate(ref != null && ref.matches(HASH), "handoff_ref");
        validate(receiptHash != null && receiptHash.matches(HASH), "receipt_sha256");
        validate(root != null && root.isAbsolute() && root.normalize().equals(root) && !Files.isSymbolicLink(root), "handoff_root");
        try {
            validate(root.toRealPath().equals(root) && Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS), "handoff_root");
            Path directory = root.resolve(ref);
            Object rootKey = directoryKey(root), directoryKey = directoryKey(directory);
            sealed(directory, true);
            var process = PythonProcess.execute(executable, workdir, List.of("-B", "-m", "processing.evaluation", "verify-handoff", ref,
                    "--root", root.toString()), new byte[0], timeout);
            if (process.exitCode() != 0) {
                throw new ExtractionException(switch (process.exitCode()) {
                    case 2 -> "EXTRACTION_VALIDATION_ERROR";
                    case 3 -> "EXTRACTION_ARCHIVE_INVALID";
                    case 5 -> "EXTRACTION_IO_ERROR";
                    default -> "EXTRACTION_PROTOCOL_ERROR";
                }, null, false);
            }
            JsonNode receipt = json.parseJson(process.stdout());
            shape(receipt, "format_version status handoff_ref frozen_at artifacts summary");
            require(text(receipt, "format_version").equals("human-handoff-archive-v1")
                    && text(receipt, "status").equals("frozen") && text(receipt, "handoff_ref").equals(ref));
            text(receipt, "frozen_at");
            JsonNode artifacts = receipt.path("artifacts");
            require(artifacts.isObject() && artifacts.has("selection.json") && artifacts.has("projection.json"));
            for (JsonNode artifact : artifacts) {
                shape(artifact, "sha256 size");
                require(text(artifact, "sha256").matches(HASH) && count(artifact, "size") >= 0);
            }
            byte[] savedReceipt = read(directory.resolve("receipt.json"));
            require(json.parseJson(savedReceipt).equals(receipt) && ReviewedImportReader.sha256(savedReceipt).equals(receiptHash));
            JsonNode summary = receipt.path("summary");
            shape(summary, "protocol_version status backend_import_supported review_required handoff_ref data_kind review_ref source_run_id source_status source_execution_mode event_count evidence_count projection_sha256 review_basis review_duration_ns");
            require(text(summary, "protocol_version").equals("human-handoff-summary-v1")
                    && text(summary, "status").equals("projection_only")
                    && summary.path("backend_import_supported").isBoolean() && !summary.path("backend_import_supported").booleanValue()
                    && summary.path("review_required").isBoolean() && summary.path("review_required").booleanValue()
                    && text(summary, "handoff_ref").equals(ref));
            require(Set.of("synthetic", "real").contains(text(summary, "data_kind"))
                    && Set.of("source_only", "gold_feedback", "unknown").contains(text(summary, "review_basis")));
            require(summary.path("review_duration_ns").isIntegralNumber() && summary.path("review_duration_ns").bigIntegerValue().signum() >= 0);
            byte[] projectionBytes = checked(directory, "projection.json", receipt);
            require(ReviewedImportReader.sha256(projectionBytes).equals(text(summary, "projection_sha256")));
            JsonNode projection = json.parseJson(projectionBytes);
            shape(projection, "schema_version handoff_id handoff_ref projected_at review parent context data_kind documents evidence events");
            require(text(projection, "schema_version").equals("human-handoff-projection-v1")
                    && text(projection, "handoff_id").matches(UUID) && text(projection, "handoff_ref").equals(ref)
                    && ReviewedImportReader.sha256(text(projection, "handoff_id").getBytes(StandardCharsets.UTF_8)).equals(ref)
                    && projection.path("data_kind").equals(summary.path("data_kind")));
            text(projection, "projected_at");
            require(projection.path("documents").isArray() && projection.path("documents").size() == 1
                    && projection.path("events").isArray() && projection.path("events").size() == count(summary, "event_count")
                    && projection.path("evidence").isArray() && projection.path("evidence").size() == count(summary, "evidence_count"));
            shape(projection.path("context"), "area_id split_group_id dictionary_version");
            require(text(projection.path("context"), "area_id").matches(UUID) && text(projection.path("context"), "split_group_id").matches(UUID));
            text(projection.path("context"), "dictionary_version");
            JsonNode reviewRef = projection.path("review"), parent = projection.path("parent");
            shape(reviewRef, "review_id review_ref receipt_sha256");
            shape(parent, "run_id receipt_sha256 status execution_mode");
            String reviewId = text(reviewRef, "review_id"), reviewHash = text(reviewRef, "review_ref");
            require(reviewId.matches(UUID) && reviewHash.matches(HASH)
                    && ReviewedImportReader.sha256(reviewId.getBytes(StandardCharsets.UTF_8)).equals(reviewHash)
                    && reviewRef.path("review_ref").equals(summary.path("review_ref"))
                    && text(reviewRef, "receipt_sha256").matches(HASH));
            require(text(parent, "run_id").matches(UUID) && text(parent, "receipt_sha256").matches(HASH)
                    && Set.of("validated", "failed").contains(text(parent, "status"))
                    && Set.of("api", "manual_import").contains(text(parent, "execution_mode"))
                    && parent.path("run_id").equals(summary.path("source_run_id"))
                    && parent.path("status").equals(summary.path("source_status"))
                    && parent.path("execution_mode").equals(summary.path("source_execution_mode")));
            String reviewPath = "review/" + reviewHash + "/";
            byte[] reviewReceiptBytes = checked(directory, reviewPath + "receipt.json", receipt);
            require(ReviewedImportReader.sha256(reviewReceiptBytes).equals(reviewRef.path("receipt_sha256").textValue()));
            JsonNode reviewReceipt = json.parseJson(reviewReceiptBytes);
            require(text(reviewReceipt, "format_version").equals("human-review-archive-v1")
                    && text(reviewReceipt, "status").equals("frozen") && reviewReceipt.path("review_ref").equals(reviewRef.path("review_ref"))
                    && reviewReceipt.path("summary").path("review_id").equals(reviewRef.path("review_id")));
            JsonNode review = json.parseJson(checked(directory, reviewPath + "review.json", receipt));
            shape(review, "schema_version review_id source review output changes");
            require(text(review, "schema_version").equals("human-review-v1") && review.path("review_id").equals(reviewRef.path("review_id"))
                    && review.path("review").isObject() && review.path("output").isObject() && review.path("changes").isArray());
            JsonNode source = review.path("source");
            shape(source, "run_id snapshot_ref receipt_sha256");
            String snapshot = text(source, "snapshot_ref"), runId = parent.path("run_id").textValue();
            require(source.path("run_id").equals(parent.path("run_id")) && source.path("receipt_sha256").equals(parent.path("receipt_sha256"))
                    && (snapshot.equals(runId) || snapshot.equals("registered/" + parent.path("receipt_sha256").textValue() + "/" + runId)));
            byte[] parentReceiptBytes = checked(directory, reviewPath + "source/" + snapshot + "/receipt.json", receipt);
            require(ReviewedImportReader.sha256(parentReceiptBytes).equals(parent.path("receipt_sha256").textValue()));
            JsonNode parentReceipt = json.parseJson(parentReceiptBytes);
            require(text(parentReceipt, "format_version").equals("extraction-archive-v1")
                    && parentReceipt.path("run_id").equals(parent.path("run_id")) && parentReceipt.path("status").equals(parent.path("status"))
                    && parentReceipt.path("execution_mode").equals(parent.path("execution_mode"))
                    && parentReceipt.path("data_kind").equals(projection.path("data_kind"))
                    && text(parentReceipt, "document_version_id").matches(UUID)
                    && parentReceipt.path("document_version_id").equals(projection.path("documents").get(0).path("document_version_id"))
                    && parentReceipt.path("document_version_id").equals(review.path("output").path("document_version_id")));
            require(Objects.equals(rootKey, directoryKey(root)) && Objects.equals(directoryKey, directoryKey(directory)));
            sealed(directory, true);
            return new VerifiedHandoff(directory, projection, review, receipt, receiptHash);
        } catch (PythonProcess.Failure ex) {
            throw new ExtractionException("EXTRACTION_RUNTIME_UNAVAILABLE", null, ex.retryable());
        } catch (ImportException ex) {
            throw new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false);
        } catch (IOException | SecurityException ex) {
            throw new ExtractionException("EXTRACTION_IO_ERROR", null, true);
        }
    }

    private Object directoryKey(Path directory) throws IOException {
        require(Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS) && directory.toRealPath().equals(directory));
        return Files.readAttributes(directory, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS).fileKey();
    }

    private byte[] checked(Path directory, String name, JsonNode receipt) throws IOException {
        byte[] bytes = read(directory.resolve(name));
        JsonNode artifact = receipt.path("artifacts").path(name);
        require(count(artifact, "size") == bytes.length && text(artifact, "sha256").equals(ReviewedImportReader.sha256(bytes)));
        return bytes;
    }

    private byte[] read(Path file) throws IOException {
        require(Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS) && file.toRealPath().equals(file));
        sealed(file, false);
        try (var stream = Files.newInputStream(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = stream.readNBytes(LIMIT + 1);
            require(bytes.length > 0 && bytes.length <= LIMIT);
            return bytes;
        }
    }

    private void sealed(Path path, boolean directory) throws IOException {
        var view = Files.getFileAttributeView(path, PosixFileAttributeView.class, LinkOption.NOFOLLOW_LINKS);
        require(view != null);
        require(view.readAttributes().permissions().equals(directory
                ? Set.of(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_EXECUTE) : Set.of(PosixFilePermission.OWNER_READ)));
    }

    private static String text(JsonNode node, String key) {
        JsonNode value = node.path(key);
        require(value.isTextual() && !value.textValue().isBlank());
        return value.textValue();
    }

    private static long count(JsonNode node, String key) {
        JsonNode value = node.path(key);
        require(value.isIntegralNumber() && value.canConvertToLong() && value.longValue() >= 0);
        return value.longValue();
    }

    private static void shape(JsonNode node, String names) {
        var keys = new HashSet<String>(); node.fieldNames().forEachRemaining(keys::add);
        require(node.isObject() && keys.equals(Set.of(names.split(" "))));
    }

    private static void require(boolean condition) {
        if (!condition) throw new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false);
    }

    private static void validate(boolean condition, String field) {
        if (!condition) throw new ExtractionException("EXTRACTION_VALIDATION_ERROR", field, false);
    }
}
