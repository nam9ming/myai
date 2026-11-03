package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.PublicationRepository;
import kr.ac.myai.backend.source.SourceReviewCommandReader;
import kr.ac.myai.backend.source.SourceReviewException;
import kr.ac.myai.backend.source.SourceReviewState;
import kr.ac.myai.backend.source.SourceView;
import org.junit.jupiter.api.Test;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.*;

class SourceReviewStateTest {
    private final ObjectMapper mapper = new ObjectMapper();
    private final ReviewedImportReader json = new ReviewedImportReader();
    private final SourceReviewCommandReader reader = new SourceReviewCommandReader(json);
    private final SourceReviewState state = new SourceReviewState(json);
    private final Instant recorded = Instant.parse("2026-11-04T01:00:00.123456Z");
    private static final String DOC = "10000000-0000-4000-8000-000000000001";
    private static final String VERSION = "10000000-0000-4000-8000-000000000002";
    private static final String LEGACY = "10000000-0000-4000-8000-000000000003";

    @Test
    void appendsWithoutChangingOriginalAndKeepsAllChecksAfterFailedAttempt() throws Exception {
        var original = document(true);
        var first = state.append(state.view(original, List.of()), request(20, 0, "verified", "2026-11-03T01:00:00Z", "allowed", "사용"), "operator", recorded);
        var view = state.view(original, List.of(first));
        var second = state.append(view, request(21, 1, "unreachable", "2026-11-04T00:00:00Z", "restricted", "중단"), "operator2", recorded.plusSeconds(1));
        var full = state.view(original, List.of(first, second));
        var effective = mapper.readTree(full.effectiveMetadata()).path("document");
        assertThat(full.original()).isEqualTo(original);
        assertThat(mapper.readTree(original.metadata()).path("document").path("checks")).hasSize(1);
        assertThat(effective.path("checks")).hasSize(3);
        assertThat(effective.path("checks").get(0).path("check_id").asText()).isEqualTo(LEGACY);
        assertThat(effective.path("checks").get(1).path("check_id").asText()).isEqualTo(first.reviewId());
        assertThat(effective.path("checks").get(2).path("reviewer_id").asText()).isEqualTo("operator2");
        assertThat(effective.path("last_verified_at").asText()).isEqualTo("2026-11-03T01:00:00Z");
        assertThat(effective.path("latest_check_attempt_at").asText()).isEqualTo("2026-11-04T00:00:00Z");
        assertThat(effective.path("check_result").asText()).isEqualTo("unreachable");
        assertThat(effective.path("use_review").asText()).isEqualTo("restricted");
        assertThat(full.reviewNo()).isEqualTo(2);
        assertThat(full.reviewSha256()).isEqualTo(second.recordSha256());
        assertThatThrownBy(() -> full.checkRecordedAt().put("x", recorded)).isInstanceOf(UnsupportedOperationException.class);
    }

    @Test
    void rightsOnlyDoesNotInventCheckOrSuccessAndRejectsNoOp() throws Exception {
        var original = document(false);
        var baseline = state.view(original, List.of());
        assertThat(baseline.effectiveMetadata()).isEqualTo(original.metadata());
        assertThat(baseline.reviewNo()).isZero(); assertThat(baseline.reviewSha256()).isNull();
        var stored = state.append(baseline, request(20, 0, null, null, "restricted", "수집 중단"), "operator", recorded);
        var effective = mapper.readTree(state.view(original, List.of(stored)).effectiveMetadata()).path("document");
        assertThat(effective.path("checks")).isEmpty();
        assertThat(effective.path("last_verified_at").isNull()).isTrue();
        assertThat(effective.path("latest_check_attempt_at").isNull()).isTrue();
        assertThat(effective.path("check_result").asText()).isEqualTo("unchecked");
        rejected(() -> state.append(baseline, request(20, 0, null, null, "pending", "원래 메모"), "operator", recorded));
    }

    @Test
    void bindsExactRequestAndAllOriginalDocumentFieldsInTenKeyRecord() throws Exception {
        var original = document(false);
        var request = request(20, 0, "verified", "2026-11-03T01:00:00Z", "allowed", "사용");
        var stored = state.append(new SourceView(original), request, "operator", recorded);
        var record = mapper.readTree(stored.recordJson());
        assertThat(record.fieldNames()).toIterable().containsExactlyInAnyOrder("record_version", "review_id", "document_version_id", "review_no", "document_sha256", "previous_record_sha256", "input_json", "input_sha256", "actor", "recorded_at");
        assertThat(record.path("input_json").asText()).isEqualTo(request.inputJson());
        assertThat(record.path("input_sha256").asText()).isEqualTo(request.inputSha256());
        assertThat(record.path("recorded_at").asText()).isEqualTo(recorded.toString());
        assertThat(record.path("previous_record_sha256").isNull()).isTrue();
        assertThat(stored.recordSha256()).isEqualTo(ReviewedImportReader.sha256(stored.recordJson().getBytes(StandardCharsets.UTF_8)));
        for (var changed : List.of(new PublicationRepository.Document("10000000-0000-4000-8000-000000000099", VERSION, 1, original.textHash(), original.metadata(), original.privateRef()),
                new PublicationRepository.Document(DOC, "10000000-0000-4000-8000-000000000099", 1, original.textHash(), original.metadata(), original.privateRef()),
                new PublicationRepository.Document(DOC, VERSION, 2, original.textHash(), original.metadata(), original.privateRef()),
                new PublicationRepository.Document(DOC, VERSION, 1, "c".repeat(64), original.metadata(), original.privateRef()),
                new PublicationRepository.Document(DOC, VERSION, 1, original.textHash(), original.metadata().replace("원래 제목", "다른 제목"), original.privateRef()),
                new PublicationRepository.Document(DOC, VERSION, 1, original.textHash(), original.metadata(), "other.txt"))) {
            assertThat(state.documentSha(changed)).isNotEqualTo(state.documentSha(original));
            rejected(() -> state.view(changed, List.of(stored)));
        }
        var pretty = new PublicationRepository.Document(DOC, VERSION, 1, original.textHash(), mapper.readTree(original.metadata()).toPrettyString(), original.privateRef());
        assertThat(state.documentSha(pretty)).isEqualTo(state.documentSha(original));
    }

    @Test
    void enforcesExplicitCompareAndSwapAndCheckOrdering() {
        var baseline = state.view(document(true), List.of());
        rejected(() -> state.append(baseline, request(20, 1, null, null, "restricted", "메모"), "operator", recorded));
        rejected(() -> state.append(baseline, request(20, Long.MAX_VALUE, null, null, "restricted", "메모"), "operator", recorded));
        for (String time : List.of("2026-11-02T01:00:00Z", "2026-11-02T00:00:00Z", "2026-11-04T02:00:00Z")) {
            rejected(() -> state.append(baseline, request(20, 0, "verified", time, "allowed", "메모"), "operator", recorded));
        }
        var wrongId = requestJson(20, 0, null, null, "restricted", "메모"); wrongId.put("document_version_id", DOC);
        rejected(() -> state.append(baseline, parse(wrongId), "operator", recorded));
        var wrongHash = requestJson(20, 0, null, null, "restricted", "메모"); wrongHash.put("expected_text_sha256", "c".repeat(64));
        rejected(() -> state.append(baseline, parse(wrongHash), "operator", recorded));
        for (String actor : List.of("", "\u00a0\u0085", "operator\n", "x".repeat(129))) {
            rejected(() -> state.append(baseline, request(20, 0, null, null, "restricted", "메모"), actor, recorded));
        }
        rejected(() -> state.append(baseline, request(20, 0, null, null, "restricted", "메모"), "operator", recorded.plusNanos(1)));
        rejected(() -> state.append(baseline, request(20, 0, null, null, "restricted", "메모"), "operator", Instant.parse("0999-01-01T00:00:00Z")));
    }

    @Test
    void replayUsesEachOwnPrefixAndRecordedCutoff() {
        var original = document(true);
        var first = state.append(new SourceView(original), request(20, 0, "verified", "2026-11-03T01:00:00Z", "allowed", "사용"), "operator", recorded);
        var second = state.append(state.view(original, List.of(first)), request(21, 1, "changed", "2026-11-03T02:00:00Z", "allowed", "사용"), "operator", recorded.plusSeconds(1));
        var view = state.view(original, List.of(first, second));
        assertThat(view.checkVisible(LEGACY, recorded.minusSeconds(100))).isTrue();
        assertThat(view.checkVisible(first.reviewId(), recorded.minusNanos(1))).isFalse();
        assertThat(view.checkVisible(first.reviewId(), recorded)).isTrue();
        assertThat(view.checkVisible(second.reviewId(), recorded)).isFalse();
        assertThat(view.checkVisible(second.reviewId(), recorded.plusSeconds(1))).isTrue();
        rejected(() -> state.append(view, request(22, 2, null, null, "restricted", "메모"), "operator", recorded));
    }

    @Test
    void rejectsMissingReorderedDuplicateRowsAndTamperedRecordFields() throws Exception {
        var original = document(false);
        var first = state.append(new SourceView(original), request(20, 0, "verified", "2026-11-03T01:00:00Z", "allowed", "사용"), "operator", recorded);
        var second = state.append(state.view(original, List.of(first)), request(21, 1, null, null, "restricted", "중단"), "operator", recorded.plusSeconds(1));
        for (var rows : List.of(List.of(second), List.of(second, first), List.of(first, first))) rejected(() -> state.view(original, rows));
        var changedRow = new SourceReviewState.Stored(first.reviewId(), first.documentVersionId(), 2, first.inputSha256(), first.recordJson(), first.recordSha256());
        rejected(() -> state.view(original, List.of(changedRow)));
        var badSha = new SourceReviewState.Stored(first.reviewId(), first.documentVersionId(), 1, first.inputSha256(), first.recordJson(), "f".repeat(64));
        rejected(() -> state.view(original, List.of(badSha)));
        for (String key : List.of("review_id", "document_version_id", "document_sha256", "input_sha256", "actor", "recorded_at", "record_version")) {
            var changed = (ObjectNode) mapper.readTree(first.recordJson()); changed.put(key, key.equals("actor") ? "invalid\nactor" : "invalid");
            rejected(() -> state.view(original, List.of(rehash(first, changed))));
        }
        var changed = (ObjectNode) mapper.readTree(second.recordJson()); changed.put("previous_record_sha256", "f".repeat(64));
        var brokenParent = rehash(second, changed); rejected(() -> state.view(original, List.of(first, brokenParent)));
        changed = (ObjectNode) mapper.readTree(first.recordJson()); changed.put("input_json", first.recordJson());
        var brokenInput = rehash(first, changed); rejected(() -> state.view(original, List.of(brokenInput)));
        changed = (ObjectNode) mapper.readTree(first.recordJson()); changed.put("extra", true);
        var extra = rehash(first, changed); rejected(() -> state.view(original, List.of(extra)));
        changed = (ObjectNode) mapper.readTree(first.recordJson()); changed.put("recorded_at", "2026-11-03T00:00:00Z");
        var futureCheck = rehash(first, changed); rejected(() -> state.view(original, List.of(futureCheck)));
    }

    @Test
    void refusesEscapedRecordCumulativeAndEffectiveMetadataOversizeWithoutTruncation() throws Exception {
        var original = document(false);
        var largeInput = requestJson(20, 0, null, null, "restricted", "메모"); largeInput.put("reason", "\\".repeat(2_200_000));
        var validLarge = parse(largeInput);
        rejected(() -> state.append(new SourceView(original), validLarge, "operator", recorded));
        var rows = new ArrayList<SourceReviewState.Stored>();
        for (int i = 0; i < 3; i++) {
            var input = requestJson(20 + i, i, null, null, "restricted", "메모" + i); input.put("reason", "x".repeat(2_000_000));
            rows.add(state.append(state.view(original, rows), parse(input), "operator", recorded.plusSeconds(i)));
        }
        var over = requestJson(23, 3, null, null, "allowed", "다음"); over.put("reason", "x".repeat(2_500_000));
        rejected(() -> state.append(state.view(original, rows), parse(over), "operator", recorded.plusSeconds(3)));
        assertThat(state.view(original, rows).reviewNo()).isEqualTo(3);
        var largeDoc = (ObjectNode) mapper.readTree(original.metadata()); largeDoc.put("preserved", "x".repeat(8 * 1024 * 1024 - original.metadata().length() - 30));
        var largeOriginal = new PublicationRepository.Document(DOC, VERSION, 1, original.textHash(), largeDoc.toString(), original.privateRef());
        var rights = requestJson(20, 0, null, null, "allowed", "y".repeat(200));
        rejected(() -> state.append(new SourceView(largeOriginal), parse(rights), "operator", recorded));
        assertThat(rows).hasSize(3);
    }

    @Test
    void rejectsForgedViewsAndPreservesTheOriginalCheckPrefix() throws Exception {
        var original = document(true);
        var first = state.append(new SourceView(original), request(20, 0, "verified", "2026-11-03T01:00:00Z", "allowed", "사용"), "operator", recorded);
        var full = state.view(original, List.of(first));
        var manuallyBuilt = new SourceView(original, full.effectiveMetadata(), full.reviewNo(), full.reviewSha256(), full.checkRecordedAt());
        rejected(() -> state.append(manuallyBuilt, request(21, 1, null, null, "restricted", "중단"), "operator", recorded.plusSeconds(1)));
        var forged = (ObjectNode) mapper.readTree(original.metadata());
        ((ObjectNode) forged.path("document").path("checks").get(0)).put("note", "변조");
        var changedPrefix = new SourceView(original, forged.toString(), 0, null, Map.of());
        rejected(() -> state.append(changedPrefix, request(20, 0, null, null, "restricted", "중단"), "operator", recorded));
        var changedFacts = new SourceView(original, original.metadata().replace("원래 제목", "변경 제목"), 0, null, Map.of());
        rejected(() -> state.append(changedFacts, request(20, 0, null, null, "restricted", "중단"), "operator", recorded));
        var scalar = new SourceView(original, "[]", 0, null, Map.of());
        rejected(() -> state.append(scalar, request(20, 0, null, null, "restricted", "중단"), "operator", recorded));
    }

    @Test
    void rejectsUnpairedJavaUnicodeInStoredStringsAndMalformedRowFields() throws Exception {
        var original = document(false);
        var first = state.append(new SourceView(original), request(20, 0, null, null, "restricted", "사용"), "operator", recorded);
        var rawRecord = first.recordJson().replace("operator", "operator" + (char) 0xd800);
        var rawBad = new SourceReviewState.Stored(first.reviewId(), first.documentVersionId(), first.reviewNo(), first.inputSha256(), rawRecord, ReviewedImportReader.sha256(rawRecord.getBytes(StandardCharsets.UTF_8)));
        assertThatThrownBy(() -> state.view(original, List.of(rawBad))).isInstanceOfSatisfying(SourceReviewException.class,
                error -> assertThat(error.code()).isEqualTo("SOURCE_REVIEW_CONFLICT"));
        for (var row : List.of(new SourceReviewState.Stored("invalid", first.documentVersionId(), 1, first.inputSha256(), first.recordJson(), first.recordSha256()),
                new SourceReviewState.Stored(first.reviewId(), "invalid", 1, first.inputSha256(), first.recordJson(), first.recordSha256()),
                new SourceReviewState.Stored(first.reviewId(), first.documentVersionId(), 1, "invalid", first.recordJson(), first.recordSha256()))) {
            assertThatThrownBy(() -> state.view(original, List.of(row))).isInstanceOfSatisfying(SourceReviewException.class,
                    error -> assertThat(error.code()).isEqualTo("SOURCE_REVIEW_CONFLICT"));
        }
    }

    private SourceReviewState.Stored rehash(SourceReviewState.Stored source, ObjectNode record) {
        String value = record.toString();
        return new SourceReviewState.Stored(source.reviewId(), source.documentVersionId(), source.reviewNo(), source.inputSha256(), value, ReviewedImportReader.sha256(value.getBytes(StandardCharsets.UTF_8)));
    }

    private void rejected(Runnable operation) { assertThatThrownBy(operation::run).isInstanceOf(SourceReviewException.class); }
    private SourceReviewCommandReader.Request request(int id, long no, String result, String at, String rights, String note) { return parse(requestJson(id, no, result, at, rights, note)); }
    private SourceReviewCommandReader.Request parse(ObjectNode input) { return reader.parse(input.toString().getBytes(StandardCharsets.UTF_8)); }
    private ObjectNode requestJson(int id, long no, String result, String at, String rights, String note) {
        var input = mapper.createObjectNode().put("schema_version", "source-review-v1").put("review_id", String.format("10000000-0000-4000-8000-%012d", id))
                .put("document_version_id", VERSION).put("expected_review_no", no).put("expected_text_sha256", "b".repeat(64))
                .put("use_review", rights).put("use_note", note).put("reason", "합성 검토");
        if (result == null) input.putNull("check");
        else input.putObject("check").put("checked_at", at).put("result", result).put("text_sha256", "b".repeat(64)).put("note", "확인");
        return input;
    }
    private PublicationRepository.Document document(boolean checked) {
        var metadata = mapper.createObjectNode().put("data_kind", "synthetic");
        var doc = metadata.putObject("document").put("document_id", DOC).put("document_version_id", VERSION).put("version_no", 1)
                .put("title", "원래 제목").put("text_sha256", "b".repeat(64)).put("raw_asset_path", "synthetic.txt")
                .put("use_review", "pending").put("use_note", "원래 메모");
        var checks = doc.putArray("checks");
        if (checked) {
            checks.addObject().put("check_id", LEGACY).put("checked_at", "2026-11-02T01:00:00Z").put("result", "verified")
                    .put("reviewer_id", "legacy\nreviewer").put("text_sha256", "b".repeat(64)).put("note", "기존\n메모");
            doc.put("latest_check_attempt_at", "2026-11-02T01:00:00Z").put("last_verified_at", "2026-11-02T01:00:00Z").put("check_result", "verified");
        } else doc.putNull("latest_check_attempt_at").putNull("last_verified_at").put("check_result", "unchecked");
        return new PublicationRepository.Document(DOC, VERSION, 1, "b".repeat(64), metadata.toString(), "synthetic.txt");
    }
}
