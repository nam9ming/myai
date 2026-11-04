package kr.ac.myai.backend;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.ServletInputStream;
import kr.ac.myai.backend.logging.PublicRequestLogContext;
import kr.ac.myai.backend.logging.PublicRequestLogFilter;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.io.BufferedReader;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class PublicRequestLogTest {
    private static final String SNAPSHOT = "37d9f0b8-424f-5145-9329-e71ffd6413e3";
    private static final String OTHER_SNAPSHOT = "48bb73cf-3cd9-5e4f-895e-9ba9ce62560f";
    private final ObjectMapper mapper = new ObjectMapper();
    private final PublicRequestLogFilter filter = new PublicRequestLogFilter();
    private final Logger logger = (Logger) LoggerFactory.getLogger(PublicRequestLogFilter.class);
    private final ListAppender<ILoggingEvent> appender = new ListAppender<>();
    private Level previousLevel;

    @BeforeEach
    void captureRequestLogs() {
        RequestContextHolder.resetRequestAttributes();
        previousLevel = logger.getLevel();
        logger.setLevel(Level.INFO);
        appender.start();
        logger.addAppender(appender);
    }

    @AfterEach
    void releaseRequestLogs() {
        RequestContextHolder.resetRequestAttributes();
        logger.detachAppender(appender);
        logger.setLevel(previousLevel);
        appender.stop();
    }

    @Test
    void shouldUseServerIdWithoutReadingPrivateRequestFields() throws Exception {
        var request = new UnreadRequest();
        request.addHeader("X-Request-ID", "client-private-id");
        request.addHeader("Origin", "https://private-origin.example");
        request.addHeader("User-Agent", "private-user-agent");
        request.setQueryString("private-query");
        request.setRemoteAddr("192.0.2.88");
        request.setContent("private-business-hours-body".getBytes(java.nio.charset.StandardCharsets.UTF_8));
        var response = new MockHttpServletResponse();
        String[] observedId = new String[1];

        run(request, response, (req, res) -> {
            observedId[0] = PublicRequestLogContext.requestId();
            res.getWriter().write("private-response-body");
        });

        assertThat(response.getContentAsString()).isEqualTo("private-response-body");
        String id = response.getHeader("X-Request-ID");
        assertThat(UUID.fromString(id).toString()).isEqualTo(id);
        assertThat(id).isEqualTo(observedId[0]).isNotEqualTo("client-private-id");
        JsonNode row = onlyRow();
        assertThat(row.path("request_id").asText()).isEqualTo(id);
        assertThat(row.path("error_code").isNull()).isTrue();
        assertThat(row.path("snapshot_id").isNull()).isTrue();
        assertThat(row.path("rules_version").isNull()).isTrue();
        assertThat(appender.list.getFirst().getFormattedMessage()).doesNotContain(
                "private", "192.0.2.88", "business-hours", "User-Agent", "Origin");
    }

    @Test
    void shouldPreserveSelectedUnicodeVersionsAfterContextReset() throws Exception {
        String rules = "규칙-α-🧭-v1\"\\2026";
        run(new MockHttpServletRequest("POST", "/api/v1/matches"), new MockHttpServletResponse(), (req, res) -> {
            PublicRequestLogContext.response(OTHER_SNAPSHOT, "old-response");
            PublicRequestLogContext.selected(SNAPSHOT, rules);
            PublicRequestLogContext.response(OTHER_SNAPSHOT, "replacement-response");
            PublicRequestLogContext.error("CALCULATION_PROTOCOL_ERROR");
            ((MockHttpServletResponse) res).setStatus(500);
        });

        JsonNode row = onlyRow();
        assertThat(row.path("snapshot_id").asText()).isEqualTo(SNAPSHOT);
        assertThat(row.path("rules_version").asText()).isEqualTo(rules);
        assertThat(row.path("error_code").asText()).isEqualTo("CALCULATION_PROTOCOL_ERROR");
        assertThat(RequestContextHolder.getRequestAttributes()).isNull();
    }

    @Test
    void shouldObserveResponseOnlyUntilSnapshotSelectionIsConfirmed() throws Exception {
        run(new MockHttpServletRequest(), new MockHttpServletResponse(), (req, res) -> {
            PublicRequestLogContext.selected(null, null);
            PublicRequestLogContext.response(SNAPSHOT, "response-rules");
        });
        JsonNode row = onlyRow();
        assertThat(row.path("snapshot_id").asText()).isEqualTo(SNAPSHOT);
        assertThat(row.path("rules_version").asText()).isEqualTo("response-rules");

        appender.list.clear();
        run(new MockHttpServletRequest(), new MockHttpServletResponse(), (req, res) -> {
            PublicRequestLogContext.selected(SNAPSHOT, null);
            PublicRequestLogContext.response(OTHER_SNAPSHOT, "unconfirmed-rules");
        });
        row = onlyRow();
        assertThat(row.path("snapshot_id").asText()).isEqualTo(SNAPSHOT);
        assertThat(row.path("rules_version").isNull()).isTrue();
    }

    @Test
    void shouldIsolateRepeatedRequestsAndIgnoreSettersOutsideRequest() throws Exception {
        PublicRequestLogContext.selected(OTHER_SNAPSHOT, "outside-rules");
        PublicRequestLogContext.response(OTHER_SNAPSHOT, "outside-response-rules");
        PublicRequestLogContext.error("OUTSIDE_ERROR");
        String outsideId = PublicRequestLogContext.requestId();
        assertThat(UUID.fromString(outsideId).toString()).isEqualTo(outsideId);
        assertThat(PublicRequestLogContext.requestId()).isNotEqualTo(outsideId);
        var first = new MockHttpServletResponse();
        run(new MockHttpServletRequest(), first, (req, res) -> {
            PublicRequestLogContext.selected(SNAPSHOT, "selected-rules");
            PublicRequestLogContext.error("INVALID_REQUEST");
            ((MockHttpServletResponse) res).setStatus(422);
        });
        var second = new MockHttpServletResponse();
        run(new MockHttpServletRequest("GET", "/health"), second, (req, res) -> {});

        List<JsonNode> rows = rows();
        assertThat(rows).hasSize(2);
        assertThat(first.getHeader("X-Request-ID")).isNotEqualTo(second.getHeader("X-Request-ID"));
        assertThat(rows.get(0).path("error_code").asText()).isEqualTo("INVALID_REQUEST");
        assertThat(rows.get(1).path("snapshot_id").isNull()).isTrue();
        assertThat(rows.get(1).path("rules_version").isNull()).isTrue();
        assertThat(rows.get(1).path("error_code").isNull()).isTrue();
    }

    @Test
    void shouldUseFixedStatusFallbackWhenNoTypedErrorWasObserved() throws Exception {
        for (int status : new int[]{400, 403, 404, 413, 503}) {
            var response = new MockHttpServletResponse();
            run(new MockHttpServletRequest(), response, (req, res) -> response.setStatus(status));
        }

        assertThat(rows()).extracting(row -> row.path("error_code").asText())
                .containsExactly("HTTP_400", "HTTP_403", "HTTP_404", "HTTP_413", "HTTP_503");
    }

    @Test
    void shouldPropagateChainFailureWithoutLoggingExceptionDetails() throws Exception {
        var failure = new ServletException("private-exception-business-hours\nprivate-stack-token");
        var response = new MockHttpServletResponse();

        assertThatThrownBy(() -> run(new MockHttpServletRequest(), response, (req, res) -> {
            throw failure;
        })).isSameAs(failure);

        JsonNode row = onlyRow();
        assertThat(row.path("error_code").asText()).isEqualTo("INTERNAL_ERROR");
        assertThat(row.path("request_id").asText()).isEqualTo(response.getHeader("X-Request-ID"));
        assertThat(appender.list.getFirst().getFormattedMessage()).doesNotContain("private", "ServletException");
    }

    @Test
    void shouldPreserveTypedErrorWhenChainFailsAfterSelection() throws Exception {
        var failure = new ServletException("private-protocol-failure");
        assertThatThrownBy(() -> run(new MockHttpServletRequest(), new MockHttpServletResponse(), (req, res) -> {
            PublicRequestLogContext.selected(SNAPSHOT, "v1");
            PublicRequestLogContext.error("CALCULATION_PROTOCOL_ERROR");
            throw failure;
        })).isSameAs(failure);

        JsonNode row = onlyRow();
        assertThat(row.path("error_code").asText()).isEqualTo("CALCULATION_PROTOCOL_ERROR");
        assertThat(row.path("snapshot_id").asText()).isEqualTo(SNAPSHOT);
    }

    @Test
    void shouldRejectUnsafeRulesButKeepKnownSnapshot() throws Exception {
        for (String rules : List.of("", " \t", "\u00a0", "v".repeat(101), "v\nsecret", "v\u0000", "v\u007f",
                "v\u0085", "v\u2028", "v\u2029", "v\u200d", "v\ud800", "v\udc00")) {
            run(new MockHttpServletRequest(), new MockHttpServletResponse(), (req, res) ->
                    PublicRequestLogContext.selected(SNAPSHOT, rules));
        }

        assertThat(rows()).hasSize(13).allSatisfy(row -> {
            assertThat(row.path("snapshot_id").asText()).isEqualTo(SNAPSHOT);
            assertThat(row.path("rules_version").isNull()).isTrue();
        });
        appender.list.clear();
        run(new MockHttpServletRequest(), new MockHttpServletResponse(), (req, res) ->
                PublicRequestLogContext.selected(SNAPSHOT, "규".repeat(98) + "🧭"));
        assertThat(onlyRow().path("rules_version").asText()).isEqualTo("규".repeat(98) + "🧭");
    }

    @Test
    void shouldDropNoncanonicalSnapshotAndHostileErrorCode() throws Exception {
        for (String snapshot : List.of("not-a-uuid", SNAPSHOT.toUpperCase(java.util.Locale.ROOT),
                " " + SNAPSHOT, "1-1-1-1-1")) {
            run(new MockHttpServletRequest(), new MockHttpServletResponse(), (req, res) -> {
                PublicRequestLogContext.response(snapshot, "v1");
                PublicRequestLogContext.error("INVALID_REQUEST\nprivate-error");
                ((MockHttpServletResponse) res).setStatus(422);
            });
        }

        assertThat(rows()).hasSize(4).allSatisfy(row -> {
            assertThat(row.path("snapshot_id").isNull()).isTrue();
            assertThat(row.path("rules_version").asText()).isEqualTo("v1");
            assertThat(row.path("error_code").asText()).isEqualTo("HTTP_422");
        });
        for (String code : List.of("", "private", "A".repeat(101), "ERROR-PRIVATE")) {
            appender.list.clear();
            run(new MockHttpServletRequest(), new MockHttpServletResponse(), (req, res) ->
                    PublicRequestLogContext.error(code));
            assertThat(onlyRow().path("error_code").isNull()).isTrue();
        }
    }

    private void run(MockHttpServletRequest request, MockHttpServletResponse response, FilterChain chain) throws Exception {
        filter.doFilter(request, response, (req, res) -> {
            var attributes = new ServletRequestAttributes(request, response);
            RequestContextHolder.setRequestAttributes(attributes);
            try {
                chain.doFilter(req, res);
            } finally {
                RequestContextHolder.resetRequestAttributes();
                attributes.requestCompleted();
            }
        });
    }

    private JsonNode onlyRow() throws Exception {
        List<JsonNode> rows = rows();
        assertThat(rows).hasSize(1);
        return rows.getFirst();
    }

    private List<JsonNode> rows() throws Exception {
        List<JsonNode> rows = new ArrayList<>();
        for (ILoggingEvent event : appender.list) {
            assertThat(event.getLevel()).isEqualTo(Level.INFO);
            assertThat(event.getThrowableProxy()).isNull();
            String message = event.getFormattedMessage();
            assertThat(message).startsWith("public_request ").doesNotContain("\n", "\r");
            JsonNode row = mapper.readTree(message.substring("public_request ".length()));
            List<String> fields = new ArrayList<>();
            row.fieldNames().forEachRemaining(fields::add);
            assertThat(fields).containsExactlyInAnyOrder("request_id", "error_code", "latency_ms", "snapshot_id", "rules_version");
            assertThat(row.path("latency_ms").isIntegralNumber()).isTrue();
            assertThat(row.path("latency_ms").asLong()).isGreaterThanOrEqualTo(0);
            rows.add(row);
        }
        return rows;
    }

    private static class UnreadRequest extends MockHttpServletRequest {
        UnreadRequest() { super("POST", "/private-path"); }
        @Override public String getMethod() { throw new AssertionError("요청 method를 읽으면 안 됩니다."); }
        @Override public String getRequestURI() { throw new AssertionError("요청 URI를 읽으면 안 됩니다."); }
        @Override public String getQueryString() { throw new AssertionError("요청 query를 읽으면 안 됩니다."); }
        @Override public String getRemoteAddr() { throw new AssertionError("요청 IP를 읽으면 안 됩니다."); }
        @Override public String getHeader(String name) { throw new AssertionError("요청 header를 읽으면 안 됩니다."); }
        @Override public Enumeration<String> getHeaders(String name) { throw new AssertionError("요청 header를 읽으면 안 됩니다."); }
        @Override public Enumeration<String> getHeaderNames() { throw new AssertionError("요청 header를 읽으면 안 됩니다."); }
        @Override public ServletInputStream getInputStream() { throw new AssertionError("요청 body를 읽으면 안 됩니다."); }
        @Override public BufferedReader getReader() { throw new AssertionError("요청 body를 읽으면 안 됩니다."); }
    }
}
