package kr.ac.myai.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.dto.MatchRequest;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.repository.PublicSnapshotRepository;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.*;

@Service
@Profile("!fixture")
@Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
public class SnapshotNoticeService implements PublicNoticeService {
    private static final String FIELDS = "applicability exceptions route_names stop_names directions";
    private static final String FACTS = "event_id revision_id title types lifecycle lifecycle_evidence_ids area_membership document_links relations source_version_ids";
    private final PublicSnapshotRepository repository;
    private final PublicationContent content;
    private final ObjectMapper mapper;

    public SnapshotNoticeService(PublicSnapshotRepository repository, PublicationContent content, ObjectMapper mapper) {
        this.repository = repository; this.content = content; this.mapper = mapper;
    }

    @Override
    public JsonNode config(String mode, UUID caseId) {
        JsonNode snapshot = active(mode, caseId);
        var data = content.select(snapshot, "created_at data_kind timezone window_days radius_m document_count event_count mode case_id anchor_date reference_instant knowledge_cutoff history_fidelity collection_range last_check_min last_check_max rules_version dictionary_version");
        data.put("server_now", Instant.now().toString());
        data.set("area", content.select(snapshot.path("area"), "area_id name description"));
        var points = data.putArray("points");
        for (JsonNode point : snapshot.path("points")) points.add(content.select(point, "point_id label is_test_reference"));
        var sources = data.putArray("sources");
        Set<String> publishers = new HashSet<>();
        for (JsonNode source : snapshot.path("sources")) {
            if (publishers.add(source.path("publisher").asText())) sources.addObject().put("publisher", source.path("publisher").asText())
                    .put("is_fixture", synthetic(snapshot));
        }
        var cases = data.putArray("cases");
        // shortcut: 소수의 시연 사례를 순차 검증한다. 사례가 늘면 checksum을 검증하는 목록 projection으로 전환한다.
        for (String id : repository.replayHeads(snapshot.path("area_id").asText(), snapshot.path("data_kind").asText())) {
            JsonNode replay = load(id, true);
            cases.add(content.select(replay, "case_id snapshot_id anchor_date reference_instant knowledge_cutoff history_fidelity"));
        }
        return envelope(snapshot, data);
    }

    @Override
    public JsonNode matches(MatchRequest query) {
        JsonNode snapshot = query.snapshotId() == null ? active(query.mode(), query.caseId()) : load(query.snapshotId().toString(), true);
        if (!snapshot.path("mode").asText().equals(query.mode()) || !Objects.equals(snapshot.path("case_id").textValue(), query.caseId() == null ? null : query.caseId().toString())) {
            throw ApiException.invalid("snapshot_id", "선택한 모드·사례와 같은 snapshot을 사용해 주세요.");
        }
        boolean known = false;
        for (JsonNode point : snapshot.path("points")) if (point.path("point_id").asText().equals(query.pointId().toString())) known = true;
        if (!known) throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_POINT", "활성 시험 지점을 선택해 주세요.", "point_id");
        throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "CALCULATOR_NOT_READY", "Python 계산기가 아직 연결되지 않았습니다.", null);
    }

    @Override
    public JsonNode event(UUID eventId, UUID snapshotId) {
        JsonNode snapshot = load(snapshotId.toString(), true);
        JsonNode facts = findEvent(snapshot, eventId.toString());
        if (facts == null) throw new ApiException(HttpStatus.NOT_FOUND, "EVENT_NOT_FOUND", "공개 사건을 찾을 수 없습니다.", "event_id");
        ObjectNode event = publicEvent(snapshot, facts);
        event.set("history", history(snapshot, facts));
        var data = content.select(snapshot, "data_kind mode case_id anchor_date reference_instant knowledge_cutoff history_fidelity");
        data.set("event", event);
        return envelope(snapshot, data);
    }

    private JsonNode active(String mode, UUID caseId) {
        String id = repository.head(channel(mode, caseId == null ? null : caseId.toString())).orElseThrow(() -> mode.equals("replay")
                ? new ApiException(HttpStatus.NOT_FOUND, "CASE_NOT_FOUND", "등록된 재현 사례가 없습니다.", "case_id")
                : new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "PUBLIC_DATA_NOT_READY", "검토된 공개 snapshot이 아직 없습니다.", null));
        JsonNode snapshot = load(id, false);
        if (!snapshot.path("mode").asText().equals(mode) || !Objects.equals(snapshot.path("case_id").textValue(), caseId == null ? null : caseId.toString())) throw invalidSnapshot();
        return snapshot;
    }

    private JsonNode load(String id, boolean requireActive) {
        var published = repository.published(id).orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "SNAPSHOT_NOT_FOUND", "공개 snapshot을 찾을 수 없습니다.", "snapshot_id"));
        var row = published.snapshot();
        if (requireActive && !id.equals(published.currentId())) {
            throw new ApiException(HttpStatus.CONFLICT, "SNAPSHOT_RETIRED", "공개본이 교체되었습니다. 새 버전을 선택해 주세요.", "snapshot_id", published.currentId());
        }
        try {
            content.verifySnapshot(row, channel(row.mode(), row.caseId()));
            JsonNode snapshot = content.parse(row.canonical());
            content.check(published.schemaVersion().equals("snapshot-v1") && Instant.parse(snapshot.path("created_at").asText()).equals(published.createdAt()), "snapshot");
            content.check(snapshot.path("points").isArray() && snapshot.path("points").size() == 5
                    && snapshot.path("event_public_payloads").isArray() && snapshot.path("sources").isArray()
                    && snapshot.path("event_count").asInt(-1) == snapshot.path("event_public_payloads").size(), "snapshot");
            return snapshot;
        } catch (PublicationException | ImportException | java.time.DateTimeException ex) {
            throw new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "SNAPSHOT_INVALID", "공개 snapshot의 무결성을 확인할 수 없습니다.", null);
        }
    }

    private ObjectNode publicEvent(JsonNode snapshot, JsonNode facts) {
        ObjectNode result = content.select(facts, FACTS);
        var fieldValues = result.putObject("field_values");
        for (String field : FIELDS.split(" ")) {
            result.set(field, facts.path(field).path("value").deepCopy());
            fieldValues.set(field, content.select(facts.path(field), "value knowledge evidence_ids reason"));
        }
        var occurrences = result.putArray("occurrences");
        for (JsonNode occurrence : facts.path("occurrences")) occurrences.add(content.select(occurrence, "occurrence_id date_start date_end time_start time_end end_day_offset precision recurrence_dates location_ids evidence_ids knowledge"));
        var locations = result.putArray("locations");
        for (JsonNode location : facts.path("locations")) {
            var publicLocation = content.select(location, "location_id kind status geometry coverage evidence_ids");
            publicLocation.set("name", location.path("name").path("value").deepCopy());
            publicLocation.set("address", location.path("address").path("value").deepCopy());
            publicLocation.set("field_values", content.select(location, "name address"));
            locations.add(publicLocation);
        }
        Map<String, JsonNode> sources = new HashMap<>();
        for (JsonNode source : snapshot.path("sources")) sources.put(source.path("document_version_id").asText(), source);
        var references = result.putArray("source_refs");
        for (JsonNode id : facts.path("source_version_ids")) {
            JsonNode source = sources.get(id.asText());
            if (source == null) throw invalidSnapshot();
            var reference = content.select(source, "document_id document_version_id publisher title official_number published_date collected_at last_verified_at latest_check_attempt_at check_result current_last_verified_at current_latest_check_attempt_at current_check_result");
            reference.set("url", source.path("official_url"));
            reference.put("is_fixture", synthetic(snapshot));
            references.add(reference);
        }
        var evidence = result.putArray("evidence");
        for (JsonNode item : facts.path("evidence")) {
            JsonNode source = sources.get(item.path("document_version_id").asText());
            if (source == null) throw invalidSnapshot();
            var publicEvidence = content.select(item, "evidence_id document_version_id block_id quote start_char end_char text_sha256");
            publicEvidence.set("source_document_id", source.path("document_id"));
            publicEvidence.put("is_fixture", synthetic(snapshot));
            evidence.add(publicEvidence);
        }
        return result;
    }

    private ArrayNode history(JsonNode selected, JsonNode selectedEvent) {
        var result = mapper.createArrayNode();
        ObjectNode previous = null;
        String eventId = selectedEvent.path("event_id").asText();
        for (var item : repository.history(eventId, channel(selected.path("mode").asText(), selected.path("case_id").textValue()), selected.path("snapshot_id").asText())) {
            JsonNode snapshot = item.snapshotId().equals(selected.path("snapshot_id").asText()) ? selected : load(item.snapshotId(), false);
            if (!sameContext(selected, snapshot) || previous != null && previous.path("revision_id").asText().equals(item.revisionId())) continue;
            JsonNode facts = findEvent(snapshot, eventId);
            if (facts == null || !facts.path("revision_id").asText().equals(item.revisionId())) throw invalidSnapshot();
            ObjectNode current = publicEvent(snapshot, facts);
            if (previous != null) {
                var entry = mapper.createObjectNode().put("revision_id", item.revisionId()).put("snapshot_id", item.snapshotId()).put("published_at", item.publishedAt().toString()).put("action", item.action());
                var changes = entry.putArray("changes");
                for (var fields = current.fieldNames(); fields.hasNext();) {
                    String field = fields.next();
                    if (!field.equals("revision_id") && !previous.path(field).equals(current.path(field))) {
                        var change = changes.addObject().put("field", field);
                        change.set("before", previous.path(field)); change.set("after", current.path(field));
                    }
                }
                entry.set("evidence", current.path("evidence"));
                entry.set("source_refs", current.path("source_refs"));
                entry.set("before_revision_id", previous.path("revision_id"));
                entry.set("before_evidence", previous.path("evidence"));
                entry.set("before_source_refs", previous.path("source_refs"));
                result.add(entry);
            }
            previous = current;
        }
        return result;
    }

    private boolean sameContext(JsonNode selected, JsonNode other) {
        String fields = "data_kind area_id mode case_id";
        if (selected.path("mode").asText().equals("replay")) fields += " anchor_date reference_instant knowledge_cutoff";
        for (String field : fields.split(" ")) if (!selected.path(field).equals(other.path(field))) return false;
        return true;
    }

    private JsonNode findEvent(JsonNode snapshot, String eventId) {
        for (JsonNode event : snapshot.path("event_public_payloads")) if (event.path("event_id").asText().equals(eventId)) return event;
        return null;
    }

    private ObjectNode envelope(JsonNode snapshot, ObjectNode data) {
        var result = mapper.createObjectNode().put("schema_version", "api-v1").put("snapshot_id", snapshot.path("snapshot_id").asText()).put("generated_at", Instant.now().toString());
        result.set("data", data); return result;
    }

    private boolean synthetic(JsonNode snapshot) { return snapshot.path("data_kind").asText().equals("synthetic"); }
    private String channel(String mode, String caseId) { return mode.equals("current") ? "current" : "replay:" + caseId; }
    private ApiException invalidSnapshot() { return new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "SNAPSHOT_INVALID", "공개 snapshot의 무결성을 확인할 수 없습니다.", null); }
}
