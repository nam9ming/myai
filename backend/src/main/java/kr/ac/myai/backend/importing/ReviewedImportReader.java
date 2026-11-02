package kr.ac.myai.backend.importing;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.StreamReadConstraints;
import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.*;

@Component
public class ReviewedImportReader {
    private static final int LIMIT = 8 * 1024 * 1024;
    private final ObjectMapper mapper = new ObjectMapper(JsonFactory.builder()
            .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
            .streamReadConstraints(StreamReadConstraints.builder().maxNestingDepth(100).maxStringLength(LIMIT).build())
            .build()).enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);

    public ReviewedBatch read(Path file, Path sourceRoot) {
        try {
            byte[] bytes = readBounded(file, "file");
            String json = StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
            JsonNode input = mapper.readTree(json);
            unicode(input);
            shape(input, "$", "schema_version data_kind documents evidence events");
            check(text(input, "schema_version", 100).equals("reviewed-import-v1"), "schema_version");
            String kind = choice(input, "data_kind", "synthetic", "real");
            List<ReviewedBatch.Document> documents = new ArrayList<>();
            Map<String, JsonNode> sources = new HashMap<>();
            Set<String> versions = new HashSet<>();
            Set<String> checkIds = new HashSet<>();
            Path root = sourceRoot.toRealPath();
            check(Files.isDirectory(root), "source_root");
            for (JsonNode doc : array(input, "documents", true)) {
                var document = document(doc, root, kind, checkIds);
                check(sources.putIfAbsent(document.versionId(), doc) == null, "documents.document_version_id");
                check(versions.add(document.id() + ":" + document.versionNo()), "documents.version_no");
                documents.add(document);
            }
            Map<String, JsonNode> evidence = evidence(input, sources);
            List<ReviewedBatch.Event> events = new ArrayList<>();
            Set<String> eventIds = new HashSet<>();
            Set<String> revisionIds = new HashSet<>();
            for (JsonNode event : array(input, "events", true)) {
                var reviewed = event(event, sources, evidence, kind);
                check(eventIds.add(reviewed.id()), "events.event_id");
                check(revisionIds.add(reviewed.revisionId()), "events.revision.revision_id");
                events.add(reviewed);
            }
            return new ReviewedBatch("reviewed-import-v1", sha256(bytes), kind, documents, events);
        } catch (IOException | IllegalArgumentException ex) {
            throw invalid("file", "UTF-8 JSON 또는 원문 파일을 읽고 검증할 수 없습니다.");
        }
    }

    private ReviewedBatch.Document document(JsonNode doc, Path root, String kind, Set<String> checkIds) throws IOException {
        shape(doc, "documents", "document_id publisher official_url title official_number published_date collected_at document_version_id version_no raw_asset_path raw_sha256 cleaned_text text_sha256 block_index redaction_log preprocessing_version use_review use_note collection_method latest_check_attempt_at last_verified_at check_result checks");
        String id = uuid(doc, "document_id");
        String versionId = uuid(doc, "document_version_id");
        long version = integer(doc, "version_no", 1, Long.MAX_VALUE);
        text(doc, "publisher", 255);
        text(doc, "title", LIMIT);
        String url = text(doc, "official_url", 8192);
        URI uri = URI.create(url);
        check(Set.of("http", "https").contains(uri.getScheme()) && uri.getHost() != null && uri.getUserInfo() == null, "documents.official_url");
        nullableText(doc, "official_number", 255);
        date(doc, "published_date");
        instant(doc, "collected_at", false);
        String rawRef = text(doc, "raw_asset_path", 4096);
        Path relative = Path.of(rawRef);
        check(!relative.isAbsolute() && relative.normalize().equals(relative) && !relative.startsWith(".."), "documents.raw_asset_path");
        Path raw = root.resolve(relative).toRealPath();
        check(raw.startsWith(root), "documents.raw_asset_path");
        check(sha256(readBounded(raw, "documents.raw_asset_path")).equals(hash(doc, "raw_sha256")), "documents.raw_sha256");
        String cleaned = text(doc, "cleaned_text", LIMIT);
        String textHash = hash(doc, "text_sha256");
        check(sha256(cleaned.getBytes(StandardCharsets.UTF_8)).equals(textHash), "documents.text_sha256");
        Set<String> blocks = new HashSet<>();
        for (JsonNode block : array(doc, "block_index", true)) {
            shape(block, "documents.block_index", "block_id page text");
            check(blocks.add(text(block, "block_id", 128)), "documents.block_index.block_id");
            check(cleaned.contains(text(block, "text", LIMIT)), "documents.block_index.text");
            if (!block.path("page").isNull()) integer(block, "page", 1, Integer.MAX_VALUE);
        }
        for (JsonNode redaction : array(doc, "redaction_log", false)) {
            shape(redaction, "documents.redaction_log", "category location");
            text(redaction, "category", 128);
            text(redaction, "location", 512);
        }
        text(doc, "preprocessing_version", 100);
        choice(doc, "use_review", "pending", "allowed", "restricted");
        text(doc, "use_note", LIMIT);
        text(doc, "collection_method", 100);
        Instant latest = instant(doc, "latest_check_attempt_at", true);
        Instant lastVerified = instant(doc, "last_verified_at", true);
        String latestResult = choice(doc, "check_result", "unchecked", "verified", "changed", "unreachable", "uncertain");
        List<ReviewedBatch.SourceCheck> checks = new ArrayList<>();
        Instant previousTime = null;
        Instant verifiedTime = null;
        String lastSuccess = null;
        String result = "unchecked";
        for (JsonNode sourceCheck : array(doc, "checks", false)) {
            shape(sourceCheck, "documents.checks", "check_id checked_at result reviewer_id text_sha256 note");
            String checkId = uuid(sourceCheck, "check_id");
            check(checkIds.add(checkId), "documents.checks.check_id");
            Instant at = instant(sourceCheck, "checked_at", false);
            check(previousTime == null || at.isAfter(previousTime), "documents.checks.checked_at");
            text(sourceCheck, "reviewer_id", 128);
            result = choice(sourceCheck, "result", "verified", "changed", "unreachable", "uncertain");
            String checkedHash = hash(sourceCheck, "text_sha256");
            String note = text(sourceCheck, "note", LIMIT);
            if (result.equals("verified")) {
                check(checkedHash.equals(textHash), "documents.checks.text_sha256");
                verifiedTime = at;
            }
            checks.add(new ReviewedBatch.SourceCheck(checkId, at, result, lastSuccess, note));
            if (result.equals("verified")) lastSuccess = checkId;
            previousTime = at;
        }
        check(Objects.equals(previousTime, latest) && Objects.equals(verifiedTime, lastVerified) && result.equals(latestResult), "documents.checks");
        ObjectNode metadata = mapper.createObjectNode().put("data_kind", kind);
        metadata.set("document", doc);
        return new ReviewedBatch.Document(id, versionId, version, url, textHash, metadata.toString(), rawRef, checks);
    }

    private Map<String, JsonNode> evidence(JsonNode input, Map<String, JsonNode> sources) {
        Map<String, JsonNode> result = new LinkedHashMap<>();
        for (JsonNode item : array(input, "evidence", true)) {
            shape(item, "evidence", "evidence_id document_version_id block_id quote start_char end_char text_sha256");
            String id = text(item, "evidence_id", 128);
            check(result.putIfAbsent(id, item) == null, "evidence.evidence_id");
            JsonNode doc = sources.get(uuid(item, "document_version_id"));
            check(doc != null, "evidence.document_version_id");
            check(hash(item, "text_sha256").equals(doc.path("text_sha256").asText()), "evidence.text_sha256");
            String blockId = text(item, "block_id", 128);
            String blockText = null;
            for (JsonNode block : doc.path("block_index")) {
                if (block.path("block_id").asText().equals(blockId)) blockText = block.path("text").asText();
            }
            check(blockText != null, "evidence.block_id");
            int start = (int) integer(item, "start_char", 0, Integer.MAX_VALUE);
            int end = (int) integer(item, "end_char", 1, Integer.MAX_VALUE);
            check(start < end && end <= blockText.codePointCount(0, blockText.length()), "evidence.end_char");
            String quote = text(item, "quote", LIMIT);
            check(quote.equals(blockText.substring(blockText.offsetByCodePoints(0, start), blockText.offsetByCodePoints(0, end))), "evidence.quote");
        }
        return result;
    }

    private ReviewedBatch.Event event(JsonNode event, Map<String, JsonNode> sources, Map<String, JsonNode> evidence, String kind) {
        shape(event, "events", "event_id area_id area_membership document_links relations suspected_duplicate_ids split_group_id expected_revision_no revision");
        String id = uuid(event, "event_id");
        uuid(event, "area_id");
        uuid(event, "split_group_id");
        choice(event, "area_membership", "verified", "uncertain", "outside");
        long expected = integer(event, "expected_revision_no", 0, Long.MAX_VALUE - 1);
        List<String> duplicates = ids(event, "suspected_duplicate_ids", false, true);
        check(!duplicates.contains(id), "events.suspected_duplicate_ids");
        JsonNode revision = event.path("revision");
        shape(revision, "events.revision", "revision_id event_id revision_no title types occurrences locations applicability exceptions route_names stop_names directions lifecycle lifecycle_evidence_ids human_overrides review_status reviewer_id reviewed_at publication_intent origin source_version_ids originating_run_ids rules_version dictionary_version");
        check(uuid(revision, "event_id").equals(id), "events.revision.event_id");
        String revisionId = uuid(revision, "revision_id");
        long number = integer(revision, "revision_no", 1, Long.MAX_VALUE);
        check(number == expected + 1, "events.revision.revision_no");
        text(revision, "title", LIMIT);
        for (String type : ids(revision, "types", true, false)) check(Set.of("construction", "event", "traffic").contains(type), "events.revision.types");
        List<String> sourceIds = ids(revision, "source_version_ids", true, true);
        Set<String> documentIds = new HashSet<>();
        for (String sourceId : sourceIds) {
            check(sources.containsKey(sourceId), "events.revision.source_version_ids");
            documentIds.add(sources.get(sourceId).path("document_id").asText());
        }
        Set<String> allowedEvidence = new HashSet<>();
        evidence.forEach((key, value) -> { if (sourceIds.contains(value.path("document_version_id").asText())) allowedEvidence.add(key); });
        Set<String> linked = new HashSet<>();
        for (JsonNode link : array(event, "document_links", true)) {
            shape(link, "events.document_links", "document_id role evidence_ids");
            String documentId = uuid(link, "document_id");
            check(documentIds.contains(documentId) && linked.add(documentId), "events.document_links.document_id");
            choice(link, "role", "original", "correction", "cancellation", "repost");
            for (String evidenceId : evidenceIds(link, "evidence_ids", allowedEvidence, true)) {
                check(sources.get(evidence.get(evidenceId).path("document_version_id").asText()).path("document_id").asText().equals(documentId), "events.document_links.evidence_ids");
            }
        }
        check(linked.equals(documentIds), "events.document_links");
        relations(event, documentIds);
        Set<String> locations = new HashSet<>();
        for (JsonNode location : array(revision, "locations", true)) {
            location(location, allowedEvidence);
            check(locations.add(uuid(location, "location_id")), "events.revision.locations.location_id");
        }
        Set<String> occurrences = new HashSet<>();
        for (JsonNode occurrence : array(revision, "occurrences", true)) {
            occurrence(occurrence, locations, allowedEvidence);
            check(occurrences.add(uuid(occurrence, "occurrence_id")), "events.revision.occurrences.occurrence_id");
        }
        for (String name : List.of("applicability", "exceptions")) fieldValue(revision.path(name), allowedEvidence, false);
        for (String name : List.of("route_names", "stop_names", "directions")) fieldValue(revision.path(name), allowedEvidence, true);
        String lifecycle = choice(revision, "lifecycle", "active", "cancelled", "uncertain");
        evidenceIds(revision, "lifecycle_evidence_ids", allowedEvidence, lifecycle.equals("cancelled"));
        for (JsonNode change : array(revision, "human_overrides", false)) {
            shape(change, "events.revision.human_overrides", "field_path before after reason evidence_ids reviewer time");
            text(change, "field_path", 512);
            text(change, "reason", LIMIT);
            text(change, "reviewer", 128);
            instant(change, "time", false);
            evidenceIds(change, "evidence_ids", allowedEvidence, true);
        }
        String status = choice(revision, "review_status", "draft", "needs_review");
        choice(revision, "publication_intent", "hidden");
        String reviewer = nullableText(revision, "reviewer_id", 128);
        Instant reviewedAt = instant(revision, "reviewed_at", true);
        check((reviewer == null) == (reviewedAt == null), "events.revision.reviewed_at");
        List<String> runs = ids(revision, "originating_run_ids", false, true);
        String origin = choice(revision, "origin", "human", "ai_reviewed");
        check(origin.equals("human") == runs.isEmpty(), "events.revision.originating_run_ids");
        text(revision, "rules_version", 100);
        text(revision, "dictionary_version", 100);
        ObjectNode payload = mapper.createObjectNode().put("data_kind", kind);
        ObjectNode facts = event.deepCopy();
        facts.remove(List.of("revision", "expected_revision_no"));
        payload.set("event", facts);
        payload.set("revision", revision);
        var citations = payload.putArray("evidence");
        evidence.forEach((key, value) -> { if (allowedEvidence.contains(key)) citations.add(value); });
        String json = payload.toString();
        return new ReviewedBatch.Event(id, revisionId, number, expected, json, sha256(json.getBytes(StandardCharsets.UTF_8)), status, reviewer, reviewedAt, runs, sourceIds, duplicates);
    }

    private void relations(JsonNode event, Set<String> documents) {
        Map<String, List<String>> corrections = new HashMap<>();
        for (JsonNode relation : array(event, "relations", false)) {
            shape(relation, "events.relations", "from_document_id to_document_id type reviewed_by reason created_at");
            String from = uuid(relation, "from_document_id");
            String to = uuid(relation, "to_document_id");
            check(!from.equals(to) && documents.contains(from) && documents.contains(to), "events.relations");
            String type = choice(relation, "type", "corrects", "cancels", "reposts", "duplicates");
            text(relation, "reviewed_by", 128);
            text(relation, "reason", LIMIT);
            instant(relation, "created_at", false);
            if (type.equals("corrects")) corrections.computeIfAbsent(from, ignored -> new ArrayList<>()).add(to);
        }
        Set<String> remaining = new HashSet<>(documents);
        while (!remaining.isEmpty()) {
            Set<String> leaves = new HashSet<>();
            for (String id : remaining) if (corrections.getOrDefault(id, List.of()).stream().noneMatch(remaining::contains)) leaves.add(id);
            check(!leaves.isEmpty(), "events.relations");
            remaining.removeAll(leaves);
        }
    }

    private void occurrence(JsonNode node, Set<String> locations, Set<String> evidence) {
        shape(node, "occurrences", "occurrence_id date_start date_end time_start time_end end_day_offset precision recurrence_dates location_ids evidence_ids knowledge normalization_note");
        LocalDate startDate = date(node, "date_start");
        LocalDate endDate = date(node, "date_end");
        check(startDate == null || endDate == null || !endDate.isBefore(startDate), "occurrences.date_end");
        LocalTime start = time(node, "time_start");
        LocalTime end = time(node, "time_end");
        Long offset = node.path("end_day_offset").isNull() ? null : integer(node, "end_day_offset", 0, 1);
        String precision = choice(node, "precision", "exact_time", "date_only", "explicit_all_day", "unknown");
        String knowledge = choice(node, "knowledge", "known", "not_stated", "ambiguous", "not_applicable");
        check(precision.equals("unknown") != knowledge.equals("known"), "occurrences.knowledge");
        if (!precision.equals("unknown")) {
            check(startDate != null && endDate != null, "occurrences.date_start");
            evidenceIds(node, "evidence_ids", evidence, true);
        } else evidenceIds(node, "evidence_ids", evidence, false);
        if (precision.equals("exact_time")) {
            check(start != null && end != null && offset != null, "occurrences.time_start");
        } else if (!precision.equals("unknown")) check(start == null && end == null && offset == null, "occurrences.time_start");
        // 미상 날짜의 부분 시간은 보존하되 완전한 시간 구간의 모순은 거부한다.
        if (start != null && end != null && offset != null) {
            long seconds = end.toSecondOfDay() + offset * 86400 - start.toSecondOfDay();
            check(seconds > 0 && seconds <= 86400, "occurrences.time_end");
        }
        if (!node.path("recurrence_dates").isNull()) {
            Set<LocalDate> dates = new HashSet<>();
            for (JsonNode value : array(node, "recurrence_dates", false)) {
                LocalDate day = parseDate(value, "occurrences.recurrence_dates");
                check(dates.add(day) && (startDate == null || !day.isBefore(startDate)) && (endDate == null || !day.isAfter(endDate)), "occurrences.recurrence_dates");
            }
        }
        for (String location : ids(node, "location_ids", true, true)) check(locations.contains(location), "occurrences.location_ids");
        nullableText(node, "normalization_note", LIMIT);
    }

    private void location(JsonNode node, Set<String> evidence) {
        shape(node, "locations", "location_id name address kind status geometry coverage source checked_by checked_at evidence_ids");
        fieldValue(node.path("name"), evidence, false);
        fieldValue(node.path("address"), evidence, false);
        for (String key : List.of("name", "address")) {
            JsonNode value = node.path(key).path("value");
            check(value.isNull() || value.isTextual(), "locations." + key + ".value");
        }
        String kind = choice(node, "kind", "point", "segment", "stops", "area", "unknown");
        String status = choice(node, "status", "verified", "ambiguous", "unknown");
        choice(node, "coverage", "complete", "partial", "unknown");
        nullableText(node, "source", LIMIT);
        String checkedBy = nullableText(node, "checked_by", 128);
        Instant checkedAt = instant(node, "checked_at", true);
        check((checkedBy == null) == (checkedAt == null), "locations.checked_at");
        evidenceIds(node, "evidence_ids", evidence, status.equals("verified"));
        JsonNode geometry = node.path("geometry");
        if (status.equals("verified")) check(!geometry.isNull() && checkedBy != null, "locations.geometry");
        if (kind.equals("unknown")) check(geometry.isNull() && !status.equals("verified"), "locations.geometry");
        if (!geometry.isNull()) {
            shape(geometry, "locations.geometry", "type coordinates");
            String type = choice(geometry, "type", "Point", "LineString", "MultiPoint");
            check((!kind.equals("point") || type.equals("Point")) && (!kind.equals("segment") || type.equals("LineString")) && (!kind.equals("stops") || type.equals("MultiPoint")), "locations.geometry.type");
            if (type.equals("Point")) coordinate(geometry.path("coordinates"));
            else {
                JsonNode points = array(geometry, "coordinates", true);
                check(!type.equals("LineString") || points.size() >= 2, "locations.geometry.coordinates");
                for (JsonNode point : points) coordinate(point);
            }
        }
    }

    private void coordinate(JsonNode coordinate) {
        check(coordinate.isArray() && coordinate.size() == 2 && coordinate.get(0).isNumber() && coordinate.get(1).isNumber(), "locations.geometry.coordinates");
        double longitude = coordinate.get(0).doubleValue();
        double latitude = coordinate.get(1).doubleValue();
        check(Double.isFinite(longitude) && Double.isFinite(latitude) && longitude >= -180 && longitude <= 180 && latitude >= -90 && latitude <= 90, "locations.geometry.coordinates");
    }

    private void fieldValue(JsonNode field, Set<String> evidence, boolean listOnly) {
        shape(field, "field_value", "value knowledge evidence_ids reason");
        String knowledge = choice(field, "knowledge", "known", "not_stated", "ambiguous", "not_applicable");
        boolean known = knowledge.equals("known");
        evidenceIds(field, "evidence_ids", evidence, known);
        String reason = nullableText(field, "reason", LIMIT);
        JsonNode value = field.path("value");
        if (!known) check(value.isNull() && reason != null, "field_value.value");
        else if (listOnly) ids(field, "value", false, false);
        else if (value.isArray()) ids(field, "value", false, false);
        else text(field, "value", LIMIT);
    }

    private List<String> evidenceIds(JsonNode node, String key, Set<String> allowed, boolean required) {
        List<String> ids = ids(node, key, required, false);
        check(allowed.containsAll(ids), "evidence_ids");
        return ids;
    }

    private List<String> ids(JsonNode node, String key, boolean required, boolean uuid) {
        List<String> result = new ArrayList<>();
        Set<String> unique = new HashSet<>();
        for (JsonNode value : array(node, key, required)) {
            String id = string(value, key, LIMIT);
            if (uuid) check(id.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), key);
            check(unique.add(id), key);
            result.add(id);
        }
        return result;
    }

    private void shape(JsonNode node, String path, String names) {
        check(node != null && node.isObject(), path);
        Set<String> expected = Set.of(names.split(" "));
        Set<String> actual = new HashSet<>();
        node.fieldNames().forEachRemaining(actual::add);
        check(actual.equals(expected), path);
    }

    private JsonNode array(JsonNode node, String key, boolean required) {
        JsonNode value = node.path(key);
        check(value.isArray() && (!required || !value.isEmpty()), key);
        return value;
    }

    private String text(JsonNode node, String key, int max) { return string(node.path(key), key, max); }

    private String string(JsonNode value, String path, int max) {
        check(value.isTextual() && !value.textValue().isBlank() && value.textValue().length() <= max, path);
        String text = value.textValue();
        validUnicode(text, path);
        return text;
    }

    private void unicode(JsonNode node) {
        if (node == null) return;
        if (node.isTextual()) validUnicode(node.textValue(), "file");
        else if (node.isContainerNode()) node.forEach(this::unicode);
    }

    private void validUnicode(String text, String path) {
        for (int i = 0; i < text.length(); i++) {
            char current = text.charAt(i);
            if (Character.isHighSurrogate(current)) check(++i < text.length() && Character.isLowSurrogate(text.charAt(i)), path);
            else check(!Character.isLowSurrogate(current), path);
        }
    }

    private String nullableText(JsonNode node, String key, int max) {
        return node.path(key).isNull() ? null : text(node, key, max);
    }

    private String uuid(JsonNode node, String key) {
        String value = text(node, key, 36);
        check(value.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), key);
        return value;
    }

    private String hash(JsonNode node, String key) {
        String value = text(node, key, 64);
        check(value.matches("[0-9a-f]{64}"), key);
        return value;
    }

    private String choice(JsonNode node, String key, String... values) {
        String value = text(node, key, 100);
        check(Arrays.asList(values).contains(value), key);
        return value;
    }

    private long integer(JsonNode node, String key, long min, long max) {
        JsonNode value = node.path(key);
        check(value.isIntegralNumber() && value.canConvertToLong() && value.longValue() >= min && value.longValue() <= max, key);
        return value.longValue();
    }

    private LocalDate date(JsonNode node, String key) {
        return node.path(key).isNull() ? null : parseDate(node.path(key), key);
    }

    private LocalDate parseDate(JsonNode value, String path) {
        String date = string(value, path, 10);
        check(date.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}"), path);
        try { return LocalDate.parse(date); }
        catch (java.time.DateTimeException ex) { throw invalid(path, "유효한 날짜가 필요합니다."); }
    }

    private LocalTime time(JsonNode node, String key) {
        if (node.path(key).isNull()) return null;
        String value = text(node, key, 8);
        check(value.matches("[0-9]{2}:[0-9]{2}(:[0-9]{2})?"), key);
        try { return LocalTime.parse(value); }
        catch (java.time.DateTimeException ex) { throw invalid(key, "유효한 지역 시간이 필요합니다."); }
    }

    private Instant instant(JsonNode node, String key, boolean nullable) {
        if (nullable && node.path(key).isNull()) return null;
        String value = text(node, key, 32);
        check(value.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,6})?Z"), key);
        try {
            check(Integer.parseInt(value.substring(0, 4)) >= 1000, key);
            LocalDate.parse(value.substring(0, 10));
            LocalTime.parse(value.substring(11, value.length() - 1));
            return Instant.parse(value);
        }
        catch (java.time.DateTimeException ex) { throw invalid(key, "마이크로초 이하 정밀도의 UTC 시각이 필요합니다."); }
    }

    private byte[] readBounded(Path file, String path) throws IOException {
        check(Files.isRegularFile(file), path);
        try (var input = Files.newInputStream(file)) {
            byte[] bytes = input.readNBytes(LIMIT + 1);
            check(bytes.length > 0 && bytes.length <= LIMIT, path);
            return bytes;
        }
    }

    public static String sha256(byte[] bytes) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
        catch (NoSuchAlgorithmException ex) { throw new IllegalStateException(ex); }
    }

    private void check(boolean condition, String field) {
        if (!condition) throw invalid(field, "검토본 형식·값·근거 또는 참조가 유효하지 않습니다.");
    }

    private ImportException invalid(String field, String message) { return new ImportException("IMPORT_VALIDATION_ERROR", message, field); }
}
