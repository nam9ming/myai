package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.*;

class ReviewedImportReaderTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final ReviewedImportReader reader = new ReviewedImportReader();
    ObjectNode input;

    @BeforeEach
    void fixture() throws Exception {
        input = (ObjectNode) mapper.readTree(Path.of("examples/reviewed-import.json").toFile());
        Files.copy(Path.of("examples/synthetic-source.txt"), root.resolve("synthetic-source.txt"));
    }

    @Test
    void preparesPrivateHandoffWithExplicitRunHashAndEmptyEventList() throws Exception {
        handoff();
        var batch = reader.prepareHandoff(input, root, "c".repeat(64), "71fb66f0-e610-4f9c-8f26-4bb77655ee8c");
        assertThat(batch.schemaVersion()).isEqualTo("human-handoff-import-v1");
        assertThat(batch.inputSha256()).isEqualTo("c".repeat(64));
        assertThat(batch.originatingRunId()).isEqualTo("71fb66f0-e610-4f9c-8f26-4bb77655ee8c");
        assertThat(batch.draftJson()).isNull();
        assertThat(mapper.readTree(batch.handoffJson())).isEqualTo(input.path("human_handoffs"));
        input.putArray("events"); input.putArray("evidence");
        assertThat(reader.prepareHandoff(input, root, "c".repeat(64), "71fb66f0-e610-4f9c-8f26-4bb77655ee8c").events()).isEmpty();
        input.put("schema_version", "human-handoff-import-v1");
        rejected();
    }

    @Test
    void preservesHandoffPartialFactsAndProofButApprovalRemainsStrict() throws Exception {
        handoff();
        var revision = (ObjectNode) input.path("events").get(0).path("revision");
        revision.putNull("title").putArray("types");
        var directions = (ObjectNode) revision.path("directions");
        directions.put("knowledge", "known").putNull("reason");
        directions.putArray("value").add("상행").add("상행");
        directions.putArray("evidence_ids").add("body-quote");
        var occurrence = (ObjectNode) revision.path("occurrences").get(0);
        occurrence.putNull("date_start").putNull("date_end").put("time_start", "12:00").put("time_end", "10:00")
                .put("end_day_offset", 0).put("precision", "unknown").put("knowledge", "ambiguous");
        var saved = mapper.readTree(reader.read(write(), root).events().getFirst().payloadJson());
        assertThat(saved.path("human_handoffs")).isEqualTo(input.path("human_handoffs"));
        assertThat(saved.path("revision")).isEqualTo(revision);
        revision.put("review_status", "approved");
        assertThatThrownBy(() -> reader.validateStored(input, root)).isInstanceOf(ImportException.class);
        revision.put("title", "합성 제목"); revision.putArray("types").add("traffic");
        assertThatThrownBy(() -> reader.validateStored(input, root)).isInstanceOf(ImportException.class);
        directions.putArray("value").add("상행");
        assertThatThrownBy(() -> reader.validateStored(input, root)).isInstanceOf(ImportException.class);
    }

    @Test
    void handoffCanPreserveEvidenceFreeUnknownEventsAndHistoricalCitations() throws Exception {
        handoff();
        var revision = (ObjectNode) input.path("events").get(0).path("revision");
        revision.putNull("title").putArray("types");
        var occurrence = (ObjectNode) revision.path("occurrences").get(0);
        occurrence.putNull("date_start").putNull("date_end").putNull("time_start").putNull("time_end")
                .putNull("end_day_offset").put("precision", "unknown").put("knowledge", "not_stated");
        occurrence.putArray("evidence_ids");
        var location = (ObjectNode) revision.path("locations").get(0);
        location.put("status", "unknown").put("coverage", "unknown").putNull("geometry")
                .putNull("source").putNull("checked_by").putNull("checked_at").putArray("evidence_ids");
        for (var field : java.util.List.of(location.withObject("name"), revision.withObject("applicability"))) {
            field.putNull("value").put("knowledge", "not_stated").put("reason", "미상").putArray("evidence_ids");
        }
        ((ObjectNode) input.path("events").get(0).path("document_links").get(0)).putArray("evidence_ids");
        input.putArray("evidence");
        var history = revision.withArray("human_overrides").addObject().put("field_path", "evidence")
                .put("reason", "과거 인용 보존").put("reviewer", "past-reviewer").put("time", "2026-11-02T01:00:00Z");
        history.putArray("before"); history.putArray("after"); history.putArray("evidence_ids").add("removed-evidence");
        assertThat(reader.read(write(), root).events()).hasSize(1);
        history.putArray("evidence_ids");
        assertThat(reader.read(write(), root).events()).hasSize(1);
        input.putArray("events");
        var empty = reader.read(write(), root);
        assertThat(empty.events()).isEmpty();
        assertThat(empty.handoffJson()).isEqualTo(input.path("human_handoffs").toString());
        input.remove("human_handoffs");
        rejected();
    }

    @Test
    void rejectsMalformedProofAndKeepsD06TimestampPrecision() throws Exception {
        handoff();
        ((ObjectNode) input.path("events").get(0).path("revision")).put("reviewed_at", "2026-11-02T02:00:00.123456789Z");
        rejected();
        ((ObjectNode) input.path("events").get(0).path("revision")).put("reviewed_at", "2026-11-02T02:00:00.123456Z");
        assertThat(reader.read(write(), root).events()).hasSize(1);
        ((ObjectNode) input.path("human_handoffs").get(0)).put("unexpected", true);
        rejected();
        handoff(); input.putArray("human_handoffs"); rejected();
        handoff(); input.putNull("human_handoffs"); rejected();
        handoff(); input.put("schema_version", "source-import-v1"); rejected();
    }

    private void handoff() {
        input.putArray("human_handoffs").addObject().put("directory", root.resolve("a".repeat(64)).toString())
                .put("handoff_ref", "a".repeat(64)).put("receipt_sha256", "b".repeat(64));
        var revision = (ObjectNode) input.path("events").get(0).path("revision");
        revision.put("origin", "ai_reviewed").putArray("originating_run_ids").add("71fb66f0-e610-4f9c-8f26-4bb77655ee8c");
    }

    @Test
    void rejectsHumanHandoffProjectionBeforeRevisionImport() throws Exception {
        assertThat(reader.read(write(), root).events()).hasSize(1);
        input.put("schema_version", "human-handoff-projection-v1");
        assertThatThrownBy(() -> reader.read(write(), root)).isInstanceOfSatisfying(ImportException.class, error -> {
            assertThat(error.code()).isEqualTo("IMPORT_VALIDATION_ERROR");
            assertThat(error.field()).isEqualTo("schema_version");
        });
    }

    @Test
    void rejectsCalendarYearZeroButAcceptsTheFirstSupportedYear() throws Exception {
        var occurrence = (ObjectNode) input.path("events").get(0).path("revision").path("occurrences").get(0);
        occurrence.put("date_start", "0000-01-01").put("date_end", "0000-01-01");
        rejected();
        occurrence.put("date_start", "0001-01-01").put("date_end", "0001-01-01");
        assertThat(reader.read(write(), root).events()).hasSize(1);
    }

    @Test
    void rejectsPythonWhitespaceOnlyValuesWithoutTrimmingRealText() throws Exception {
        int[] whitespace = {9, 10, 11, 12, 13, 28, 29, 30, 31, 32, 133, 160, 5760, 8192, 8193, 8194,
                8195, 8196, 8197, 8198, 8199, 8200, 8201, 8202, 8232, 8233, 8239, 8287, 12288};
        var revision = (ObjectNode) input.path("events").get(0).path("revision");
        for (int point : whitespace) {
            revision.put("title", new String(Character.toChars(point)));
            rejected();
        }
        String title = Character.toString(160) + "원문 제목" + Character.toString(8239);
        revision.put("title", title);
        var saved = mapper.readTree(reader.read(write(), root).events().getFirst().payloadJson());
        assertThat(saved.path("revision").path("title").asText()).isEqualTo(title);
    }

    @Test
    void rawDraftPreservesDuplicateTextValuesButReviewedAndReferenceIdsStayUnique() throws Exception {
        rawDraft();
        var revision = (ObjectNode) input.path("events").get(0).path("revision");
        for (String name : java.util.List.of("exceptions", "route_names", "stop_names", "directions")) {
            var field = (ObjectNode) revision.path(name);
            field.put("knowledge", "known").putNull("reason");
            field.putArray("value").add("상행").add("상행");
            field.putArray("evidence_ids").add("body-quote");
        }
        assertThat(reader.read(write(), root).events()).hasSize(1);
        ((ObjectNode) revision.path("directions")).putArray("evidence_ids").add("body-quote").add("body-quote");
        rejected();
        ((ObjectNode) revision.path("directions")).putArray("evidence_ids").add("body-quote");
        input.put("schema_version", "reviewed-import-v1"); input.remove("originating_run_id");
        revision.put("origin", "ai_reviewed").put("title", "합성 제목"); revision.putArray("types").add("traffic");
        rejected();
    }

    @Test
    void acceptsHiddenAiDraftWithUnknownTitleAndTypesOnlyInItsSchema() throws Exception {
        rawDraft();
        var batch = reader.read(write(), root);
        var revision = mapper.readTree(batch.events().getFirst().payloadJson()).path("revision");
        assertThat(revision.path("title").isNull()).isTrue();
        assertThat(revision.path("types").isEmpty()).isTrue();
        assertThat(batch.events().getFirst().reviewStatus()).isEqualTo("draft");
        assertThat(batch.events().getFirst().reviewerId()).isNull();
        input.put("schema_version", "reviewed-import-v1"); rejected();
    }

    @Test
    void rawDraftRejectsHumanClaimsGeometryAndStatePromotion() throws Exception {
        for (String change : java.util.List.of("status", "intent", "reviewer", "geometry", "area", "origin")) {
            fixtureReset(); rawDraft();
            var event = (ObjectNode) input.path("events").get(0);
            var revision = (ObjectNode) event.path("revision");
            switch (change) {
                case "status" -> revision.put("review_status", "needs_review");
                case "intent" -> revision.put("publication_intent", "public");
                case "reviewer" -> revision.put("reviewer_id", "forged").put("reviewed_at", "2026-11-02T02:00:00Z");
                case "geometry" -> ((ObjectNode) revision.path("locations").get(0)).set("geometry",
                        mapper.readTree("{\"type\":\"Point\",\"coordinates\":[127,37]}"));
                case "area" -> event.put("area_membership", "verified");
                case "origin" -> revision.put("origin", "ai_reviewed");
            }
            rejected();
        }
    }

    @Test
    void rawNoEventFoundKeepsDocumentOnlyAndCannotBecomeReviewedBatch() throws Exception {
        input.put("schema_version", "ai-draft-import-v1");
        input.putArray("events"); input.putArray("evidence");
        rejected();
        input.put("originating_run_id", "71fb66f0-e610-4f9c-8f26-4bb77655ee8c");
        assertThat(reader.read(write(), root).events()).isEmpty();
        input.put("schema_version", "reviewed-import-v1"); rejected();
    }

    @Test
    void storedRawAiDraftCannotClaimApproval() throws Exception {
        rawDraft();
        var revision = (ObjectNode) input.path("events").get(0).path("revision");
        revision.put("title", "합성 제목"); revision.putArray("types").add("construction");
        revision.put("review_status", "approved").put("publication_intent", "public")
                .put("reviewer_id", "forged").put("reviewed_at", "2026-11-02T02:00:00Z");
        assertThatThrownBy(() -> reader.validateStored(input, root)).isInstanceOf(ImportException.class);
    }

    @Test
    void rawUnknownPreservesContradictoryPartialClocksForHumanReview() throws Exception {
        rawDraft();
        var occurrence = (ObjectNode) input.path("events").get(0).path("revision").path("occurrences").get(0);
        occurrence.putNull("date_start").putNull("date_end").put("time_start", "12:00").put("time_end", "10:00")
                .put("end_day_offset", 0).put("precision", "unknown").put("knowledge", "ambiguous");
        assertThat(reader.read(write(), root).events()).hasSize(1);
    }

    private void rawDraft() {
        input.put("schema_version", "ai-draft-import-v1");
        input.put("originating_run_id", "71fb66f0-e610-4f9c-8f26-4bb77655ee8c");
        var event = (ObjectNode) input.path("events").get(0);
        event.put("area_membership", "uncertain");
        var revision = (ObjectNode) event.path("revision");
        revision.put("origin", "ai_draft").put("review_status", "draft").putNull("reviewer_id")
                .putNull("reviewed_at").putNull("title");
        revision.putArray("types");
        revision.putArray("originating_run_ids").add("71fb66f0-e610-4f9c-8f26-4bb77655ee8c");
        var location = (ObjectNode) revision.path("locations").get(0);
        location.put("status", "unknown").put("coverage", "unknown").putNull("geometry")
                .putNull("source").putNull("checked_by").putNull("checked_at");
    }

    @Test
    void acceptsExplicitSourceOnlyBatchWithoutInventingEvents() throws Exception {
        input.put("schema_version", "source-import-v1");
        input.putArray("events"); input.putArray("evidence");
        assertThat(mapper.readTree(Path.of("examples/source-import.json").toFile())).isEqualTo(input);
        var batch = reader.read(write(), root);
        assertThat(batch.schemaVersion()).isEqualTo("source-import-v1");
        assertThat(batch.documents()).hasSize(1); assertThat(batch.events()).isEmpty();
    }

    @Test
    void sourceOnlyRejectsEventOrEvidenceAndReviewedStillRequiresBoth() throws Exception {
        input.put("schema_version", "source-import-v1"); rejected();
        input.putArray("events"); rejected();
        input.putArray("evidence");
        input.put("schema_version", "reviewed-import-v1"); rejected();
    }

    @Test
    void acceptsFullSyntheticRevisionAndCodePointEvidence() throws Exception {
        var batch = reader.read(write(), root);
        assertThat(batch.schemaVersion()).isEqualTo("reviewed-import-v1");
        assertThat(batch.documents()).hasSize(1);
        assertThat(batch.events()).hasSize(1);
        assertThat(batch.events().getFirst().payloadJson()).contains("합성", "😀", "\"value\":null");
    }

    @Test
    void rejectsHashAndCodePointQuoteMismatch() throws Exception {
        ((ObjectNode) input.path("evidence").get(0)).put("end_char", 8);
        rejected();
        fixtureReset();
        ((ObjectNode) input.path("documents").get(0)).put("text_sha256", "0".repeat(64));
        rejected();
        fixtureReset();
        ((ObjectNode) input.path("documents").get(0)).put("raw_sha256", "0".repeat(64));
        rejected();
        fixtureReset();
        ((ObjectNode) input.path("evidence").get(0)).put("text_sha256", "0".repeat(64));
        rejected();
    }

    @Test
    void rejectsUnknownFieldsDuplicateKeysAndTrailingJson() throws Exception {
        input.put("unexpected", true);
        rejected();
        fixtureReset();
        ((ObjectNode) input.path("events").get(0).path("revision")).put("classification", "candidate");
        rejected();
        fixtureReset();
        Files.writeString(root.resolve("batch.json"), input.toString().replace("\"data_kind\":\"synthetic\"", "\"data_kind\":\"synthetic\",\"data_kind\":\"real\""));
        assertThatThrownBy(() -> reader.read(root.resolve("batch.json"), root)).isInstanceOf(ImportException.class);
        Files.writeString(root.resolve("batch.json"), input + "{}");
        assertThatThrownBy(() -> reader.read(root.resolve("batch.json"), root)).isInstanceOf(ImportException.class);
    }

    @Test
    void rejectsMissingReferencesAndPublicationEscalation() throws Exception {
        ((ObjectNode) input.path("events").get(0).path("revision").path("applicability")).putArray("evidence_ids").add("missing");
        rejected();
        fixtureReset();
        ((ObjectNode) input.path("events").get(0).path("revision").path("occurrences").get(0)).putArray("location_ids").add("20000000-0000-4000-8000-000000000009");
        rejected();
        fixtureReset();
        ((ObjectNode) input.path("events").get(0).path("revision")).put("review_status", "approved");
        rejected();
        fixtureReset();
        ((ObjectNode) input.path("events").get(0).path("revision")).put("publication_intent", "public");
        rejected();
    }

    @Test
    void rejectsInvalidDatesGeometryScalarsAndUnknownKnowledge() throws Exception {
        var occurrence = (ObjectNode) input.path("events").get(0).path("revision").path("occurrences").get(0);
        occurrence.put("date_start", "2026-02-30");
        rejected();
        fixtureReset();
        ((ObjectNode) input.path("events").get(0).path("revision").path("occurrences").get(0)).put("end_day_offset", 0.5);
        rejected();
        fixtureReset();
        ((ObjectNode) input.path("events").get(0).path("revision").path("locations").get(0).path("geometry")).putArray("coordinates").add(181).add(37);
        rejected();
        fixtureReset();
        ((ObjectNode) input.path("events").get(0).path("revision").path("exceptions")).put("value", "예외 없음");
        rejected();
    }

    @Test
    void rejectsPathTraversalSymlinkEscapeAndOversizeFiles() throws Exception {
        var document = (ObjectNode) input.path("documents").get(0);
        document.put("raw_asset_path", "../synthetic-source.txt");
        rejected();
        Path outside = Files.createTempFile("myai-import-outside", ".txt");
        try {
            Files.copy(root.resolve("synthetic-source.txt"), outside, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
            Files.createSymbolicLink(root.resolve("escaped.txt"), outside);
            document.put("raw_asset_path", "escaped.txt");
            rejected();
        } finally { Files.deleteIfExists(outside); }
        document.put("raw_asset_path", "synthetic-source.txt");
        Files.write(root.resolve("synthetic-source.txt"), new byte[8 * 1024 * 1024 + 1]);
        rejected();
        Files.write(root.resolve("batch.json"), new byte[8 * 1024 * 1024 + 1]);
        assertThatThrownBy(() -> reader.read(root.resolve("batch.json"), root)).isInstanceOf(ImportException.class);
    }

    @Test
    void preservesUnknownFactsAndPartialEmojiQuote() throws Exception {
        ((ObjectNode) input.path("evidence").get(0)).put("quote", "😀").put("start_char", 6).put("end_char", 7);
        var revision = input.path("events").get(0).path("revision");
        var occurrence = (ObjectNode) revision.path("occurrences").get(0);
        occurrence.putNull("date_start").putNull("date_end").putNull("time_start").putNull("time_end").putNull("end_day_offset");
        occurrence.put("precision", "unknown").put("knowledge", "not_stated");
        occurrence.putArray("evidence_ids");
        var location = (ObjectNode) revision.path("locations").get(0);
        location.put("kind", "unknown").put("status", "unknown").put("coverage", "unknown");
        location.putNull("geometry").putNull("source").putNull("checked_by").putNull("checked_at");
        location.putArray("evidence_ids");
        var payload = mapper.readTree(reader.read(write(), root).events().getFirst().payloadJson());
        assertThat(payload.path("revision").path("occurrences").get(0).path("date_start").isNull()).isTrue();
        assertThat(payload.path("revision").path("locations").get(0).path("geometry").isNull()).isTrue();
        assertThat(payload.path("evidence").get(0).path("quote").asText()).isEqualTo("😀");
    }

    @Test
    void rejectsListInsteadOfLocationName() throws Exception {
        ((ObjectNode) input.path("events").get(0).path("revision").path("locations").get(0).path("name")).putArray("value").add("가상도로");
        rejected();
    }

    @Test
    void rejectsMalformedUnicodeInsideOverrideValues() throws Exception {
        var changes = ((ObjectNode) input.path("events").get(0).path("revision")).putArray("human_overrides");
        var change = changes.addObject().put("field_path", "title").putNull("before").put("after", "합성 공지").put("reason", "합성 수정").put("reviewer", "synthetic-reviewer").put("time", "2026-11-02T02:00:00Z");
        change.putArray("evidence_ids").add("heading-quote");
        Path file = Files.writeString(root.resolve("batch.json"), input.toString().replace("\"before\":null", "\"before\":\"\\uD800\""));
        assertThatThrownBy(() -> reader.read(file, root)).isInstanceOf(ImportException.class);
    }

    @Test
    void rejectsMalformedUnicodeInsideNestedObjectKeys() throws Exception {
        var changes = ((ObjectNode) input.path("events").get(0).path("revision")).putArray("human_overrides");
        var change = changes.addObject().put("field_path", "title").put("after", "합성 공지").put("reason", "합성 수정").put("reviewer", "synthetic-reviewer").put("time", "2026-11-02T02:00:00Z");
        change.putObject("before").put("placeholder", "합성 공지");
        change.putArray("evidence_ids").add("heading-quote");
        Path file = Files.writeString(root.resolve("batch.json"), input.toString().replace("\"placeholder\":", "\"\\uD800\":"));
        assertThatThrownBy(() -> reader.read(file, root)).isInstanceOf(ImportException.class);
    }

    @Test
    void preservesDecimalCoordinatePrecision() throws Exception {
        var geometry = (ObjectNode) input.path("events").get(0).path("revision").path("locations").get(0).path("geometry");
        geometry.putArray("coordinates").add(new java.math.BigDecimal("127.27000000000000001")).add(new java.math.BigDecimal("37.01000000000000001"));
        assertThat(reader.read(write(), root).events().getFirst().payloadJson()).contains("127.27000000000000001", "37.01000000000000001");
    }

    @Test
    void rejectsNormalizedMidnightAndOutOfDatabaseRangeTimestamps() throws Exception {
        var document = (ObjectNode) input.path("documents").get(0);
        document.put("collected_at", "2026-11-02T24:00:00Z");
        rejected();
        fixtureReset();
        ((ObjectNode) input.path("documents").get(0)).put("collected_at", "0999-11-02T02:00:00Z");
        rejected();
    }

    @Test
    void preservesEvidenceBackedKnownEmptyListsAsDistinctFromNull() throws Exception {
        var revision = input.path("events").get(0).path("revision");
        for (String field : java.util.List.of("exceptions", "route_names", "stop_names", "directions")) {
            var value = (ObjectNode) revision.path(field);
            value.put("knowledge", "known").putNull("reason");
            value.putArray("value");
            value.putArray("evidence_ids").add("body-quote");
        }
        // 이 시험은 목록·null의 구조 보존을 검사하며 인용의 의미 대조는 사람 검토 사항이다.
        var saved = mapper.readTree(reader.read(write(), root).events().getFirst().payloadJson()).path("revision");
        for (String field : java.util.List.of("exceptions", "route_names", "stop_names", "directions")) {
            assertThat(saved.path(field).path("value").isArray()).isTrue();
            assertThat(saved.path(field).path("value").isEmpty()).isTrue();
            assertThat(saved.path(field).path("knowledge").asText()).isEqualTo("known");
        }
        ((ObjectNode) revision.path("exceptions")).putArray("evidence_ids");
        rejected();
    }

    @Test
    void validatesCompleteTimeRangeEvenWhenDatePrecisionIsUnknown() throws Exception {
        var occurrence = (ObjectNode) input.path("events").get(0).path("revision").path("occurrences").get(0);
        occurrence.put("precision", "unknown").put("knowledge", "ambiguous").putNull("date_end");
        var saved = mapper.readTree(reader.read(write(), root).events().getFirst().payloadJson()).path("revision").path("occurrences").get(0);
        assertThat(saved.path("date_start").asText()).isEqualTo("2026-11-03");
        assertThat(saved.path("date_end").isNull()).isTrue();
        assertThat(saved.path("time_start").asText()).isEqualTo("10:00");
        occurrence.putNull("time_end").putNull("end_day_offset");
        saved = mapper.readTree(reader.read(write(), root).events().getFirst().payloadJson()).path("revision").path("occurrences").get(0);
        assertThat(saved.path("time_start").asText()).isEqualTo("10:00");
        assertThat(saved.path("time_end").isNull()).isTrue();
        occurrence.put("time_start", "12:00").put("time_end", "10:00").put("end_day_offset", 0);
        rejected();
    }

    @Test
    void retainsPreHandoffUtcMicrosecondInputLimits() throws Exception {
        var original = input.deepCopy();
        assertThat(reader.read(write(), root).events()).hasSize(1);
        for (String stamp : java.util.List.of("2026-11-02T01:00:00.123456789Z", "2026-11-02T10:00:00+09:00")) {
            for (String field : java.util.List.of("reviewed_at", "override_time")) {
                input = original.deepCopy();
                var revision = (ObjectNode) input.path("events").get(0).path("revision");
                revision.put("reviewer_id", "synthetic-reviewer").put("reviewed_at", "2026-11-02T01:00:00Z");
                if (field.equals("reviewed_at")) revision.put("reviewed_at", stamp);
                else {
                    var record = revision.putArray("human_overrides").addObject().put("field_path", "title").put("before", "old")
                            .put("reason", "합성 시각 규격 검증").put("reviewer", "synthetic-reviewer").put("time", stamp);
                    record.set("after", revision.path("title"));
                    record.putArray("evidence_ids").add(input.path("evidence").get(0).path("evidence_id"));
                }
                assertThatThrownBy(() -> reader.read(write(), root)).isInstanceOfSatisfying(ImportException.class,
                        error -> assertThat(error.field()).isEqualTo(field.equals("reviewed_at") ? "reviewed_at" : "time"));
            }
        }
    }

    private Path write() throws Exception {
        return Files.writeString(root.resolve("batch.json"), input.toString());
    }

    @Test
    void acceptsExplicitContinuousDatesButKeepsRecurringTimeValidation() throws Exception {
        var occurrence = (ObjectNode) input.path("events").get(0).path("revision").path("occurrences").get(0);
        occurrence.put("date_end", "2026-11-05").put("time_start", "22:00").put("time_end", "02:00").put("end_day_offset", 0);
        assertThat(reader.read(write(), root).events()).hasSize(1);
        occurrence.put("time_start", "10:00").put("time_end", "10:00");
        assertThat(reader.read(write(), root).events()).hasSize(1);
        occurrence.putArray("recurrence_dates").add("2026-11-03").add("2026-11-05");
        rejected();
        occurrence.put("time_start", "22:00").put("time_end", "02:00").put("end_day_offset", 1);
        assertThat(reader.read(write(), root).events()).hasSize(1);
    }

    private void rejected() throws Exception {
        Path file = write();
        assertThatThrownBy(() -> reader.read(file, root)).isInstanceOf(ImportException.class);
    }

    private void fixtureReset() throws Exception {
        input = (ObjectNode) mapper.readTree(Path.of("examples/reviewed-import.json").toFile());
    }
}
