package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedBatch;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.importing.LocalImportCommand;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.context.WebApplicationContext;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class ReviewedImportMySqlTest {
    @Autowired ReviewedImportService importer;
    @Autowired ReviewedImportReader reader;
    @Autowired JdbcTemplate jdbc;
    @Autowired MockMvc mvc;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();

    @BeforeEach
    void source() throws Exception {
        Files.copy(Path.of("examples/synthetic-source.txt"), root.resolve("synthetic-source.txt"));
    }

    @Test
    void importsOnceWithAuditAndNeverPublishes() throws Exception {
        var batch = read(fresh());
        long snapshots = jdbc.queryForObject("SELECT COUNT(*) FROM snapshots", Long.class);
        long heads = jdbc.queryForObject("SELECT COUNT(*) FROM publication_heads", Long.class);
        var first = importer.importBatch(batch, "synthetic-importer");
        var repeated = importer.importBatch(batch, "another-importer");
        assertThat(first.alreadyImported()).isFalse();
        assertThat(repeated.alreadyImported()).isTrue();
        assertThat(repeated.importId()).isEqualTo(first.importId());
        assertThat(repeated.revisionIds()).isEqualTo(first.revisionIds());
        var event = batch.events().getFirst();
        assertThat(count("event_revisions", "event_id", event.id())).isEqualTo(1);
        assertThat(count("review_audits", "event_id", event.id())).isEqualTo(1);
        assertThat(count("import_batches", "input_sha256", batch.inputSha256())).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT actor FROM review_audits WHERE event_id = ?", String.class, event.id())).isEqualTo("synthetic-importer");
        assertThat(jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id = ?", String.class, event.revisionId())).isEqualTo(event.payloadJson());
        assertThat(jdbc.queryForObject("SELECT payload_sha256 FROM event_revisions WHERE revision_id = ?", String.class, event.revisionId())).isEqualTo(event.payloadSha256());
        assertThat(jdbc.queryForObject("SELECT current_review_revision_id FROM events WHERE event_id = ?", String.class, event.id())).isEqualTo(event.revisionId());
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM snapshots", Long.class)).isEqualTo(snapshots);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM publication_heads", Long.class)).isEqualTo(heads);
        mvc.perform(get("/api/v1/config")).andExpect(status().isServiceUnavailable()).andExpect(jsonPath("$.error.code").value("PUBLIC_DATA_NOT_READY"));
        mvc.perform(get("/local/import")).andExpect(status().isNotFound());
    }

    @Test
    void appendsRevisionWithoutOverwritingOriginal() throws Exception {
        ObjectNode input = fresh();
        var first = read(input);
        importer.importBatch(first, "synthetic-importer");
        nextRevision(input);
        var second = read(input);
        importer.importBatch(second, "synthetic-editor");
        var original = first.events().getFirst();
        var updated = second.events().getFirst();
        assertThat(count("event_revisions", "event_id", original.id())).isEqualTo(2);
        assertThat(count("document_versions", "document_id", first.documents().getFirst().id())).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id = ?", String.class, original.revisionId())).isEqualTo(original.payloadJson());
        assertThat(jdbc.queryForObject("SELECT current_review_revision_id FROM events WHERE event_id = ?", String.class, original.id())).isEqualTo(updated.revisionId());
        assertThat(jdbc.queryForObject("SELECT before_ref FROM review_audits WHERE revision_id = ?", String.class, updated.revisionId())).isEqualTo(original.revisionId());
    }

    @Test
    void rejectsChangedDocumentIdentityWithoutAddingRevision() throws Exception {
        ObjectNode input = fresh();
        var original = read(input);
        importer.importBatch(original, "synthetic-importer");
        nextRevision(input);
        ((ObjectNode) input.path("documents").get(0)).put("title", "기존 문서 버전 덮어쓰기 시도");
        var changed = read(input);
        conflict(() -> importer.importBatch(changed, "synthetic-importer"));
        assertThat(count("event_revisions", "event_id", original.events().getFirst().id())).isEqualTo(1);
        assertThat(count("import_batches", "input_sha256", changed.inputSha256())).isZero();
    }

    @Test
    void rollsBackEarlierRowsWhenLaterEventConflicts() throws Exception {
        ObjectNode existingInput = fresh();
        var existing = read(existingInput);
        importer.importBatch(existing, "synthetic-importer");
        ObjectNode candidate = fresh();
        String newDocument = candidate.path("documents").get(0).path("document_id").asText();
        String newEvent = candidate.path("events").get(0).path("event_id").asText();
        candidate.withArray("documents").add(existingInput.path("documents").get(0));
        // 두 사건의 로컬 근거 ID를 분리해 입력 검증은 통과시킨다.
        ObjectNode conflictingEvent = (ObjectNode) existingInput.path("events").get(0).deepCopy();
        String renamed = conflictingEvent.toString().replace("heading-quote", "existing-heading").replace("body-quote", "existing-body");
        conflictingEvent = (ObjectNode) mapper.readTree(renamed);
        ((ObjectNode) conflictingEvent.path("revision")).put("revision_id", UUID.randomUUID().toString());
        candidate.withArray("events").add(conflictingEvent);
        for (var evidence : existingInput.path("evidence")) {
            candidate.withArray("evidence").add(mapper.readTree(evidence.toString().replace("heading-quote", "existing-heading").replace("body-quote", "existing-body")));
        }
        var batch = read(candidate);
        conflict(() -> importer.importBatch(batch, "synthetic-importer"));
        assertThat(count("documents", "document_id", newDocument)).isZero();
        assertThat(count("events", "event_id", newEvent)).isZero();
        assertThat(count("review_audits", "event_id", newEvent)).isZero();
        assertThat(count("import_batches", "input_sha256", batch.inputSha256())).isZero();
        assertThat(count("event_revisions", "event_id", existing.events().getFirst().id())).isEqualTo(1);
    }

    @Test
    void concurrentSameBatchReturnsOneCommittedResult() throws Exception {
        var batch = read(fresh());
        var barrier = new CyclicBarrier(2);
        try (var pool = Executors.newFixedThreadPool(2)) {
            Callable<ReviewedImportService.ImportResult> action = () -> {
                barrier.await(10, TimeUnit.SECONDS);
                return importer.importBatch(batch, "synthetic-importer");
            };
            var first = pool.submit(action);
            var second = pool.submit(action);
            var a = first.get(20, TimeUnit.SECONDS);
            var b = second.get(20, TimeUnit.SECONDS);
            assertThat(a.importId()).isEqualTo(b.importId());
            assertThat(a.alreadyImported()).isNotEqualTo(b.alreadyImported());
            assertThat(count("event_revisions", "event_id", batch.events().getFirst().id())).isEqualTo(1);
        }
    }

    @Test
    void concurrentRevisionEditsAllowOnlyOneWinner() throws Exception {
        ObjectNode input = fresh();
        var original = read(input);
        importer.importBatch(original, "synthetic-importer");
        ObjectNode a = input.deepCopy();
        ObjectNode b = input.deepCopy();
        nextRevision(a);
        nextRevision(b);
        var first = read(a);
        var second = read(b);
        var barrier = new CyclicBarrier(2);
        try (var pool = Executors.newFixedThreadPool(2)) {
            var left = pool.submit(() -> attempt(first, barrier));
            var right = pool.submit(() -> attempt(second, barrier));
            assertThat(java.util.List.of(left.get(20, TimeUnit.SECONDS), right.get(20, TimeUnit.SECONDS))).containsExactlyInAnyOrder("success", "IMPORT_CONFLICT");
        }
        assertThat(count("event_revisions", "event_id", original.events().getFirst().id())).isEqualTo(2);
        assertThat(count("review_audits", "event_id", original.events().getFirst().id())).isEqualTo(2);
    }

    @Test
    void localCommandRunsWithoutHttpAndReturnsFailureCodes() throws Exception {
        ObjectNode input = fresh();
        Path file = Files.writeString(root.resolve("command.json"), input.toString());
        String[] args = {"--myai.import.file=" + file, "--myai.import.source-root=" + root, "--myai.import.actor=synthetic-importer"};
        try (var context = new SpringApplicationBuilder(MyaiBackendApplication.class).profiles("local-import").run(args)) {
            assertThat(context).isNotInstanceOf(WebApplicationContext.class);
            assertThat(context.getBean(LocalImportCommand.class).getExitCode()).isZero();
            assertThat(count("events", "event_id", input.path("events").get(0).path("event_id").asText())).isEqualTo(1);
        }
        input.put("schema_version", "extract-schema-v1");
        Files.writeString(file, input.toString());
        try (var context = new SpringApplicationBuilder(MyaiBackendApplication.class).profiles("local-import").run(args)) {
            assertThat(context.getBean(LocalImportCommand.class).getExitCode()).isEqualTo(2);
        }
    }

    private String attempt(ReviewedBatch batch, CyclicBarrier barrier) throws Exception {
        barrier.await(10, TimeUnit.SECONDS);
        try { importer.importBatch(batch, "synthetic-editor"); return "success"; }
        catch (ImportException ex) { return ex.code(); }
    }

    private void conflict(Callable<?> call) {
        assertThatThrownBy(call::call).isInstanceOfSatisfying(ImportException.class, ex -> assertThat(ex.code()).isEqualTo("IMPORT_CONFLICT"));
    }

    private long count(String table, String column, String id) {
        return jdbc.queryForObject("SELECT COUNT(*) FROM " + table + " WHERE " + column + " = ?", Long.class, id);
    }

    private ReviewedBatch read(ObjectNode input) throws Exception {
        Path path = root.resolve(UUID.randomUUID() + ".json");
        Files.writeString(path, input.toString());
        return reader.read(path, root);
    }

    private ObjectNode fresh() throws Exception {
        String json = Files.readString(Path.of("examples/reviewed-import.json"));
        Map<String, String> replacements = new HashMap<>();
        String unique = Pattern.compile("10000000-0000-4000-8000-[0-9]{12}").matcher(json)
                .replaceAll(match -> replacements.computeIfAbsent(match.group(), ignored -> UUID.randomUUID().toString()));
        return (ObjectNode) mapper.readTree(unique);
    }

    private void nextRevision(ObjectNode input) {
        var event = (ObjectNode) input.path("events").get(0);
        var revision = (ObjectNode) event.path("revision");
        event.put("expected_revision_no", 1);
        revision.put("revision_no", 2).put("revision_id", UUID.randomUUID().toString());
    }
}
