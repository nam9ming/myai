package kr.ac.myai.backend.extraction;

import com.fasterxml.jackson.databind.JsonNode;

import java.nio.file.Path;

public record VerifiedExtraction(Path directory, JsonNode input, JsonNode metadata, JsonNode receipt,
                                 String metadataJson, String receiptJson, String receiptSha256) {
    public String runId() { return receipt.path("run_id").asText(); }
    public String documentVersionId() { return receipt.path("document_version_id").asText(); }
    public String status() { return receipt.path("status").asText(); }
    public String dataKind() { return receipt.path("data_kind").asText(); }
    public int attempts() { return receipt.path("attempts").size(); }
    public String inputSha256() { return receipt.path("input_sha256").asText(); }
    public String metadataSha256() { return receipt.path("metadata_sha256").asText(); }
    public String outputSha256() { return receipt.path("artifacts").path("attempt-" + attempts() + ".output").path("sha256").asText(); }
    public String nullable(String key) { return metadata.path(key).isNull() ? null : metadata.path(key).asText(); }
}
