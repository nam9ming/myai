package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.calculation.PythonCalculator;
import kr.ac.myai.backend.controller.ApiExceptionHandler;
import kr.ac.myai.backend.dto.MatchRequest;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.repository.PublicSnapshotRepository;
import kr.ac.myai.backend.service.SnapshotNoticeService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;

import java.nio.file.Path;
import java.time.*;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

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
        var service = service(CalculationFixtures.snapshot(mapper), calculator(probe), fixed); var q = query();
        var error = (ApiException) catchThrowable(() -> service.matches(q));
        var response = new ApiExceptionHandler().domain(error);
        assertThat(response.getStatusCode().value()).isEqualTo(500);
        assertThat(output.getAll()).contains(response.getBody().requestId(), "CALCULATION_PROTOCOL_ERROR")
                .doesNotContain("PRIVATE_PATH", root.toString());
    }

    private SnapshotNoticeService service(ObjectNode snapshot, PythonCalculator calculator, Clock clock) throws Exception {
        var repository = mock(PublicSnapshotRepository.class);
        var row = CalculationFixtures.published(snapshot, mapper);
        String channel = row.snapshot().mode().equals("current") ? "current" : "replay:" + row.snapshot().caseId();
        when(repository.head(channel)).thenReturn(Optional.of(row.snapshot().id()));
        when(repository.published(row.snapshot().id())).thenReturn(Optional.of(row));
        return new SnapshotNoticeService(repository, new PublicationContent(json, mapper), mapper, calculator, clock);
    }

    private PythonCalculator calculator(Path workdir) {
        return new PythonCalculator(mapper, json, PythonProbe.PYTHON, workdir.toString(), 5000);
    }

    private MatchRequest query() throws Exception {
        return mapper.treeToValue(mapper.readTree(PythonProbe.REPO.resolve("processing/examples/match-input.json").toFile()).path("query"), MatchRequest.class);
    }
}
