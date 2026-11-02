package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("public")
@Import(CalculationMySqlTest.FixedClock.class)
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class CalculationMySqlTest {
    @Autowired PublicationService publication;
    @Autowired PublicationCommandReader commands;
    @Autowired ReviewedImportService importer;
    @Autowired ReviewedImportReader reader;
    @Autowired JdbcTemplate jdbc;
    @Autowired MockMvc mvc;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();

    @DynamicPropertySource
    static void runtime(DynamicPropertyRegistry registry) {
        registry.add("app.calculation.workdir", () -> PythonProbe.REPO.toString());
        registry.add("app.calculation.python-executable", () -> PythonProbe.PYTHON);
        registry.add("app.calculation.timeout-ms", () -> 5000);
    }

    @TestConfiguration
    static class FixedClock {
        @Bean @Primary Clock clock() { return Clock.fixed(Instant.parse("2026-11-03T02:00:00Z"), ZoneOffset.UTC); }
    }

    @BeforeEach
    void setup() throws Exception {
        clearPublished();
        Files.copy(Path.of("examples/synthetic-source.txt"), root.resolve("synthetic-source.txt"));
    }

    @AfterEach
    void clearPublished() {
        for (String table : List.of("publication_audits", "publication_heads", "snapshot_revisions", "snapshots")) jdbc.update("DELETE FROM " + table);
    }

    @Test
    void realApiComputesChangedConditionsWithoutWritingAnyDatabaseData() throws Exception {
        var input = fresh(); var revisions = approve(input); var command = publishCommand(input, revisions, null);
        String snapshot = execute(command); ObjectNode query = query(command, snapshot);
        var before = databaseState();
        var response = matches(query); var data = response.path("data");
        assertThat(response.path("snapshot_id").asText()).isEqualTo(snapshot);
        assertThat(data.path("counts").path("candidate").asInt()).isEqualTo(1);
        assertThat(data.path("items").get(0).path("distance_m").asInt()).isZero();
        assertThat(data.path("items").get(0).path("time_overlap_minutes").asDouble()).isEqualTo(120);
        assertThat(data.path("items").get(0).path("field_values").path("exceptions").path("knowledge").asText()).isEqualTo("not_stated");
        query.path("weekly_hours").forEach(day -> ((ObjectNode) day).put("state", "closed").putArray("intervals"));
        assertThat(matches(query).path("data").path("counts").path("candidate").asInt()).isZero();
        query = query(command, snapshot); query.putArray("types").add("traffic");
        assertThat(matches(query).path("data").path("items").isEmpty()).isTrue();
        query = query(command, snapshot); query.put("selection", "needs_check");
        query.path("weekly_hours").forEach(day -> ((ObjectNode) day).put("state", "unknown").putArray("intervals"));
        var unknown = matches(query).path("data");
        assertThat(unknown.path("counts").path("needs_check").asInt()).isEqualTo(1);
        assertThat(unknown.path("items").get(0).path("time_overlap_minutes").isNull()).isTrue();
        assertThat(databaseState()).isEqualTo(before);
    }

    @Test
    void matchesKeepPublishedFactsAfterNewUnapprovedWorkingRevision() throws Exception {
        var input = fresh(); var revisions = approve(input); var command = publishCommand(input, revisions, null);
        String snapshot = execute(command); ObjectNode query = query(command, snapshot);
        JsonNode first = matches(query).path("data");
        var event = (ObjectNode) input.path("events").get(0); var revision = (ObjectNode) event.path("revision");
        event.put("expected_revision_no", 2); revision.put("revision_id", UUID.randomUUID().toString()).put("revision_no", 3).put("title", "미승인 작업 제목");
        importBatch(input);
        var before = databaseState();
        assertThat(matches(query).path("data")).isEqualTo(first);
        assertThat(databaseState()).isEqualTo(before);
    }

    @Test
    void cancelledNoticeStaysOutOfCandidatesAndUnknownTimeIsNotAllDay() throws Exception {
        var input = fresh();
        rewriteSource(input, "2026-11-03 10:00~12:00 가상도로 공사. 차량 통행 제한 안내가 취소되었습니다.");
        var revision = (ObjectNode) input.path("events").get(0).path("revision");
        revision.put("lifecycle", "cancelled").putArray("lifecycle_evidence_ids").add("body-quote");
        ((ObjectNode) input.path("events").get(0).path("document_links").get(0)).put("role", "cancellation");
        var command = publishCommand(input, approve(input), null); String snapshot = execute(command);
        var query = query(command, snapshot); var data = matches(query).path("data");
        assertThat(data.path("counts").path("candidate").asInt()).isZero();
        assertThat(data.path("counts").path("cancelled").asInt()).isEqualTo(1);
        query.put("selection", "cancelled");
        assertThat(matches(query).path("data").path("items").get(0).path("lifecycle").asText()).isEqualTo("cancelled");
        clearPublished();
        input = fresh(); rewriteSource(input, "2026-11-03 가상도로 공사. 시간 추후 안내. 차량 통행 제한.");
        var occurrence = (ObjectNode) input.path("events").get(0).path("revision").path("occurrences").get(0);
        occurrence.put("precision", "date_only").putNull("time_start").putNull("time_end").putNull("end_day_offset");
        command = publishCommand(input, approve(input), null); snapshot = execute(command);
        query = query(command, snapshot); query.put("selection", "needs_check");
        var item = matches(query).path("data").path("items").get(0);
        assertThat(item.path("time_overlap_minutes").isNull()).isTrue();
        assertThat(item.path("reason_codes").toString()).contains("TIME_UNKNOWN");
    }

    @Test
    void candidateOverlapGroupsRemainWhenAnotherSelectionIsShown() throws Exception {
        var input = fresh();
        rewriteSource(input, "2026-11-03 10:00~12:00 가상도로 공사. 차량 통행 제한. 2026-11-03 11:00~13:00 가상도로 행사. 방문자 안내.");
        var first = (ObjectNode) input.path("events").get(0); var second = first.deepCopy();
        String id = UUID.randomUUID().toString(), location = UUID.randomUUID().toString();
        second.put("event_id", id);
        var revision = (ObjectNode) second.path("revision");
        revision.put("event_id", id).put("revision_id", UUID.randomUUID().toString()).putArray("types").add("event");
        ((ObjectNode) revision.path("applicability")).put("value", "방문자");
        ((ObjectNode) revision.path("locations").get(0)).put("location_id", location);
        ((ObjectNode) revision.path("occurrences").get(0)).put("occurrence_id", UUID.randomUUID().toString())
                .put("time_start", "11:00").put("time_end", "13:00").putArray("location_ids").add(location);
        ((com.fasterxml.jackson.databind.node.ArrayNode) input.path("events")).add(second);
        var command = publishCommand(input, approve(input), null); String snapshot = execute(command); var query = query(command, snapshot);
        var candidate = matches(query).path("data");
        assertThat(candidate.path("counts").path("candidate").asInt()).isEqualTo(2);
        assertThat(candidate.path("overlap_groups").size()).isEqualTo(1);
        assertThat(candidate.path("overlap_groups").get(0).path("start_at").asText()).isEqualTo("2026-11-03T02:00:00Z");
        assertThat(candidate.path("overlap_groups").get(0).path("end_at").asText()).isEqualTo("2026-11-03T03:00:00Z");
        query.put("selection", "needs_check"); var other = matches(query).path("data");
        assertThat(other.path("items").isEmpty()).isTrue();
        assertThat(other.path("overlap_groups")).isEqualTo(candidate.path("overlap_groups"));
        query.putArray("types").add("construction");
        assertThat(matches(query).path("data").path("overlap_groups").isEmpty()).isTrue();
    }

    @Test
    void replacementReturns409AndRollbackRestoresSameCalculation() throws Exception {
        var input = fresh(); var command = publishCommand(input, approve(input), null); String first = execute(command);
        ObjectNode query = query(command, first); JsonNode original = matches(query).path("data");
        command.put("expected_head_version", 0).putArray("revision_ids"); String empty = execute(command);
        mvc.perform(post("/api/v1/matches").contentType("application/json").content(query.toString()))
                .andExpect(status().isConflict()).andExpect(jsonPath("$.error.code").value("SNAPSHOT_RETIRED"))
                .andExpect(jsonPath("$.current_snapshot_id").value(empty));
        assertThat(matches(query(command, empty)).path("data").path("items").isEmpty()).isTrue();
        var rollback = fixture("rollback"); rollback.put("snapshot_id", first).put("expected_head_version", 1); execute(rollback);
        assertThat(matches(query).path("data")).isEqualTo(original);
    }

    @Test
    void replayUsesHistoricalContextAndRawFilesAreNotLiveQueryInputs() throws Exception {
        var input = fresh(); var command = publishCommand(input, approve(input), null); String caseId = UUID.randomUUID().toString();
        command.put("mode", "replay").put("case_id", caseId).put("anchor_date", "2026-11-02").put("reference_instant", "2026-11-02T12:00:00Z")
                .put("knowledge_cutoff", "2026-11-02T11:00:00Z").put("history_fidelity", "verified_snapshot");
        String snapshot = execute(command); var query = query(command, snapshot); query.put("mode", "replay").put("case_id", caseId);
        Files.delete(root.resolve("synthetic-source.txt"));
        var data = matches(query).path("data");
        assertThat(data.path("counts").path("candidate").asInt()).isEqualTo(1);
        assertThat(data.path("query_context").path("anchor_date").asText()).isEqualTo("2026-11-02");
        assertThat(data.path("query_context").path("history_fidelity").asText()).isEqualTo("verified_snapshot");
        query.put("case_id", UUID.randomUUID().toString());
        mvc.perform(post("/api/v1/matches").contentType("application/json").content(query.toString())).andExpect(status().isUnprocessableEntity());
    }

    @Test
    void processesFortySyntheticDocumentsAcrossAllTypes() throws Exception {
        ObjectNode first = null; String area = UUID.randomUUID().toString(); var revisions = new ArrayList<String>();
        String[] types = {"construction", "event", "traffic"}, names = {"공사", "행사", "교통 변경"};
        for (int i = 0; i < 40; i++) {
            var input = fresh(); var document = (ObjectNode) input.path("documents").get(0);
            String title = "합성 " + names[i % 3] + " " + i + " 😀";
            document.put("raw_asset_path", "notice-" + i + ".txt").put("official_url", "https://example.org/synthetic-notice-" + i).put("title", title);
            ((ObjectNode) document.path("block_index").get(0)).put("text", title);
            var event = (ObjectNode) input.path("events").get(0); event.put("area_id", area);
            ((ObjectNode) event.path("revision")).put("title", title).putArray("types").add(types[i % 3]);
            rewriteSource(input, "2026-11-03 10:00~12:00 가상도로 " + names[i % 3] + " " + i + ". 차량 통행 제한.");
            revisions.addAll(approve(input));
            if (first == null) first = input;
        }
        var command = publishCommand(first, revisions, null); String snapshot = execute(command); var query = query(command, snapshot);
        var before = databaseState(); var times = new ArrayList<Long>();
        for (int i = 0; i < 5; i++) {
            long start = System.nanoTime(); var data = matches(query).path("data"); times.add((System.nanoTime() - start) / 1_000_000);
            assertThat(data.path("counts").path("candidate").asInt()).isEqualTo(40);
            assertThat(data.path("items").size()).isEqualTo(40);
            assertThat(data.path("overlap_groups").size()).isEqualTo(1);
            assertThat(data.path("overlap_groups").get(0).path("event_ids").size()).isEqualTo(40);
        }
        query.putArray("types").add("traffic");
        assertThat(matches(query).path("data").path("counts").path("candidate").asInt()).isEqualTo(13);
        assertThat(databaseState()).isEqualTo(before);
        Collections.sort(times);
        System.out.println("SYNTHETIC_40_MOCKMVC_MS median=" + times.get(2) + " max=" + times.get(4));
    }

    private ObjectNode fresh() throws Exception {
        String text = Files.readString(Path.of("examples/reviewed-import.json")); var ids = new HashMap<String, String>();
        return (ObjectNode) mapper.readTree(Pattern.compile("10000000-0000-4000-8000-[0-9]{12}").matcher(text)
                .replaceAll(match -> ids.computeIfAbsent(match.group(), ignored -> UUID.randomUUID().toString())));
    }

    private void importBatch(ObjectNode input) throws Exception {
        Path file = Files.writeString(root.resolve(UUID.randomUUID() + ".json"), input.toString());
        importer.importBatch(reader.read(file, root), "synthetic-importer");
    }

    private List<String> approve(ObjectNode input) throws Exception {
        importBatch(input); var revisions = new ArrayList<String>();
        for (var event : input.path("events")) {
            var command = fixture("approve"); command.put("event_id", event.path("event_id").asText()).put("expected_revision_no", 1);
            revisions.add(publication.execute(commands.read(write(command)), root, "synthetic-reviewer").revisionId());
        }
        return revisions;
    }

    private ObjectNode publishCommand(ObjectNode input, List<String> revisions, Long expected) throws Exception {
        var command = fixture("publish"); String area = input.path("events").get(0).path("area_id").asText();
        ((ObjectNode) command.path("area")).put("area_id", area);
        for (var point : command.path("points")) ((ObjectNode) point).put("area_id", area).put("point_id", UUID.randomUUID().toString());
        var ids = command.putArray("revision_ids"); revisions.forEach(ids::add);
        if (expected == null) command.putNull("expected_head_version"); else command.put("expected_head_version", expected);
        return command;
    }

    private String execute(ObjectNode command) throws Exception { return publication.execute(commands.read(write(command)), root, "synthetic-publisher").snapshotId(); }
    private Path write(ObjectNode input) throws Exception { return Files.writeString(root.resolve(UUID.randomUUID() + ".json"), input.toString()); }
    private ObjectNode fixture(String name) throws Exception { return (ObjectNode) mapper.readTree(Path.of("examples/" + name + ".json").toFile()); }
    private ObjectNode query(ObjectNode command, String snapshot) throws Exception {
        return ((ObjectNode) mapper.readTree(Path.of("../contracts/examples/matches-request.json").toFile()))
                .put("point_id", command.path("points").get(0).path("point_id").asText()).put("snapshot_id", snapshot);
    }
    private JsonNode matches(ObjectNode query) throws Exception {
        return mapper.readTree(mvc.perform(post("/api/v1/matches").contentType("application/json").content(query.toString()))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString(StandardCharsets.UTF_8));
    }

    private Map<String, List<Map<String, String>>> databaseState() {
        var state = new LinkedHashMap<String, List<Map<String, String>>>();
        for (String table : List.of("test_points", "place_dictionary", "documents", "document_versions", "source_checks", "extraction_runs", "events", "event_revisions",
                "review_audits", "snapshots", "snapshot_revisions", "publication_heads", "import_batches", "publication_audits")) {
            var rows = new ArrayList<Map<String, String>>();
            for (var row : jdbc.queryForList("SELECT * FROM " + table + " ORDER BY 1")) {
                var values = new LinkedHashMap<String, String>(); row.forEach((k, v) -> values.put(k, v == null ? null : v.toString())); rows.add(values);
            }
            state.put(table, rows);
        }
        return state;
    }

    private void rewriteSource(ObjectNode input, String body) throws Exception {
        var document = (ObjectNode) input.path("documents").get(0); String heading = document.path("block_index").get(0).path("text").asText();
        String text = heading + "\n" + body + "\n", hash = ReviewedImportReader.sha256(text.getBytes(StandardCharsets.UTF_8));
        Path asset = root.resolve(document.path("raw_asset_path").asText()).normalize();
        assertThat(asset.startsWith(root)).isTrue(); Files.writeString(asset, text);
        document.put("cleaned_text", text).put("text_sha256", hash).put("raw_sha256", hash);
        ((ObjectNode) document.path("block_index").get(1)).put("text", body);
        for (var check : document.path("checks")) ((ObjectNode) check).put("text_sha256", hash);
        for (var evidence : input.path("evidence")) {
            ((ObjectNode) evidence).put("text_sha256", hash);
            String quote = evidence.path("block_id").asText().equals("body") ? body : heading;
            ((ObjectNode) evidence).put("quote", quote).put("end_char", quote.codePointCount(0, quote.length()));
        }
    }
}
