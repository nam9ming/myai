package kr.ac.myai.backend.handoff;

import com.fasterxml.jackson.databind.JsonNode;

import java.nio.file.Path;

public record VerifiedHandoff(Path directory, JsonNode projection, JsonNode review, JsonNode receipt,
                              String receiptSha256) {
    public HandoffReference reference() {
        return new HandoffReference(directory.toString(), receipt.path("handoff_ref").asText(), receiptSha256);
    }
}
