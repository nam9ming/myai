package kr.ac.myai.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.logging.PublicRequestLogContext;
import kr.ac.myai.backend.publication.CitizenPublicationContent;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.repository.PublicSnapshotRepository;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.time.DateTimeException;
import java.time.Instant;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;

@Service
@Profile("!fixture")
@Transactional(readOnly = true, isolation = Isolation.REPEATABLE_READ)
public class CitizenNoticeService {
    private static final int HISTORY_BYTES = 8 * 1024 * 1024;
    private final PublicSnapshotRepository repository;
    private final CitizenPublicationContent citizens;
    private final PublicationContent shared;
    private final ObjectMapper mapper;

    public CitizenNoticeService(PublicSnapshotRepository repository, CitizenPublicationContent citizens, PublicationContent shared, ObjectMapper mapper) {
        this.repository = repository; this.citizens = citizens; this.shared = shared; this.mapper = mapper;
    }

    public JsonNode list(UUID snapshotId) {
        JsonNode selected = select(snapshotId, new Reads());
        return envelope(selected, shared.select(selected, "created_at data_kind mode timezone notice_count notices sources"));
    }

    public JsonNode notice(UUID eventId, UUID snapshotId) {
        if (eventId == null) throw ApiException.invalid("event_id", "시민 공지 ID를 지정해 주세요.");
        if (snapshotId == null) throw ApiException.invalid("snapshot_id", "목록과 같은 공개본을 지정해 주세요.");
        var reads = new Reads();
        JsonNode selected = select(snapshotId, reads);
        JsonNode notice = find(selected, eventId.toString());
        if (notice == null) throw new ApiException(HttpStatus.NOT_FOUND, "NOTICE_NOT_FOUND", "공개 시민 공지를 찾을 수 없습니다.", "event_id");
        var data = shared.select(selected, "created_at data_kind mode timezone");
        data.set("notice", notice.deepCopy());
        data.set("sources", sources(selected, notice));
        data.set("history", history(selected, eventId.toString(), reads));
        return envelope(selected, data);
    }

    private JsonNode select(UUID snapshotId, Reads reads) {
        boolean explicit = snapshotId != null;
        String id = explicit ? snapshotId.toString() : repository.head(CitizenPublicationContent.CHANNEL).orElseThrow(() ->
                new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "PUBLIC_DATA_NOT_READY", "검토된 시민 공개본이 아직 없습니다.", null));
        var published = repository.citizenPublished(id).orElseThrow(() -> explicit
                ? new ApiException(HttpStatus.NOT_FOUND, "SNAPSHOT_NOT_FOUND", "시민 공개본을 찾을 수 없습니다.", "snapshot_id") : invalid());
        JsonNode selected = reads.verify(id, published);
        if (!id.equals(published.currentId())) {
            if (!explicit) throw invalid();
            throw new ApiException(HttpStatus.CONFLICT, "SNAPSHOT_RETIRED", "공개본이 교체되었습니다. 새 버전을 선택해 주세요.", "snapshot_id", published.currentId());
        }
        PublicRequestLogContext.selected(id, null);
        return selected;
    }

    private ObjectNode history(JsonNode selected, String eventId, Reads reads) {
        String selectedId = selected.path("snapshot_id").textValue();
        var audits = repository.citizenHistory(eventId, selectedId);
        if (audits.size() > PublicSnapshotRepository.MAX_CITIZEN_HISTORY) throw tooLarge();
        if (audits.isEmpty() || !selectedId.equals(audits.getLast().snapshotId())) throw invalid();
        var history = mapper.createObjectNode().put("scope", "same_data_kind_published_snapshots").put("completeness", "unknown");
        var entries = history.putArray("entries");
        ObjectNode previous = null;
        boolean observed = false;
        for (var item : audits) {
            if (item.snapshotId() == null || item.publishedAt() == null || !("publish".equals(item.action()) || "rollback".equals(item.action()))) throw invalid();
            JsonNode snapshot = reads.historic(item.snapshotId());
            if (item.publishedAt().isBefore(Instant.parse(snapshot.path("created_at").textValue()))) throw invalid();
            JsonNode notice = find(snapshot, eventId);
            String revisionId = notice == null ? null : notice.path("revision_id").textValue();
            if (!Objects.equals(revisionId, item.revisionId())) throw invalid();
            if (!snapshot.path("data_kind").equals(selected.path("data_kind"))) continue;
            ObjectNode current = notice == null ? null : state(snapshot, notice);
            if (!observed || !Objects.equals(previous, current)) {
                String kind = !observed ? "first_observed" : current == null ? "withdrawn" : previous == null ? "restored" : "changed";
                var entry = entries.addObject().put("kind", kind).put("snapshot_id", item.snapshotId())
                        .put("published_at", item.publishedAt().toString()).put("action", item.action());
                entry.set("before", previous);
                entry.set("after", current);
            }
            previous = current;
            observed = true;
        }
        if (!observed) throw invalid();
        return history;
    }

    private ObjectNode state(JsonNode snapshot, JsonNode notice) {
        var result = mapper.createObjectNode();
        result.set("notice", notice.deepCopy());
        result.set("sources", sources(snapshot, notice));
        return result;
    }

    private ArrayNode sources(JsonNode snapshot, JsonNode notice) {
        var ids = new HashSet<String>();
        notice.path("source_version_ids").forEach(id -> ids.add(id.textValue()));
        var result = mapper.createArrayNode();
        for (var source : snapshot.path("sources")) if (ids.contains(source.path("document_version_id").textValue())) result.add(source.deepCopy());
        return result;
    }

    private JsonNode find(JsonNode snapshot, String eventId) {
        for (var notice : snapshot.path("notices")) if (eventId.equals(notice.path("event_id").textValue())) return notice;
        return null;
    }

    private ObjectNode envelope(JsonNode selected, ObjectNode data) {
        var result = mapper.createObjectNode().put("schema_version", "citizen-api-v1").put("snapshot_id", selected.path("snapshot_id").textValue())
                .put("generated_at", Instant.now().toString());
        result.set("data", data);
        return result;
    }

    private final class Reads {
        private final Map<String, JsonNode> verified = new HashMap<>();
        private long bytes;

        private JsonNode historic(String id) {
            JsonNode cached = verified.get(id);
            if (cached != null) return cached;
            return verify(id, repository.citizenPublished(id).orElseThrow(CitizenNoticeService.this::invalid));
        }

        private JsonNode verify(String id, PublicSnapshotRepository.Published published) {
            try {
                var row = published.snapshot();
                shared.check(row != null && id.equals(row.id()), "snapshot_id");
                citizens.verifySnapshot(row, published.schemaVersion(), published.createdAt());
                JsonNode snapshot = shared.parse(row.canonical());
                bytes += row.canonical().getBytes(StandardCharsets.UTF_8).length;
                if (bytes > HISTORY_BYTES) throw tooLarge();
                verified.put(id, snapshot);
                return snapshot;
            } catch (PublicationException | ImportException | DateTimeException failure) { throw invalid(); }
        }
    }

    private ApiException invalid() {
        return new ApiException(HttpStatus.INTERNAL_SERVER_ERROR, "SNAPSHOT_INVALID", "시민 공개본의 무결성·공개 이력을 확인할 수 없습니다.", null);
    }
    private ApiException tooLarge() {
        return new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "CITIZEN_HISTORY_TOO_LARGE", "확보된 공개 이력이 조회 한도를 초과했습니다.", null, false);
    }
}
