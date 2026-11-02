package kr.ac.myai.backend.publication;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedBatch;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.PublicationRepository;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Instant;
import java.time.ZoneId;
import java.util.*;

@Component
public class PublicationContent {
    private final ReviewedImportReader json;
    private final ObjectMapper mapper;

    public PublicationContent(ReviewedImportReader json, ObjectMapper mapper) { this.json = json; this.mapper = mapper; }

    public JsonNode parse(String value) { return json.parseJson(value.getBytes(StandardCharsets.UTF_8)); }

    public JsonNode payload(PublicationRepository.Revision row) {
        check(ReviewedImportReader.sha256(row.payload().getBytes(StandardCharsets.UTF_8)).equals(row.hash()), "payload_sha256");
        JsonNode payload = parse(row.payload()); JsonNode revision = payload.path("revision");
        check(revision.path("revision_id").asText().equals(row.id()) && revision.path("event_id").asText().equals(row.eventId())
                && payload.path("event").path("event_id").asText().equals(row.eventId())
                && revision.path("revision_no").isIntegralNumber() && revision.path("revision_no").asLong() == row.number()
                && revision.path("review_status").asText().equals(row.status()) && revision.path("publication_intent").asText().equals(row.intent()), "revision");
        return payload;
    }

    public ReviewedBatch.Event validate(JsonNode payload, List<PublicationRepository.Document> documents, Path root) {
        check(root != null, "source_root");
        var envelope = mapper.createObjectNode().put("schema_version", "reviewed-import-v1").put("data_kind", payload.path("data_kind").asText());
        var sources = envelope.putArray("documents");
        for (var row : documents) {
            var metadata = parse(row.metadata()); var document = metadata.path("document");
            check(metadata.path("data_kind").equals(payload.path("data_kind")), "data_kind");
            check(document.path("document_id").asText().equals(row.id()) && document.path("document_version_id").asText().equals(row.versionId())
                    && document.path("version_no").asLong() == row.number() && document.path("text_sha256").asText().equals(row.textHash())
                    && Objects.equals(document.path("raw_asset_path").textValue(), row.privateRef()), "documents");
            check(document.path("use_review").asText().equals("allowed") && !document.path("last_verified_at").isNull(), "documents.use_review");
            for (String field : List.of("collected_at", "last_verified_at", "latest_check_attempt_at")) {
                check(!document.path(field).isNull() && !Instant.parse(document.path(field).asText()).isAfter(Instant.now()), "documents." + field);
            }
            sources.add(document);
        }
        envelope.set("evidence", payload.path("evidence"));
        ObjectNode event = payload.path("event").deepCopy();
        event.set("revision", payload.path("revision"));
        event.put("expected_revision_no", payload.path("revision").path("revision_no").asLong() - 1);
        envelope.putArray("events").add(event);
        var validated = json.validateStored(envelope, root).events().getFirst();
        for (JsonNode location : payload.path("revision").path("locations")) {
            if (!location.path("checked_at").isNull()) check(!Instant.parse(location.path("checked_at").asText()).isAfter(Instant.now()), "locations.checked_at");
        }
        for (JsonNode change : payload.path("revision").path("human_overrides")) {
            check(!Instant.parse(change.path("time").asText()).isAfter(Instant.now()), "human_overrides.time");
        }
        return validated;
    }

    public ObjectNode select(JsonNode source, String fields) {
        var result = mapper.createObjectNode();
        for (String field : fields.split(" ")) {
            check(source.has(field), field);
            result.set(field, source.get(field).deepCopy());
        }
        return result;
    }

    public PublicationRepository.Snapshot snapshot(PublicationCommand.Publish command, List<PublicationRepository.Revision> revisions,
                                                   Map<String, PublicationRepository.Document> documents, String id, Instant createdAt) {
        var result = mapper.createObjectNode().put("schema_version", "snapshot-v1").put("snapshot_id", id).put("created_at", createdAt.toString())
                .put("data_kind", command.dataKind()).put("mode", command.mode()).put("rules_version", command.rulesVersion()).put("dictionary_version", command.dictionaryVersion())
                .put("area_id", command.area().areaId().toString()).put("timezone", "Asia/Seoul").put("window_days", 14).put("radius_m", 500);
        result.set("area", mapper.valueToTree(command.area()));
        result.put("case_id", command.caseId() == null ? null : command.caseId().toString());
        result.put("anchor_date", command.anchorDate() == null ? null : command.anchorDate().toString());
        result.put("reference_instant", command.referenceInstant() == null ? null : command.referenceInstant().toString());
        result.put("knowledge_cutoff", command.knowledgeCutoff() == null ? null : command.knowledgeCutoff().toString());
        result.put("history_fidelity", command.historyFidelity());
        var pointIds = result.putArray("point_ids"); var points = result.putArray("points");
        command.points().stream().sorted(Comparator.comparing(p -> p.pointId().toString())).forEach(point -> {
            pointIds.add(point.pointId().toString());
            points.addObject().put("point_id", point.pointId().toString()).put("area_id", point.areaId().toString()).put("label", point.label())
                    .put("longitude", point.lon()).put("latitude", point.lat()).put("version", point.version()).put("dictionary_version", point.dictionaryVersion())
                    .put("verification_status", point.verificationStatus()).put("active", true).put("is_test_reference", true);
        });
        var revisionIds = result.putArray("revision_ids"); var events = result.putArray("event_public_payloads");
        for (var revision : revisions) {
            JsonNode payload = payload(revision); JsonNode facts = payload.path("event"); JsonNode reviewed = payload.path("revision");
            check(payload.path("data_kind").asText().equals(command.dataKind()) && facts.path("area_id").asText().equals(command.area().areaId().toString()), "data_kind/area_id");
            check(reviewed.path("rules_version").asText().equals(command.rulesVersion()) && reviewed.path("dictionary_version").asText().equals(command.dictionaryVersion()), "rules_version/dictionary_version");
            revisionIds.add(revision.id());
            var event = select(reviewed, "event_id revision_id title types applicability exceptions route_names stop_names directions lifecycle lifecycle_evidence_ids source_version_ids");
            event.set("area_membership", facts.path("area_membership"));
            event.set("document_links", facts.path("document_links"));
            var relations = event.putArray("relations");
            for (var relation : facts.path("relations")) relations.add(select(relation, "from_document_id to_document_id type reason created_at"));
            var occurrences = event.putArray("occurrences");
            for (var occurrence : reviewed.path("occurrences")) occurrences.add(select(occurrence, "occurrence_id date_start date_end time_start time_end end_day_offset precision recurrence_dates location_ids evidence_ids knowledge"));
            var locations = event.putArray("locations");
            for (var location : reviewed.path("locations")) locations.add(select(location, "location_id name address kind status geometry coverage evidence_ids"));
            event.set("evidence", payload.path("evidence"));
            events.add(event);
        }
        Set<String> documentIds = new HashSet<>(); List<Instant> verified = new ArrayList<>(); List<Instant> collected = new ArrayList<>();
        var sources = result.putArray("sources");
        documents.values().stream().sorted(Comparator.comparing(PublicationRepository.Document::versionId)).forEach(row -> {
            JsonNode doc = parse(row.metadata()).path("document");
            Instant collection = Instant.parse(doc.path("collected_at").asText());
            if (command.mode().equals("replay")) check(!collection.isAfter(command.knowledgeCutoff()), "knowledge_cutoff");
            documentIds.add(row.id()); collected.add(collection);
            var source = select(doc, "document_id document_version_id publisher official_url title official_number published_date collected_at text_sha256");
            source.set("current_last_verified_at", doc.path("last_verified_at"));
            source.set("current_latest_check_attempt_at", doc.path("latest_check_attempt_at"));
            source.set("current_check_result", doc.path("check_result"));
            String latest = null; String success = null; String checkResult = "unchecked";
            var checks = source.putArray("checks");
            for (JsonNode check : doc.path("checks")) {
                Instant at = Instant.parse(check.path("checked_at").asText());
                if (command.mode().equals("replay") && at.isAfter(command.knowledgeCutoff())) continue;
                checks.add(select(check, "checked_at result text_sha256"));
                latest = check.path("checked_at").asText(); checkResult = check.path("result").asText();
                if (checkResult.equals("verified")) success = latest;
            }
            source.put("last_verified_at", success).put("latest_check_attempt_at", latest).put("check_result", checkResult);
            if (command.mode().equals("replay") && command.historyFidelity().equals("verified_snapshot")) check(success != null, "history_fidelity");
            if (success != null) verified.add(Instant.parse(success));
            sources.add(source);
        });
        result.put("document_count", documentIds.size()).put("event_count", revisions.size());
        var range = result.putObject("collection_range");
        range.put("from", collected.stream().min(Comparator.naturalOrder()).map(at -> at.atZone(ZoneId.of("Asia/Seoul")).toLocalDate().toString()).orElse(null));
        range.put("to", collected.stream().max(Comparator.naturalOrder()).map(at -> at.atZone(ZoneId.of("Asia/Seoul")).toLocalDate().toString()).orElse(null));
        result.put("last_check_min", verified.stream().min(Comparator.naturalOrder()).map(Instant::toString).orElse(null));
        result.put("last_check_max", verified.stream().max(Comparator.naturalOrder()).map(Instant::toString).orElse(null));
        String canonical = result.toString(); byte[] bytes = canonical.getBytes(StandardCharsets.UTF_8);
        check(bytes.length <= 8 * 1024 * 1024, "snapshot");
        return new PublicationRepository.Snapshot(id, command.mode(), command.caseId() == null ? null : command.caseId().toString(), canonical,
                ReviewedImportReader.sha256(bytes), command.dataKind(), command.rulesVersion(), command.dictionaryVersion());
    }

    public void verifySnapshot(PublicationRepository.Snapshot snapshot, String channel) {
        check(ReviewedImportReader.sha256(snapshot.canonical().getBytes(StandardCharsets.UTF_8)).equals(snapshot.checksum()), "snapshot.checksum");
        JsonNode content = parse(snapshot.canonical());
        String actual = snapshot.mode().equals("current") ? "current" : "replay:" + snapshot.caseId();
        check(actual.equals(channel) && content.path("snapshot_id").asText().equals(snapshot.id()) && content.path("schema_version").asText().equals("snapshot-v1")
                && content.path("mode").asText().equals(snapshot.mode()) && Objects.equals(content.path("case_id").textValue(), snapshot.caseId())
                && content.path("data_kind").asText().equals(snapshot.kind()) && content.path("rules_version").asText().equals(snapshot.rulesVersion())
                && content.path("dictionary_version").asText().equals(snapshot.dictionaryVersion()), "snapshot");
    }

    public void check(boolean condition, String field) {
        if (!condition) throw new PublicationException("PUBLICATION_VALIDATION_ERROR", "검토본·원문·공개 자료의 값과 근거를 확인해 주세요.", field);
    }
}
