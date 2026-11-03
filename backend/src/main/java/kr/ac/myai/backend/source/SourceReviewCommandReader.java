package kr.ac.myai.backend.source;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.DateTimeException;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

@Component
public class SourceReviewCommandReader {
    static final int LIMIT = 8 * 1024 * 1024;
    private final ReviewedImportReader json;

    public record Request(String reviewId, String documentVersionId, long expectedReviewNo, String expectedTextSha256,
                          Check check, String useReview, String useNote, String reason, String inputJson, String inputSha256) { }
    public record Check(Instant checkedAt, String result, String textSha256, String note) { }

    public SourceReviewCommandReader(ReviewedImportReader json) { this.json = json; }

    public Request read(Path file) {
        try { return parse(json.readBounded(file, "file")); }
        catch (IOException | ImportException | IllegalArgumentException ex) { throw invalid("file"); }
    }

    public Request parse(byte[] bytes) {
        try {
            JsonNode input = json.parseJson(bytes);
            shape(input, "file", "schema_version review_id document_version_id expected_review_no expected_text_sha256 check use_review use_note reason");
            require(text(input, "schema_version", 100).equals("source-review-v1"), "schema_version");
            String reviewId = uuid(input, "review_id");
            String documentId = uuid(input, "document_version_id");
            long expected = integer(input, "expected_review_no", 0);
            String hash = hash(input, "expected_text_sha256");
            Check check = null;
            if (!input.path("check").isNull()) {
                JsonNode node = input.path("check");
                shape(node, "check", "checked_at result text_sha256 note");
                Instant at = instant(node, "checked_at", false);
                String result = choice(node, "result", "verified", "changed", "unreachable", "uncertain");
                String checkHash = hash(node, "text_sha256");
                String note = text(node, "note", LIMIT);
                require(note.getBytes(StandardCharsets.UTF_8).length <= 65535, "check.note");
                require(!result.equals("verified") || checkHash.equals(hash), "check.text_sha256");
                check = new Check(at, result, checkHash, note);
            }
            return new Request(reviewId, documentId, expected, hash, check,
                    choice(input, "use_review", "pending", "allowed", "restricted"), text(input, "use_note", LIMIT),
                    text(input, "reason", LIMIT), new String(bytes, StandardCharsets.UTF_8), ReviewedImportReader.sha256(bytes));
        } catch (ImportException | IllegalArgumentException ex) { throw invalid("file"); }
    }

    static void shape(JsonNode node, String field, String names) {
        require(node != null && node.isObject(), field);
        var actual = new HashSet<String>(); node.fieldNames().forEachRemaining(actual::add);
        require(actual.equals(Set.of(names.split(" "))), field);
    }

    static String text(JsonNode node, String key, int max) {
        JsonNode value = node.path(key);
        require(value.isTextual(), key);
        return string(value.textValue(), key, max);
    }

    static String string(String value, String field, int max) {
        require(value != null && value.length() <= max, field);
        require(value.codePoints().anyMatch(c -> !Character.isWhitespace(c) && !Character.isSpaceChar(c) && c != 0x85), field);
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (Character.isHighSurrogate(c)) require(++i < value.length() && Character.isLowSurrogate(value.charAt(i)), field);
            else require(!Character.isLowSurrogate(c), field);
        }
        return value;
    }

    static String uuid(JsonNode node, String key) {
        String value = text(node, key, 36);
        require(value.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), key);
        return value;
    }

    static String hash(JsonNode node, String key) {
        String value = text(node, key, 64);
        require(value.matches("[0-9a-f]{64}"), key);
        return value;
    }

    static String choice(JsonNode node, String key, String... choices) {
        String value = text(node, key, 100);
        require(Arrays.asList(choices).contains(value), key);
        return value;
    }

    static long integer(JsonNode node, String key, long min) {
        JsonNode value = node.path(key);
        require(value.isIntegralNumber() && value.canConvertToLong() && value.longValue() >= min, key);
        return value.longValue();
    }

    static Instant instant(JsonNode node, String key, boolean nullable) {
        if (nullable && node.path(key).isNull()) return null;
        String value = text(node, key, 32);
        require(value.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,6})?Z"), key);
        try {
            require(Integer.parseInt(value.substring(0, 4)) >= 1000, key);
            LocalDate.parse(value.substring(0, 10)); LocalTime.parse(value.substring(11, value.length() - 1));
            return Instant.parse(value);
        } catch (DateTimeException ex) { throw invalid(key); }
    }

    public static String actor(String actor) {
        string(actor, "actor", 128);
        require(actor.codePoints().noneMatch(Character::isISOControl), "actor");
        return actor;
    }

    static void require(boolean condition, String field) { if (!condition) throw invalid(field); }
    static SourceReviewException invalid(String field) { return new SourceReviewException("SOURCE_REVIEW_VALIDATION_ERROR", field); }
}
