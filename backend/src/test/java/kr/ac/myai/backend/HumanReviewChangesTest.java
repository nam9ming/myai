package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.HumanReviewChanges;
import kr.ac.myai.backend.importing.ImportException;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.*;

class HumanReviewChangesTest {
    final ObjectMapper mapper = new ObjectMapper();

    ObjectNode payload() {
        var value = mapper.createObjectNode();
        value.putObject("event").put("area_membership", "uncertain");
        value.putObject("revision").put("title", "AI 초안").put("reviewer_id", "reviewer")
                .put("reviewed_at", "2026-11-02T02:00:00Z").putArray("human_overrides");
        return value;
    }

    ObjectNode record(ObjectNode next, String path, Object before, Object after) {
        var change = next.withObject("revision").withArray("human_overrides").addObject()
                .put("field_path", path).put("reviewer", "reviewer").put("time", "2026-11-02T02:00:00Z");
        change.set("before", mapper.valueToTree(before)); change.set("after", mapper.valueToTree(after));
        return change;
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
