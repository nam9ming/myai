package kr.ac.myai.backend.handoff;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
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
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashSet;
import java.util.HexFormat;
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
            var process = PythonProcess.executeKeyless(executable, workdir, List.of("-B", "-s", "-m", "processing.evaluation", "verify-handoff", ref,
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
            boolean citizen = text(projection, "schema_version").equals("citizen-human-handoff-projection-v1");
            require((citizen || text(projection, "schema_version").equals("human-handoff-projection-v1"))
                    && text(projection, "handoff_id").matches(UUID) && text(projection, "handoff_ref").equals(ref)
                    && ReviewedImportReader.sha256(text(projection, "handoff_id").getBytes(StandardCharsets.UTF_8)).equals(ref)
                    && projection.path("data_kind").equals(summary.path("data_kind")));
            text(projection, "projected_at");
            require(projection.path("documents").isArray() && projection.path("documents").size() == 1
                    && projection.path("events").isArray() && projection.path("events").size() == count(summary, "event_count")
                    && projection.path("evidence").isArray() && projection.path("evidence").size() == count(summary, "evidence_count"));
            shape(projection.path("context"), citizen ? "split_group_id" : "area_id split_group_id dictionary_version");
            require(text(projection.path("context"), "split_group_id").matches(UUID));
            if (!citizen) {
                require(text(projection.path("context"), "area_id").matches(UUID));
                text(projection.path("context"), "dictionary_version");
            }
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
            String parentPath = reviewPath + "source/" + snapshot + "/";
            byte[] parentReceiptBytes = checked(directory, parentPath + "receipt.json", receipt);
            require(ReviewedImportReader.sha256(parentReceiptBytes).equals(parent.path("receipt_sha256").textValue()));
            JsonNode parentReceipt = json.parseJson(parentReceiptBytes);
            ExtractionArchiveReader.artifactNames(parentReceipt);
            require(parentReceipt.path("run_id").equals(parent.path("run_id")) && parentReceipt.path("status").equals(parent.path("status"))
                    && parentReceipt.path("execution_mode").equals(parent.path("execution_mode"))
                    && parentReceipt.path("data_kind").equals(projection.path("data_kind"))
                    && text(parentReceipt, "document_version_id").matches(UUID)
                    && parentReceipt.path("document_version_id").equals(projection.path("documents").get(0).path("document_version_id"))
                    && parentReceipt.path("document_version_id").equals(review.path("output").path("document_version_id")));
            JsonNode selection = json.parseJson(checked(directory, "selection.json", receipt));
            shape(selection, citizen ? "schema_version handoff_id review_ref review_receipt_sha256 source split_group_id"
                    : "schema_version handoff_id review_ref review_receipt_sha256 source area_id split_group_id dictionary_version");
            require(text(selection, "schema_version").equals(citizen ? "citizen-human-handoff-v1" : "human-handoff-v1")
                    && selection.path("handoff_id").equals(projection.path("handoff_id"))
                    && selection.path("review_ref").equals(reviewRef.path("review_ref"))
                    && selection.path("review_receipt_sha256").equals(reviewRef.path("receipt_sha256")));
            for (var fields = projection.path("context").fieldNames(); fields.hasNext();) {
                String field = fields.next(); require(selection.path(field).equals(projection.path("context").path(field)));
            }
            JsonNode selectedSource = selection.path("source");
            shape(selectedSource, "schema_version data_kind documents evidence events");
            require(text(selectedSource, "schema_version").equals("source-import-v1")
                    && selectedSource.path("data_kind").equals(projection.path("data_kind"))
                    && selectedSource.path("documents").equals(projection.path("documents"))
                    && selectedSource.path("evidence").isArray() && selectedSource.path("evidence").isEmpty()
                    && selectedSource.path("events").isArray() && selectedSource.path("events").isEmpty());
            JsonNode metadata = json.parseJson(checked(directory, parentPath + "metadata.json", receipt));
            String schema = citizen ? "extract-citizen-v1" : "extract-schema-v1";
            require(text(metadata, "schema_version").equals(schema) && text(review.path("output"), "schema_version").equals(schema)
                    && metadata.path("run_id").equals(parent.path("run_id"))
                    && metadata.path("execution_mode").equals(parent.path("execution_mode")));
            if (citizen) {
                require(text(parentReceipt, "format_version").equals("extraction-archive-v1")
                        && text(parent, "execution_mode").equals("manual_import"));
                JsonNode input = json.parseJson(checked(directory, parentPath + "input.json", receipt));
                JsonNode document = projection.path("documents").get(0);
                var expected = com.fasterxml.jackson.databind.node.JsonNodeFactory.instance.objectNode();
                expected.set("data_kind", projection.path("data_kind"));
                for (String field : List.of("document_version_id", "title", "published_date")) expected.set(field, document.path(field));
                expected.set("blocks", document.path("block_index"));
                require(input.equals(expected) && metadata.path("preprocessing_version").equals(document.path("preprocessing_version")));
                verifyCitizenTree(directory, receipt, reviewReceipt, parentReceipt, reviewPath, parentPath);
            }
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

    private void verifyCitizenTree(Path directory, JsonNode receipt, JsonNode reviewReceipt, JsonNode parentReceipt,
                                   String reviewPath, String parentPath) throws IOException {
        var parentNames = new HashSet<>(ExtractionArchiveReader.artifactNames(parentReceipt));
        parentNames.addAll(Set.of("identity.json", "receipt.json"));
        var reviewNames = new HashSet<>(Set.of("review.json", "output.json"));
        String sourcePath = parentPath.substring(reviewPath.length());
        for (String name : parentNames) reviewNames.add(sourcePath + name);
        require(keys(reviewReceipt.path("artifacts")).equals(reviewNames));
        var names = new HashSet<>(Set.of("selection.json", "projection.json"));
        reviewNames.addAll(Set.of("identity.json", "receipt.json"));
        for (String name : reviewNames) names.add(reviewPath + name);
        require(keys(receipt.path("artifacts")).equals(names));
        bindArtifacts(receipt, reviewReceipt, reviewPath);
        bindArtifacts(receipt, parentReceipt, parentPath);
        JsonNode identity = json.parseJson(read(directory.resolve("identity.json")));
        shape(identity, "format_version handoff_ref artifacts recorded_at");
        require(identity.path("format_version").equals(receipt.path("format_version"))
                && identity.path("handoff_ref").equals(receipt.path("handoff_ref"))
                && identity.path("artifacts").equals(receipt.path("artifacts"))
                && identity.path("recorded_at").equals(receipt.path("frozen_at")));
        require(json.parseJson(checked(directory, reviewPath + "output.json", receipt))
                .equals(json.parseJson(checked(directory, reviewPath + "review.json", receipt)).path("output")));
        names.addAll(Set.of("identity.json", "receipt.json"));
        var expectedDirectories = new HashSet<Path>(); expectedDirectories.add(directory);
        for (String name : names) {
            Path path = directory.resolve(name);
            require(path.normalize().equals(path) && path.startsWith(directory) && !path.equals(directory));
            for (Path parent = path.getParent(); parent.startsWith(directory); parent = parent.getParent()) expectedDirectories.add(parent);
        }
        var actual = new HashSet<String>();
        try (var paths = Files.walk(directory)) {
            for (Path path : paths.toList()) {
                require(path.toRealPath().equals(path));
                if (Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) {
                    require(expectedDirectories.contains(path)); sealed(path, true);
                } else {
                    require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)); sealed(path, false);
                    String name = directory.relativize(path).toString(); require(names.contains(name)); actual.add(name);
                    if (receipt.path("artifacts").has(name)) fingerprint(path, receipt.path("artifacts").path(name));
                }
            }
        }
        require(actual.equals(names));
    }

    private void bindArtifacts(JsonNode receipt, JsonNode child, String prefix) {
        require(child.path("artifacts").isObject());
        for (var fields = child.path("artifacts").fieldNames(); fields.hasNext();) {
            String name = fields.next(); require(child.path("artifacts").path(name).equals(receipt.path("artifacts").path(prefix + name)));
        }
    }

    private void fingerprint(Path file, JsonNode artifact) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (var stream = new DigestInputStream(Files.newInputStream(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS), digest)) {
                long size = stream.transferTo(java.io.OutputStream.nullOutputStream());
                require(size == count(artifact, "size") && HexFormat.of().formatHex(digest.digest()).equals(text(artifact, "sha256")));
            }
        } catch (NoSuchAlgorithmException ex) { throw new IllegalStateException(ex); }
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
        require(node.isObject() && keys(node).equals(Set.of(names.split(" "))));
    }

    private static Set<String> keys(JsonNode node) { var keys = new HashSet<String>(); node.fieldNames().forEachRemaining(keys::add); return keys; }

    private static void require(boolean condition) {
        if (!condition) throw new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false);
    }

    private static void validate(boolean condition, String field) {
        if (!condition) throw new ExtractionException("EXTRACTION_VALIDATION_ERROR", field, false);
    }
}
