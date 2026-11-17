package kr.ac.myai.backend.controller;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.service.CitizenNoticeService;
import org.springframework.context.annotation.Profile;
import org.springframework.util.MultiValueMap;
import org.springframework.web.bind.annotation.*;

import java.util.UUID;

@RestController
@Profile("!fixture & !local-api")
@RequestMapping("/api/v1/citizen/notices")
public class CitizenNoticeController {
    private final CitizenNoticeService notices;

    public CitizenNoticeController(CitizenNoticeService notices) { this.notices = notices; }

    @GetMapping
    public JsonNode list(@RequestParam MultiValueMap<String, String> parameters) {
        return notices.list(snapshot(parameters, false));
    }

    @GetMapping("/{eventId}")
    public JsonNode notice(@PathVariable("eventId") String eventId, @RequestParam MultiValueMap<String, String> parameters) {
        return notices.notice(uuid(eventId, "event_id"), snapshot(parameters, true));
    }

    private UUID snapshot(MultiValueMap<String, String> parameters, boolean required) {
        if (parameters.keySet().stream().anyMatch(key -> !key.equals("snapshot_id"))) {
            throw ApiException.invalid("query", "지원하는 조회 조건을 확인해 주세요.");
        }
        var values = parameters.get("snapshot_id");
        if (values == null && !required) return null;
        if (values == null || values.size() != 1) throw ApiException.invalid("snapshot_id", "목록과 같은 공개본 ID를 하나 지정해 주세요.");
        return uuid(values.getFirst(), "snapshot_id");
    }

    private UUID uuid(String value, String field) {
        if (value == null || !value.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")) {
            throw ApiException.invalid(field, "소문자 표준 UUID 형식을 사용해 주세요.");
        }
        return UUID.fromString(value);
    }
}
