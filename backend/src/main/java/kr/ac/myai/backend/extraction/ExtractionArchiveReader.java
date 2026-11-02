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
import java.util.HashSet;
import java.util.List;
import java.util.Set;

@Component
@Profile("!fixture")
public class ExtractionArchiveReader {
    private static final int LIMIT = 8 * 1024 * 1024;
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
        validate(runId != null && runId.matches(UUID), "run_id");
        validate(root.isAbsolute() && !Files.isSymbolicLink(root), "archive_root");
        try {
            Path base = root.toRealPath();
            Path directory = base.resolve(runId);
            validate(Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS), "archive_root");
            var process = PythonProcess.execute(executable, workdir, List.of("-m", "processing.extraction", "verify", runId,
                    "--root", base.toString()), new byte[0], timeout);
            if (process.exitCode() != 0 && process.exitCode() != 4) {
                throw new ExtractionException(switch (process.exitCode()) {
                    case 2 -> "EXTRACTION_VALIDATION_ERROR";
                    case 3 -> "EXTRACTION_ARCHIVE_INVALID";
                    case 5 -> "EXTRACTION_IO_ERROR";
                    default -> "EXTRACTION_PROTOCOL_ERROR";
                }, null, false);
            }
            JsonNode receipt = json.parseJson(process.stdout());
            require(keys(receipt).equals(Set.of("format_version", "run_id", "document_version_id", "data_kind", "execution_mode",
                    "recorded_at", "status", "review_required", "input_sha256", "metadata_sha256", "artifacts", "attempts")));
            require(receipt.path("format_version").asText().equals("extraction-archive-v1") && receipt.path("run_id").asText().equals(runId));
            require(receipt.path("document_version_id").asText().matches(UUID));
            require(receipt.path("data_kind").isTextual() && Set.of("synthetic", "real").contains(receipt.path("data_kind").asText()));
            require(receipt.path("execution_mode").asText().equals("manual_import"));
            require(receipt.path("status").asText().equals(process.exitCode() == 0 ? "validated" : "failed"));
            require(receipt.path("review_required").isBoolean() && receipt.path("review_required").asBoolean());
            require(receipt.path("attempts").isArray() && receipt.path("attempts").size() >= 1 && receipt.path("attempts").size() <= 3);
            var names = new HashSet<>(Set.of("input.json", "metadata.json"));
            for (int i = 1; i <= receipt.path("attempts").size(); i++) {
                names.add("attempt-" + i + ".prompt"); names.add("attempt-" + i + ".output");
            }
            require(keys(receipt.path("artifacts")).equals(names));
            byte[] savedReceipt = read(directory.resolve("receipt.json"));
            require(json.parseJson(savedReceipt).equals(receipt));
            byte[] input = checked(directory, "input.json", receipt);
            byte[] metadata = checked(directory, "metadata.json", receipt);
            require(receipt.path("input_sha256").asText().equals(ReviewedImportReader.sha256(input))
                    && receipt.path("metadata_sha256").asText().equals(ReviewedImportReader.sha256(metadata)));
            JsonNode source = json.parseJson(input), info = json.parseJson(metadata);
            require(info.path("run_id").asText().equals(runId) && info.path("document_version_id").equals(receipt.path("document_version_id"))
                    && source.path("document_version_id").equals(receipt.path("document_version_id"))
                    && source.path("data_kind").equals(receipt.path("data_kind"))
                    && info.path("execution_mode").equals(receipt.path("execution_mode"))
                    && info.path("schema_version").asText().equals("extract-schema-v1"));
            require(info.path("attempts").isIntegralNumber() && info.path("attempts").asInt() == receipt.path("attempts").size());
            require(receipt.path("attempts").get(receipt.path("attempts").size() - 1).path("status").equals(receipt.path("status")));
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

    private byte[] checked(Path directory, String name, JsonNode receipt) throws IOException {
        byte[] bytes = read(directory.resolve(name));
        JsonNode artifact = receipt.path("artifacts").path(name);
        require(artifact.path("size").isIntegralNumber() && artifact.path("size").longValue() == bytes.length
                && artifact.path("sha256").asText().equals(ReviewedImportReader.sha256(bytes)));
        return bytes;
    }

    private byte[] read(Path file) throws IOException {
        require(Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS));
        try (var stream = Files.newInputStream(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = stream.readNBytes(LIMIT + 1); require(bytes.length <= LIMIT); return bytes;
        }
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
