package kr.ac.myai.backend;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import jakarta.servlet.ServletInputStream;
import kr.ac.myai.backend.controller.PublicNoticeController;
import kr.ac.myai.backend.controller.StatusController;
import kr.ac.myai.backend.local.LocalApiSecurityFilter;
import kr.ac.myai.backend.logging.PublicRequestLogFilter;
import kr.ac.myai.backend.service.PublicNoticeService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Bean;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockServletContext;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.support.AnnotationConfigWebApplicationContext;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;

import java.io.BufferedReader;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class LocalApiSecurityTest {
    private static final String TOKEN = "SYNTHETIC_LOCAL_TOKEN_0123456789_abcdef";
    private static final String HOST = "127.0.0.1:49123";
    private static final String ORIGIN = "http://" + HOST;
    private static final String PRIVATE_BODY = "SYNTHETIC_PRIVATE_BODY /synthetic/private/source.json";
    private final ObjectMapper mapper = new ObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    private final LocalApiSecurityFilter filter = new LocalApiSecurityFilter(new MockEnvironment()
            .withProperty("myai.local-api.token", TOKEN).withProperty("server.port", "8081"), mapper);
    private final PublicRequestLogFilter logging = new PublicRequestLogFilter();
    private final Logger logger = (Logger) LoggerFactory.getLogger(PublicRequestLogFilter.class);
    private final ListAppender<ILoggingEvent> appender = new ListAppender<>();
    private Level previousLevel;
    private int domainCalls;

    @BeforeEach
    void captureLogsWithoutBindingRequestContext() {
        RequestContextHolder.resetRequestAttributes();
        previousLevel = logger.getLevel();
        logger.setLevel(Level.INFO);
        appender.start();
        logger.addAppender(appender);
    }

    @AfterEach
    void releaseLogs() {
        RequestContextHolder.resetRequestAttributes();
        logger.detachAppender(appender);
        logger.setLevel(previousLevel);
        appender.stop();
    }

    @ParameterizedTest(name = "valid auth scheme [{index}]")
    @ValueSource(strings = {"Bearer", "bearer", "BEARER"})
    void exactTokenAndActualSocketPortReachDomainWithoutReadingBody(String scheme) throws Exception {
        var request = request();
        request.removeHeader("Authorization");
        request.addHeader("Authorization", scheme + " " + TOKEN);
        var response = run(request);
        assertThat(response.getStatus()).isEqualTo(204);
        assertThat(domainCalls).isEqualTo(1);
        assertThat(request.bodyReads).isZero();
        assertThat(onlyRow().path("error_code").isNull()).isTrue();
    }

    @ParameterizedTest
    @CsvSource({"127.0.0.1,http://127.0.0.1", "127.0.0.1:80,http://127.0.0.1",
            "127.0.0.1,http://127.0.0.1:80", "127.0.0.1:80,http://127.0.0.1:80"})
    void defaultHttpSocketPortAllowsOmittedOrExplicitHeaderPort(String host, String origin) throws Exception {
        var request = request();
        request.setLocalPort(80);
        request.removeHeader("Host");
        request.addHeader("Host", host);
        request.removeHeader("Origin");
        request.addHeader("Origin", origin);
        var response = run(request);
        assertThat(response.getStatus()).isEqualTo(204);
        assertThat(domainCalls).isEqualTo(1);
        assertThat(request.bodyReads).isZero();
        assertThat(onlyRow().path("error_code").isNull()).isTrue();
    }

    @ParameterizedTest
    @CsvSource({"127.0.0.1:81,http://127.0.0.1", "127.0.0.1,http://127.0.0.1:81",
            "localhost,http://127.0.0.1", "127.0.0.1,http://localhost", "127.0.0.1,https://127.0.0.1",
            "127.0.0.1:80,https://127.0.0.1:80", "127.0.0.1,http://127.0.0.1/"})
    void defaultHttpSocketPortStillRejectsOtherPortsHostsAndSchemes(String host, String origin) throws Exception {
        var request = request();
        request.setLocalPort(80);
        request.removeHeader("Host");
        request.addHeader("Host", host);
        request.removeHeader("Origin");
        request.addHeader("Origin", origin);
        denied(request, 403, "LOCAL_API_FORBIDDEN");
    }

    @ParameterizedTest(name = "authorization rejection [{index}]")
    @NullAndEmptySource
    @ValueSource(strings = {"Basic SYNTHETIC_PRIVATE_CREDENTIAL", "Bearer", "Bearer wrong", "Bearer SYNTHETIC_LOCAL_TOKEN_0123456789_abcdef ", "Bearer SYNTHETIC_LOCAL_TOKEN_0123456789_abcdeg", "bearer sYNTHETIC_LOCAL_TOKEN_0123456789_abcdef"})
    void malformedOrMissingTokenStopsBeforeBodyAndDomain(String authorization) throws Exception {
        var request = request();
        request.removeHeader("Authorization");
        if (authorization != null) request.addHeader("Authorization", authorization);
        denied(request, 401, "LOCAL_API_UNAUTHORIZED");
    }

    @Test
    void duplicateAuthorizationIsRejectedEvenWhenBothTokensMatch() throws Exception {
        var request = request();
        request.addHeader("Authorization", "Bearer " + TOKEN);
        denied(request, 401, "LOCAL_API_UNAUTHORIZED");
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {"null", "https://127.0.0.1:49123", "http://localhost:49123", "http://127.0.0.1:8081",
            "http://127.0.0.1:49123/", "http://127.0.0.1:49123.evil.example", "http://127.0.0.1:49123, http://127.0.0.1:49123"})
    void missingOrDifferentOriginStopsBeforeBodyAndDomain(String origin) throws Exception {
        var request = request();
        request.removeHeader("Origin");
        if (origin != null) request.addHeader("Origin", origin);
        denied(request, 403, "LOCAL_API_FORBIDDEN");
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {"localhost:49123", "127.0.0.1:8081", "127.0.0.1", "127.0.0.1:49123.evil.example", "[::1]:49123"})
    void missingOrDifferentHostStopsBeforeBodyAndDomain(String host) throws Exception {
        var request = request();
        request.removeHeader("Host");
        if (host != null) request.addHeader("Host", host);
        denied(request, 403, "LOCAL_API_FORBIDDEN");
    }

    @ParameterizedTest
    @ValueSource(strings = {"Origin", "Host"})
    void duplicateOriginAndHostAreRejectedEvenWhenValuesMatch(String name) throws Exception {
        var request = request();
        request.addHeader(name, name.equals("Origin") ? ORIGIN : HOST);
        denied(request, 403, "LOCAL_API_FORBIDDEN");
    }

    @Test
    void remoteSocketCannotBeReplacedByForwardedHeaders() throws Exception {
        var request = request();
        request.setRemoteAddr("192.0.2.88");
        request.addHeader("Forwarded", "for=127.0.0.1;host=" + HOST + ";proto=http");
        request.addHeader("X-Forwarded-For", "127.0.0.1");
        request.addHeader("X-Forwarded-Host", HOST);
        request.addHeader("X-Forwarded-Port", "49123");
        request.addHeader("X-Forwarded-Proto", "http");
        denied(request, 403, "LOCAL_API_FORBIDDEN");
    }

    @Test
    void externalLocalSocketAndWrongActualPortAreRejected() throws Exception {
        var request = request();
        request.setLocalAddr("192.0.2.89");
        denied(request, 403, "LOCAL_API_FORBIDDEN");
        appender.list.clear();
        request = request();
        request.setLocalPort(49124);
        request.addHeader("X-Forwarded-Port", "49123");
        denied(request, 403, "LOCAL_API_FORBIDDEN");
    }

    @Test
    void forwardedHostCannotRepairInvalidHost() throws Exception {
        var request = request();
        request.removeHeader("Host");
        request.addHeader("Host", "SYNTHETIC_PRIVATE_HOST.example");
        request.addHeader("X-Forwarded-Host", HOST);
        request.addHeader("Forwarded", "host=" + HOST);
        denied(request, 403, "LOCAL_API_FORBIDDEN");
    }

    @ParameterizedTest
    @ValueSource(strings = {"/local/documents", "/locality", "/%6cocal/documents", "/local%2fdocuments", "/api/v1/config", "/health", "/error", "/unknown"})
    void everyServletPathRequiresAuthentication(String path) throws Exception {
        var request = request();
        request.setRequestURI(path);
        request.removeHeader("Authorization");
        denied(request, 401, "LOCAL_API_UNAUTHORIZED");
    }

    @Test
    void optionsDoesNotBypassAuthenticationOrOrigin() throws Exception {
        var request = request();
        request.setMethod("OPTIONS");
        request.addHeader("Access-Control-Request-Method", "POST");
        request.removeHeader("Authorization");
        denied(request, 401, "LOCAL_API_UNAUTHORIZED");
        appender.list.clear();
        request = request();
        request.setMethod("OPTIONS");
        request.removeHeader("Origin");
        denied(request, 403, "LOCAL_API_FORBIDDEN");
    }

    @Test
    void unauthenticatedOversizedChunkedBodyIsNeverRead() throws Exception {
        var request = new UnreadRequest(true);
        configure(request);
        request.setContent(new byte[8 * 1024 * 1024 + 1]);
        request.removeHeader("Authorization");
        denied(request, 401, "LOCAL_API_UNAUTHORIZED");
    }

    @Test
    void authenticationRunsImmediatelyAfterRequestLogging() {
        var order = LocalApiSecurityFilter.class.getAnnotation(Order.class);
        assertThat(order).isNotNull();
        assertThat(order.value()).isEqualTo(Ordered.HIGHEST_PRECEDENCE + 1);
    }

    @Test
    void validLocalAuthenticationCannotExposePublicControllers() throws Exception {
        try (var context = new AnnotationConfigWebApplicationContext()) {
            context.setServletContext(new MockServletContext());
            context.getEnvironment().setActiveProfiles("local-api");
            context.register(ControllerBoundary.class, PublicNoticeController.class, StatusController.class);
            context.refresh();
            var mvc = MockMvcBuilders.webAppContextSetup(context).build();
            mvc.perform(get("/api/v1/config").header("Authorization", "Bearer " + TOKEN).header("Origin", ORIGIN).header("Host", HOST))
                    .andExpect(status().isNotFound());
            mvc.perform(get("/health").header("Authorization", "Bearer " + TOKEN).header("Origin", ORIGIN).header("Host", HOST))
                    .andExpect(status().isNotFound());
            verifyNoInteractions(context.getBean(PublicNoticeService.class));
        }
    }

    private UnreadRequest request() {
        var request = new UnreadRequest(false);
        configure(request);
        return request;
    }

    private void configure(UnreadRequest request) {
        request.setMethod("POST");
        request.setRequestURI("/local/documents");
        request.setScheme("http");
        request.setServerName("127.0.0.1");
        request.setServerPort(8081);
        request.setLocalAddr("127.0.0.1");
        request.setLocalPort(49123);
        request.setRemoteAddr("127.0.0.1");
        request.addHeader("Authorization", "Bearer " + TOKEN);
        request.addHeader("Origin", ORIGIN);
        request.addHeader("Host", HOST);
        request.addHeader("X-Request-ID", "SYNTHETIC_PRIVATE_CLIENT_ID");
        request.setContent(PRIVATE_BODY.getBytes(StandardCharsets.UTF_8));
    }

    private MockHttpServletResponse run(UnreadRequest request) throws Exception {
        var response = new MockHttpServletResponse();
        logging.doFilter(request, response, (req, res) -> filter.doFilter(req, res, (accepted, result) -> {
            domainCalls++;
            ((MockHttpServletResponse) result).setStatus(204);
        }));
        return response;
    }

    private void denied(UnreadRequest request, int status, String code) throws Exception {
        var response = run(request);
        assertThat(response.getStatus()).isEqualTo(status);
        assertThat(domainCalls).isZero();
        assertThat(request.bodyReads).isZero();
        assertThat(response.getContentType()).startsWith("application/json");
        var body = mapper.readTree(response.getContentAsByteArray());
        assertThat(body.path("error").path("code").asText()).isEqualTo(code);
        assertThat(body.path("error").path("field_errors").isArray()).isTrue();
        assertThat(body.path("error").path("retryable").asBoolean()).isFalse();
        String id = response.getHeader("X-Request-ID");
        assertThat(UUID.fromString(id).toString()).isEqualTo(id);
        assertThat(body.path("request_id").asText()).isEqualTo(id);
        assertThat(onlyRow().path("request_id").asText()).isEqualTo(id);
        assertThat(onlyRow().path("error_code").asText()).isEqualTo(code);
        assertThat(response.getContentAsString() + appender.list.getFirst().getFormattedMessage())
                .doesNotContain(TOKEN, PRIVATE_BODY, "/synthetic/private", "SYNTHETIC_PRIVATE", "192.0.2.", "Authorization", "Origin", "Exception", "\tat ");
        assertThat(RequestContextHolder.getRequestAttributes()).isNull();
    }

    private JsonNode onlyRow() throws Exception {
        assertThat(appender.list).hasSize(1);
        return mapper.readTree(appender.list.getFirst().getFormattedMessage().substring("public_request ".length()));
    }

    @TestConfiguration(proxyBeanMethods = false)
    @EnableWebMvc
    static class ControllerBoundary {
        @Bean PublicNoticeService publicNoticeService() { return mock(PublicNoticeService.class); }
    }

    static class UnreadRequest extends MockHttpServletRequest {
        private final boolean chunked;
        int bodyReads;

        UnreadRequest(boolean chunked) { this.chunked = chunked; }
        @Override public int getContentLength() { return chunked ? -1 : super.getContentLength(); }
        @Override public long getContentLengthLong() { return chunked ? -1L : super.getContentLengthLong(); }
        @Override public ServletInputStream getInputStream() { bodyReads++; throw new AssertionError("인증 전에 본문을 읽음"); }
        @Override public BufferedReader getReader() { bodyReads++; throw new AssertionError("인증 전에 본문을 읽음"); }
    }
}
