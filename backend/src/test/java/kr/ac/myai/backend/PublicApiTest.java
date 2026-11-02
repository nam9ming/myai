package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
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
}
