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

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;

import static org.assertj.core.api.Assertions.*;

class PublicationCommandReaderTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();

    @Test
    void citizenPublicationUsesPointFreeCommandsAndCannotMakeReviewDecisions() throws Exception {
        var input = mapper.createObjectNode().put("schema_version", "citizen-publication-command-v1")
                .put("action", "preview").put("reason", "합성 시민 공개 검토").put("data_kind", "synthetic")
                .putNull("expected_head_version");
        input.putArray("revision_ids").add("20000000-0000-4000-8000-000000000007");
        for (String action : java.util.List.of("preview", "publish")) {
            input.put("action", action);
            var command = read(input);
            assertThat(command.action()).isEqualTo(action);
            assertThat(command.schemaVersion()).isEqualTo("citizen-publication-command-v1");
            assertThat(command).isNotInstanceOf(PublicationCommand.Publish.class);
        }
        for (String field : java.util.List.of("points", "area", "rules_version", "dictionary_version")) {
            var extra = input.deepCopy().putNull(field); rejected(extra);
        }
        rejected(input.deepCopy().put("action", "approve"));
        rejected(input.deepCopy().put("action", "reject"));
        var rollback = mapper.createObjectNode().put("schema_version", "citizen-publication-command-v1")
                .put("action", "rollback").put("reason", "합성 시민 공개 복구")
                .put("snapshot_id", "20000000-0000-4000-8000-000000000007").put("expected_head_version", 0);
        assertThat(read(rollback).action()).isEqualTo("rollback");
        rejected(rollback.putNull("expected_head_version"));
    }

    @Test
    void citizenPublicationBoundsVersionsAndRevisionSelectionWithoutCoercion() throws Exception {
        var input = fixture("citizen-publish");
        input.put("expected_head_version", Long.MAX_VALUE - 1);
        assertThat(read(input)).isInstanceOf(PublicationCommand.CitizenPublish.class);
        rejected(input.deepCopy().put("expected_head_version", Long.MAX_VALUE));
        rejected(input.deepCopy().put("expected_head_version", -1));
        rejected(input.deepCopy().put("expected_head_version", "0"));
        rejected(input.deepCopy().put("expected_head_version", 0.5));
        var duplicate = input.deepCopy();
        duplicate.withArray("revision_ids").add(duplicate.path("revision_ids").get(0));
        rejected(duplicate);
        var tooMany = input.deepCopy();
        var ids = tooMany.putArray("revision_ids");
        for (int i = 0; i < 1001; i++) ids.add(java.util.UUID.randomUUID().toString());
        rejected(tooMany);
        input.putArray("revision_ids");
        assertThat(read(input)).isInstanceOf(PublicationCommand.CitizenPublish.class);
    }

    private PublicationCommand read(ObjectNode node) throws Exception {
        byte[] content = node.toString().getBytes(StandardCharsets.UTF_8);
        Path file = Files.write(root.resolve("command.json"), content);
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            var reader = new PublicationCommandReader(new ReviewedImportReader(), factory.getValidator());
            var command = reader.read(file);
            assertThat(reader.read(content)).isEqualTo(command);
            return command;
        }
    }

    private ObjectNode fixture(String name) throws Exception {
        return (ObjectNode) mapper.readTree(Path.of("examples/" + name + ".json").toFile());
    }

    @Test
    void acceptsCitizenApprovalAndRejectionWithoutOpeningPublicationActions() throws Exception {
        var input = fixture("approve");
        input.put("schema_version", "citizen-review-command-v1");
        var approved = (PublicationCommand.Decision) read(input);
        assertThat(approved.schemaVersion()).isEqualTo("citizen-review-command-v1");
        assertThat(approved.action()).isEqualTo("approve");
        input.put("action", "reject");
        assertThat(((PublicationCommand.Decision) read(input)).action()).isEqualTo("reject");
        for (String action : java.util.List.of("publish", "preview", "rollback")) {
            var unsupported = fixture(action.equals("rollback") ? "rollback" : "publish");
            unsupported.put("schema_version", "citizen-review-command-v1").put("action", action);
            rejected(unsupported);
        }
        input.put("action", "approve").putArray("evidence_ids");
        rejected(input);
    }

    @Test
    void byteInputMatchesAllFileCommandShapesIncludingWhitespace() throws Exception {
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            var reader = new PublicationCommandReader(new ReviewedImportReader(), factory.getValidator());
            for (String name : java.util.List.of("approve", "publish", "rollback")) {
                var input = fixture(name);
                var expected = read(input);
                byte[] content = (" \n" + input.toPrettyString() + "\n ").getBytes(StandardCharsets.UTF_8);
                Path file = Files.write(root.resolve("command.json"), content);
                assertThat(reader.read(content)).isEqualTo(expected).isEqualTo(reader.read(file));
            }
        }
    }

    @Test
    void rejectsMalformedTrailingAndInvalidUtf8ThroughBothEntryPoints() throws Exception {
        rejected(new byte[0]);
        rejected("{".getBytes(StandardCharsets.UTF_8));
        rejected((fixture("approve") + "{}").getBytes(StandardCharsets.UTF_8));
        rejected(new byte[] {'{', '"', (byte) 0xc3, '(', '"', ':', '0', '}'});
    }

    @Test
    void acceptsEightMiBButRejectsOneMoreByteThroughBothEntryPoints() throws Exception {
        byte[] json = fixture("approve").toString().getBytes(StandardCharsets.UTF_8);
        byte[] atLimit = Arrays.copyOf(json, 8 * 1024 * 1024);
        Arrays.fill(atLimit, json.length, atLimit.length, (byte) ' ');
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            var reader = new PublicationCommandReader(new ReviewedImportReader(), factory.getValidator());
            var command = reader.read(atLimit);
            assertThat(command).isInstanceOf(PublicationCommand.Decision.class);
            assertThat(reader.read(Files.write(root.resolve("command.json"), atLimit))).isEqualTo(command);
        }
        byte[] overLimit = Arrays.copyOf(atLimit, atLimit.length + 1);
        overLimit[overLimit.length - 1] = ' ';
        rejected(overLimit);
    }

    @Test
    void rejectsBeanValidationViolationsThroughBothEntryPoints() throws Exception {
        var input = fixture("approve");
        input.put("reason", " ");
        rejected(input);
        input = fixture("approve");
        input.put("expected_revision_no", 0);
        rejected(input);
    }

    @Test
    void permitsEmptyRejectionEvidenceForTheServiceToCheckButNeverForApproval() throws Exception {
        var command = fixture("approve");
        command.put("action", "reject"); command.putArray("evidence_ids");
        assertThat(read(command)).isInstanceOf(PublicationCommand.Decision.class);
        command.put("action", "approve");
        rejected(command);
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
        rejected(node);
        node.remove("unexpected");
        node.put("expected_revision_no", 1.5);
        rejected(node);
        node.put("expected_revision_no", "1");
        rejected(node);
        node.remove("expected_revision_no");
        rejected(node);
    }

    @Test
    void rejectsUnverifiedDuplicateOrCrossAreaPointsAndRounding() throws Exception {
        var unverified = fixture("publish");
        ((ObjectNode) unverified.path("points").get(0)).put("verification_status", "unverified");
        rejected(unverified);
        var node = fixture("publish");
        ((ObjectNode) node.path("points").get(0)).put("point_id", node.path("points").get(1).path("point_id").asText());
        rejected(node);
        var crossArea = fixture("publish");
        ((ObjectNode) crossArea.path("points").get(0)).put("area_id", "90000000-0000-4000-8000-000000000001");
        rejected(crossArea);
        var precision = fixture("publish");
        ((ObjectNode) precision.path("points").get(0)).put("lat", new java.math.BigDecimal("37.12345678"));
        rejected(precision);
    }

    @Test
    void validatesReplayContextWithoutAcceptingItInCurrentMode() throws Exception {
        var node = fixture("publish");
        node.put("case_id", "90000000-0000-4000-8000-000000000001");
        rejected(node);
        node.put("mode", "replay").put("anchor_date", "2026-11-02").put("reference_instant", "2026-11-02T03:00:00Z")
                .put("knowledge_cutoff", "2026-11-02T03:00:00Z").put("history_fidelity", "verified_snapshot");
        assertThat(read(node)).isInstanceOf(PublicationCommand.Publish.class);
        node.putNull("history_fidelity");
        rejected(node);
        node.put("history_fidelity", "verified_snapshot");
        node.put("knowledge_cutoff", "2026-11-02T03:00:01Z");
        rejected(node);
    }

    @Test
    void rejectsDuplicateJsonKeysAndInvalidUtcTime() throws Exception {
        var node = fixture("publish");
        ((ObjectNode) node.path("points").get(0)).put("checked_at", "2026-11-02T24:00:00Z");
        rejected(node);
        var valid = fixture("approve");
        rejected(valid.toString().replace("\"action\":\"approve\"", "\"action\":\"approve\",\"action\":\"reject\"").getBytes(StandardCharsets.UTF_8));
    }

    private void rejected(ObjectNode input) throws Exception {
        rejected(input.toString().getBytes(StandardCharsets.UTF_8));
    }

    private void rejected(byte[] content) throws Exception {
        Path file = Files.write(root.resolve("command.json"), content);
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            var reader = new PublicationCommandReader(new ReviewedImportReader(), factory.getValidator());
            var fileError = catchThrowableOfType(() -> reader.read(file), PublicationException.class);
            var byteError = catchThrowableOfType(() -> reader.read(content), PublicationException.class);
            assertThat(fileError).isNotNull();
            assertThat(byteError).isNotNull();
            assertThat(byteError.code()).isEqualTo(fileError.code());
            assertThat(byteError.field()).isEqualTo(fileError.field());
            assertThat(byteError.getMessage()).isEqualTo(fileError.getMessage());
        }
    }
}
