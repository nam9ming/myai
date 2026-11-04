package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.controller.ApiExceptionHandler;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.local.LocalApiSecurityFilter;
import kr.ac.myai.backend.local.LocalBodyLimitAdvice;
import kr.ac.myai.backend.local.LocalManagementController;
import kr.ac.myai.backend.local.LocalManagementService;
import kr.ac.myai.backend.local.LocalRequestStore;
import kr.ac.myai.backend.logging.PublicRequestLogFilter;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.service.ExtractionImportService;
import kr.ac.myai.backend.service.HumanHandoffImportService;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.http.converter.ByteArrayHttpMessageConverter;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static kr.ac.myai.backend.SourceReviewFixtures.*;
import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class LocalManagementMySqlTest {
    private static final String TOKEN = "SYNTHETIC_LOCAL_MYSQL_TOKEN_0123456789";
    private static final String ACTOR = "synthetic-local-http-manager";
    @Autowired JdbcTemplate jdbc;
    @Autowired ReviewedImportReader reader;
    @Autowired PublicationCommandReader commands;
    @Autowired ReviewedImportService imports;
    @Autowired ExtractionImportService extractions;
    @Autowired HumanHandoffImportService handoffs;
    @Autowired PublicationService publication;
    @Autowired MockMvc publicMvc;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper().findAndRegisterModules()
            .setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    final List<String> ownedCases = new ArrayList<>();
    Path requests;
    SourceReviewFixtures fixtures;
    MockMvc local;

    @DynamicPropertySource
    static void python(DynamicPropertyRegistry properties) {
        properties.add("app.calculation.workdir", () -> PythonProbe.REPO.toString());
        properties.add("app.calculation.python-executable", () -> PythonProbe.PYTHON);
        properties.add("app.extraction.timeout-ms", () -> 10000);
    }

    @BeforeEach
    void syntheticHttp() throws Exception {
        root = root.toRealPath();
        requests = Files.createDirectory(root.resolve("requests"),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        fixtures = new SourceReviewFixtures(root, jdbc, reader, imports);
        local = localMvc(root, root);
    }

    @AfterEach
    void removeOnlyOwnedPublicationRowsAndUnsealTemps() throws Exception {
        try {
            for (String caseId : ownedCases) {
                String channel = "replay:" + caseId;
                jdbc.update("DELETE FROM publication_audits WHERE channel_key=?", channel);
                jdbc.update("DELETE FROM publication_heads WHERE channel_key=?", channel);
                jdbc.update("DELETE FROM snapshot_revisions WHERE snapshot_id IN (SELECT snapshot_id FROM snapshots WHERE case_id=?)", caseId);
                jdbc.update("DELETE FROM snapshots WHERE case_id=?", caseId);
            }
        } finally { ExtractionArchiveReaderTest.unseal(root); }
    }

    @Test
    void httpDocumentsAndValidatedOrFailedRunsPreserveOriginalsAndExactReplay() throws Exception {
        var source = fixtures.source(false);
        byte[] body = raw(source);
        var first = success(post("/local/documents"), body);
        assertThat(first.path("data").path("revision_ids")).isEmpty();
        assertThat(first.path("data").path("document_version_ids").get(0).asText()).isEqualTo(version(source));
        var registered = database();
        assertThat(success(post("/local/documents"), body).path("data").path("already_imported").asBoolean()).isTrue();
        assertThat(database()).isEqualTo(registered);
        assertRetained(body);
        byte[] sourceBefore = Files.readAllBytes(root.resolve("synthetic-source.txt"));
        for (boolean failed : new boolean[] {false, true}) {
            String run = UUID.randomUUID().toString();
            Path archive = fixtures.extraction.archive(source, run, failed);
            local = localMvc(archive, root);
            var originalFiles = fileHashes(archive.resolve(run));
            String inputHash = ReviewedImportReader.sha256(Files.readAllBytes(archive.resolve(run).resolve("input.json")));
            var request = extraction(run, "0".repeat(64));
            var before = database();
            error(post("/local/extractions/import"), raw(request), 422, "EXTRACTION_VALIDATION_ERROR");
            assertThat(database()).isEqualTo(before);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM extraction_runs WHERE run_id=?", Long.class, run)).isZero();
            assertRetained(raw(request));
            request.put("expected_input_hash", inputHash);
            byte[] extractionBody = raw(request);
            var result = success(post("/local/extractions/import"), extractionBody).path("data");
            assertThat(result.path("status").asText()).isEqualTo(failed ? "failed" : "validated");
            assertThat(result.path("run_id").asText()).isEqualTo(run);
            assertThat(result.path("review_required").asBoolean()).isTrue();
            var row = jdbc.queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", run);
            assertThat(row.get("input_sha256")).isEqualTo(inputHash);
            assertThat(row.get("status")).isEqualTo(failed ? "failed" : "validated");
            var saved = database();
            assertThat(success(post("/local/extractions/import"), extractionBody).path("data").path("already_registered").asBoolean()).isTrue();
            assertThat(database()).isEqualTo(saved);
            assertThat(fileHashes(archive.resolve(run))).isEqualTo(originalFiles);
            assertRetained(extractionBody);
        }
        assertThat(Files.readAllBytes(root.resolve("synthetic-source.txt"))).isEqualTo(sourceBefore);
    }

    @Test
    void singleAndExplicitBatchReviewsKeepUrlAndStaleRevisionBoundaries() throws Exception {
        var input = fixtures.human(false);
        String eventId = event(input);
        byte[] body = raw(input);
        var before = database();
        var files = fileHashes(requests);
        error(put("/local/events/" + UUID.randomUUID() + "/review"), body, 422, "LOCAL_API_VALIDATION_ERROR");
        assertThat(database()).isEqualTo(before);
        assertThat(fileHashes(requests)).isEqualTo(files);
        var imported = success(put("/local/events/" + eventId + "/review"), body).path("data");
        String originalId = imported.path("revision_ids").get(0).asText();
        String original = payload(originalId);
        var update = input.deepCopy();
        var updatedEvent = (ObjectNode) update.path("events").get(0);
        updatedEvent.put("expected_revision_no", 1);
        ((ObjectNode) updatedEvent.path("revision")).put("revision_no", 2).put("revision_id", UUID.randomUUID().toString());
        byte[] updateBody = raw(update);
        String updatedId = success(put("/local/events/" + eventId + "/review"), updateBody).path("data").path("revision_ids").get(0).asText();
        assertThat(current(eventId)).isEqualTo(updatedId);
        var saved = database();
        assertThat(success(put("/local/events/" + eventId + "/review"), updateBody).path("data").path("already_imported").asBoolean()).isTrue();
        assertThat(database()).isEqualTo(saved);
        ((ObjectNode) updatedEvent.path("revision")).put("revision_id", UUID.randomUUID().toString());
        error(put("/local/events/" + eventId + "/review"), raw(update), 409, "IMPORT_CONFLICT");
        assertThat(database()).isEqualTo(saved);
        assertThat(payload(originalId)).isEqualTo(original);

        var batch = fixtures.human(false);
        var second = (ObjectNode) batch.path("events").get(0).deepCopy();
        String secondId = UUID.randomUUID().toString();
        second.put("event_id", secondId);
        ((ObjectNode) second.path("revision")).put("event_id", secondId).put("revision_id", UUID.randomUUID().toString());
        batch.withArray("events").add(second);
        byte[] batchBody = raw(batch);
        before = database(); files = fileHashes(requests);
        error(put("/local/events/" + event(batch) + "/review"), batchBody, 422, "LOCAL_API_VALIDATION_ERROR");
        assertThat(database()).isEqualTo(before);
        assertThat(fileHashes(requests)).isEqualTo(files);
        var result = success(post("/local/reviews/import"), batchBody).path("data");
        assertThat(result.path("revision_ids")).hasSize(2);
        for (var item : batch.path("events")) assertThat(current(item.path("event_id").asText()))
                .isEqualTo(item.path("revision").path("revision_id").asText());
        var staleBatch = batch.deepCopy();
        for (int index = 0; index < 2; index++) {
            var item = (ObjectNode) staleBatch.path("events").get(index);
            item.put("expected_revision_no", index == 0 ? 1 : 0);
            ((ObjectNode) item.path("revision")).put("revision_no", index == 0 ? 2 : 1)
                    .put("revision_id", UUID.randomUUID().toString());
        }
        before = database();
        error(post("/local/reviews/import"), raw(staleBatch), 409, "IMPORT_CONFLICT");
        assertThat(database()).isEqualTo(before);
        assertRetained(body); assertRetained(updateBody); assertRetained(batchBody);
    }

    @Test
    void pendingSourcesAndUnreviewedRevisionsStayPrivateWhileRejectionIsRecorded() throws Exception {
        var input = fixtures.human(true);
        String eventId = event(input);
        String original = success(put("/local/events/" + eventId + "/review"), raw(input))
                .path("data").path("revision_ids").get(0).asText();
        var before = database();
        error(put("/local/events/" + eventId + "/review"), raw(decision(eventId, "approve", 1)), 422, "PUBLICATION_VALIDATION_ERROR");
        assertThat(database()).isEqualTo(before);
        var publish = publish(input.path("events").get(0).path("area_id").asText(), original);
        error(post("/local/publish"), raw(publish), 409, "PUBLICATION_CONFLICT");
        assertThat(database()).isEqualTo(before);
        var forged = input.deepCopy();
        ((ObjectNode) forged.path("events").get(0).path("revision")).put("review_status", "approved").put("publication_intent", "public");
        var files = fileHashes(requests);
        error(put("/local/events/" + eventId + "/review"), raw(forged), 422, "IMPORT_VALIDATION_ERROR");
        assertThat(database()).isEqualTo(before);
        assertThat(fileHashes(requests)).isEqualTo(files);
        String rejected = success(put("/local/events/" + eventId + "/review"), raw(decision(eventId, "reject", 1)))
                .path("data").path("revision_id").asText();
        var revision = mapper.readTree(payload(rejected)).path("revision");
        assertThat(revision.path("review_status").asText()).isEqualTo("rejected");
        assertThat(revision.path("publication_intent").asText()).isEqualTo("hidden");
        assertThat(current(eventId)).isEqualTo(rejected);
        assertThat(mapper.readTree(payload(original)).path("revision").path("review_status").asText()).isEqualTo("needs_review");
        assertThat(jdbc.queryForObject("SELECT actor FROM review_audits WHERE revision_id=?", String.class, rejected)).isEqualTo(ACTOR);
    }

    @Test
    void failedRunHandoffPreservesProofThroughExplicitHumanReviewAndPublication() throws Exception {
        var source = fixtures.source(false);
        success(post("/local/documents"), raw(source));
        String run = UUID.randomUUID().toString();
        Path archive = fixtures.extraction.archive(source, run, true);
        local = localMvc(archive, root);
        String hash = ReviewedImportReader.sha256(Files.readAllBytes(archive.resolve(run).resolve("input.json")));
        success(post("/local/extractions/import"), raw(extraction(run, hash)));
        var parent = jdbc.queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", run);
        var handoff = fixtures.handoff(source, run, archive);
        var image = fileHashes(handoff.image());
        local = localMvc(archive, handoff.directory());
        byte[] body = Files.readAllBytes(handoff.file());
        JsonNode request = mapper.readTree(body);
        assertThat(request.path("revisions")).hasSize(1);
        String eventId = request.path("revisions").get(0).path("event_id").asText();
        var before = database(); var files = fileHashes(requests);
        error(put("/local/events/" + UUID.randomUUID() + "/review"), body, 422, "LOCAL_API_VALIDATION_ERROR");
        assertThat(database()).isEqualTo(before); assertThat(fileHashes(requests)).isEqualTo(files);
        String revision = success(put("/local/events/" + eventId + "/review"), body).path("data").path("revision_ids").get(0).asText();
        var saved = mapper.readTree(payload(revision));
        assertThat(saved.path("human_handoffs").get(0).path("handoff_ref")).isEqualTo(request.path("handoff_ref"));
        assertThat(saved.path("revision").path("origin").asText()).isEqualTo("ai_reviewed");
        assertThat(saved.path("revision").path("reviewer_id").asText()).isEqualTo(ACTOR);
        assertThat(saved.path("revision").path("originating_run_ids").get(0).asText()).isEqualTo(run);
        before = database();
        assertThat(success(post("/local/reviews/import"), body).path("data").path("already_imported").asBoolean()).isTrue();
        assertThat(database()).isEqualTo(before);
        var completed = (ObjectNode) saved.deepCopy();
        var facts = (ObjectNode) completed.path("event");
        facts.put("area_membership", "verified");
        var next = (ObjectNode) completed.path("revision");
        next.put("revision_id", UUID.randomUUID().toString()).put("revision_no", 2).put("reviewer_id", ACTOR)
                .put("reviewed_at", Instant.now().truncatedTo(ChronoUnit.MICROS).toString());
        var change = next.withArray("human_overrides").addObject().put("field_path", "event").put("reason", "합성 구역 소속 대조")
                .put("reviewer", ACTOR).put("time", next.path("reviewed_at").asText());
        change.set("before", saved.path("event").deepCopy()); change.set("after", facts.deepCopy());
        var citations = change.putArray("evidence_ids");
        saved.path("evidence").forEach(item -> citations.add(item.path("evidence_id").asText()));
        var review = source.deepCopy(); review.put("schema_version", "reviewed-import-v1");
        review.set("evidence", completed.path("evidence")); review.set("human_handoffs", completed.path("human_handoffs"));
        facts.put("expected_revision_no", 1); facts.set("revision", next); review.putArray("events").add(facts);
        String completedId = success(put("/local/events/" + eventId + "/review"), raw(review)).path("data").path("revision_ids").get(0).asText();
        var reviewed = mapper.readTree(payload(completedId));
        assertThat(reviewed.path("revision").path("human_overrides")).hasSize(saved.path("revision").path("human_overrides").size() + 1);
        String approved = success(put("/local/events/" + eventId + "/review"), raw(decision(eventId, "approve", 2)))
                .path("data").path("revision_id").asText();
        var approvedPayload = mapper.readTree(payload(approved));
        assertThat(approvedPayload.path("revision").path("review_status").asText()).isEqualTo("approved");
        assertThat(approvedPayload.path("human_handoffs")).isEqualTo(saved.path("human_handoffs"));
        assertThat(approvedPayload.path("revision").path("human_overrides")).isEqualTo(reviewed.path("revision").path("human_overrides"));
        var publish = publish(approvedPayload.path("event").path("area_id").asText(), approved);
        publish.put("action", "preview");
        before = database(); files = fileHashes(root);
        assertThat(success(post("/local/publish"), raw(publish)).path("data").path("preview").path("event_count").asInt()).isEqualTo(1);
        assertThat(database()).isEqualTo(before); assertThat(fileHashes(root)).isEqualTo(files);
        publish.put("action", "publish");
        String snapshot = success(post("/local/publish"), raw(publish)).path("data").path("snapshot_id").asText();
        publicSnapshot(publish.path("case_id").asText(), snapshot, eventId, approved);
        assertThat(jdbc.queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", run)).isEqualTo(parent);
        assertThat(parent.get("status")).isEqualTo("failed");
        assertThat(fileHashes(handoff.image())).isEqualTo(image);
        assertRetained(body);
    }

    @Test
    void previewPublicationPublicReadsAndRollbackPreserveImmutableSnapshots() throws Exception {
        var input = fixtures.human(false);
        String eventId = event(input);
        success(put("/local/events/" + eventId + "/review"), raw(input));
        String approved = success(put("/local/events/" + eventId + "/review"), raw(decision(eventId, "approve", 1)))
                .path("data").path("revision_id").asText();
        var command = publish(input.path("events").get(0).path("area_id").asText(), approved);
        command.put("action", "preview");
        var before = database(); var files = fileHashes(root);
        var preview = success(post("/local/publish"), raw(command)).path("data");
        assertThat(preview.path("preview").path("event_count").asInt()).isEqualTo(1);
        assertThat(preview.path("preview").path("revision_ids").get(0).asText()).isEqualTo(approved);
        assertThat(database()).isEqualTo(before); assertThat(fileHashes(root)).isEqualTo(files);
        command.put("action", "publish");
        var first = success(post("/local/publish"), raw(command)).path("data");
        String firstId = first.path("snapshot_id").asText();
        String firstCanonical = canonical(firstId);
        String caseId = command.path("case_id").asText();
        publicSnapshot(caseId, firstId, eventId, approved);
        command.put("expected_head_version", first.path("head_version").asLong()).put("reason", "합성 다음 공개본");
        var second = success(post("/local/publish"), raw(command)).path("data");
        String secondId = second.path("snapshot_id").asText(), secondCanonical = canonical(secondId);
        assertThat(secondId).isNotEqualTo(firstId);
        publicSnapshot(caseId, secondId, eventId, approved);
        publicMvc.perform(get("/api/v1/events/" + eventId).param("snapshot_id", firstId))
                .andExpect(status().isConflict()).andExpect(jsonPath("$.error.code").value("SNAPSHOT_RETIRED"));
        before = database();
        error(post("/local/publish"), raw(command), 409, "PUBLICATION_CONFLICT");
        assertThat(database()).isEqualTo(before);
        assertThat(canonical(firstId)).isEqualTo(firstCanonical);
        assertThat(canonical(secondId)).isEqualTo(secondCanonical);
        var rollback = mapper.createObjectNode().put("schema_version", "publication-command-v1").put("action", "rollback")
                .put("reason", "합성 이전 공개본 복구").put("mode", "replay").put("case_id", caseId)
                .put("snapshot_id", firstId).put("expected_head_version", second.path("head_version").asLong());
        var restored = success(post("/local/publish"), raw(rollback)).path("data");
        assertThat(restored.path("head_version").asLong()).isGreaterThan(second.path("head_version").asLong());
        publicSnapshot(caseId, firstId, eventId, approved);
        assertThat(canonical(firstId)).isEqualTo(firstCanonical);
        assertThat(canonical(secondId)).isEqualTo(secondCanonical);
    }

    @Test
    void requestFileConflictAndAuthenticationFailureCannotWriteBusinessRows() throws Exception {
        var source = fixtures.source(false);
        byte[] body = raw(source);
        Path target = requests.resolve(ReviewedImportReader.sha256(body) + ".json");
        Files.writeString(target, "SYNTHETIC_EXISTING_CANARY");
        Files.setPosixFilePermissions(target, PosixFilePermissions.fromString("rw-------"));
        var before = database();
        byte[] original = Files.readAllBytes(root.resolve("synthetic-source.txt"));
        error(post("/local/documents"), body, 409, "LOCAL_API_REQUEST_CONFLICT");
        assertThat(database()).isEqualTo(before);
        assertThat(Files.readString(target)).isEqualTo("SYNTHETIC_EXISTING_CANARY");
        Files.delete(target);
        Path canary = Files.writeString(root.resolve("unrelated"), "SYNTHETIC_UNRELATED_CANARY");
        Files.createSymbolicLink(target, canary);
        error(post("/local/documents"), body, 409, "LOCAL_API_REQUEST_CONFLICT");
        assertThat(database()).isEqualTo(before);
        assertThat(Files.isSymbolicLink(target)).isTrue();
        assertThat(Files.readString(canary)).isEqualTo("SYNTHETIC_UNRELATED_CANARY");
        var files = fileHashes(requests);
        local.perform(auth(post("/local/documents")).header("Authorization", "Bearer wrong").content(body))
                .andExpect(status().isUnauthorized()).andExpect(jsonPath("$.error.code").value("LOCAL_API_UNAUTHORIZED"));
        assertThat(database()).isEqualTo(before);
        assertThat(fileHashes(requests)).isEqualTo(files);
        assertThat(Files.readAllBytes(root.resolve("synthetic-source.txt"))).isEqualTo(original);
    }

    private MockMvc localMvc(Path extractionRoot, Path handoffRoot) {
        var env = new MockEnvironment().withProperty("myai.local-api.token", TOKEN).withProperty("myai.local-api.actor", ACTOR)
                .withProperty("myai.local-api.source-root", root.toString()).withProperty("myai.local-api.extraction-root", extractionRoot.toString())
                .withProperty("myai.local-api.handoff-root", handoffRoot.toString());
        var service = new LocalManagementService(reader, commands, imports, extractions, handoffs, publication,
                new LocalRequestStore(requests.toString()), env);
        return MockMvcBuilders.standaloneSetup(new LocalManagementController(service))
                .setControllerAdvice(new ApiExceptionHandler(), new LocalBodyLimitAdvice())
                .setMessageConverters(new ByteArrayHttpMessageConverter(), new MappingJackson2HttpMessageConverter(mapper))
                .addFilters(new PublicRequestLogFilter(), new LocalApiSecurityFilter(env, mapper)).build();
    }

    private MockHttpServletRequestBuilder auth(MockHttpServletRequestBuilder request) {
        return request.contentType(MediaType.APPLICATION_JSON).header("Authorization", "Bearer " + TOKEN)
                .header("Host", "127.0.0.1:49123").header("Origin", "http://127.0.0.1:49123").with(input -> {
                    input.setLocalAddr("127.0.0.1"); input.setRemoteAddr("127.0.0.1");
                    input.setLocalPort(49123); input.setServerPort(49123); return input;
                });
    }

    private JsonNode success(MockHttpServletRequestBuilder request, byte[] body) throws Exception {
        var response = local.perform(auth(request).content(body)).andExpect(status().isOk())
                .andExpect(jsonPath("$.schema_version").value("local-management-result-v1"))
                .andExpect(jsonPath("$.request_sha256").value(ReviewedImportReader.sha256(body)))
                .andReturn().getResponse();
        return mapper.readTree(response.getContentAsByteArray());
    }

    private void error(MockHttpServletRequestBuilder request, byte[] body, int status, String code) throws Exception {
        var response = local.perform(auth(request).content(body)).andExpect(status().is(status))
                .andExpect(jsonPath("$.error.code").value(code)).andReturn().getResponse().getContentAsString(StandardCharsets.UTF_8);
        assertThat(response).doesNotContain(root.toString(), TOKEN, "SYNTHETIC_EXISTING_CANARY", "SYNTHETIC_UNRELATED_CANARY");
    }

    private ObjectNode extraction(String run, String hash) {
        return mapper.createObjectNode().put("schema_version", "extraction-import-request-v1").put("run_id", run).put("expected_input_hash", hash);
    }

    private ObjectNode decision(String eventId, String action, long expected) throws Exception {
        var command = mapper.createObjectNode().put("schema_version", "publication-command-v1").put("action", action)
                .put("reason", "합성 HTTP 검토 결정").put("event_id", eventId).put("expected_revision_no", expected);
        var ids = command.putArray("evidence_ids");
        mapper.readTree(payload(current(eventId))).path("evidence").forEach(item -> ids.add(item.path("evidence_id").asText()));
        return command;
    }

    private ObjectNode publish(String area, String revision) throws Exception {
        var command = (ObjectNode) mapper.readTree(Path.of("examples/publish.json").toFile());
        String caseId = UUID.randomUUID().toString(); ownedCases.add(caseId);
        command.put("mode", "replay").put("case_id", caseId).put("anchor_date", "2026-11-03")
                .put("reference_instant", "2026-11-03T00:00:00Z").put("knowledge_cutoff", "2026-11-03T00:00:00Z")
                .put("history_fidelity", "reconstructed");
        ((ObjectNode) command.path("area")).put("area_id", area);
        for (var point : command.path("points")) ((ObjectNode) point).put("area_id", area).put("point_id", UUID.randomUUID().toString());
        command.putArray("revision_ids").add(revision); return command;
    }

    private void publicSnapshot(String caseId, String snapshot, String eventId, String revision) throws Exception {
        publicMvc.perform(get("/api/v1/config").param("mode", "replay").param("case_id", caseId)).andExpect(status().isOk())
                .andExpect(jsonPath("$.snapshot_id").value(snapshot)).andExpect(jsonPath("$.data.points.length()").value(5));
        publicMvc.perform(get("/api/v1/events/" + eventId).param("snapshot_id", snapshot)).andExpect(status().isOk())
                .andExpect(jsonPath("$.data.event.event_id").value(eventId)).andExpect(jsonPath("$.data.event.revision_id").value(revision));
    }

    private byte[] raw(JsonNode input) { return (" \n" + input.toPrettyString() + "\n ").getBytes(StandardCharsets.UTF_8); }
    private void assertRetained(byte[] body) throws Exception {
        Path file = requests.resolve(ReviewedImportReader.sha256(body) + ".json");
        assertThat(Files.readAllBytes(file)).isEqualTo(body);
        assertThat(Files.getPosixFilePermissions(file)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
    }
    private String current(String eventId) { return jdbc.queryForObject("SELECT current_review_revision_id FROM events WHERE event_id=?", String.class, eventId); }
    private String payload(String revision) { return jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id=?", String.class, revision); }
    private String canonical(String snapshot) { return jdbc.queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id=?", String.class, snapshot); }

    private Map<String, String> fileHashes(Path directory) throws Exception {
        var hashes = new LinkedHashMap<String, String>();
        try (var stream = Files.walk(directory)) {
            for (Path file : stream.filter(Files::isRegularFile).sorted().toList())
                hashes.put(directory.relativize(file).toString(), ReviewedImportReader.sha256(Files.readAllBytes(file)));
        }
        return hashes;
    }

    private Map<String, List<Map<String, String>>> database() {
        var result = new LinkedHashMap<String, List<Map<String, String>>>();
        for (String table : List.of("test_points", "place_dictionary", "documents", "document_versions", "source_checks", "extraction_runs",
                "events", "event_revisions", "review_audits", "snapshots", "snapshot_revisions", "publication_heads", "import_batches", "publication_audits", "source_reviews")) {
            var rows = new ArrayList<Map<String, String>>();
            for (var row : jdbc.queryForList("SELECT * FROM " + table + " ORDER BY 1,2")) {
                var values = new LinkedHashMap<String, String>(); row.forEach((key, value) -> values.put(key, value == null ? null : value.toString())); rows.add(values);
            }
            result.put(table, rows);
        }
        return result;
    }
}
