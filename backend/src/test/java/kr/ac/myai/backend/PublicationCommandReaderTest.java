package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.validation.Validation;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.publication.PublicationException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.*;

class PublicationCommandReaderTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();

    private PublicationCommand read(ObjectNode node) throws Exception {
        Path file = Files.writeString(root.resolve("command.json"), node.toString());
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            return new PublicationCommandReader(new ReviewedImportReader(), factory.getValidator()).read(file);
        }
    }

    private ObjectNode fixture(String name) throws Exception {
        return (ObjectNode) mapper.readTree(Path.of("examples/" + name + ".json").toFile());
    }

    @Test
    void permitsEmptyRejectionEvidenceForTheServiceToCheckButNeverForApproval() throws Exception {
        var command = fixture("approve");
        command.put("action", "reject"); command.putArray("evidence_ids");
        assertThat(read(command)).isInstanceOf(PublicationCommand.Decision.class);
        command.put("action", "approve");
        assertThatThrownBy(() -> read(command)).isInstanceOf(kr.ac.myai.backend.publication.PublicationException.class);
    }

    @Test
    void acceptsDecisionAndExactlyFiveVerifiedPoints() throws Exception {
        assertThat(read(fixture("approve"))).isInstanceOf(PublicationCommand.Decision.class);
        var command = (PublicationCommand.Publish) read(fixture("publish"));
        assertThat(command.points()).hasSize(5);
        assertThat(command.expectedHeadVersion()).isNull();
        assertThat(command.points().getFirst().lon()).isEqualByComparingTo("127.27");
        var preview = fixture("publish"); preview.put("action", "preview");
        assertThat(read(preview)).isInstanceOf(PublicationCommand.Publish.class);
    }

    @Test
    void rejectsUnknownMissingAndCoercedFields() throws Exception {
        var node = fixture("approve");
        node.put("unexpected", true);
        assertThatThrownBy(() -> read(node)).isInstanceOf(PublicationException.class);
        node.remove("unexpected");
        node.put("expected_revision_no", 1.5);
        assertThatThrownBy(() -> read(node)).isInstanceOf(PublicationException.class);
        node.put("expected_revision_no", "1");
        assertThatThrownBy(() -> read(node)).isInstanceOf(PublicationException.class);
        node.remove("expected_revision_no");
        assertThatThrownBy(() -> read(node)).isInstanceOf(PublicationException.class);
    }

    @Test
    void rejectsUnverifiedDuplicateOrCrossAreaPointsAndRounding() throws Exception {
        var unverified = fixture("publish");
        ((ObjectNode) unverified.path("points").get(0)).put("verification_status", "unverified");
        assertThatThrownBy(() -> read(unverified)).isInstanceOf(PublicationException.class);
        var node = fixture("publish");
        ((ObjectNode) node.path("points").get(0)).put("point_id", node.path("points").get(1).path("point_id").asText());
        ObjectNode duplicates = node;
        assertThatThrownBy(() -> read(duplicates)).isInstanceOf(PublicationException.class);
        var crossArea = fixture("publish");
        ((ObjectNode) crossArea.path("points").get(0)).put("area_id", "90000000-0000-4000-8000-000000000001");
        assertThatThrownBy(() -> read(crossArea)).isInstanceOf(PublicationException.class);
        var precision = fixture("publish");
        ((ObjectNode) precision.path("points").get(0)).put("lat", new java.math.BigDecimal("37.12345678"));
        assertThatThrownBy(() -> read(precision)).isInstanceOf(PublicationException.class);
    }

    @Test
    void validatesReplayContextWithoutAcceptingItInCurrentMode() throws Exception {
        var node = fixture("publish");
        node.put("case_id", "90000000-0000-4000-8000-000000000001");
        assertThatThrownBy(() -> read(node)).isInstanceOf(PublicationException.class);
        node.put("mode", "replay").put("anchor_date", "2026-11-02").put("reference_instant", "2026-11-02T03:00:00Z")
                .put("knowledge_cutoff", "2026-11-02T03:00:00Z").put("history_fidelity", "verified_snapshot");
        assertThat(read(node)).isInstanceOf(PublicationCommand.Publish.class);
        node.putNull("history_fidelity");
        assertThatThrownBy(() -> read(node)).isInstanceOf(PublicationException.class);
        node.put("history_fidelity", "verified_snapshot");
        node.put("knowledge_cutoff", "2026-11-02T03:00:01Z");
        assertThatThrownBy(() -> read(node)).isInstanceOf(PublicationException.class);
    }

    @Test
    void rejectsDuplicateJsonKeysAndInvalidUtcTime() throws Exception {
        var node = fixture("publish");
        ((ObjectNode) node.path("points").get(0)).put("checked_at", "2026-11-02T24:00:00Z");
        assertThatThrownBy(() -> read(node)).isInstanceOf(PublicationException.class);
        var valid = fixture("approve");
        Path file = Files.writeString(root.resolve("duplicate.json"), valid.toString().replace("\"action\":\"approve\"", "\"action\":\"approve\",\"action\":\"reject\""));
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            var reader = new PublicationCommandReader(new ReviewedImportReader(), factory.getValidator());
            assertThatThrownBy(() -> reader.read(file)).isInstanceOf(PublicationException.class);
        }
    }
}
