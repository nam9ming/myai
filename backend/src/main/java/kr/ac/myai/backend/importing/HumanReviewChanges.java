package kr.ac.myai.backend.importing;

import com.fasterxml.jackson.databind.JsonNode;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** AI 파생 revision의 의미값 변경과 사람 검토 기록을 대조한다. */
public final class HumanReviewChanges {
    private HumanReviewChanges() { }

    public static void validate(JsonNode previous, JsonNode next) {
        var revision = next.path("revision");
        Map<String, List<JsonNode>> records = new HashMap<>();
        String reviewer = revision.path("reviewer_id").textValue();
        Instant at = revision.path("reviewed_at").isTextual() ? Instant.parse(revision.path("reviewed_at").asText()) : null;
        var historical = new HashSet<JsonNode>();
        previous.path("revision").path("human_overrides").forEach(historical::add);
        for (JsonNode change : revision.path("human_overrides")) {
            String path = change.path("field_path").asText();
            if (!historical.contains(change) && !matches(change, value(previous, path), value(next, path), reviewer, at)) {
                throw conflict();
            }
            records.computeIfAbsent(path, ignored -> new ArrayList<>()).add(change);
        }
        for (String field : ("title types occurrences locations applicability exceptions route_names stop_names directions "
                + "lifecycle lifecycle_evidence_ids source_version_ids originating_run_ids rules_version dictionary_version").split(" ")) {
            covered(previous.path("revision").path(field), revision.path(field), field, records, reviewer, at);
        }
        covered(previous.path("event"), next.path("event"), "event", records, reviewer, at);
    }

    private static void covered(JsonNode before, JsonNode after, String path, Map<String, List<JsonNode>> records,
                                String reviewer, Instant at) {
        if (before.equals(after)) return;
        for (JsonNode change : records.getOrDefault(path, List.of())) {
            if (matches(change, before, after, reviewer, at)) return;
        }
        if (before.isObject() && after.isObject() && before.size() == after.size()) {
            before.fieldNames().forEachRemaining(name ->
                    covered(before.path(name), after.path(name), path + "." + name, records, reviewer, at));
            return;
        }
        throw conflict();
    }

    private static boolean matches(JsonNode change, JsonNode before, JsonNode after, String reviewer, Instant at) {
        return !before.equals(after) && reviewer != null && at != null && Objects.equals(reviewer, change.path("reviewer").textValue())
                && at.equals(Instant.parse(change.path("time").asText()))
                && before.equals(change.path("before")) && after.equals(change.path("after"));
    }

    private static JsonNode value(JsonNode payload, String path) {
        if (path.equals("event")) return payload.path("event");
        JsonNode value = payload.path(path.startsWith("event.") ? "event" : "revision");
        String local = path.startsWith("event.") ? path.substring(6) : path;
        for (String name : local.split("\\.", -1)) {
            if (!value.isObject() || !value.has(name)) throw conflict();
            value = value.path(name);
        }
        return value;
    }

    private static ImportException conflict() {
        return new ImportException("IMPORT_CONFLICT", "변경 전후 값·검토자·시각에 일치하는 사람 검토 기록이 필요합니다.", "human_overrides");
    }
}
