package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.controller.ApiExceptionHandler;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.logging.PublicRequestLogContext;
import kr.ac.myai.backend.logging.PublicRequestLogFilter;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.core.io.ClassPathResource;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.converter.StringHttpMessageConverter;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;

@ExtendWith(OutputCaptureExtension.class)
class PublicRequestLogAdviceTest {
    private static final String SNAPSHOT = "37d9f0b8-424f-5145-9329-e71ffd6413e3";
    private static final String OTHER_SNAPSHOT = "1a0e932b-988b-4d02-bf51-0dd44c5d8186";
    private static final String PRIVATE_RESPONSE = "PRIVATE_RESPONSE_DETAIL";
    private static final String PRIVATE_REQUEST = "PRIVATE_REQUEST_DETAIL";
    private final ObjectMapper mapper = new ObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);

    @ParameterizedTest
    @ValueSource(strings = {"config-response", "matches-response", "event-response"})
    void observesOnlyPublicEnvelopeMetadata(String fixtureName, CapturedOutput output) throws Exception {
        JsonNode body;
        try (var input = new ClassPathResource("fixtures/" + fixtureName + ".json").getInputStream()) {
            body = mapper.readTree(input);
        }
        ((ObjectNode) body.path("data")).put("private_detail", PRIVATE_RESPONSE);
        var response = perform(body, () -> {});
        assertThat(response.getStatus()).isEqualTo(200);
        assertThat(mapper.readTree(response.getContentAsByteArray())).isEqualTo(body);
        JsonNode log = requestLog(output, response, null);
        assertThat(log.path("snapshot_id").textValue()).isEqualTo(SNAPSHOT);
        assertThat(log.path("rules_version").textValue())
                .isEqualTo(fixtureName.equals("matches-response") ? "rules-v1-proposed" : null);
    }

    @Test
    void keepsSelectedMetadataWhenDetailHasNoRulesVersion(CapturedOutput output) throws Exception {
        JsonNode body = mapper.readTree("""
                {"snapshot_id":"1a0e932b-988b-4d02-bf51-0dd44c5d8186","data":{"event":{},
                  "history":[{"snapshot_id":"1a0e932b-988b-4d02-bf51-0dd44c5d8186","rules_version":"history-rules"}]}}
                """);
        var response = perform(body, () -> PublicRequestLogContext.selected(SNAPSHOT, "selected-rules"));
        JsonNode log = requestLog(output, response, null);
        assertThat(log.path("snapshot_id").textValue()).isEqualTo(SNAPSHOT);
        assertThat(log.path("rules_version").textValue()).isEqualTo("selected-rules");
    }

    @Test
    void retiredErrorKeepsCurrentSnapshotOnlyInResponse(CapturedOutput output) throws Exception {
        var response = perform(null, () -> {
            throw new ApiException(HttpStatus.CONFLICT, "SNAPSHOT_RETIRED", "새 공개본을 조회해 주세요.", null, OTHER_SNAPSHOT);
        });
        assertThat(response.getStatus()).isEqualTo(409);
        JsonNode body = mapper.readTree(response.getContentAsByteArray());
        assertThat(body.path("current_snapshot_id").textValue()).isEqualTo(OTHER_SNAPSHOT);
        assertThat(body.path("error").path("retryable").booleanValue()).isFalse();
        JsonNode log = requestLog(output, response, "SNAPSHOT_RETIRED");
        assertThat(log.path("snapshot_id").isNull()).isTrue();
        assertThat(log.path("rules_version").isNull()).isTrue();
    }

    @Test
    void domainErrorKeepsFieldsAndSelectedMetadataWithoutLoggingMessage(CapturedOutput output) throws Exception {
        var response = perform(null, () -> {
            PublicRequestLogContext.selected(SNAPSHOT, "selected-rules");
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "CALCULATION_UNAVAILABLE", PRIVATE_RESPONSE, "point_id", false);
        });
        assertThat(response.getStatus()).isEqualTo(503);
        JsonNode body = mapper.readTree(response.getContentAsByteArray());
        assertThat(body.path("error").path("message").textValue()).isEqualTo(PRIVATE_RESPONSE);
        assertThat(body.path("error").path("retryable").booleanValue()).isFalse();
        assertThat(body.path("error").path("field_errors").get(0).path("field").textValue()).isEqualTo("point_id");
        JsonNode log = requestLog(output, response, "CALCULATION_UNAVAILABLE");
        assertThat(log.path("snapshot_id").textValue()).isEqualTo(SNAPSHOT);
        assertThat(log.path("rules_version").textValue()).isEqualTo("selected-rules");
    }

    @Test
    void unexpectedErrorDoesNotLogCauseOrStack(CapturedOutput output) throws Exception {
        var response = perform(null, () -> {
            throw new IllegalStateException(PRIVATE_RESPONSE, new RuntimeException(PRIVATE_REQUEST));
        });
        assertThat(response.getStatus()).isEqualTo(500);
        JsonNode body = mapper.readTree(response.getContentAsByteArray());
        assertThat(body.path("error").path("message").textValue()).isEqualTo("요청 처리 중 오류가 발생했습니다.");
        assertThat(body.path("error").path("retryable").booleanValue()).isFalse();
        requestLog(output, response, "INTERNAL_ERROR");
        assertThat(output.getAll()).doesNotContain("IllegalStateException", "RuntimeException", "at kr.ac.myai");
    }

    @ParameterizedTest
    @ValueSource(strings = {"null", "[]", "42", "{}", "{\"snapshot_id\":17,\"data\":{\"rules_version\":false}}",
            "{\"snapshot_id\":{},\"data\":[]}", "{\"data\":null}",
            "{\"current_snapshot_id\":\"1a0e932b-988b-4d02-bf51-0dd44c5d8186\",\"data\":{\"history\":[{\"snapshot_id\":\"1a0e932b-988b-4d02-bf51-0dd44c5d8186\",\"rules_version\":\"history-rules\"}]}}"})
    void ignoresMissingOrNonTextMetadata(String json, CapturedOutput output) throws Exception {
        JsonNode body = mapper.readTree(json);
        var response = perform(body, () -> {});
        assertThat(response.getStatus()).isEqualTo(200);
        assertThat(mapper.readTree(response.getContentAsByteArray())).isEqualTo(body);
        JsonNode log = requestLog(output, response, null);
        assertThat(log.path("snapshot_id").isNull()).isTrue();
        assertThat(log.path("rules_version").isNull()).isTrue();
    }

    @Test
    void ignoresMapMetadata(CapturedOutput output) throws Exception {
        var response = perform(Map.of("snapshot_id", OTHER_SNAPSHOT, "data", Map.of("rules_version", "map-rules"),
                "private_detail", PRIVATE_RESPONSE), () -> {});
        JsonNode log = requestLog(output, response, null);
        assertThat(log.path("snapshot_id").isNull()).isTrue();
        assertThat(log.path("rules_version").isNull()).isTrue();
    }

    @Test
    void ignoresStringMetadata(CapturedOutput output) throws Exception {
        var response = perform("{\"snapshot_id\":\"" + OTHER_SNAPSHOT
                + "\",\"data\":{\"rules_version\":\"string-rules\"}}", () -> {});
        JsonNode log = requestLog(output, response, null);
        assertThat(log.path("snapshot_id").isNull()).isTrue();
        assertThat(log.path("rules_version").isNull()).isTrue();
    }

    @Test
    void returnsSameBodyAndSupportsEveryConverter() throws Exception {
        var advice = new ApiExceptionHandler();
        assertThat(advice.supports(null, MappingJackson2HttpMessageConverter.class)).isTrue();
        assertThat(advice.supports(null, StringHttpMessageConverter.class)).isTrue();
        var bodies = List.of(mapper.readTree("{}"), new ApiExceptionHandler.ErrorResponse(null, "existing-id"),
                Map.of("snapshot_id", OTHER_SNAPSHOT), PRIVATE_RESPONSE, new Object());
        for (Object body : bodies) {
            assertThat(advice.beforeBodyWrite(body, null, null, null, null, null)).isSameAs(body);
        }
        assertThat(advice.beforeBodyWrite(null, null, null, null, null, null)).isNull();
    }

    private MockHttpServletResponse perform(Object body, Runnable selection) throws Exception {
        var mvc = MockMvcBuilders.standaloneSetup(new ResponseController(body, selection))
                .setControllerAdvice(new ApiExceptionHandler())
                .setMessageConverters(new StringHttpMessageConverter(), new MappingJackson2HttpMessageConverter(mapper))
                .addFilters(new PublicRequestLogFilter()).build();
        return mvc.perform(get("/api/v1/probe/" + PRIVATE_REQUEST).queryParam("business_hours", PRIVATE_REQUEST)
                .header("User-Agent", PRIVATE_REQUEST).header("X-Request-ID", PRIVATE_REQUEST)
                .contentType(MediaType.APPLICATION_JSON).content("{\"business_hours\":\"" + PRIVATE_REQUEST + "\"}"))
                .andReturn().getResponse();
    }

    private JsonNode requestLog(CapturedOutput output, MockHttpServletResponse response, String errorCode) throws Exception {
        var lines = output.getAll().lines().filter(line -> line.contains("public_request ")).toList();
        assertThat(lines).hasSize(1);
        String line = lines.getFirst();
        JsonNode log = mapper.readTree(line.substring(line.indexOf("public_request ") + "public_request ".length()));
        assertThat(log.size()).isEqualTo(5);
        String requestId = response.getHeader("X-Request-ID");
        assertThat(UUID.fromString(requestId)).isNotNull();
        assertThat(log.path("request_id").textValue()).isEqualTo(requestId);
        assertThat(log.path("error_code").textValue()).isEqualTo(errorCode);
        assertThat(log.path("latency_ms").isIntegralNumber()).isTrue();
        assertThat(log.path("latency_ms").longValue()).isNotNegative();
        if (errorCode != null) {
            assertThat(mapper.readTree(response.getContentAsByteArray()).path("request_id").textValue()).isEqualTo(requestId);
        }
        assertThat(output.getAll()).doesNotContain(PRIVATE_RESPONSE, PRIVATE_REQUEST, "business_hours", "User-Agent");
        return log;
    }

    @RestController
    static class ResponseController {
        private final Object body;
        private final Runnable selection;

        ResponseController(Object body, Runnable selection) {
            this.body = body;
            this.selection = selection;
        }

        @GetMapping("/api/v1/probe/{secret}")
        Object body() {
            selection.run();
            return body;
        }
    }
}
