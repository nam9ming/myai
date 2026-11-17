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
        UUID event = uuid(eventId, "event_id"), selected = snapshot(parameters, true);
        Long before = number(parameters, "history_before_version");
        Long limit = number(parameters, "history_limit");
        if (limit != null && limit > 1000) throw ApiException.invalid("history_limit", "이력 개수는1~1000을 사용해 주세요.");
        return notices.notice(event, selected, before, limit == null ? 1000 : limit.intValue());
    }

    private UUID snapshot(MultiValueMap<String, String> parameters, boolean required) {
        if (parameters.keySet().stream().anyMatch(key -> !key.equals("snapshot_id")
                && !(required && (key.equals("history_before_version") || key.equals("history_limit"))))) {
            throw ApiException.invalid("query", "지원하는 조회 조건을 확인해 주세요.");
        }
        var values = parameters.get("snapshot_id");
        if (values == null && !required) return null;
        if (values == null || values.size() != 1) throw ApiException.invalid("snapshot_id", "목록과 같은 공개본 ID를 하나 지정해 주세요.");
        return uuid(values.getFirst(), "snapshot_id");
    }

    private Long number(MultiValueMap<String, String> parameters, String field) {
        var values = parameters.get(field);
        if (values == null) return null;
        if (values.size() != 1 || values.getFirst() == null || !values.getFirst().matches("[1-9][0-9]{0,18}"))
            throw ApiException.invalid(field, "양의 정수 하나를 지정해 주세요.");
        try { return Long.parseLong(values.getFirst()); }
        catch (NumberFormatException failure) { throw ApiException.invalid(field, "지원하는 정수 범위를 확인해 주세요."); }
    }

    private UUID uuid(String value, String field) {
        if (value == null || !value.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")) {
            throw ApiException.invalid(field, "소문자 표준 UUID 형식을 사용해 주세요.");
        }
        return UUID.fromString(value);
    }
}
