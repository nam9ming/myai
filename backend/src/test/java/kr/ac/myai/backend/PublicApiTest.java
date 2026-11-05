package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.core.io.ClassPathResource;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import java.util.UUID;
import java.util.List;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("fixture")
@ExtendWith(OutputCaptureExtension.class)
class PublicApiTest {
    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;

    private JsonNode fixture(String name) throws Exception {
        try (var input = new ClassPathResource("fixtures/" + name + ".json").getInputStream()) {
            return mapper.readTree(input);
        }
    }

    @Test
    void shouldServeSyntheticConfigAndHealth() throws Exception {
        mvc.perform(get("/health")).andExpect(status().isOk()).andExpect(jsonPath("$.status").value("UP"));
        var result = mvc.perform(get("/api/v1/config"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.data_kind").value("synthetic"))
                .andReturn();
        assertThat(mapper.readTree(result.getResponse().getContentAsByteArray())).isEqualTo(fixture("config-response"));
    }

    @Test
    void shouldServeContractMatchesAndAcceptPinnedSnapshot() throws Exception {
        ObjectNode query = (ObjectNode) fixture("matches-request");
        var result = mvc.perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content(query.toString()))
                .andExpect(status().isOk()).andReturn();
        assertThat(mapper.readTree(result.getResponse().getContentAsByteArray())).isEqualTo(fixture("matches-response"));
        query.put("snapshot_id", fixture("config-response").path("snapshot_id").asText());
        mvc.perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content(query.toString()))
                .andExpect(status().isOk());
    }

    @Test
    void shouldServeEveryListedEventInSameSnapshot() throws Exception {
        String snapshot = fixture("config-response").path("snapshot_id").asText();
        for (JsonNode event : fixture("public-events")) {
            var result = mvc.perform(get("/api/v1/events/" + event.path("event_id").asText()).param("snapshot_id", snapshot))
                    .andExpect(status().isOk()).andReturn();
            assertThat(mapper.readTree(result.getResponse().getContentAsByteArray()).path("data").path("event")).isEqualTo(event);
        }
    }

    @Test
    void shouldRejectUnknownSnapshotAndEvent() throws Exception {
        String event = fixture("event-response").path("data").path("event").path("event_id").asText();
        mvc.perform(get("/api/v1/events/" + event).param("snapshot_id", UUID.randomUUID().toString()))
                .andExpect(status().isNotFound()).andExpect(jsonPath("$.error.code").value("SNAPSHOT_NOT_FOUND"));
        mvc.perform(get("/api/v1/events/" + UUID.randomUUID()).param("snapshot_id", fixture("config-response").path("snapshot_id").asText()))
                .andExpect(status().isNotFound());
        mvc.perform(get("/api/v1/events/" + event)).andExpect(status().isUnprocessableEntity());
    }

    @Test
    void shouldRejectInvalidQueriesAndKeepErrorEnvelope() throws Exception {
        ObjectNode query = (ObjectNode) fixture("matches-request");
        query.put("point_id", "not-a-uuid");
        var result = mvc.perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content(query.toString()))
                .andExpect(status().isUnprocessableEntity()).andExpect(jsonPath("$.error.field_errors").isArray())
                .andExpect(jsonPath("$.error.retryable").value(false)).andReturn();
        JsonNode error = mapper.readTree(result.getResponse().getContentAsByteArray());
        assertThat(UUID.fromString(error.path("request_id").asText())).isNotNull();
        assertThat(error.has("trace")).isFalse();
        query = (ObjectNode) fixture("matches-request");
        query.put("radius_m", 999);
        mvc.perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content(query.toString()))
                .andExpect(status().isUnprocessableEntity());
        query.remove("radius_m");
        ((ObjectNode) query.path("weekly_hours")).remove("sunday");
        mvc.perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content(query.toString()))
                .andExpect(status().isUnprocessableEntity());
    }

    @Test
    void shouldValidateHoursAndRefuseUncalculatedConditions() throws Exception {
        ObjectNode query = (ObjectNode) fixture("matches-request");
        ((ObjectNode) query.path("weekly_hours").path("monday").path("intervals").get(0)).put("end", "08:00");
        mvc.perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content(query.toString()))
                .andExpect(status().isUnprocessableEntity());
        query = (ObjectNode) fixture("matches-request");
        query.put("point_id", fixture("config-response").path("data").path("points").get(1).path("point_id").asText());
        mvc.perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content(query.toString()))
                .andExpect(status().isServiceUnavailable()).andExpect(jsonPath("$.error.code").value("CALCULATOR_NOT_READY"));
    }

    @Test
    void shouldLimitPublicBodyAndNotExposeLocalRoutes() throws Exception {
        mvc.perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content(" ".repeat(32769) + "{}"))
                .andExpect(status().isPayloadTooLarge()).andExpect(jsonPath("$.error.code").value("PAYLOAD_TOO_LARGE"));
        mvc.perform(get("/local/documents")).andExpect(status().isNotFound());
        mvc.perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content("{"))
                .andExpect(status().isUnprocessableEntity());
    }

    @Test
    void shouldAllowOnlyConfiguredFrontendOrigin() throws Exception {
        mvc.perform(options("/api/v1/matches").header("Origin", "http://localhost:5173")
                        .header("Access-Control-Request-Method", "POST").header("Access-Control-Request-Headers", "content-type"))
                .andExpect(status().isOk()).andExpect(header().string("Access-Control-Allow-Origin", "http://localhost:5173"));
        mvc.perform(options("/api/v1/matches").header("Origin", "https://untrusted.example")
                        .header("Access-Control-Request-Method", "POST"))
                .andExpect(status().isForbidden());
    }

    @Test
    void shouldExposeServerRequestIdWithoutLoggingPrivateInputs(CapturedOutput output) throws Exception {
        var response = mvc.perform(get("/api/v1/config").param("private", "PRIVATE_QUERY")
                        .header("Origin", "http://localhost:5173").header("X-Request-ID", "PRIVATE_CLIENT_ID")
                        .header("User-Agent", "PRIVATE_AGENT").header("X-Forwarded-For", "PRIVATE_IP"))
                .andExpect(status().isOk())
                .andExpect(header().string("Access-Control-Expose-Headers", "X-Request-ID"))
                .andReturn().getResponse();
        String id = response.getHeader("X-Request-ID");
        assertThat(UUID.fromString(id).toString()).isEqualTo(id);
        assertThat(mapper.readTree(response.getContentAsByteArray())).isEqualTo(fixture("config-response"));
        var logs = requestLogs(output);
        assertThat(logs).hasSize(1);
        assertThat(logs.getFirst().path("request_id").asText()).isEqualTo(id);
        assertThat(logs.getFirst().path("snapshot_id")).isEqualTo(fixture("config-response").path("snapshot_id"));
        assertThat(logs.getFirst().path("rules_version").isNull()).isTrue();
        assertThat(output.getAll()).doesNotContain("PRIVATE_QUERY", "PRIVATE_CLIENT_ID", "PRIVATE_AGENT", "PRIVATE_IP");
    }

    @Test
    void shouldLogHealthValidationBodyLimitUnknownRouteAndCorsOnce(CapturedOutput output) throws Exception {
        var requests = List.of(get("/health"), get("/local/PRIVATE_ROUTE"),
                post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content(" ".repeat(32769) + "PRIVATE_BODY"),
                post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content("{"),
                options("/api/v1/matches").header("Origin", "https://PRIVATE_ORIGIN.example")
                        .header("Access-Control-Request-Method", "POST"));
        var codes = java.util.Arrays.asList(null, "NOT_FOUND", "PAYLOAD_TOO_LARGE", "INVALID_REQUEST", "HTTP_403");
        int[] statuses = {200, 404, 413, 422, 403};
        var ids = new java.util.HashSet<String>();
        for (int i = 0; i < requests.size(); i++) {
            var response = mvc.perform(requests.get(i)).andReturn().getResponse();
            assertThat(response.getStatus()).isEqualTo(statuses[i]);
            String id = response.getHeader("X-Request-ID");
            assertThat(UUID.fromString(id).toString()).isEqualTo(id);
            assertThat(ids.add(id)).isTrue();
            var logs = requestLogs(output);
            assertThat(logs).hasSize(i + 1);
            var log = logs.get(i);
            assertThat(log.size()).isEqualTo(5);
            assertThat(log.path("request_id").textValue()).isEqualTo(id);
            assertThat(log.path("error_code").textValue()).isEqualTo(codes.get(i));
            assertThat(log.path("latency_ms").isIntegralNumber()).isTrue();
            assertThat(log.path("latency_ms").longValue()).isGreaterThanOrEqualTo(0);
            assertThat(log.path("snapshot_id").isNull()).isTrue();
            assertThat(log.path("rules_version").isNull()).isTrue();
            if (i >= 1 && i <= 3) {
                assertThat(mapper.readTree(response.getContentAsByteArray()).path("request_id").asText()).isEqualTo(id);
            }
        }
        assertThat(output.getAll()).doesNotContain("PRIVATE_ROUTE", "PRIVATE_BODY", "PRIVATE_ORIGIN");
    }

    private List<JsonNode> requestLogs(CapturedOutput output) throws Exception {
        var rows = new java.util.ArrayList<JsonNode>();
        for (String line : output.getAll().split("\n")) {
            int start = line.indexOf("public_request ");
            if (start >= 0) rows.add(mapper.readTree(line.substring(start + "public_request ".length())));
        }
        return rows;
    }

    @Test
    void shouldRejectMalformedHoursAndModeCombinations() throws Exception {
        List<Consumer<ObjectNode>> invalid = List.of(
                q -> ((ObjectNode) q.path("weekly_hours").path("monday").path("intervals").get(0)).put("start", "25:00"),
                q -> ((ObjectNode) q.path("weekly_hours").path("monday").path("intervals").get(0)).put("end_day_offset", 1),
                q -> ((ObjectNode) q.path("weekly_hours").path("monday")).put("state", "unknown"),
                q -> ((ObjectNode) q.path("weekly_hours").path("monday")).put("full_day", true),
                q -> ((ObjectNode) q.path("weekly_hours").path("monday")).put("full_day", "false"),
                q -> q.put("case_id", UUID.randomUUID().toString()),
                q -> q.put("mode", "replay"),
                q -> q.remove("mode"),
                q -> q.remove("types"));
        for (var change : invalid) {
            ObjectNode query = (ObjectNode) fixture("matches-request");
            change.accept(query);
            mvc.perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content(query.toString()))
                    .andExpect(status().isUnprocessableEntity());
        }
    }

    @Test
    void shouldApplyDefaultSelectionAndAcceptValidOvernightHoursAsUnprepared() throws Exception {
        ObjectNode query = (ObjectNode) fixture("matches-request");
        query.remove(List.of("selection", "sort"));
        mvc.perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content(query.toString()))
                .andExpect(status().isOk());
        ObjectNode interval = (ObjectNode) query.path("weekly_hours").path("monday").path("intervals").get(0);
        interval.put("start", "22:00").put("end", "02:00").put("end_day_offset", 1);
        mvc.perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content(query.toString()))
                .andExpect(status().isServiceUnavailable());
    }

    @Test
    void shouldRejectFloatingPointDayOffsets() throws Exception {
        for (double offset : new double[]{-0.5, 0.0, 0.5, 1.0, 1.5}) {
            ObjectNode query = (ObjectNode) fixture("matches-request");
            ObjectNode interval = (ObjectNode) query.path("weekly_hours").path("monday").path("intervals").get(0);
            interval.put("end_day_offset", offset);
            if (offset >= 1) interval.put("start", "22:00").put("end", "02:00");
            mvc.perform(post("/api/v1/matches").contentType(MediaType.APPLICATION_JSON).content(query.toString()))
                    .andExpect(status().isUnprocessableEntity());
        }
    }
}
