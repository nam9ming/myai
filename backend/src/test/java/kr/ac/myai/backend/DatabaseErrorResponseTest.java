package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import kr.ac.myai.backend.controller.ApiExceptionHandler;
import kr.ac.myai.backend.controller.PublicNoticeController;
import kr.ac.myai.backend.dto.MatchRequest;
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
    void unavailableStorageReturnsSafeRetryable503(RuntimeException failure) throws Exception {
        assertResponse(failure, 503, "DATABASE_UNAVAILABLE", true);
    }

    @ParameterizedTest
    @MethodSource("permanentFailures")
    void permanentSqlErrorsReturn500AndLogRequestId(RuntimeException failure, CapturedOutput output) throws Exception {
        String requestId = assertResponse(failure, 500, "INTERNAL_ERROR", false);
        assertThat(output.getAll()).contains(requestId, failure.getClass().getSimpleName());
    }

    private String assertResponse(RuntimeException failure, int expectedStatus, String code, boolean retryable) throws Exception {
        var service = new PublicNoticeService() {
            public JsonNode config(String mode, UUID caseId) { throw failure; }
            public JsonNode matches(MatchRequest query) { throw failure; }
            public JsonNode event(UUID eventId, UUID snapshotId) { throw failure; }
        };
        var mvc = MockMvcBuilders.standaloneSetup(new PublicNoticeController(service)).setControllerAdvice(new ApiExceptionHandler())
                .setMessageConverters(new MappingJackson2HttpMessageConverter(mapper)).build();
        var response = mvc.perform(get("/api/v1/config")).andReturn().getResponse();
        assertThat(response.getStatus()).isEqualTo(expectedStatus);
        var json = mapper.readTree(response.getContentAsString(StandardCharsets.UTF_8));
        assertThat(json.path("error").path("code").asText()).isEqualTo(code);
        assertThat(json.path("error").path("retryable").asBoolean()).isEqualTo(retryable);
        assertThat(json.path("error").path("field_errors")).isEmpty();
        assertThat(json.toString()).doesNotContain(PRIVATE_DETAIL, "PRIVATE_SQL_DETAIL", "SQLException", "stack_trace");
        String requestId = json.path("request_id").asText();
        assertThat(UUID.fromString(requestId)).isNotNull();
        return requestId;
    }
}
