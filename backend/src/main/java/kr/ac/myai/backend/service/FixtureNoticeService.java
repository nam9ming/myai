package kr.ac.myai.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.dto.MatchRequest;
import kr.ac.myai.backend.exception.ApiException;
import org.springframework.context.annotation.Profile;
import org.springframework.core.io.ClassPathResource;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.io.IOException;
import java.util.UUID;

@Service
@Profile("fixture")
public class FixtureNoticeService implements PublicNoticeService {
    private final ObjectMapper mapper;
    private final JsonNode config;
    private final JsonNode request;
    private final JsonNode matches;
    private final JsonNode detail;
    private final JsonNode events;
    private final UUID snapshotId;

    public FixtureNoticeService(ObjectMapper mapper) throws IOException {
        this.mapper = mapper;
        config = load("config-response");
        request = load("matches-request");
        matches = load("matches-response");
        detail = load("event-response");
        events = load("public-events");
        snapshotId = UUID.fromString(config.path("snapshot_id").asText());
        for (JsonNode envelope : new JsonNode[]{config, matches, detail}) {
            if (!envelope.path("data").path("data_kind").asText().equals("synthetic")
                    || !envelope.path("snapshot_id").asText().equals(snapshotId.toString())) {
                throw new IllegalStateException("동일 snapshot의 합성 fixture만 사용할 수 있습니다.");
            }
        }
    }

    private JsonNode load(String name) throws IOException {
        try (var input = new ClassPathResource("fixtures/" + name + ".json").getInputStream()) {
            return mapper.readTree(input);
        }
    }

    @Override
    public JsonNode config(String mode, UUID caseId) {
        if (mode.equals("replay")) throw new ApiException(HttpStatus.NOT_FOUND, "CASE_NOT_FOUND", "등록된 재현 사례가 없습니다.", "case_id");
        return config.deepCopy();
    }

    @Override
    public JsonNode matches(MatchRequest query) {
        config(query.mode(), query.caseId());
        if (query.snapshotId() != null) requireSnapshot(query.snapshotId());
        boolean knownPoint = false;
        for (JsonNode point : config.path("data").path("points")) {
            if (query.pointId().toString().equals(point.path("point_id").asText())) knownPoint = true;
        }
        if (!knownPoint) throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_POINT", "활성 시험 지점을 선택해 주세요.", "point_id");
        ObjectNode normalized = mapper.valueToTree(query);
        normalized.putNull("snapshot_id");
        // shortcut: 고정 예제 조건만 지원하며, Python 연결 후 실제 계산 서비스로 교체한다.
        if (!normalized.equals(request)) throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "CALCULATOR_NOT_READY", "fixture는 matches-request.json 조건만 지원합니다. 실제 계산기는 아직 연결되지 않았습니다.", null);
        return matches.deepCopy();
    }

    @Override
    public JsonNode event(UUID eventId, UUID requestedSnapshot) {
        requireSnapshot(requestedSnapshot);
        for (JsonNode event : events) {
            if (eventId.toString().equals(event.path("event_id").asText())) {
                ObjectNode response = detail.deepCopy();
                ((ObjectNode) response.path("data")).set("event", event.deepCopy());
                return response;
            }
        }
        throw new ApiException(HttpStatus.NOT_FOUND, "EVENT_NOT_FOUND", "공개 사건을 찾을 수 없습니다.", "event_id");
    }

    private void requireSnapshot(UUID requested) {
        if (!snapshotId.equals(requested)) throw new ApiException(HttpStatus.NOT_FOUND, "SNAPSHOT_NOT_FOUND", "공개 snapshot을 찾을 수 없습니다.", "snapshot_id");
    }
}
