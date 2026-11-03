package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.repository.PublicationRepository;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;

class PublicationContentTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final ReviewedImportReader reader = new ReviewedImportReader();
    final PublicationContent content = new PublicationContent(reader, mapper);

    @Test
    void validatesPrivateProofWithoutLeakingItIntoPublicSnapshot() throws Exception {
        var envelope = (ObjectNode) mapper.readTree(Path.of("examples/reviewed-import.json").toFile());
        Files.copy(Path.of("examples/synthetic-source.txt"), root.resolve("synthetic-source.txt"));
        var batch = reader.read(Files.writeString(root.resolve("input.json"), envelope.toString()), root);
        var payload = (ObjectNode) mapper.readTree(batch.events().getFirst().payloadJson());
        var revision = (ObjectNode) payload.path("revision");
        revision.put("review_status", "approved");
        payload.putArray("human_handoffs").addObject().put("directory", root.resolve("a".repeat(64)).toString())
                .put("handoff_ref", "a".repeat(64)).put("receipt_sha256", "b".repeat(64));
        var document = batch.documents().getFirst();
        var row = new PublicationRepository.Document(document.id(), document.versionId(), document.versionNo(),
                document.textSha256(), document.metadataJson(), document.privateContentRef());
        var validated = content.validate(payload, List.of(row), root);
        assertThat(mapper.readTree(validated.payloadJson()).path("human_handoffs")).isEqualTo(payload.path("human_handoffs"));
        String json = payload.toString();
        var saved = new PublicationRepository.Revision(validated.revisionId(), validated.id(), validated.revisionNo(),
                "approved", "hidden", json, ReviewedImportReader.sha256(json.getBytes(StandardCharsets.UTF_8)), validated.revisionId(), 1);
        var command = new PublicationCommand.Publish("publication-command-v1", "publish", "합성 공개", "current", null,
                null, null, null, "not_applicable", "synthetic", new PublicationCommand.Area(
                UUID.fromString(payload.path("event").path("area_id").asText()), "합성 지역", "합성 시험"),
                revision.path("rules_version").asText(), revision.path("dictionary_version").asText(),
                List.of(UUID.fromString(validated.revisionId())), List.of(), 0L);
        var snapshot = content.snapshot(command, List.of(saved), Map.of(row.versionId(), row), UUID.randomUUID().toString(),
                Instant.parse("2026-11-03T00:00:00Z"));
        assertThat(snapshot.canonical()).doesNotContain("human_handoffs", "handoff_ref", "receipt_sha256", root.toString(),
                "reviewer_id", "human_overrides");
        revision.putNull("title");
        assertThatThrownBy(() -> content.validate(payload, List.of(row), root)).isInstanceOf(ImportException.class);
    }
}
