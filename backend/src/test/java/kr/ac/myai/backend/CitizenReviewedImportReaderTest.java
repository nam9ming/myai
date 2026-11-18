package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;

import static org.assertj.core.api.Assertions.*;

class CitizenReviewedImportReaderTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final ReviewedImportReader reader = new ReviewedImportReader();
    ObjectNode input;

    @BeforeEach
    void fixture() throws Exception {
        input = (ObjectNode) mapper.readTree(Path.of("examples/citizen-reviewed-import.json").toFile());
        Files.copy(Path.of("examples/citizen-source.txt"), root.resolve("citizen-source.txt"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"education", "support", "culture", "construction_traffic", "living"})
    void storesEveryCitizenCategoryWithoutLegacyAreaOrRules(String category) throws Exception {
        revision().putArray("categories").add(category);
        var batch = reader.read(bytes(), root);
        JsonNode payload = mapper.readTree(batch.events().getFirst().payloadJson());
        assertThat(batch.schemaVersion()).isEqualTo("citizen-reviewed-import-v1");
        assertThat(payload.path("schema_version").asText()).isEqualTo("citizen-revision-v1");
        assertThat(payload.path("revision").path("categories")).isEqualTo(mapper.readTree("[\"" + category + "\"]"));
        assertThat(payload.path("revision").path("title").asText()).isEqualTo("합성 시민 공지 😀");
        assertThat(payload.path("event").has("area_id")).isFalse();
        assertThat(payload.path("event").has("area_membership")).isFalse();
        assertThat(payload.path("revision").has("rules_version")).isFalse();
        assertThat(payload.path("revision").has("dictionary_version")).isFalse();
    }

    @Test
    void preservesDistinctApplicationScheduleRegionPlaceAndResidencyFacts() throws Exception {
        known("regions", "안성시 일부 지역");
        known("residency_requirement", "안성시에 거주하는 시민");
        var saved = payload().path("revision");
        assertThat(saved.path("application_period").path("value").asText()).isEqualTo("2026-11-20~2026-11-25");
        assertThat(saved.path("occurrences").path("value").asText()).isEqualTo("2026-12-01~2026-12-02");
        assertThat(saved.path("regions").path("value").asText()).isEqualTo("안성시 일부 지역");
        assertThat(saved.path("locations").path("value").asText()).isEqualTo("가상시민센터");
        assertThat(saved.path("residency_requirement").path("value").asText()).isEqualTo("안성시에 거주하는 시민");
        assertThat(saved.path("target").path("value").asText()).isEqualTo("시민");
        assertThat(saved.path("eligibility").path("value").isNull()).isTrue();
        assertThat(saved.path("recruitment").path("knowledge").asText()).isEqualTo("not_stated");
    }

    @Test
    void preservesUnknownCostSeparatelyFromExplicitFreeText() throws Exception {
        var unknown = payload().path("revision").path("cost");
        assertThat(unknown.path("value").isNull()).isTrue();
        assertThat(unknown.path("knowledge").asText()).isEqualTo("not_stated");
        replaceBody(document().path("block_index").get(1).path("text").asText() + " 별도 합성 무료 프로그램: 참가비 무료.");
        known("cost", "참가비 무료");
        var free = payload().path("revision").path("cost");
        assertThat(free.path("value").asText()).isEqualTo("참가비 무료");
        assertThat(free.path("knowledge").asText()).isEqualTo("known");
        assertThat(free.path("evidence_ids")).isEqualTo(mapper.readTree("[\"body-quote\"]"));
        assertThat(free.has("amount")).isFalse();
    }

    @Test
    void acceptsSeveralCategoriesAndLiteralStringListsWithoutNormalizingFacts() throws Exception {
        revision().putArray("categories").add("education").add("support");
        known("application_method", "신청 전 원문 확인").putArray("value").add("전화 문의").add("방문 접수");
        known("occurrences", "일정은 추후 공지");
        var saved = payload().path("revision");
        assertThat(saved.path("categories")).isEqualTo(mapper.readTree("[\"education\",\"support\"]"));
        assertThat(saved.path("application_method").path("value")).isEqualTo(mapper.readTree("[\"전화 문의\",\"방문 접수\"]"));
        assertThat(saved.path("occurrences").path("value").asText()).isEqualTo("일정은 추후 공지");
    }

    @Test
    void hashesOriginalRequestBytesAndKeepsFileAndStoredValidationEquivalent() throws Exception {
        byte[] content = (" \n" + input.toPrettyString() + "\n ").getBytes(StandardCharsets.UTF_8);
        var batch = reader.read(content, root);
        assertThat(batch.inputSha256()).isEqualTo(sha(content));
        assertThat(reader.read(Files.write(root.resolve("batch.json"), content), root)).isEqualTo(batch);
        assertThat(reader.validateStored(input, root).events()).isEqualTo(batch.events());
        assertThat(mapper.readTree(batch.events().getFirst().payloadJson()).path("revision")).isEqualTo(revision());
    }

    @ParameterizedTest
    @CsvSource({"empty,categories", "duplicate,categories", "legacy,events.revision.categories",
            "unknown,events.revision.categories", "number,categories"})
    void rejectsMissingDuplicateOrUnsupportedCategories(String change, String field) throws Exception {
        var categories = revision().putArray("categories");
        switch (change) {
            case "duplicate" -> categories.add("education").add("education");
            case "legacy" -> categories.add("traffic");
            case "unknown" -> categories.add("health");
            case "number" -> categories.add(1);
        }
        rejected(field);
    }

    @Test
    void knownEmptyStringListPreservesItsExplicitKnowledgeAndEvidence() throws Exception {
        known("preparation", "별도 준비 없음").putArray("value");
        var saved = payload().path("revision").path("preparation");
        assertThat(saved.path("value").isArray()).isTrue();
        assertThat(saved.path("value").isEmpty()).isTrue();
        assertThat(saved.path("knowledge").asText()).isEqualTo("known");
        assertThat(saved.path("evidence_ids")).isEqualTo(mapper.readTree("[\"body-quote\"]"));
    }

    @ParameterizedTest
    @CsvSource({"envelope,$", "area,events", "membership,events", "rules,events.revision", "dictionary,events.revision",
            "field,field_value", "handoff,human_handoffs", "revision_schema,events.revision"})
    void rejectsExtraKeysInsteadOfSilentlyTakingLegacyValues(String change, String field) throws Exception {
        switch (change) {
            case "envelope" -> input.put("unexpected", true);
            case "area" -> event().put("area_id", "20000000-0000-4000-8000-000000000010");
            case "membership" -> event().put("area_membership", "verified");
            case "rules" -> revision().put("rules_version", "synthetic-rules");
            case "dictionary" -> revision().put("dictionary_version", "synthetic-dictionary");
            case "field" -> ((ObjectNode) revision().path("cost")).put("amount", 0);
            case "handoff" -> input.putArray("human_handoffs");
            case "revision_schema" -> revision().put("schema_version", "citizen-revision-v1");
        }
        rejected(field);
    }

    @ParameterizedTest
    @ValueSource(strings = {"application_period", "occurrences", "regions", "locations", "residency_requirement", "target",
            "eligibility", "application_method", "preparation", "cost", "recruitment", "lifecycle"})
    void requiresEvidenceForEveryKnownCitizenFact(String name) throws Exception {
        known(name, "합성 원문 표현").putArray("evidence_ids");
        rejected("evidence_ids");
    }

    @ParameterizedTest
    @ValueSource(strings = {"not_stated", "ambiguous", "not_applicable"})
    void unknownFactRequiresNullAndReason(String knowledge) throws Exception {
        var cost = (ObjectNode) revision().path("cost");
        cost.put("knowledge", knowledge).put("value", "무료");
        rejected("field_value.value");
        cost.putNull("value").putNull("reason");
        rejected("field_value.value");
        cost.put("reason", "원문에 비용 없음");
        assertThat(payload().path("revision").path("cost").path("knowledge").asText()).isEqualTo(knowledge);
    }

    @ParameterizedTest
    @ValueSource(strings = {"ai_reviewed", "ai_draft"})
    void citizenInputAndStoredPayloadCannotClaimAiOrigin(String origin) throws Exception {
        revision().put("origin", origin);
        revision().putArray("originating_run_ids").add("20000000-0000-4000-8000-000000000020");
        rejected("origin");
        rejectedStored("origin");
    }

    @Test
    void humanCitizenRevisionCannotBorrowAiRunIds() throws Exception {
        revision().putArray("originating_run_ids").add("20000000-0000-4000-8000-000000000020");
        rejected("events.revision.originating_run_ids");
    }

    @Test
    void ordinaryCitizenProofCannotStoreAnEmptyBatchButTrustedHandoffCan() throws Exception {
        String run = "20000000-0000-4000-8000-000000000020";
        citizenProof(run);
        input.putArray("events");
        assertThatThrownBy(() -> reader.read(bytes(), root)).isInstanceOfSatisfying(ImportException.class,
                ex -> assertThat(ex.field()).isEqualTo("events"));
        assertThat(reader.prepareHandoff(input, root, sha(bytes()), run).events()).isEmpty();
    }

    @Test
    void citizenPayloadExcludesEvidenceUnrelatedToItsLinksAndFacts() throws Exception {
        var expected = input.path("evidence").deepCopy();
        var unrelated = ((ObjectNode) input.path("evidence").get(1)).deepCopy().put("evidence_id", "unrelated-quote");
        input.withArray("evidence").add(unrelated);
        assertThat(payload().path("evidence")).isEqualTo(expected);
        assertThat(input.path("evidence")).hasSize(3);
    }

    @Test
    void preparesCitizenHandoffWithExplicitRunAndPreservesStoredProof() throws Exception {
        String run = "20000000-0000-4000-8000-000000000020";
        citizenProof(run);
        var batch = reader.prepareHandoff(input, root, sha(bytes()), run);
        assertThat(batch.schemaVersion()).isEqualTo("citizen-human-handoff-import-v1");
        assertThat(batch.originatingRunId()).isEqualTo(run);
        assertThat(batch.handoffJson()).isEqualTo(input.path("human_handoffs").toString());
        var saved = mapper.readTree(batch.events().getFirst().payloadJson());
        assertThat(saved.path("schema_version").asText()).isEqualTo("citizen-revision-v1");
        assertThat(saved.path("revision")).isEqualTo(revision());
        assertThat(saved.path("event").has("area_id")).isFalse();
        assertThat(saved.path("human_handoffs")).isEqualTo(input.path("human_handoffs"));
        assertThat(reader.validateStored(input, root).events()).isEqualTo(batch.events());
        revision().put("review_status", "approved").put("publication_intent", "public");
        assertThat(reader.validateStored(input, root).events().getFirst().originatingRunIds()).containsExactly(run);
    }

    @Test
    void citizenProofCannotLaunderHumanOriginOrUnresolvedTitle() throws Exception {
        String run = "20000000-0000-4000-8000-000000000020";
        citizenProof(run);
        revision().putNull("title");
        assertThatThrownBy(() -> reader.prepareHandoff(input, root, sha(bytes()), run)).isInstanceOf(ImportException.class);
        revision().put("title", "합성 시민 공지 😀").put("origin", "human").putArray("originating_run_ids");
        assertThatThrownBy(() -> reader.prepareHandoff(input, root, sha(bytes()), run)).isInstanceOf(ImportException.class);
        assertThatThrownBy(() -> reader.validateStored(input, root)).isInstanceOf(ImportException.class);
    }

    @Test
    void citizenHandoffRejectsDifferentRunAndDraftOrPublicWorkflow() throws Exception {
        String run = "20000000-0000-4000-8000-000000000020";
        citizenProof(run);
        assertThatThrownBy(() -> reader.prepareHandoff(input, root, sha(bytes()),
                "20000000-0000-4000-8000-000000000021")).isInstanceOf(ImportException.class);
        revision().put("review_status", "draft");
        assertThatThrownBy(() -> reader.prepareHandoff(input, root, sha(bytes()), run)).isInstanceOf(ImportException.class);
        revision().put("review_status", "approved").put("publication_intent", "public");
        assertThatThrownBy(() -> reader.prepareHandoff(input, root, sha(bytes()), run)).isInstanceOf(ImportException.class);
    }

    private void citizenProof(String run) {
        revision().put("origin", "ai_reviewed").put("review_status", "needs_review").put("publication_intent", "hidden");
        revision().putArray("originating_run_ids").add(run);
        input.putArray("human_handoffs").addObject().put("directory", root.resolve("a".repeat(64)).toString())
                .put("handoff_ref", "a".repeat(64)).put("receipt_sha256", "b".repeat(64));
    }

    @ParameterizedTest
    @CsvSource({"approved,public", "rejected,hidden"})
    void importCannotForgeStoredDecisionsButStoredValidationCanReadThem(String status, String intent) throws Exception {
        revision().put("review_status", status).put("publication_intent", intent);
        rejected("review_status");
        var saved = reader.validateStored(input, root).events().getFirst();
        assertThat(saved.reviewStatus()).isEqualTo(status);
        assertThat(saved.publicationIntent()).isEqualTo(intent);
    }

    @Test
    void publicIntentRequiresApprovalAndReviewer() throws Exception {
        revision().put("publication_intent", "public");
        rejected("publication_intent");
        rejectedStored("events.revision.publication_intent");
        revision().put("review_status", "approved").putNull("reviewer_id").putNull("reviewed_at");
        rejectedStored("events.revision.reviewer_id");
    }

    @Test
    void checksExpectedRevisionBeforeCreatingPayload() throws Exception {
        event().put("expected_revision_no", 1);
        rejected("events.revision.revision_no");
        revision().put("revision_no", 2);
        var saved = reader.read(bytes(), root).events().getFirst();
        assertThat(saved.expectedRevisionNo()).isEqualTo(1);
        assertThat(saved.revisionNo()).isEqualTo(2);
    }

    @Test
    void firstRevisionRejectsFabricatedHistoryButLaterRevisionPreservesRemovedCitations() throws Exception {
        var history = revision().putArray("human_overrides").addObject().put("field_path", "title")
                .put("before", "이전 합성 제목").put("after", "합성 시민 공지 😀").put("reason", "원문 재대조")
                .put("reviewer", "synthetic-reviewer").put("time", "2026-11-02T02:00:00Z");
        history.putArray("evidence_ids").add("removed-evidence");
        rejected("events.revision.human_overrides");
        event().put("expected_revision_no", 1);
        revision().put("revision_no", 2);
        assertThat(payload().path("revision").path("human_overrides").get(0)).isEqualTo(history);
    }

    @Test
    void verifiesSourceBytesAndUnicodeCodePointQuotes() throws Exception {
        assertThat(payload().path("evidence").get(0).path("quote").asText()).isEqualTo("합성 시민 공지 😀");
        ((ObjectNode) input.path("evidence").get(0)).put("end_char", 9);
        rejected("evidence.quote");
        ((ObjectNode) input.path("evidence").get(0)).put("end_char", 10);
        Files.writeString(root.resolve("citizen-source.txt"), "변조된 합성 원문");
        rejected("documents.raw_sha256");
        rejectedStored("documents.raw_sha256");
    }

    @Test
    void rejectsEvidenceOutsideSelectedSources() throws Exception {
        var other = document().deepCopy().put("document_version_id", "20000000-0000-4000-8000-000000000030").put("version_no", 2);
        other.putArray("checks").addObject().put("check_id", "20000000-0000-4000-8000-000000000031")
                .put("checked_at", "2026-11-02T02:00:00Z").put("result", "verified").put("reviewer_id", "synthetic-reviewer")
                .put("text_sha256", other.path("text_sha256").asText()).put("note", "두 번째 합성 버전");
        input.withArray("documents").add(other);
        ((ObjectNode) input.path("evidence").get(1)).put("document_version_id", "20000000-0000-4000-8000-000000000030");
        rejected("evidence_ids");
    }

    @Test
    void rejectsUnregisteredSourceVersionAndMismatchedDocumentLinks() throws Exception {
        revision().putArray("source_version_ids").add("20000000-0000-4000-8000-000000000030");
        rejected("events.revision.source_version_ids");
        revision().putArray("source_version_ids").add("20000000-0000-4000-8000-000000000002");
        ((ObjectNode) event().path("document_links").get(0)).put("document_id", "20000000-0000-4000-8000-000000000030");
        rejected("events.document_links.document_id");
    }

    @Test
    void retainsRelationAndDuplicateValidationForCitizenEvents() throws Exception {
        event().putArray("relations").addObject().put("from_document_id", "20000000-0000-4000-8000-000000000001")
                .put("to_document_id", "20000000-0000-4000-8000-000000000001").put("type", "corrects")
                .put("reviewed_by", "synthetic-reviewer").put("reason", "자기 자신으로 관계 생성 금지")
                .put("created_at", "2026-11-02T02:00:00Z");
        rejected("events.relations");
        event().putArray("relations");
        event().putArray("suspected_duplicate_ids").add("20000000-0000-4000-8000-000000000004");
        rejected("events.suspected_duplicate_ids");
        event().putArray("suspected_duplicate_ids");
        input.withArray("events").add(event().deepCopy());
        rejected("events.event_id");
    }

    @Test
    void legacyPayloadKeepsExistingShapeAndBytes() throws Exception {
        var legacy = (ObjectNode) mapper.readTree(Path.of("examples/reviewed-import.json").toFile());
        Files.copy(Path.of("examples/synthetic-source.txt"), root.resolve("synthetic-source.txt"));
        var saved = reader.read(legacy.toString().getBytes(StandardCharsets.UTF_8), root).events().getFirst();
        JsonNode payload = mapper.readTree(saved.payloadJson());
        assertThat(saved.payloadSha256()).isEqualTo("abc9cbe8c76f0327d9d4bccee001924d9ae9612e0353d0cae4985aa26be43c7a");
        assertThat(payload.has("schema_version")).isFalse();
        assertThat(payload.path("event").path("area_id").asText()).isEqualTo(legacy.path("events").get(0).path("area_id").asText());
        assertThat(payload.path("revision")).isEqualTo(legacy.path("events").get(0).path("revision"));
        assertThat(reader.validateStored(legacy, root).events().getFirst().payloadJson()).isEqualTo(saved.payloadJson());
    }

    private JsonNode payload() throws Exception {
        return mapper.readTree(reader.read(bytes(), root).events().getFirst().payloadJson());
    }

    private ObjectNode known(String name, String value) {
        var field = (ObjectNode) revision().path(name);
        field.put("value", value).put("knowledge", "known").putNull("reason").putArray("evidence_ids").add("body-quote");
        return field;
    }

    private void replaceBody(String body) throws Exception {
        String cleaned = "합성 시민 공지 😀\n" + body + "\n";
        byte[] raw = cleaned.getBytes(StandardCharsets.UTF_8);
        Files.write(root.resolve("citizen-source.txt"), raw);
        String hash = sha(raw);
        document().put("cleaned_text", cleaned).put("raw_sha256", hash).put("text_sha256", hash);
        ((ObjectNode) document().path("block_index").get(1)).put("text", body);
        ((ObjectNode) document().path("checks").get(0)).put("text_sha256", hash);
        for (JsonNode evidence : input.path("evidence")) ((ObjectNode) evidence).put("text_sha256", hash);
        ((ObjectNode) input.path("evidence").get(1)).put("quote", body).put("end_char", body.codePointCount(0, body.length()));
    }

    private byte[] bytes() { return input.toString().getBytes(StandardCharsets.UTF_8); }
    private ObjectNode event() { return (ObjectNode) input.path("events").get(0); }
    private ObjectNode revision() { return (ObjectNode) event().path("revision"); }
    private ObjectNode document() { return (ObjectNode) input.path("documents").get(0); }

    private String sha(byte[] content) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content));
    }

    private void rejected(String field) throws Exception {
        byte[] content = bytes();
        Path file = Files.write(root.resolve("batch.json"), content);
        assertThatThrownBy(() -> reader.read(content, root)).isInstanceOfSatisfying(ImportException.class,
                error -> assertThat(error.field()).isEqualTo(field));
        assertThatThrownBy(() -> reader.read(file, root)).isInstanceOfSatisfying(ImportException.class,
                error -> assertThat(error.field()).isEqualTo(field));
    }

    private void rejectedStored(String field) {
        assertThatThrownBy(() -> reader.validateStored(input, root)).isInstanceOfSatisfying(ImportException.class,
                error -> assertThat(error.field()).isEqualTo(field));
    }
}
