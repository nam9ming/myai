package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.extraction.VerifiedExtraction;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;
import java.util.List;
import java.util.Set;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.*;

class ExtractionArchiveProtocolTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void keepsManualAndApiV1ArtifactSetsExact() {
        var receipt = receipt(false);
        assertThat(ExtractionArchiveReader.artifactNames(receipt)).containsExactlyInAnyOrder(
                "input.json", "metadata.json", "attempt-1.prompt", "attempt-1.output", "attempt-1.response", "attempt-1.exchange");
        receipt.put("execution_mode", "manual_import");
        ((ObjectNode) receipt.path("artifacts")).remove(List.of("attempt-1.response", "attempt-1.exchange"));
        assertThat(ExtractionArchiveReader.artifactNames(receipt)).containsExactlyInAnyOrder(
                "input.json", "metadata.json", "attempt-1.prompt", "attempt-1.output");
    }

    @Test
    void includesOnlyAttemptedV2SubrequestsAndFullCycleOutputs() {
        var receipt = receipt(true);
        assertThat(ExtractionArchiveReader.artifactNames(receipt)).hasSize(15).contains(
                "chunk-plan.json", "attempt-1.prompt", "attempt-1.output", "attempt-2.prompt", "attempt-2.output",
                "attempt-1-chunk-000001.response", "attempt-2-chunk-000001.exchange");
        var run = new VerifiedExtraction(Path.of("/synthetic"), mapper.createObjectNode(), mapper.createObjectNode(),
                receipt, "{}", receipt.toString(), "0".repeat(64));
        assertThat(run.attempts()).isEqualTo(2);
        assertThat(run.outputSha256()).isEqualTo("2".repeat(64));
    }

    @Test
    void acceptsUnattemptedPlanFailureWithoutAnySubrequestFiles() {
        var receipt = receipt(true);
        receipt.put("status", "failed").put("total_calls", 0);
        var attempts = receipt.putArray("attempts");
        var attempt = result(1, false); attempt.put("error_code", "CHUNK_REQUEST_LIMIT").put("failure_kind", "review").put("retryable", false);
        attempt.putArray("chunks").add(unattempted("chunk-000001", "CHUNK_REQUEST_LIMIT")); attempts.add(attempt);
        var artifacts = receipt.putObject("artifacts");
        for (String name : List.of("input.json", "metadata.json", "chunk-plan.json", "attempt-1.prompt", "attempt-1.output")) artifact(artifacts, name);
        assertThat(ExtractionArchiveReader.artifactNames(receipt)).hasSize(5);
    }

    @Test
    void rejectsMissingExtraUnsafeAndNoncanonicalArtifactNames() {
        for (boolean chunked : List.of(false, true)) {
            invalid(chunked, value -> ((ObjectNode) value.path("artifacts")).remove("attempt-1.output"));
            for (String name : List.of("../outside", "/absolute", "attempt-0.output", "attempt-4.prompt", "attempt-1-chunk-000001/response", "attempt-1-chunk-1.output"))
                invalid(chunked, value -> artifact((ObjectNode) value.path("artifacts"), name));
            invalid(chunked, value -> value.put("extra", true));
            invalid(chunked, value -> ((ObjectNode) value.path("attempts").get(0)).put("extra", true));
        }
        invalid(false, value -> value.put("chunk_plan_sha256", "0".repeat(64)));
        invalid(true, value -> ((ObjectNode) value.path("artifacts")).remove("chunk-plan.json"));
        invalid(true, value -> artifact((ObjectNode) value.path("artifacts"), "attempt-1.response"));
    }

    @Test
    void rejectsInvalidChunkStatusesAttemptsCallsAndHashes() {
        invalid(true, value -> value.put("execution_mode", "manual_import"));
        invalid(true, value -> value.put("total_calls", 1));
        invalid(true, value -> value.put("total_calls", 4294967298L));
        invalid(true, value -> value.put("total_calls", true));
        invalid(true, value -> value.put("chunk_plan_sha256", "1".repeat(64)));
        invalid(true, value -> value.put("status", "failed"));
        invalid(true, value -> ((ObjectNode) value.path("attempts").get(0)).put("attempt", 2));
        invalid(true, value -> ((ObjectNode) chunk(value, 0)).put("attempted", false));
        invalid(true, value -> ((ObjectNode) chunk(value, 0)).put("attempted", "true"));
        invalid(true, value -> ((ObjectNode) chunk(value, 0)).put("status", "not_attempted"));
        invalid(true, value -> ((ObjectNode) chunk(value, 0)).put("chunk_id", "../chunk-000001"));
        invalid(true, value -> ((ObjectNode) chunk(value, 1)).put("chunk_id", "chunk-000002"));
        invalid(true, value -> ((ObjectNode) chunk(value, 1)).put("extra", true));
        invalid(true, value -> ((ObjectNode) chunk(value, 1)).put("retryable", true));
        invalid(true, value -> ((ObjectNode) value.path("artifacts").path("attempt-2.output")).put("sha256", "not-a-hash"));
        invalid(true, value -> ((ObjectNode) value.path("artifacts").path("attempt-2.output")).put("sha256", new java.math.BigInteger("2".repeat(64))));
        invalid(true, value -> ((ObjectNode) value.path("artifacts").path("attempt-2.output")).put("size", -1));
    }

    private JsonNode chunk(JsonNode receipt, int cycle) { return receipt.path("attempts").get(cycle).path("chunks").get(0); }

    private void invalid(boolean chunked, Consumer<ObjectNode> edit) {
        var value = receipt(chunked); edit.accept(value);
        assertThatThrownBy(() -> ExtractionArchiveReader.artifactNames(value)).isInstanceOfSatisfying(ExtractionException.class,
                ex -> assertThat(ex.code()).isEqualTo("EXTRACTION_ARCHIVE_INVALID"));
    }

    private ObjectNode receipt(boolean chunked) {
        var value = mapper.createObjectNode().put("format_version", chunked ? "extraction-archive-v2" : "extraction-archive-v1")
                .put("run_id", "71fb66f0-e610-4f9c-8f26-4bb77655ee8c").put("document_version_id", "10000000-0000-4000-8000-000000000001")
                .put("data_kind", "synthetic").put("execution_mode", "api").put("recorded_at", "2026-11-04T00:00:00Z")
                .put("status", "validated").put("review_required", true).put("input_sha256", "0".repeat(64)).put("metadata_sha256", "0".repeat(64));
        var artifacts = value.putObject("artifacts"); artifact(artifacts, "input.json"); artifact(artifacts, "metadata.json");
        if (chunked) { value.put("chunk_plan_sha256", "0".repeat(64)).put("total_calls", 2); artifact(artifacts, "chunk-plan.json"); }
        var attempts = value.putArray("attempts");
        for (int cycle = 1; cycle <= (chunked ? 2 : 1); cycle++) {
            var attempt = result(cycle, !chunked || cycle == 2);
            if (chunked) {
                var chunk = attempt.deepCopy(); chunk.remove("attempt"); chunk.put("chunk_id", "chunk-000001").put("attempted", true);
                attempt.putArray("chunks").add(chunk);
            }
            attempts.add(attempt);
            for (String suffix : List.of("prompt", "output")) artifact(artifacts, "attempt-" + cycle + "." + suffix);
            for (String suffix : List.of("prompt", "output", "response", "exchange"))
                if (chunked || !Set.of("prompt", "output").contains(suffix)) artifact(artifacts, "attempt-" + cycle + (chunked ? "-chunk-000001" : "") + "." + suffix);
        }
        if (chunked) ((ObjectNode) artifacts.path("attempt-2.output")).put("sha256", "2".repeat(64));
        return value;
    }

    private ObjectNode result(int cycle, boolean valid) {
        var value = mapper.createObjectNode().put("attempt", cycle).put("status", valid ? "validated" : "failed").put("retryable", !valid);
        if (valid) value.putNull("error_code").putNull("error_path").putNull("failure_kind");
        else value.put("error_code", "JSON_INVALID").put("error_path", "$").put("failure_kind", "schema");
        return value;
    }

    private ObjectNode unattempted(String id, String code) {
        return mapper.createObjectNode().put("chunk_id", id).put("attempted", false).put("status", "not_attempted")
                .put("error_code", code).putNull("error_path").put("failure_kind", "review").put("retryable", false);
    }

    private void artifact(ObjectNode artifacts, String name) { artifacts.putObject(name).put("sha256", "0".repeat(64)).put("size", 0); }
}
