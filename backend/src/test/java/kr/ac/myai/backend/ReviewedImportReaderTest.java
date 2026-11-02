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

    private Path write() throws Exception {
        return Files.writeString(root.resolve("batch.json"), input.toString());
    }

    private void rejected() throws Exception {
        Path file = write();
        assertThatThrownBy(() -> reader.read(file, root)).isInstanceOf(ImportException.class);
    }

    private void fixtureReset() throws Exception {
        input = (ObjectNode) mapper.readTree(Path.of("examples/reviewed-import.json").toFile());
    }
}
