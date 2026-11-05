package kr.ac.myai.backend.source;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.PublicationRepository;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;

import static kr.ac.myai.backend.source.SourceReviewCommandReader.*;

@Component
public class SourceReviewState {
    private static final Set<String> OPERATING_FIELDS = Set.of("use_review", "use_note", "checks", "latest_check_attempt_at", "last_verified_at", "check_result");
    private final ReviewedImportReader json;
    private final SourceReviewCommandReader reader;
    private final ObjectMapper mapper = new ObjectMapper();

    public record Stored(String reviewId, String documentVersionId, long reviewNo, String inputSha256,
                         String recordJson, String recordSha256) { }

    public SourceReviewState(ReviewedImportReader json) { this.json = json; this.reader = new SourceReviewCommandReader(json); }

    public String documentSha(PublicationRepository.Document document) {
        var identity = mapper.createObjectNode().put("id", document.id()).put("version_id", document.versionId())
                .put("number", document.number()).put("text_hash", document.textHash()).put("private_ref", document.privateRef());
        identity.set("metadata", parse(document.metadata()));
        return sha(canonical(identity).toString());
    }

    public SourceView view(PublicationRepository.Document original, List<Stored> records) {
        try {
            metadata(original);
            var current = new SourceView(original);
            var ids = new HashSet<String>();
            String documentSha = documentSha(original);
            for (Stored stored : records) {
                require(stored != null && stored.recordJson() != null, "source_reviews");
                long length = size(stored.recordJson());
                require(length <= LIMIT - current.historyBytes(), "source_reviews");
                require(Objects.equals(stored.recordSha256(), sha(stored.recordJson())), "record_sha256");
                JsonNode record = parse(stored.recordJson());
                shape(record, "record_json", "record_version review_id document_version_id review_no document_sha256 previous_record_sha256 input_json input_sha256 actor recorded_at");
                require(text(record, "record_version", 100).equals("source-review-record-v1"), "record_version");
                String id = uuid(record, "review_id");
                require(ids.add(id) && id.equals(stored.reviewId()), "review_id");
                require(uuid(record, "document_version_id").equals(original.versionId()) && original.versionId().equals(stored.documentVersionId()), "document_version_id");
                long number = integer(record, "review_no", 1);
                require(current.reviewNo() < Long.MAX_VALUE && number == current.reviewNo() + 1 && number == stored.reviewNo(), "review_no");
                require(hash(record, "document_sha256").equals(documentSha), "document_sha256");
                String previous = record.path("previous_record_sha256").isNull() ? null : hash(record, "previous_record_sha256");
                require(Objects.equals(previous, current.reviewSha256()), "previous_record_sha256");
                String input = text(record, "input_json", LIMIT);
                Request request = reader.parse(input.getBytes(StandardCharsets.UTF_8));
                require(hash(record, "input_sha256").equals(request.inputSha256()) && request.inputSha256().equals(stored.inputSha256())
                        && request.reviewId().equals(id), "input_sha256");
                String actor = actor(text(record, "actor", 128));
                Instant recordedAt = instant(record, "recorded_at", false);
                ObjectNode effective = apply(current, request, actor, recordedAt);
                var recordedChecks = new HashMap<>(current.checkRecordedAt());
                if (request.check() != null) recordedChecks.put(id, recordedAt);
                current = new SourceView(original, effective.toString(), number, stored.recordSha256(), recordedChecks,
                        recordedAt, current.historyBytes() + length);
            }
            return current;
        } catch (ImportException | SourceReviewException | IllegalArgumentException ex) {
            throw conflict("source_reviews");
        }
    }

    public Stored append(SourceView current, Request request, String actor, Instant recordedAt) {
        actor(actor);
        ObjectNode effective = apply(current, request, actor, recordedAt);
        var record = mapper.createObjectNode().put("record_version", "source-review-record-v1")
                .put("review_id", request.reviewId()).put("document_version_id", current.original().versionId())
                .put("review_no", current.reviewNo() + 1).put("document_sha256", documentSha(current.original()));
        if (current.reviewSha256() == null) record.putNull("previous_record_sha256");
        else record.put("previous_record_sha256", current.reviewSha256());
        record.put("input_json", request.inputJson()).put("input_sha256", request.inputSha256())
                .put("actor", actor).put("recorded_at", recordedAt.toString());
        String value = record.toString();
        require(size(value) <= LIMIT - current.historyBytes(), "record_json");
        require(size(effective.toString()) <= LIMIT, "effective_metadata");
        return new Stored(request.reviewId(), current.original().versionId(), current.reviewNo() + 1,
                request.inputSha256(), value, sha(value));
    }

    private ObjectNode apply(SourceView current, Request request, String actor, Instant recordedAt) {
        require(current != null && request != null && request.inputJson() != null, "file");
        require(reader.parse(request.inputJson().getBytes(StandardCharsets.UTF_8)).equals(request), "input_json");
        actor(actor);
        require(recordedAt != null && recordedAt.getNano() % 1000 == 0, "recorded_at");
        instant(mapper.createObjectNode().put("recorded_at", recordedAt.toString()), "recorded_at", false);
        require(current.reviewNo() >= 0 && (current.reviewNo() == 0
                ? current.reviewSha256() == null && current.lastRecordedAt() == null && current.historyBytes() == 0 && current.checkRecordedAt().isEmpty()
                : current.reviewSha256() != null && current.reviewSha256().matches("[0-9a-f]{64}") && current.lastRecordedAt() != null && current.historyBytes() > 0), "source_reviews");
        if (current.lastRecordedAt() != null) require(!recordedAt.isBefore(current.lastRecordedAt()), "recorded_at");
        if (request.expectedReviewNo() != current.reviewNo() || current.reviewNo() == Long.MAX_VALUE) throw conflict("expected_review_no");
        if (!request.documentVersionId().equals(current.original().versionId())) throw conflict("document_version_id");
        if (!request.expectedTextSha256().equals(current.original().textHash())) throw conflict("expected_text_sha256");
        ObjectNode baseline = metadata(current.original());
        JsonNode parsed = parse(current.effectiveMetadata());
        require(parsed.isObject() && parsed.path("document").isObject(), "effective_metadata");
        ObjectNode effective = (ObjectNode) parsed;
        var originalDoc = (ObjectNode) baseline.path("document");
        var doc = (ObjectNode) effective.path("document");
        var originalFacts = baseline.deepCopy(); ((ObjectNode) originalFacts.path("document")).remove(OPERATING_FIELDS);
        var effectiveFacts = effective.deepCopy(); ((ObjectNode) effectiveFacts.path("document")).remove(OPERATING_FIELDS);
        require(originalFacts.equals(effectiveFacts), "effective_metadata");
        validateChecks(doc, current.original().textHash());
        ArrayNode checks = (ArrayNode) doc.path("checks");
        JsonNode originalChecks = originalDoc.path("checks");
        require(checks.size() >= originalChecks.size(), "checks");
        for (int i = 0; i < originalChecks.size(); i++) require(checks.get(i).equals(originalChecks.get(i)), "checks");
        var checkIds = new HashSet<String>();
        for (JsonNode check : checks) require(checkIds.add(check.path("check_id").textValue()), "checks.check_id");
        var operationalIds = new HashSet<String>();
        for (int i = originalChecks.size(); i < checks.size(); i++) operationalIds.add(checks.get(i).path("check_id").textValue());
        require(operationalIds.equals(current.checkRecordedAt().keySet()), "checks");
        if (current.reviewNo() == 0) require(baseline.equals(effective), "effective_metadata");
        Instant latest = instant(doc, "latest_check_attempt_at", true);
        require(latest == null || !latest.isAfter(recordedAt), "recorded_at");
        require(request.check() != null || !request.useReview().equals(doc.path("use_review").textValue())
                || !request.useNote().equals(doc.path("use_note").textValue()), "check");
        if (request.check() != null) {
            Check check = request.check();
            require(!checkIds.contains(request.reviewId()), "review_id");
            require((latest == null || check.checkedAt().isAfter(latest)) && !check.checkedAt().isAfter(recordedAt), "check.checked_at");
            checks.addObject().put("check_id", request.reviewId()).put("checked_at", check.checkedAt().toString())
                    .put("result", check.result()).put("reviewer_id", actor).put("text_sha256", check.textSha256()).put("note", check.note());
            doc.put("latest_check_attempt_at", check.checkedAt().toString()).put("check_result", check.result());
            if (check.result().equals("verified")) doc.put("last_verified_at", check.checkedAt().toString());
        }
        doc.put("use_review", request.useReview()).put("use_note", request.useNote());
        require(size(effective.toString()) <= LIMIT, "effective_metadata");
        return effective;
    }

    private ObjectNode metadata(PublicationRepository.Document original) {
        JsonNode input = parse(original.metadata());
        require(input.isObject() && input.path("document").isObject(), "document");
        JsonNode document = input.path("document");
        require(uuid(document, "document_id").equals(original.id()) && uuid(document, "document_version_id").equals(original.versionId()), "document_version_id");
        require(integer(document, "version_no", 1) == original.number() && hash(document, "text_sha256").equals(original.textHash()), "document");
        require(text(document, "raw_asset_path", 4096).equals(original.privateRef()), "raw_asset_path");
        validateChecks(document, original.textHash());
        return (ObjectNode) input;
    }

    private void validateChecks(JsonNode document, String textHash) {
        choice(document, "use_review", "pending", "allowed", "restricted");
        text(document, "use_note", LIMIT);
        JsonNode checks = document.path("checks");
        require(checks.isArray(), "checks");
        Instant previous = null;
        Instant success = null;
        String result = "unchecked";
        var ids = new HashSet<String>();
        for (JsonNode check : checks) {
            shape(check, "checks", "check_id checked_at result reviewer_id text_sha256 note");
            require(ids.add(uuid(check, "check_id")), "checks.check_id");
            Instant at = instant(check, "checked_at", false);
            require(previous == null || at.isAfter(previous), "checks.checked_at");
            result = choice(check, "result", "verified", "changed", "unreachable", "uncertain");
            text(check, "reviewer_id", 128);
            text(check, "note", LIMIT);
            String checkedHash = hash(check, "text_sha256");
            if (result.equals("verified")) { require(checkedHash.equals(textHash), "checks.text_sha256"); success = at; }
            previous = at;
        }
        require(Objects.equals(previous, instant(document, "latest_check_attempt_at", true))
                && Objects.equals(success, instant(document, "last_verified_at", true))
                && result.equals(choice(document, "check_result", "unchecked", "verified", "changed", "unreachable", "uncertain")), "checks");
    }

    private JsonNode parse(String value) {
        string(value, "file", LIMIT);
        try { return json.parseJson(value.getBytes(StandardCharsets.UTF_8)); }
        catch (ImportException | IllegalArgumentException ex) { throw invalid("file"); }
    }

    private JsonNode canonical(JsonNode value) {
        if (value.isObject()) {
            ObjectNode result = mapper.createObjectNode();
            var sorted = new TreeMap<String, JsonNode>(); value.properties().forEach(entry -> sorted.put(entry.getKey(), entry.getValue()));
            sorted.forEach((key, child) -> result.set(key, canonical(child)));
            return result;
        }
        if (value.isArray()) { ArrayNode result = mapper.createArrayNode(); value.forEach(child -> result.add(canonical(child))); return result; }
        if (value.isNumber()) return mapper.getNodeFactory().numberNode(value.decimalValue().stripTrailingZeros());
        return value;
    }

    private static long size(String value) { return value.getBytes(StandardCharsets.UTF_8).length; }
    private static String sha(String value) { return ReviewedImportReader.sha256(value.getBytes(StandardCharsets.UTF_8)); }
    private static SourceReviewException conflict(String field) { return new SourceReviewException("SOURCE_REVIEW_CONFLICT", field); }
}
