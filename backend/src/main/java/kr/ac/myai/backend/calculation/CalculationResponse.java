package kr.ac.myai.backend.calculation;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.time.*;
import java.util.*;
import java.util.function.Function;

import static kr.ac.myai.backend.calculation.PythonCalculator.*;

public final class CalculationResponse {
    private static final String METRICS = "classification reason_codes warnings distance_m distance_basis time_overlap_minutes matched_occurrence_ids";
    private static final Set<String> REASONS = Set.of("WINDOW_OUTSIDE", "BUSINESS_CLOSED", "TIME_NO_OVERLAP", "DISTANCE_OUTSIDE", "DATE_UNKNOWN", "TIME_UNKNOWN",
            "BUSINESS_UNKNOWN", "LOCATION_UNKNOWN", "AREA_UNCERTAIN", "SOURCE_STALE", "SOURCE_UNREACHABLE", "RELATION_UNCERTAIN", "CANCELLED");

    public static void validate(ObjectNode request, ObjectNode data, Function<String, ObjectNode> publicFacts) {
        try { verify(request, data, publicFacts); }
        catch (DateTimeException | IllegalArgumentException ex) { throw protocolError(); }
    }

    private static void verify(ObjectNode request, ObjectNode data, Function<String, ObjectNode> publicFacts) {
        shape(data, "data_kind query_context counts items overlap_groups rules_version");
        var context = request.path("context"); var query = request.path("query");
        require(data.path("data_kind").equals(context.path("data_kind")) && data.path("rules_version").equals(context.path("rules_version")));
        LocalDate anchor = LocalDate.parse(context.path("anchor_date").asText());
        Instant start = anchor.atStartOfDay(ZoneId.of("Asia/Seoul")).toInstant();
        Instant end = anchor.plusDays(14).atStartOfDay(ZoneId.of("Asia/Seoul")).toInstant();
        var expectedContext = JsonNodeFactory.instance.objectNode();
        for (String field : "point_id weekly_hours mode case_id".split(" ")) expectedContext.set(field, query.path(field));
        expectedContext.put("anchor_date", anchor.toString()).put("window_start", start.toString()).put("window_end_exclusive", end.toString())
                .put("radius_m", 500).put("timezone", "Asia/Seoul");
        if (context.path("mode").asText().equals("replay")) {
            for (String field : "reference_instant knowledge_cutoff history_fidelity".split(" ")) expectedContext.set(field, context.path(field));
        }
        require(data.path("query_context").equals(expectedContext));
        var facts = new HashMap<String, JsonNode>(); var filtered = new HashSet<String>(); var types = strings(query.path("types"));
        for (JsonNode event : request.path("events")) {
            String id = event.path("event_id").asText();
            require(facts.putIfAbsent(id, event) == null);
            if (types.isEmpty() || !Collections.disjoint(types, strings(event.path("types")))) filtered.add(id);
        }
        shape(data.path("counts"), "candidate needs_check cancelled");
        long total = 0;
        for (JsonNode count : data.path("counts")) {
            require(count.isIntegralNumber() && count.canConvertToInt() && count.intValue() >= 0 && count.intValue() <= filtered.size());
            total += count.intValue();
        }
        require(total <= filtered.size() && data.path("items").isArray());
        String selection = query.path("selection").asText(); var returned = new HashSet<String>();
        for (JsonNode item : data.path("items")) {
            String id = item.path("event_id").asText();
            require(filtered.contains(id) && returned.add(id) && item.path("classification").asText().equals(selection));
            JsonNode event = facts.get(id);
            if (event.path("lifecycle").asText().equals("cancelled")) require(selection.equals("cancelled"));
            else if (event.path("lifecycle").asText().equals("uncertain") || event.path("area_membership").asText().equals("uncertain")) require(selection.equals("needs_check"));
            ObjectNode expected = publicFacts.apply(id);
            var allowed = new HashSet<>(keys(expected)); allowed.addAll(Set.of(METRICS.split(" ")));
            require(keys(item).equals(allowed));
            expected.fieldNames().forEachRemaining(field -> require(item.path(field).equals(expected.path(field))));
            require(REASONS.containsAll(strings(item.path("reason_codes"))));
            require(item.path("warnings").isArray());
            for (JsonNode warning : item.path("warnings")) require(warning.isTextual() && !warning.textValue().isBlank());
            number(item.path("distance_m"), Double.MAX_VALUE);
            number(item.path("time_overlap_minutes"), 14 * 24 * 60);
            if (item.path("distance_m").isNull()) require(item.path("distance_basis").isNull());
            else require(Set.of("haversine_point", "great_circle_segment", "minimum_verified_stops").contains(item.path("distance_basis").asText()));
            var occurrenceIds = new HashSet<String>();
            for (JsonNode occurrence : event.path("occurrences")) occurrenceIds.add(occurrence.path("occurrence_id").asText());
            var matched = strings(item.path("matched_occurrence_ids"));
            require(occurrenceIds.containsAll(matched) && (!selection.equals("candidate") || !matched.isEmpty()));
        }
        require(returned.size() == data.path("counts").path(selection).asInt(-1));
        require(data.path("overlap_groups").isArray());
        var groupIds = new HashSet<String>(); Instant previousEnd = null; Set<String> previousIds = Set.of();
        for (JsonNode group : data.path("overlap_groups")) {
            shape(group, "group_id start_at end_at event_ids");
            String id = group.path("group_id").asText();
            require(UUID.fromString(id).toString().equals(id) && groupIds.add(id));
            var members = strings(group.path("event_ids"));
            require(members.size() >= 2 && members.size() <= data.path("counts").path("candidate").asInt() && filtered.containsAll(members));
            if (selection.equals("candidate")) require(returned.containsAll(members));
            for (String member : members) {
                require(facts.get(member).path("lifecycle").asText().equals("active") && facts.get(member).path("area_membership").asText().equals("verified"));
            }
            Instant lo = utc(group.path("start_at")), hi = utc(group.path("end_at"));
            require(lo.isBefore(hi) && !lo.isBefore(start) && !hi.isAfter(end) && (previousEnd == null || !lo.isBefore(previousEnd)));
            require(previousEnd == null || !lo.equals(previousEnd) || !members.equals(previousIds));
            previousEnd = hi; previousIds = members;
        }
    }

    private static Set<String> strings(JsonNode node) {
        require(node.isArray()); var result = new HashSet<String>();
        for (JsonNode value : node) require(value.isTextual() && !value.textValue().isBlank() && result.add(value.textValue()));
        return result;
    }

    private static void number(JsonNode node, double maximum) {
        require(node.isNull() || node.isNumber() && Double.isFinite(node.doubleValue()) && node.doubleValue() >= 0 && node.doubleValue() <= maximum);
    }

    private static Instant utc(JsonNode node) {
        require(node.isTextual() && node.textValue().matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\\.[0-9]{1,9})?Z"));
        return Instant.parse(node.textValue());
    }

    private CalculationResponse() {}
}
