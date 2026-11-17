package kr.ac.myai.backend.publication;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.PublicationRepository;
import kr.ac.myai.backend.source.SourceView;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.DateTimeException;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.*;

@Component
public class CitizenPublicationContent {
    public static final String SCHEMA_VERSION = "citizen-snapshot-v1";
    public static final String CHANNEL = "citizen:current";
    private static final int LIMIT = 8 * 1024 * 1024;
    private static final String FACTS = "application_period occurrences regions locations residency_requirement target eligibility application_method preparation cost recruitment lifecycle";
    private static final String NOTICE_FIELDS = "event_id revision_id title categories " + FACTS + " source_version_ids document_links relations evidence";
    private static final String SOURCE_FIELDS = "document_id document_version_id publisher official_url title official_number published_date collected_at text_sha256 last_verified_at latest_check_attempt_at check_result";
    private static final String RELATION_FIELDS = "from_document_id to_document_id type reason created_at";
    private final PublicationContent shared;
    private final ObjectMapper mapper;

    public CitizenPublicationContent(PublicationContent shared, ObjectMapper mapper) { this.shared = shared; this.mapper = mapper; }

    public PublicationRepository.Snapshot snapshot(PublicationCommand.CitizenPublish command, List<PublicationRepository.Revision> revisions,
                                                   Map<String, SourceView> documents, String id, Instant createdAt) {
        check(command != null && "citizen-publication-command-v1".equals(command.schemaVersion())
                && ("preview".equals(command.action()) || "publish".equals(command.action())), "command");
        check(command.revisionIds() != null && command.revisionIds().size() <= 1000 && revisions != null && documents != null && createdAt != null, "revision_ids");
        var requested = new HashSet<String>();
        command.revisionIds().forEach(revision -> check(revision != null && requested.add(revision.toString()), "revision_ids"));
        var root = mapper.createObjectNode().put("schema_version", SCHEMA_VERSION).put("snapshot_id", id).put("created_at", createdAt.toString())
                .put("data_kind", command.dataKind()).put("mode", "current").putNull("case_id").put("channel_key", CHANNEL).put("timezone", "Asia/Seoul");
        var revisionIds = root.putArray("revision_ids");
        var notices = root.putArray("notices");
        Set<String> used = new HashSet<>();
        Set<String> selected = new HashSet<>();
        for (var row : revisions.stream().sorted(Comparator.comparing(PublicationRepository.Revision::eventId)).toList()) {
            check(row.payload().getBytes(StandardCharsets.UTF_8).length <= LIMIT, "revision");
            JsonNode payload;
            try { payload = shared.payload(row); }
            catch (ImportException ex) { throw invalid(ex.field()); }
            check(payload.path("schema_version").asText().equals(ReviewedImportReader.CITIZEN_PAYLOAD_VERSION)
                    && payload.path("data_kind").asText().equals(command.dataKind())
                    && row.status().equals("approved") && row.intent().equals("public") && selected.add(row.id()), "revision");
            var revision = payload.path("revision");
            var facts = payload.path("event");
            var notice = shared.select(revision, "event_id revision_id title categories " + FACTS + " source_version_ids");
            notice.set("document_links", shared.select(facts, "document_links").get("document_links"));
            var relations = notice.putArray("relations");
            check(facts.path("relations").isArray(), "relations");
            for (var relation : facts.path("relations")) relations.add(shared.select(relation, RELATION_FIELDS));
            notice.set("evidence", shared.select(payload, "evidence").get("evidence"));
            for (String sourceId : ids(notice, "source_version_ids", true, true)) used.add(sourceId);
            revisionIds.add(row.id());
            notices.add(notice);
        }
        check(selected.equals(requested), "revision_ids");
        var sources = root.putArray("sources");
        for (String versionId : used.stream().sorted().toList()) {
            var view = documents.get(versionId);
            check(view != null, "source_version_ids");
            var original = view.original();
            var metadata = parse(view.effectiveMetadata());
            var document = metadata.path("document");
            check(metadata.path("data_kind").asText().equals(command.dataKind()) && original.versionId().equals(versionId)
                    && document.path("document_version_id").asText().equals(versionId) && document.path("document_id").asText().equals(original.id())
                    && document.path("text_sha256").asText().equals(original.textHash()), "sources");
            var source = shared.select(document, SOURCE_FIELDS);
            var checks = source.putArray("checks");
            check(document.path("checks").isArray(), "sources.checks");
            for (var item : document.path("checks")) checks.add(shared.select(item, "checked_at result text_sha256"));
            sources.add(source);
        }
        root.put("notice_count", revisions.size());
        String canonical = root.toString();
        var snapshot = new PublicationRepository.Snapshot(id, "current", null, canonical,
                ReviewedImportReader.sha256(canonical.getBytes(StandardCharsets.UTF_8)), command.dataKind(), null, null);
        verifySnapshot(snapshot, SCHEMA_VERSION, createdAt);
        return snapshot;
    }

    public void verifySnapshot(PublicationRepository.Snapshot snapshot, String dbSchema, Instant dbCreatedAt) {
        check(snapshot != null && SCHEMA_VERSION.equals(dbSchema) && dbCreatedAt != null && snapshot.canonical() != null, "snapshot");
        byte[] bytes = snapshot.canonical().getBytes(StandardCharsets.UTF_8);
        check(bytes.length <= LIMIT && ReviewedImportReader.sha256(bytes).equals(snapshot.checksum()), "snapshot.checksum");
        var root = parse(snapshot.canonical());
        shape(root, "snapshot", "schema_version snapshot_id created_at data_kind mode case_id channel_key timezone revision_ids notices sources notice_count");
        check(SCHEMA_VERSION.equals(text(root, "schema_version", 100)) && CHANNEL.equals(text(root, "channel_key", 100))
                && "current".equals(snapshot.mode()) && "current".equals(text(root, "mode", 100)) && snapshot.caseId() == null
                && root.path("case_id").isNull() && snapshot.rulesVersion() == null && snapshot.dictionaryVersion() == null
                && "Asia/Seoul".equals(text(root, "timezone", 100)) && uuid(root, "snapshot_id").equals(snapshot.id())
                && choice(root, "data_kind", "synthetic", "real").equals(snapshot.kind()), "snapshot");
        Instant createdAt = instant(root, "created_at", false);
        check(createdAt.equals(dbCreatedAt), "snapshot.created_at");
        var sources = new LinkedHashMap<String, JsonNode>();
        String previousSource = null;
        for (var source : array(root, "sources", false)) {
            String versionId = source(source, createdAt);
            check(previousSource == null || previousSource.compareTo(versionId) < 0, "sources.document_version_id");
            check(sources.putIfAbsent(versionId, source) == null, "sources.document_version_id");
            previousSource = versionId;
        }
        List<String> revisionIds = ids(root, "revision_ids", false, true);
        var notices = array(root, "notices", false);
        check(integer(root, "notice_count", 0, 1000) == notices.size() && revisionIds.size() == notices.size(), "notice_count");
        var events = new HashSet<String>();
        var revisions = new ArrayList<String>();
        var used = new HashSet<String>();
        String previousEvent = null;
        for (var notice : notices) {
            shape(notice, "notices", NOTICE_FIELDS);
            String eventId = uuid(notice, "event_id");
            check(events.add(eventId) && (previousEvent == null || previousEvent.compareTo(eventId) < 0), "notices.event_id");
            previousEvent = eventId;
            revisions.add(uuid(notice, "revision_id"));
            text(notice, "title", LIMIT);
            for (String category : ids(notice, "categories", true, false)) {
                check(Set.of("education", "support", "culture", "construction_traffic", "living").contains(category), "categories");
            }
            var sourceIds = ids(notice, "source_version_ids", true, true);
            check(sources.keySet().containsAll(sourceIds), "source_version_ids");
            used.addAll(sourceIds);
            var evidence = evidence(notice, sourceIds, sources);
            for (String field : FACTS.split(" ")) fieldValue(notice.path(field), evidence.keySet());
            var documentIds = new HashSet<String>();
            sourceIds.forEach(versionId -> documentIds.add(sources.get(versionId).path("document_id").textValue()));
            var linked = new HashSet<String>();
            for (var link : array(notice, "document_links", true)) {
                shape(link, "document_links", "document_id role evidence_ids");
                String documentId = uuid(link, "document_id");
                check(documentIds.contains(documentId) && linked.add(documentId), "document_links.document_id");
                choice(link, "role", "original", "correction", "cancellation", "repost");
                for (String evidenceId : evidenceIds(link, evidence.keySet(), true)) {
                    String versionId = evidence.get(evidenceId).path("document_version_id").textValue();
                    check(sources.get(versionId).path("document_id").textValue().equals(documentId), "document_links.evidence_ids");
                }
            }
            check(linked.equals(documentIds), "document_links");
            relations(notice, documentIds);
        }
        check(revisions.equals(revisionIds) && new HashSet<>(revisions).size() == revisions.size(), "revision_ids");
        check(used.equals(sources.keySet()), "sources");
    }

    private String source(JsonNode source, Instant createdAt) {
        shape(source, "sources", SOURCE_FIELDS + " checks");
        uuid(source, "document_id");
        String versionId = uuid(source, "document_version_id");
        text(source, "publisher", 255);
        text(source, "title", LIMIT);
        String url = text(source, "official_url", 8192);
        try {
            URI uri = URI.create(url);
            check(("http".equals(uri.getScheme()) || "https".equals(uri.getScheme())) && uri.getHost() != null && uri.getUserInfo() == null, "sources.official_url");
        } catch (IllegalArgumentException ex) { throw invalid("sources.official_url"); }
        nullableText(source, "official_number", 255);
        if (!source.path("published_date").isNull()) {
            String date = text(source, "published_date", 10);
            check(date.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}") && !date.startsWith("0000-"), "sources.published_date");
            try { LocalDate.parse(date); }
            catch (DateTimeException ex) { throw invalid("sources.published_date"); }
        }
        check(!instant(source, "collected_at", false).isAfter(createdAt), "sources.collected_at");
        String textHash = hash(source, "text_sha256");
        Instant latest = instant(source, "latest_check_attempt_at", true);
        Instant verified = instant(source, "last_verified_at", true);
        String result = choice(source, "check_result", "unchecked", "verified", "changed", "unreachable", "uncertain");
        Instant previous = null;
        Instant success = null;
        String lastResult = "unchecked";
        for (var item : array(source, "checks", false)) {
            shape(item, "sources.checks", "checked_at result text_sha256");
            Instant at = instant(item, "checked_at", false);
            check((previous == null || at.isAfter(previous)) && !at.isAfter(createdAt), "sources.checks.checked_at");
            lastResult = choice(item, "result", "verified", "changed", "unreachable", "uncertain");
            String checkedHash = hash(item, "text_sha256");
            if (lastResult.equals("verified")) {
                check(checkedHash.equals(textHash), "sources.checks.text_sha256");
                success = at;
            }
            previous = at;
        }
        check(success != null && Objects.equals(previous, latest) && Objects.equals(success, verified) && lastResult.equals(result), "sources.checks");
        return versionId;
    }

    private Map<String, JsonNode> evidence(JsonNode notice, List<String> sourceIds, Map<String, JsonNode> sources) {
        var evidence = new HashMap<String, JsonNode>();
        for (var item : array(notice, "evidence", true)) {
            shape(item, "evidence", "evidence_id document_version_id block_id quote start_char end_char text_sha256");
            String id = text(item, "evidence_id", 128);
            check(evidence.putIfAbsent(id, item) == null, "evidence.evidence_id");
            String sourceId = uuid(item, "document_version_id");
            check(sourceIds.contains(sourceId), "evidence.document_version_id");
            check(hash(item, "text_sha256").equals(sources.get(sourceId).path("text_sha256").textValue()), "evidence.text_sha256");
            text(item, "block_id", 128);
            long start = integer(item, "start_char", 0, Integer.MAX_VALUE);
            long end = integer(item, "end_char", 1, Integer.MAX_VALUE);
            String quote = text(item, "quote", LIMIT);
            // 원문 substring 대조는 발행 전 공통 원문 검증이 맡고, 공개본은 위치·길이·참조·hash를 보존한다.
            check(start < end && end - start == quote.codePointCount(0, quote.length()), "evidence.quote");
        }
        return evidence;
    }

    private void fieldValue(JsonNode field, Set<String> evidence) {
        shape(field, "field_value", "value knowledge evidence_ids reason");
        boolean known = choice(field, "knowledge", "known", "not_stated", "ambiguous", "not_applicable").equals("known");
        evidenceIds(field, evidence, known);
        String reason = nullableText(field, "reason", LIMIT);
        if (!known) check(field.path("value").isNull() && reason != null, "field_value.value");
        else if (field.path("value").isArray()) ids(field, "value", false, false);
        else text(field, "value", LIMIT);
    }

    private void relations(JsonNode notice, Set<String> documents) {
        Map<String, List<String>> corrections = new HashMap<>();
        for (var relation : array(notice, "relations", false)) {
            shape(relation, "relations", RELATION_FIELDS);
            String from = uuid(relation, "from_document_id");
            String to = uuid(relation, "to_document_id");
            check(!from.equals(to) && documents.contains(from) && documents.contains(to), "relations");
            String type = choice(relation, "type", "corrects", "cancels", "reposts", "duplicates");
            text(relation, "reason", LIMIT);
            instant(relation, "created_at", false);
            if (type.equals("corrects")) corrections.computeIfAbsent(from, ignored -> new ArrayList<>()).add(to);
        }
        var remaining = new HashSet<>(documents);
        while (!remaining.isEmpty()) {
            var leaves = new HashSet<String>();
            for (String id : remaining) if (corrections.getOrDefault(id, List.of()).stream().noneMatch(remaining::contains)) leaves.add(id);
            check(!leaves.isEmpty(), "relations");
            remaining.removeAll(leaves);
        }
    }

    private List<String> evidenceIds(JsonNode node, Set<String> allowed, boolean required) {
        var ids = ids(node, "evidence_ids", required, false);
        check(allowed.containsAll(ids), "evidence_ids");
        return ids;
    }

    private List<String> ids(JsonNode node, String key, boolean required, boolean uuid) {
        var result = new ArrayList<String>();
        var unique = new HashSet<String>();
        for (var item : array(node, key, required)) {
            String id = string(item, key, LIMIT);
            if (uuid) check(id.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), key);
            check(unique.add(id), key);
            result.add(id);
        }
        return result;
    }

    private JsonNode parse(String json) {
        try { return shared.parse(json); }
        catch (ImportException ex) { throw invalid(ex.field()); }
    }

    private void shape(JsonNode node, String path, String fields) {
        check(node != null && node.isObject(), path);
        var actual = new HashSet<String>();
        node.fieldNames().forEachRemaining(actual::add);
        check(actual.equals(Set.of(fields.split(" "))), path);
    }

    private JsonNode array(JsonNode node, String key, boolean required) {
        var value = node.path(key);
        check(value.isArray() && (!required || !value.isEmpty()), key);
        return value;
    }

    private String text(JsonNode node, String key, int max) { return string(node.path(key), key, max); }
    private String nullableText(JsonNode node, String key, int max) { return node.path(key).isNull() ? null : text(node, key, max); }
    private String string(JsonNode value, String key, int max) {
        check(value.isTextual() && value.textValue().length() <= max, key);
        String text = value.textValue();
        check(text.codePoints().anyMatch(c -> !Character.isWhitespace(c) && !Character.isSpaceChar(c) && c != 0x85), key);
        return text;
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
    private String choice(JsonNode node, String key, String... choices) {
        String value = text(node, key, 100);
        check(Arrays.asList(choices).contains(value), key);
        return value;
    }
    private long integer(JsonNode node, String key, long min, long max) {
        var value = node.path(key);
        check(value.isIntegralNumber() && value.canConvertToLong() && value.longValue() >= min && value.longValue() <= max, key);
        return value.longValue();
    }
    private Instant instant(JsonNode node, String key, boolean nullable) {
        if (nullable && node.path(key).isNull()) return null;
        String value = text(node, key, 32);
        check(value.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,6})?Z")
                && Integer.parseInt(value.substring(0, 4)) >= 1000, key);
        try {
            LocalDate.parse(value.substring(0, 10));
            LocalTime.parse(value.substring(11, value.length() - 1));
            return Instant.parse(value);
        } catch (DateTimeException ex) { throw invalid(key); }
    }
    private void check(boolean condition, String field) { shared.check(condition, field); }
    private PublicationException invalid(String field) {
        return new PublicationException("PUBLICATION_VALIDATION_ERROR", "시민 공개본 형식·근거·출처가 유효하지 않습니다.", field);
    }
}
