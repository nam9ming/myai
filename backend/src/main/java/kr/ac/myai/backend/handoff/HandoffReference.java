package kr.ac.myai.backend.handoff;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.extraction.ExtractionException;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

public record HandoffReference(String directory, String handoffRef, String receiptSha256) {
    public HandoffReference {
        validate(handoffRef != null && handoffRef.matches("[0-9a-f]{64}")
                && receiptSha256 != null && receiptSha256.matches("[0-9a-f]{64}"));
        validate(directory != null && !directory.isBlank() && directory.length() <= 4096);
        try {
            Path path = Path.of(directory);
            validate(path.isAbsolute() && path.normalize().equals(path) && path.toString().equals(directory)
                    && path.getFileName() != null && path.getFileName().toString().equals(handoffRef));
        } catch (IllegalArgumentException ex) { throw invalid(); }
    }

    public static List<HandoffReference> list(JsonNode array) {
        validate(array != null);
        if (array.isMissingNode() || array.isNull()) return List.of();
        validate(array.isArray() && !array.isEmpty());
        var result = new ArrayList<HandoffReference>();
        var directories = new HashSet<String>();
        var references = new HashSet<String>();
        for (JsonNode value : array) {
            var keys = new HashSet<String>(); value.fieldNames().forEachRemaining(keys::add);
            validate(value.isObject() && keys.equals(Set.of("directory", "handoff_ref", "receipt_sha256"))
                    && value.path("directory").isTextual() && value.path("handoff_ref").isTextual()
                    && value.path("receipt_sha256").isTextual());
            var reference = new HandoffReference(value.path("directory").textValue(), value.path("handoff_ref").textValue(),
                    value.path("receipt_sha256").textValue());
            validate(directories.add(reference.directory()) && references.add(reference.handoffRef()));
            result.add(reference);
        }
        return List.copyOf(result);
    }

    private static void validate(boolean condition) { if (!condition) throw invalid(); }
    private static ExtractionException invalid() { return new ExtractionException("EXTRACTION_VALIDATION_ERROR", "human_handoffs", false); }
}
