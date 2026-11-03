package kr.ac.myai.backend.importing;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** AI 파생 revision의 의미값 변경과 사람 검토 기록을 대조한다. */
public final class HumanReviewChanges {
    private static final List<String> FIELDS = List.of(("title types occurrences locations applicability exceptions route_names stop_names directions "
            + "lifecycle lifecycle_evidence_ids source_version_ids originating_run_ids rules_version dictionary_version").split(" "));
    private HumanReviewChanges() { }

    public static void record(JsonNode previous, ObjectNode next, String actor, Instant at, String reason) {
        if (actor == null || actor.isBlank() || at == null || reason == null || reason.isBlank()) throw conflict();
        String time = at.truncatedTo(ChronoUnit.MICROS).toString();
        var revision = next.withObject("revision");
        revision.put("reviewer_id", actor).put("reviewed_at", time);
        var changes = revision.putArray("human_overrides");
        if (previous == null || previous.isNull()) return;
        previous.path("revision").path("human_overrides").forEach(change -> changes.add(change.deepCopy()));
        var citations = new LinkedHashSet<String>();
        evidence(previous).forEach(citations::add);
        evidence(next).forEach(citations::add);
        for (String field : FIELDS) add(changes, previous.path("revision").path(field), revision.path(field), field, actor, time, reason, citations);
        for (String field : List.of("event", "evidence")) add(changes, previous.path(field), next.path(field), field, actor, time, reason, citations);
    }

    private static void add(com.fasterxml.jackson.databind.node.ArrayNode changes, JsonNode before, JsonNode after,
                            String path, String actor, String time, String reason, java.util.Set<String> citations) {
        if (before.equals(after)) return;
        var change = changes.addObject().put("field_path", path).put("reason", reason).put("reviewer", actor).put("time", time);
        change.set("before", before.deepCopy()); change.set("after", after.deepCopy());
        var ids = change.putArray("evidence_ids");
        citations.forEach(ids::add);
    }

    public static void validate(JsonNode previous, JsonNode next) {
        validate(previous, next, false);
    }

    public static void validate(JsonNode previous, JsonNode next, boolean generatedHandoff) {
        var revision = next.path("revision");
        Map<String, List<JsonNode>> records = new HashMap<>();
        String reviewer = revision.path("reviewer_id").textValue();
        Instant at = instant(revision.path("reviewed_at"));
        var historical = previous.path("revision").path("human_overrides");
        var changes = revision.path("human_overrides");
        if (!historical.isArray() || !changes.isArray() || changes.size() < historical.size()) throw conflict();
        var allowed = evidence(previous); allowed.addAll(evidence(next));
        for (int index = 0; index < changes.size(); index++) {
            JsonNode change = changes.get(index);
            if (index < historical.size()) {
                if (!change.equals(historical.get(index))) throw conflict();
                continue;
            }
            String path = change.path("field_path").asText();
            if (!matches(change, value(previous, path), value(next, path), reviewer, at)) throw conflict();
            JsonNode citations = change.path("evidence_ids");
            if (!citations.isArray() || citations.isEmpty() && !generatedHandoff) throw conflict();
            var unique = new LinkedHashSet<String>();
            for (JsonNode id : citations) {
                if (!id.isTextual() || !allowed.contains(id.textValue()) || !unique.add(id.textValue())) throw conflict();
            }
            records.computeIfAbsent(path, ignored -> new ArrayList<>()).add(change);
        }
        for (String field : FIELDS) {
            covered(previous.path("revision").path(field), revision.path(field), field, records, reviewer, at);
        }
        covered(previous.path("event"), next.path("event"), "event", records, reviewer, at);
        covered(previous.path("evidence"), next.path("evidence"), "evidence", records, reviewer, at);
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
                && at.equals(instant(change.path("time")))
                && before.equals(change.path("before")) && after.equals(change.path("after"));
    }

    private static Instant instant(JsonNode value) {
        if (!value.isTextual() || !value.asText().matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,6})?Z")) return null;
        try { return Instant.parse(value.asText()); }
        catch (java.time.DateTimeException ex) { return null; }
    }

    private static LinkedHashSet<String> evidence(JsonNode payload) {
        var result = new LinkedHashSet<String>();
        for (JsonNode item : payload.path("evidence")) {
            if (!item.path("evidence_id").isTextual() || item.path("evidence_id").textValue().isBlank()) throw conflict();
            result.add(item.path("evidence_id").textValue());
        }
        return result;
    }

    private static JsonNode value(JsonNode payload, String path) {
        if (path.equals("event") || path.equals("evidence")) return payload.path(path);
        if (!path.startsWith("event.") && !FIELDS.contains(path.split("\\.", -1)[0])) throw conflict();
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
