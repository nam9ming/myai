package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import kr.ac.myai.backend.controller.ApiExceptionHandler;
import kr.ac.myai.backend.controller.PublicNoticeController;
import kr.ac.myai.backend.dto.MatchRequest;
import kr.ac.myai.backend.logging.PublicRequestLogFilter;
import kr.ac.myai.backend.service.PublicNoticeService;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.dao.*;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.jdbc.BadSqlGrammarException;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.transaction.CannotCreateTransactionException;

import java.sql.SQLException;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;

@ExtendWith(OutputCaptureExtension.class)
class DatabaseErrorResponseTest {
    private static final String PRIVATE_DETAIL = "PRIVATE_DATABASE_DETAIL";
    private final ObjectMapper mapper = new ObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);

    static Stream<RuntimeException> retryableFailures() {
        return Stream.of(new DataAccessResourceFailureException(PRIVATE_DETAIL), new QueryTimeoutException(PRIVATE_DETAIL),
                new RecoverableDataAccessException(PRIVATE_DETAIL), new CannotCreateTransactionException(PRIVATE_DETAIL));
    }

    static Stream<RuntimeException> permanentFailures() {
        return Stream.of(new BadSqlGrammarException("query", "SELECT PRIVATE_SQL_DETAIL", new SQLException(PRIVATE_DETAIL)),
                new DataIntegrityViolationException(PRIVATE_DETAIL), new InvalidDataAccessApiUsageException(PRIVATE_DETAIL));
    }

    @ParameterizedTest
    @MethodSource("retryableFailures")
    void unavailableStorageReturnsSafeRetryable503(RuntimeException failure, CapturedOutput output) throws Exception {
        assertResponse(failure, 503, "DATABASE_UNAVAILABLE", true, output);
    }

    @ParameterizedTest
    @MethodSource("permanentFailures")
    void permanentSqlErrorsReturnSafe500WithOneRequestLog(RuntimeException failure, CapturedOutput output) throws Exception {
        assertResponse(failure, 500, "INTERNAL_ERROR", false, output);
    }

    private void assertResponse(RuntimeException failure, int expectedStatus, String code, boolean retryable, CapturedOutput output) throws Exception {
        var service = new PublicNoticeService() {
            public JsonNode config(String mode, UUID caseId) { throw failure; }
            public JsonNode matches(MatchRequest query) { throw failure; }
            public JsonNode event(UUID eventId, UUID snapshotId) { throw failure; }
        };
        var mvc = MockMvcBuilders.standaloneSetup(new PublicNoticeController(service)).setControllerAdvice(new ApiExceptionHandler())
                .setMessageConverters(new MappingJackson2HttpMessageConverter(mapper))
                .addFilters(new PublicRequestLogFilter()).build();
        var response = mvc.perform(get("/api/v1/config")).andReturn().getResponse();
        assertThat(response.getStatus()).isEqualTo(expectedStatus);
        var json = mapper.readTree(response.getContentAsString(StandardCharsets.UTF_8));
        assertThat(json.path("error").path("code").asText()).isEqualTo(code);
        assertThat(json.path("error").path("retryable").asBoolean()).isEqualTo(retryable);
        assertThat(json.path("error").path("field_errors")).isEmpty();
        assertThat(json.toString()).doesNotContain(PRIVATE_DETAIL, "PRIVATE_SQL_DETAIL", "SQLException", "stack_trace");
        String requestId = json.path("request_id").asText();
        assertThat(UUID.fromString(requestId)).isNotNull();
        assertThat(response.getHeader("X-Request-ID")).isEqualTo(requestId);
        var lines = output.getAll().lines().filter(line -> line.contains("public_request ")).toList();
        assertThat(lines).hasSize(1);
        JsonNode log = mapper.readTree(lines.getFirst().substring(lines.getFirst().indexOf("public_request ") + "public_request ".length()));
        assertThat(log.size()).isEqualTo(5);
        assertThat(log.path("request_id").textValue()).isEqualTo(requestId);
        assertThat(log.path("error_code").textValue()).isEqualTo(code);
        assertThat(log.path("latency_ms").longValue()).isNotNegative();
        assertThat(log.path("snapshot_id").isNull()).isTrue();
        assertThat(log.path("rules_version").isNull()).isTrue();
        assertThat(output.getAll()).doesNotContain(PRIVATE_DETAIL, "PRIVATE_SQL_DETAIL", "SQLException",
                failure.getClass().getSimpleName(), "stack_trace", "at kr.ac.myai");
    }
}
