package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.HumanReviewChanges;
import kr.ac.myai.backend.importing.ImportException;
import org.junit.jupiter.api.Test;

import java.time.Instant;

import static org.assertj.core.api.Assertions.*;

class HumanReviewChangesTest {
    final ObjectMapper mapper = new ObjectMapper();

    ObjectNode payload() {
        var value = mapper.createObjectNode();
        value.putObject("event").put("area_membership", "uncertain");
        value.putObject("revision").put("title", "AI 초안").put("reviewer_id", "reviewer")
                .put("reviewed_at", "2026-11-02T02:00:00Z").putArray("human_overrides");
        value.putArray("evidence").addObject().put("evidence_id", "e1").put("quote", "합성 근거");
        return value;
    }

    ObjectNode record(ObjectNode next, String path, Object before, Object after) {
        var change = next.withObject("revision").withArray("human_overrides").addObject()
                .put("field_path", path).put("reviewer", "reviewer").put("time", "2026-11-02T02:00:00Z");
        change.set("before", mapper.valueToTree(before)); change.set("after", mapper.valueToTree(after));
        change.put("reason", "합성 수정").putArray("evidence_ids").add("e1");
        return change;
    }

    @Test
    void recordsActualCoarseDiffAndOperatorWhilePreservingHistoryAndEvidenceUnion() {
        var before = payload();
        before.withObject("revision").putArray("types").add("event");
        record(before, "title", "이전 제목", "AI 초안");
        var after = before.deepCopy();
        after.withObject("revision").put("title", "인계 제목").putArray("types").add("traffic");
        after.withObject("event").put("area_membership", "verified");
        after.putArray("evidence").addObject().put("evidence_id", "e2").put("quote", "새 근거");
        record(after, "output.items[0].title", "복사 금지", "추출 변경");
        HumanReviewChanges.record(before, after, "handoff-operator", Instant.parse("2026-11-03T01:02:03.123456789Z"), "인계 저장");
        var revision = after.path("revision");
        var changes = revision.path("human_overrides");
        assertThat(revision.path("reviewer_id").asText()).isEqualTo("handoff-operator");
        assertThat(revision.path("reviewed_at").asText()).isEqualTo("2026-11-03T01:02:03.123456Z");
        assertThat(changes).hasSize(5);
        assertThat(changes.get(0)).isEqualTo(before.path("revision").path("human_overrides").get(0));
        assertThat(changes.findValuesAsText("field_path")).containsExactly("title", "title", "types", "event", "evidence");
        assertThat(changes.get(2).path("before")).isEqualTo(before.path("revision").path("types"));
        assertThat(changes.get(2).path("after")).isEqualTo(after.path("revision").path("types"));
        for (int index = 1; index < changes.size(); index++) {
            var change = changes.get(index);
            assertThat(change.path("reason").asText()).isEqualTo("인계 저장");
            assertThat(change.path("reviewer").asText()).isEqualTo("handoff-operator");
            assertThat(change.path("time").asText()).isEqualTo("2026-11-03T01:02:03.123456Z");
            assertThat(change.path("evidence_ids")).isEqualTo(mapper.valueToTree(java.util.List.of("e1", "e2")));
        }
        assertThatCode(() -> HumanReviewChanges.validate(before, after, true)).doesNotThrowAnyException();
    }

    @Test
    void onlyGeneratedHandoffMayAppendEvidenceFreeAuditAndNewEventsHaveNoFakeDiff() {
        var before = payload(); before.putArray("evidence");
        var after = before.deepCopy(); after.withObject("revision").put("title", "근거 미상");
        HumanReviewChanges.record(before, after, "operator", Instant.parse("2026-11-03T01:02:03Z"), "인계 저장");
        assertThat(after.path("revision").path("human_overrides").get(0).path("evidence_ids")).isEmpty();
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        assertThatCode(() -> HumanReviewChanges.validate(before, after, true)).doesNotThrowAnyException();
        var carried = after.deepCopy(); carried.withObject("revision").put("reviewer_id", "next-reviewer");
        assertThatCode(() -> HumanReviewChanges.validate(after, carried)).doesNotThrowAnyException();
        HumanReviewChanges.record(null, carried, "operator", Instant.parse("2026-11-03T01:02:03Z"), "새 사건");
        assertThat(carried.path("revision").path("human_overrides")).isEmpty();
    }

    @Test
    void malformedAndNanosecondNewAuditTimesProduceImportConflict() {
        var before = payload(); var after = payload(); after.withObject("revision").put("title", "사람 수정");
        var change = record(after, "title", "AI 초안", "사람 수정");
        change.put("time", "invalid");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        after.withObject("revision").put("reviewed_at", "2026-11-02T02:00:00.123456789Z");
        change.put("time", "2026-11-02T02:00:00.123456789Z");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
    }

    @Test
    void historicalAuditPrefixCannotBeDroppedReorderedOrRewritten() {
        var before = payload();
        record(before, "title", "이전 제목", "AI 초안");
        record(before, "types", java.util.List.of("event"), java.util.List.of("traffic"));
        var dropped = before.deepCopy();
        dropped.withObject("revision").withArray("human_overrides").remove(0);
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, dropped)).isInstanceOf(ImportException.class);
        var after = before.deepCopy();
        var changes = after.withObject("revision").withArray("human_overrides");
        var first = changes.get(0); changes.set(0, changes.get(1)); changes.set(1, first);
        var reordered = after;
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, reordered)).isInstanceOf(ImportException.class);
        changes.set(0, before.path("revision").path("human_overrides").get(0));
        ((ObjectNode) changes.get(1)).put("reviewer", "forged-reviewer");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, reordered)).isInstanceOf(ImportException.class);
    }

    @Test
    void newCitationsMustComeFromActualPreviousOrNextEvidence() {
        var before = payload(); var after = before.deepCopy();
        after.withObject("revision").put("title", "사람 수정");
        var change = record(after, "title", "AI 초안", "사람 수정");
        change.putArray("evidence_ids").add("invented");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        change.putArray("evidence_ids");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        change.putArray("evidence_ids").add("e1");
        assertThatCode(() -> HumanReviewChanges.validate(before, after)).doesNotThrowAnyException();
    }

    @Test
    void changedTitleNeedsMatchingValuesReviewerAndTime() {
        var before = payload(); var after = payload(); after.withObject("revision").put("title", "사람 수정");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        var change = record(after, "title", "틀린 이전값", "사람 수정");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        change.put("before", "AI 초안").put("after", "다른 수정값");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        change.put("after", "사람 수정").put("reviewer", "다른 검토자");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        change.put("reviewer", "reviewer").put("time", "2026-11-02T03:00:00Z");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        change.put("time", "2026-11-02T02:00:00Z");
        assertThatCode(() -> HumanReviewChanges.validate(before, after)).doesNotThrowAnyException();
    }

    @Test
    void oneRecordCannotHideAnotherChangedMeaningField() {
        var before = payload(); var after = payload();
        before.withObject("revision").putArray("types").add("event");
        after.withObject("revision").put("title", "사람 수정").putArray("types").add("traffic");
        record(after, "title", "AI 초안", "사람 수정");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        record(after, "types", before.path("revision").path("types"), after.path("revision").path("types"));
        assertThatCode(() -> HumanReviewChanges.validate(before, after)).doesNotThrowAnyException();
    }

    @Test
    void wholeFieldValueRecordCoversKnowledgeValueAndEvidenceChanges() throws Exception {
        var before = payload(); var after = payload();
        before.withObject("revision").set("applicability", mapper.readTree("{\"value\":null,\"knowledge\":\"not_stated\",\"evidence_ids\":[],\"reason\":\"미기재\"}"));
        after.withObject("revision").set("applicability", mapper.readTree("{\"value\":\"차량\",\"knowledge\":\"known\",\"evidence_ids\":[\"e1\"],\"reason\":null}"));
        record(after, "applicability.value", null, "차량");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        record(after, "applicability", before.path("revision").path("applicability"), after.path("revision").path("applicability"));
        assertThatCode(() -> HumanReviewChanges.validate(before, after)).doesNotThrowAnyException();
    }

    @Test
    void arraysNeedTheirWholeBeforeAndAfterWhileLeafValuesRemainSupported() throws Exception {
        var before = payload(); var after = payload();
        before.withObject("revision").set("locations", mapper.readTree("[{\"geometry\":null}]"));
        after.withObject("revision").set("locations", mapper.readTree("[{\"geometry\":{\"type\":\"Point\",\"coordinates\":[127,37]}}]"));
        record(after, "locations[0].geometry", null, after.path("revision").path("locations").get(0).path("geometry"));
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        after.withObject("revision").putArray("human_overrides");
        record(after, "locations", before.path("revision").path("locations"), after.path("revision").path("locations"));
        assertThatCode(() -> HumanReviewChanges.validate(before, after)).doesNotThrowAnyException();
    }

    @Test
    void evidenceTextChangesNeedTheirOwnArrayRecordEvenWhenIdsStayTheSame() {
        var before = payload();
        before.putArray("evidence").addObject().put("evidence_id", "e1").put("quote", "이전 인용");
        var after = before.deepCopy();
        ((ObjectNode) after.path("evidence").get(0)).put("quote", "수정 인용");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        record(after, "evidence", before.path("evidence"), after.path("evidence"));
        assertThatCode(() -> HumanReviewChanges.validate(before, after)).doesNotThrowAnyException();
    }

    @Test
    void regionChangesNeedAnEventFieldRecord() {
        var before = payload(); var after = payload(); after.withObject("event").put("area_membership", "verified");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        record(after, "event.area_membership", "uncertain", "verified");
        assertThatCode(() -> HumanReviewChanges.validate(before, after)).doesNotThrowAnyException();
    }

    @Test
    void falseNewAuditEntriesAreRejectedEvenWhenTheFactDidNotChange() {
        var before = payload(); var after = payload();
        var change = record(after, "title", "가짜 이전값", "가짜 수정값");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        change.put("before", "AI 초안").put("after", "AI 초안");
        assertThatThrownBy(() -> HumanReviewChanges.validate(before, after)).isInstanceOf(ImportException.class);
        after.withObject("revision").put("title", "사람 수정");
        change.put("after", "사람 수정");
        assertThatCode(() -> HumanReviewChanges.validate(before, after)).doesNotThrowAnyException();
    }

    @Test
    void previouslyStoredAuditEntriesCanBeCarriedWithoutRewritingTheirActor() {
        var before = payload(); record(before, "title", "이전 제목", "AI 초안");
        var after = before.deepCopy(); after.withObject("revision").put("reviewer_id", "next-reviewer");
        assertThatCode(() -> HumanReviewChanges.validate(before, after)).doesNotThrowAnyException();
    }

    @Test
    void workflowMetadataAloneDoesNotRequireAFactOverride() {
        var before = payload(); var after = payload();
        after.withObject("revision").put("review_status", "needs_review").put("origin", "ai_reviewed")
                .put("revision_id", "new-id").put("revision_no", 2).put("reviewer_id", "another-reviewer");
        assertThatCode(() -> HumanReviewChanges.validate(before, after)).doesNotThrowAnyException();
    }
}
