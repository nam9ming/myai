package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.source.SourceReviewCommandReader;
import kr.ac.myai.backend.source.SourceReviewException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;

import static org.assertj.core.api.Assertions.*;

class SourceReviewCommandReaderTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final SourceReviewCommandReader reader = new SourceReviewCommandReader(new ReviewedImportReader());
    @TempDir Path root;

    @Test
    void preservesExactUtf8InputAndHash() throws Exception {
        String input = " \n" + request().toPrettyString() + "\n";
        byte[] bytes = input.getBytes(StandardCharsets.UTF_8);
        var result = reader.read(Files.write(root.resolve("request.json"), bytes));
        assertThat(result.inputJson()).isEqualTo(input);
        assertThat(result.inputSha256()).isEqualTo(ReviewedImportReader.sha256(bytes));
        assertThat(result.check().checkedAt()).isEqualTo(Instant.parse("2026-11-03T01:00:00.123456Z"));
        assertThat(result.useNote()).isEqualTo(" 사용권 😀\n보존 ");
    }

    @Test
    void acceptsRightsOnlyAndFullLongRangeWithoutCoercion() {
        var input = request();
        input.putNull("check").put("expected_review_no", Long.MAX_VALUE);
        assertThat(reader.parse(bytes(input)).check()).isNull();
        assertThat(reader.parse(bytes(input)).expectedReviewNo()).isEqualTo(Long.MAX_VALUE);
    }

    @Test
    void rejectsMissingExtraNullAndWrongScalars() {
        for (String key : List.of("schema_version", "review_id", "document_version_id", "expected_review_no", "expected_text_sha256", "check", "use_review", "use_note", "reason")) {
            var missing = request(); missing.remove(key); rejected(bytes(missing));
        }
        for (String key : List.of("schema_version", "review_id", "document_version_id", "expected_review_no", "expected_text_sha256", "use_review", "use_note", "reason")) {
            var nil = request(); nil.putNull(key); rejected(bytes(nil));
            var scalar = request(); scalar.put(key, true); rejected(bytes(scalar));
        }
        var extra = request(); extra.put("extra", 1); rejected(bytes(extra));
        for (String value : List.of("-1", "1.0", "\"0\"", "9223372036854775808", "true")) {
            rejected(request().toString().replace("\"expected_review_no\":0", "\"expected_review_no\":" + value).getBytes(StandardCharsets.UTF_8));
        }
        var check = request(); ((ObjectNode) check.path("check")).put("extra", 1); rejected(bytes(check));
        for (String key : List.of("checked_at", "result", "text_sha256", "note")) {
            var node = request(); ((ObjectNode) node.path("check")).remove(key); rejected(bytes(node));
            node = request(); ((ObjectNode) node.path("check")).putNull(key); rejected(bytes(node));
        }
        rejected("[]".getBytes(StandardCharsets.UTF_8));
    }

    @Test
    void rejectsDuplicateTrailingMalformedUtf8AndUnpairedUnicode() {
        String input = request().toString();
        rejected(input.replace("\"schema_version\":", "\"schema_version\":\"source-review-v1\",\"schema_version\":").getBytes(StandardCharsets.UTF_8));
        rejected((input + " {}").getBytes(StandardCharsets.UTF_8));
        rejected(new byte[] {(byte) 0xc3, (byte) 0x28});
        rejected(input.replace("합성 검토", "\\ud800").getBytes(StandardCharsets.UTF_8));
        rejected(input.replace("합성 검토", "\\udc00").getBytes(StandardCharsets.UTF_8));
    }

    @Test
    void rejectsBlankIdentifiersEnumsHashesAndInvalidPrecisionOrCalendar() {
        for (String blank : List.of("", " ", "\u00a0\u0085\u2003")) {
            var input = request(); input.put("reason", blank); rejected(bytes(input));
            input = request(); input.put("use_note", blank); rejected(bytes(input));
        }
        for (String key : List.of("review_id", "document_version_id", "expected_text_sha256", "use_review")) {
            var input = request(); input.put(key, "INVALID"); rejected(bytes(input));
        }
        for (String time : List.of("2026-11-03T01:00:00+00:00", "2026-11-03T01:00:00.1234567Z", "0999-11-03T01:00:00Z", "2026-02-30T01:00:00Z", "2026-11-03T24:00:00Z", "2026-11-03T01:00:60Z")) {
            var input = request(); ((ObjectNode) input.path("check")).put("checked_at", time); rejected(bytes(input));
        }
        var input = request(); ((ObjectNode) input.path("check")).put("result", "unchecked"); rejected(bytes(input));
        input = request(); ((ObjectNode) input.path("check")).put("text_sha256", "a".repeat(64)); rejected(bytes(input));
    }

    @Test
    void appliesByteBudgetsBeforeReadingAndForSqlTextNotes() throws Exception {
        var input = request(); ((ObjectNode) input.path("check")).put("note", "가".repeat(21845));
        assertThat(reader.parse(bytes(input)).check().note()).hasSize(21845);
        ((ObjectNode) input.path("check")).put("note", "가".repeat(21846)); rejected(bytes(input));
        Path oversized = root.resolve("large.json"); Files.write(oversized, new byte[8 * 1024 * 1024 + 1]);
        assertThatThrownBy(() -> reader.read(oversized)).isInstanceOf(SourceReviewException.class);
        rejected(new byte[0]); rejected(new byte[8 * 1024 * 1024 + 1]);
    }

    private void rejected(byte[] input) {
        assertThatThrownBy(() -> reader.parse(input)).isInstanceOfSatisfying(SourceReviewException.class,
                error -> assertThat(error.code()).isEqualTo("SOURCE_REVIEW_VALIDATION_ERROR"));
    }

    private byte[] bytes(ObjectNode input) { return input.toString().getBytes(StandardCharsets.UTF_8); }

    private ObjectNode request() {
        var input = mapper.createObjectNode().put("schema_version", "source-review-v1")
                .put("review_id", "10000000-0000-4000-8000-000000000020")
                .put("document_version_id", "10000000-0000-4000-8000-000000000002")
                .put("expected_review_no", 0).put("expected_text_sha256", "b".repeat(64))
                .put("use_review", "allowed").put("use_note", " 사용권 😀\n보존 ")
                .put("reason", "합성 검토");
        input.putObject("check").put("checked_at", "2026-11-03T01:00:00.123456Z").put("result", "verified")
                .put("text_sha256", "b".repeat(64)).put("note", "확인 😀\n메모");
        return input;
    }
}
