package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.PublicSnapshotRepository;
import kr.ac.myai.backend.repository.PublicationRepository;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.UUID;

final class CalculationFixtures {
    static ObjectNode snapshot(ObjectMapper mapper) throws Exception {
        var input = mapper.readTree(PythonProbe.REPO.resolve("processing/examples/match-input.json").toFile());
        var snapshot = mapper.createObjectNode().put("schema_version", "snapshot-v1").put("snapshot_id", input.path("snapshot_id").asText())
                .put("created_at", "2026-11-02T13:00:00Z").put("area_id", "10000000-0000-4000-8000-000000000005")
                .put("timezone", "Asia/Seoul").put("window_days", 14).put("radius_m", 500).put("document_count", 1).put("event_count", 1);
        for (String key : "mode case_id reference_instant knowledge_cutoff history_fidelity data_kind rules_version dictionary_version".split(" ")) snapshot.set(key, input.path("context").path(key));
        snapshot.putNull("anchor_date");
        snapshot.putObject("area").put("area_id", snapshot.path("area_id").asText()).put("name", "합성 구역").put("description", "시험 자료");
        snapshot.set("event_public_payloads", input.path("events").deepCopy());
        ((ObjectNode) snapshot.path("event_public_payloads").get(0)).put("revision_id", "10000000-0000-4000-8000-000000000021");
        snapshot.putArray("revision_ids").add("10000000-0000-4000-8000-000000000021");
        snapshot.set("sources", input.path("source_versions").deepCopy());
        var points = snapshot.putArray("points"); var ids = snapshot.putArray("point_ids");
        for (int i = 0; i < 5; i++) {
            String id = i == 0 ? input.path("point").path("point_id").asText() : UUID.nameUUIDFromBytes(("test-point-" + i).getBytes(StandardCharsets.UTF_8)).toString();
            ids.add(id);
            points.addObject().put("point_id", id).put("area_id", snapshot.path("area_id").asText()).put("label", "시험 " + i)
                    .put("longitude", 127.27).put("latitude", 37.01).put("version", 1).put("dictionary_version", snapshot.path("dictionary_version").asText())
                    .put("verification_status", "verified").put("active", true).put("is_test_reference", true);
        }
        snapshot.putObject("collection_range").put("from", "2026-11-02").put("to", "2026-11-02");
        snapshot.put("last_check_min", "2026-11-02T02:00:00Z").put("last_check_max", "2026-11-02T02:00:00Z");
        return snapshot;
    }

    static PublicSnapshotRepository.Published published(ObjectNode snapshot, ObjectMapper mapper) throws Exception {
        String canonical = mapper.writerWithDefaultPrettyPrinter().writeValueAsString(snapshot);
        var row = new PublicationRepository.Snapshot(snapshot.path("snapshot_id").asText(), snapshot.path("mode").asText(), snapshot.path("case_id").textValue(), canonical,
                ReviewedImportReader.sha256(canonical.getBytes(StandardCharsets.UTF_8)), snapshot.path("data_kind").asText(), snapshot.path("rules_version").asText(), snapshot.path("dictionary_version").asText());
        return new PublicSnapshotRepository.Published(row, "snapshot-v1", Instant.parse(snapshot.path("created_at").asText()), row.id());
    }

    private CalculationFixtures() {}
}
