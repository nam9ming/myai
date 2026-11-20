package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.calculation.PythonCalculator;
import kr.ac.myai.backend.controller.ApiExceptionHandler;
import kr.ac.myai.backend.controller.PublicNoticeController;
import kr.ac.myai.backend.dto.MatchRequest;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.repository.PublicSnapshotRepository;
import kr.ac.myai.backend.service.SnapshotNoticeService;
import kr.ac.myai.backend.logging.PublicRequestLogFilter;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.http.MediaType;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.nio.file.Path;
import java.time.*;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;

@ExtendWith(OutputCaptureExtension.class)
class SnapshotCalculationTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    final ReviewedImportReader json = new ReviewedImportReader();
    final Clock fixed = Clock.fixed(Instant.parse("2026-11-03T02:00:00Z"), ZoneOffset.UTC);

    @AfterEach
    void cleanup() throws Exception { PythonProbe.stopAll(root); }

    @Test
    void calculatesRealPythonAndPreservesAllJavaPublicFacts() throws Exception {
        var result = service(CalculationFixtures.snapshot(mapper), calculator(PythonProbe.REPO), fixed).matches(query());
        assertThat(result.path("schema_version").asText()).isEqualTo("api-v1");
        var data = result.path("data"); var item = data.path("items").get(0);
        assertThat(data.path("counts").path("candidate").asInt()).isEqualTo(1);
        assertThat(item.path("time_overlap_minutes").asDouble()).isEqualTo(120);
        var expected = json.readJson(PythonProbe.REPO.resolve("contracts/examples/event-facts-response.json")).path("data").path("event");
        expected.fieldNames().forEachRemaining(key -> { if (!key.equals("history")) assertThat(item.path(key)).as(key).isEqualTo(expected.path(key)); });
        assertThat(data.has("diagnostics")).isFalse();
        assertThat(result.has("input_sha256")).isFalse();
    }

    @Test
    void forwardsOriginalCanonicalChecksumAndDeduplicatesTypeFilter() throws Exception {
        var snapshot = CalculationFixtures.snapshot(mapper);
        Path probe = PythonProbe.realEngine(root, "Path('request.json').write_text(json.dumps(request))");
        var query = query();
        query = new MatchRequest(query.pointId(), query.weeklyHours(), query.mode(), null, java.util.List.of("construction", "construction"), null, null, null);
        service(snapshot, calculator(probe), fixed).matches(query);
        var sent = mapper.readTree(probe.resolve("request.json").toFile());
        assertThat(sent.path("snapshot_checksum").asText()).isEqualTo(CalculationFixtures.published(snapshot, mapper).snapshot().checksum());
        assertThat(sent.path("query").path("types").size()).isEqualTo(1);
        assertThat(sent.path("query").path("selection").asText()).isEqualTo("candidate");
    }

    @Test
    void fixesOneCurrentClockInstantAcrossMidnight() throws Exception {
        var calls = new AtomicInteger();
        Clock clock = new Clock() {
            public ZoneId getZone() { return ZoneOffset.UTC; }
            public Clock withZone(ZoneId zone) { return this; }
            public Instant instant() { return Instant.parse(calls.getAndIncrement() == 0 ? "2026-11-03T14:59:59.999999999Z" : "2026-11-03T15:00:00Z"); }
        };
        var q = query(); q = new MatchRequest(q.pointId(), q.weeklyHours(), q.mode(), null, q.types(), null, "needs_check", null);
        var data = service(CalculationFixtures.snapshot(mapper), calculator(PythonProbe.REPO), clock).matches(q).path("data");
        assertThat(data.path("query_context").path("anchor_date").asText()).isEqualTo("2026-11-03");
        assertThat(data.path("counts").path("needs_check").asInt()).isEqualTo(1);
        assertThat(calls.get()).isEqualTo(1);
    }

    @Test
    void replayUsesSnapshotClockAndAvailabilityContext() throws Exception {
        var snapshot = CalculationFixtures.snapshot(mapper); String id = UUID.randomUUID().toString();
        snapshot.put("mode", "replay").put("case_id", id).put("anchor_date", "2026-11-02")
                .put("reference_instant", "2026-11-02T12:00:00Z").put("knowledge_cutoff", "2026-11-02T11:00:00Z").put("history_fidelity", "verified_snapshot");
        var q = query(); q = new MatchRequest(q.pointId(), q.weeklyHours(), "replay", UUID.fromString(id), q.types(), null, null, null);
        var data = service(snapshot, calculator(PythonProbe.REPO), fixed).matches(q).path("data");
        assertThat(data.path("counts").path("candidate").asInt()).isEqualTo(1);
        assertThat(data.path("query_context").path("reference_instant").asText()).isEqualTo("2026-11-02T12:00:00Z");
        assertThat(data.path("query_context").path("anchor_date").asText()).isEqualTo("2026-11-02");
    }

    @Test
    void rejectsInconsistentDataEvenWhenProtocolEchoIsCorrect() throws Exception {
        var mutations = java.util.List.of(
                "response['data']['private_path']='PRIVATE_PATH'", "del response['data']['items']",
                "response['data']['query_context']['anchor_date']='2026-11-04'",
                "response['data']['counts']['candidate']=2", "response['data']['counts']['cancelled']=-1",
                "response['data']['rules_version']='wrong'", "response['data']['data_kind']='real'",
                "response['data']['items'][0]['classification']='cancelled'",
                "response['data']['items'][0]['title']='wrong'", "response['data']['items'][0]['revision_id']='wrong'",
                "response['data']['items'][0]['evidence'][0]['quote']='wrong'", "response['data']['items'][0]['private_path']='PRIVATE_PATH'",
                "response['data']['items'][0]['distance_m']=-1", "response['data']['items'][0]['time_overlap_minutes']='120'",
                "response['data']['items'][0]['distance_basis']='fake'", "response['data']['items'][0]['reason_codes']=['PRIVATE_PATH']",
                "response['data']['items'][0]['warnings']=[{}]", "response['data']['items'][0]['matched_occurrence_ids']=['wrong']",
                "response['data']['overlap_groups']=[dict(group_id='wrong',start_at='wrong',end_at='wrong',event_ids=[])]");
        for (String mutation : mutations) {
            Path probe = PythonProbe.realEngine(root, mutation);
            var service = service(CalculationFixtures.snapshot(mapper), calculator(probe), fixed);
            var q = query();
            var error = catchThrowable(() -> service.matches(q));
            assertThat(error).as(mutation).isInstanceOf(ApiException.class);
            assertThat(((ApiException) error).code()).as(mutation).isEqualTo("CALCULATION_PROTOCOL_ERROR");
        }
    }

    @Test
    void validatesPointBeforeUnavailableRuntimeAndReturnsNonRetryableConfigurationError() throws Exception {
        var service = service(CalculationFixtures.snapshot(mapper), calculator(root.resolve("missing")), fixed);
        var q = query();
        var valid = catchThrowable(() -> service.matches(q));
        assertThat(valid).isInstanceOf(ApiException.class);
        var http = new ApiExceptionHandler().domain((ApiException) valid);
        assertThat(http.getStatusCode().value()).isEqualTo(503);
        assertThat(http.getBody().error().retryable()).isFalse();
        var invalid = new MatchRequest(UUID.randomUUID(), q.weeklyHours(), q.mode(), null, q.types(), null, null, null);
        var point = catchThrowable(() -> service.matches(invalid));
        assertThat(((ApiException) point).code()).isEqualTo("INVALID_POINT");
    }

    @Test
    void protocolErrorLogsOnlySafePublicRequestId(CapturedOutput output) throws Exception {
        Path probe = PythonProbe.realEngine(root, "response['private_path']='PRIVATE_PATH'");
        var snapshot = CalculationFixtures.snapshot(mapper);
        var service = service(snapshot, calculator(probe), fixed);
        var response = mvc(service).perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON)
                .content(mapper.writeValueAsBytes(query()))).andReturn().getResponse();
        assertThat(response.getStatus()).isEqualTo(500);
        var body = mapper.readTree(response.getContentAsByteArray());
        assertThat(body.path("request_id").textValue()).isEqualTo(response.getHeader("X-Request-ID"));
        var log = requestLog(output, response);
        assertThat(log.path("error_code").textValue()).isEqualTo("CALCULATION_PROTOCOL_ERROR");
        assertThat(log.path("snapshot_id")).isEqualTo(snapshot.path("snapshot_id"));
        assertThat(log.path("rules_version")).isEqualTo(snapshot.path("rules_version"));
        assertThat(output.getAll())
                .doesNotContain("PRIVATE_PATH", root.toString());
    }

    @Test
    void selectedConfigMetadataSurvivesReplayFailure(CapturedOutput output) throws Exception {
        var snapshot = CalculationFixtures.snapshot(mapper);
        var replay = snapshot.deepCopy().put("snapshot_id", UUID.randomUUID().toString()).put("mode", "replay")
                .put("case_id", UUID.randomUUID().toString()).put("rules_version", "other-rules")
                .put("anchor_date", "2026-11-02").put("reference_instant", "2026-11-02T12:00:00Z")
                .put("knowledge_cutoff", "2026-11-02T11:00:00Z").put("history_fidelity", "verified_snapshot");
        var repository = mock(PublicSnapshotRepository.class);
        var row = CalculationFixtures.published(snapshot, mapper);
        var replayRow = CalculationFixtures.published(replay, mapper);
        when(repository.head("current")).thenReturn(Optional.of(row.snapshot().id()));
        when(repository.published(row.snapshot().id())).thenReturn(Optional.of(row));
        when(repository.replayHeads(anyString(), anyString())).thenReturn(java.util.List.of(replayRow.snapshot().id()));
        when(repository.published(replayRow.snapshot().id())).thenReturn(Optional.of(new PublicSnapshotRepository.Published(
                replayRow.snapshot(), "invalid-schema", replayRow.createdAt(), replayRow.currentId())));
        var response = mvc(service(repository, calculator(PythonProbe.REPO), fixed)).perform(get("/api/v1/config"))
                .andReturn().getResponse();
        assertThat(response.getStatus()).isEqualTo(500);
        var log = requestLog(output, response);
        assertThat(log.path("error_code").textValue()).isEqualTo("SNAPSHOT_INVALID");
        assertThat(log.path("snapshot_id")).isEqualTo(snapshot.path("snapshot_id"));
        assertThat(log.path("rules_version")).isEqualTo(snapshot.path("rules_version"));
    }

    @Test
    void detailKeepsSelectedRulesInsteadOfHistoricSnapshot(CapturedOutput output) throws Exception {
        var snapshot = CalculationFixtures.snapshot(mapper);
        var older = snapshot.deepCopy().put("snapshot_id", UUID.randomUUID().toString()).put("rules_version", "older-rules");
        String oldRevision = UUID.randomUUID().toString();
        ((ObjectNode) older.path("event_public_payloads").get(0)).put("revision_id", oldRevision);
        older.putArray("revision_ids").add(oldRevision);
        var repository = mock(PublicSnapshotRepository.class);
        var row = CalculationFixtures.published(snapshot, mapper);
        var oldRow = CalculationFixtures.published(older, mapper);
        String eventId = snapshot.path("event_public_payloads").get(0).path("event_id").asText();
        when(repository.published(row.snapshot().id())).thenReturn(Optional.of(row));
        when(repository.published(oldRow.snapshot().id())).thenReturn(Optional.of(oldRow));
        when(repository.history(eventId, "current", row.snapshot().id())).thenReturn(java.util.List.of(
                new PublicSnapshotRepository.Historic(oldRow.snapshot().id(), oldRevision, fixed.instant(), "publish"),
                new PublicSnapshotRepository.Historic(row.snapshot().id(), snapshot.path("revision_ids").get(0).asText(), fixed.instant(), "publish")));
        var response = mvc(service(repository, calculator(PythonProbe.REPO), fixed)).perform(get("/api/v1/events/" + eventId)
                .param("snapshot_id", row.snapshot().id())).andReturn().getResponse();
        assertThat(response.getStatus()).isEqualTo(200);
        var body = mapper.readTree(response.getContentAsByteArray());
        assertThat(body.path("data").has("rules_version")).isFalse();
        assertThat(body.path("data").path("event").path("history").size()).isEqualTo(1);
        var log = requestLog(output, response);
        assertThat(log.path("snapshot_id")).isEqualTo(snapshot.path("snapshot_id"));
        assertThat(log.path("rules_version")).isEqualTo(snapshot.path("rules_version"));
    }

    @Test
    void retiredSnapshotDoesNotLogUnselectedCurrentId(CapturedOutput output) throws Exception {
        var snapshot = CalculationFixtures.snapshot(mapper);
        var row = CalculationFixtures.published(snapshot, mapper);
        String currentId = UUID.randomUUID().toString();
        var repository = mock(PublicSnapshotRepository.class);
        when(repository.published(row.snapshot().id())).thenReturn(Optional.of(new PublicSnapshotRepository.Published(
                row.snapshot(), row.schemaVersion(), row.createdAt(), currentId)));
        String eventId = snapshot.path("event_public_payloads").get(0).path("event_id").asText();
        var response = mvc(service(repository, calculator(PythonProbe.REPO), fixed)).perform(get("/api/v1/events/" + eventId)
                .param("snapshot_id", row.snapshot().id())).andReturn().getResponse();
        assertThat(response.getStatus()).isEqualTo(409);
        assertThat(mapper.readTree(response.getContentAsByteArray()).path("current_snapshot_id").asText()).isEqualTo(currentId);
        var log = requestLog(output, response);
        assertThat(log.path("error_code").textValue()).isEqualTo("SNAPSHOT_RETIRED");
        assertThat(log.path("snapshot_id").isNull()).isTrue();
        assertThat(log.path("rules_version").isNull()).isTrue();
    }

    @Test
    void rejectsNonCandidateOverlapReferences() throws Exception {
        Path probe = PythonProbe.realEngine(root, """
                candidate = json.loads(raw)
                candidate['query']['selection'] = 'candidate'
                item = run(json.dumps(candidate).encode())['data']['items'][0]
                item.update(classification='needs_check', reason_codes=['TIME_UNKNOWN'])
                response['data']['items'] = [item]
                response['data']['counts'] = dict(candidate=2, needs_check=1, cancelled=0)
                members = response['data']['overlap_groups'][0]['event_ids']
                response['data']['overlap_groups'][0]['event_ids'] = [item['event_id'], next(v for v in members if v != item['event_id'])]
                """);
        var q = query(); q = new MatchRequest(q.pointId(), q.weeklyHours(), q.mode(), null, q.types(), null, "needs_check", null);
        var service = service(snapshotWithEvents(3), calculator(probe), fixed); var request = q;
        assertThat(catchThrowable(() -> service.matches(request))).isInstanceOfSatisfying(ApiException.class,
                error -> assertThat(error.code()).isEqualTo("CALCULATION_PROTOCOL_ERROR"));
    }

    @Test
    void rejectsOverlapUnionAboveCandidateCount() throws Exception {
        Path probe = PythonProbe.realEngine(root, """
                members = response['data']['overlap_groups'][0]['event_ids']
                response['data']['counts']['candidate'] = 2
                response['data']['overlap_groups'] = [
                    dict(group_id='20000000-0000-4000-8000-000000000001', start_at='2026-11-03T01:00:00Z', end_at='2026-11-03T02:00:00Z', event_ids=members[:2]),
                    dict(group_id='20000000-0000-4000-8000-000000000002', start_at='2026-11-03T02:00:00Z', end_at='2026-11-03T03:00:00Z', event_ids=members[2:])]
                """);
        var q = query(); q = new MatchRequest(q.pointId(), q.weeklyHours(), q.mode(), null, q.types(), null, "needs_check", null);
        var service = service(snapshotWithEvents(4), calculator(probe), fixed); var request = q;
        assertThat(catchThrowable(() -> service.matches(request))).isInstanceOfSatisfying(ApiException.class,
                error -> assertThat(error.code()).isEqualTo("CALCULATION_PROTOCOL_ERROR"));
    }

    @Test
    void rejectsCancelledResultForActiveFacts() throws Exception {
        Path probe = PythonProbe.realEngine(root, """
                candidate = json.loads(raw)
                candidate['query']['selection'] = 'candidate'
                item = run(json.dumps(candidate).encode())['data']['items'][0]
                item.update(classification='cancelled', reason_codes=['CANCELLED'])
                response['data']['items'] = [item]
                response['data']['counts'] = dict(candidate=0, needs_check=0, cancelled=1)
                """);
        var q = query(); q = new MatchRequest(q.pointId(), q.weeklyHours(), q.mode(), null, q.types(), null, "cancelled", null);
        var service = service(CalculationFixtures.snapshot(mapper), calculator(probe), fixed); var request = q;
        assertThat(catchThrowable(() -> service.matches(request))).isInstanceOfSatisfying(ApiException.class,
                error -> assertThat(error.code()).isEqualTo("CALCULATION_PROTOCOL_ERROR"));
    }

    @Test
    void rejectsUnselectedCountsThatContradictFrozenLifecycle() throws Exception {
        for (String lifecycle : java.util.List.of("active", "cancelled")) {
            var snapshot = CalculationFixtures.snapshot(mapper); var event = (ObjectNode) snapshot.path("event_public_payloads").get(0);
            event.put("lifecycle", lifecycle).putArray("lifecycle_evidence_ids").add("body-quote");
            String counts = lifecycle.equals("active") ? "dict(candidate=0, needs_check=0, cancelled=1)" : "dict(candidate=0, needs_check=1, cancelled=0)";
            Path probe = PythonProbe.realEngine(root, "response['data']['items']=[]\nresponse['data']['counts']=" + counts);
            var service = service(snapshot, calculator(probe), fixed); var request = query();
            assertThat(catchThrowable(() -> service.matches(request))).as(lifecycle).isInstanceOfSatisfying(ApiException.class,
                    error -> assertThat(error.code()).isEqualTo("CALCULATION_PROTOCOL_ERROR"));
        }
    }

    @Test
    void rejectsCandidateCountsForUncertainFacts() throws Exception {
        for (String field : java.util.List.of("lifecycle", "area_membership")) {
            var snapshot = CalculationFixtures.snapshot(mapper); ((ObjectNode) snapshot.path("event_public_payloads").get(0)).put(field, "uncertain");
            Path probe = PythonProbe.realEngine(root, "response['data']['items']=[]\nresponse['data']['counts']=dict(candidate=1, needs_check=0, cancelled=0)");
            var q = query(); var request = new MatchRequest(q.pointId(), q.weeklyHours(), q.mode(), null, q.types(), null, "needs_check", null);
            var service = service(snapshot, calculator(probe), fixed);
            assertThat(catchThrowable(() -> service.matches(request))).as(field).isInstanceOfSatisfying(ApiException.class,
                    error -> assertThat(error.code()).isEqualTo("CALCULATION_PROTOCOL_ERROR"));
        }
    }

    @Test
    void rejectsNonCancelledCountsAboveFrozenNonCancelledFacts() throws Exception {
        var snapshot = snapshotWithEvents(2); var event = (ObjectNode) snapshot.path("event_public_payloads").get(1);
        event.put("lifecycle", "cancelled").putArray("lifecycle_evidence_ids").add("body-quote");
        Path probe = PythonProbe.realEngine(root, "response['data']['items']=[]\nresponse['data']['counts']=dict(candidate=1, needs_check=1, cancelled=0)");
        var q = query(); var request = new MatchRequest(q.pointId(), q.weeklyHours(), q.mode(), null, q.types(), null, "cancelled", null);
        var service = service(snapshot, calculator(probe), fixed);
        assertThat(catchThrowable(() -> service.matches(request))).isInstanceOfSatisfying(ApiException.class,
                error -> assertThat(error.code()).isEqualTo("CALCULATION_PROTOCOL_ERROR"));
    }

    private ObjectNode snapshotWithEvents(int count) throws Exception {
        var snapshot = CalculationFixtures.snapshot(mapper); var events = snapshot.withArray("event_public_payloads");
        for (int i = 1; i < count; i++) {
            var event = ((ObjectNode) events.get(0)).deepCopy();
            event.put("event_id", UUID.randomUUID().toString()).put("revision_id", UUID.randomUUID().toString());
            events.add(event); snapshot.withArray("revision_ids").add(event.path("revision_id"));
        }
        return snapshot.put("event_count", count);
    }

    private SnapshotNoticeService service(ObjectNode snapshot, PythonCalculator calculator, Clock clock) throws Exception {
        var repository = mock(PublicSnapshotRepository.class);
        var row = CalculationFixtures.published(snapshot, mapper);
        String channel = row.snapshot().mode().equals("current") ? "current" : "replay:" + row.snapshot().caseId();
        when(repository.head(channel)).thenReturn(Optional.of(row.snapshot().id()));
        when(repository.published(row.snapshot().id())).thenReturn(Optional.of(row));
        return service(repository, calculator, clock);
    }

    private SnapshotNoticeService service(PublicSnapshotRepository repository, PythonCalculator calculator, Clock clock) {
        var transactions = mock(org.springframework.transaction.PlatformTransactionManager.class);
        when(transactions.getTransaction(any())).thenReturn(new org.springframework.transaction.support.SimpleTransactionStatus());
        return new SnapshotNoticeService(repository, new PublicationContent(json, mapper), mapper, calculator, clock, transactions);
    }

    private MockMvc mvc(SnapshotNoticeService service) {
        return MockMvcBuilders.standaloneSetup(new PublicNoticeController(service)).setControllerAdvice(new ApiExceptionHandler())
                .setMessageConverters(new MappingJackson2HttpMessageConverter(mapper)).addFilters(new PublicRequestLogFilter()).build();
    }

    private JsonNode requestLog(CapturedOutput output, MockHttpServletResponse response) throws Exception {
        var logs = new java.util.ArrayList<JsonNode>();
        for (String line : output.getAll().split("\n")) {
            int start = line.indexOf("public_request ");
            if (start >= 0) {
                var log = mapper.readTree(line.substring(start + "public_request ".length()));
                if (log.path("request_id").asText().equals(response.getHeader("X-Request-ID"))) logs.add(log);
            }
        }
        assertThat(logs).hasSize(1);
        assertThat(logs.getFirst().size()).isEqualTo(5);
        return logs.getFirst();
    }

    private PythonCalculator calculator(Path workdir) {
        return new PythonCalculator(mapper, json, PythonProbe.PYTHON, workdir.toString(), 5000);
    }

    private MatchRequest query() throws Exception {
        return mapper.treeToValue(mapper.readTree(PythonProbe.REPO.resolve("processing/examples/match-input.json").toFile()).path("query"), MatchRequest.class);
    }
}
