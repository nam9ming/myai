package kr.ac.myai.backend.local;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import kr.ac.myai.backend.controller.ApiExceptionHandler.ErrorDetail;
import kr.ac.myai.backend.controller.ApiExceptionHandler.ErrorResponse;
import kr.ac.myai.backend.logging.PublicRequestLogContext;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.context.annotation.Profile;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.core.env.Environment;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;

@Component
@Profile("local-api")
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
@Order(Ordered.HIGHEST_PRECEDENCE + 1)
public class LocalApiSecurityFilter extends OncePerRequestFilter {
    private final byte[] token;
    private final ObjectMapper mapper;

    public LocalApiSecurityFilter(Environment environment, ObjectMapper mapper) {
        this.token = environment.getRequiredProperty("myai.local-api.token").getBytes(StandardCharsets.UTF_8);
        this.mapper = mapper;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String authorization = singleHeader(request, "Authorization");
        if (authorization == null || !authorization.regionMatches(true, 0, "Bearer ", 0, 7)
                || !MessageDigest.isEqual(token, authorization.substring(7).getBytes(StandardCharsets.UTF_8))) {
            reject(request, response, 401, "LOCAL_API_UNAUTHORIZED", "로컬 관리 인증 정보를 확인해 주세요.");
            return;
        }
        int port = request.getLocalPort();
        String host = "127.0.0.1:" + port;
        String requestHost = singleHeader(request, "Host"), origin = singleHeader(request, "Origin");
        boolean sameHost = host.equals(requestHost) || port == 80 && "127.0.0.1".equals(requestHost);
        boolean sameOrigin = ("http://" + host).equals(origin) || port == 80 && "http://127.0.0.1".equals(origin);
        if (port < 1 || port > 65535 || !"127.0.0.1".equals(request.getLocalAddr()) || !loopback(request.getRemoteAddr())
                || !sameHost || !sameOrigin) {
            reject(request, response, 403, "LOCAL_API_FORBIDDEN", "로컬 관리 요청의 출처를 확인해 주세요.");
            return;
        }
        chain.doFilter(request, response);
    }

    private String singleHeader(HttpServletRequest request, String name) {
        var values = request.getHeaders(name);
        if (values == null || !values.hasMoreElements()) return null;
        String value = values.nextElement();
        return values.hasMoreElements() ? null : value;
    }

    private boolean loopback(String address) {
        try {
            return address != null && InetAddress.getByName(address).isLoopbackAddress();
        } catch (UnknownHostException error) {
            return false;
        }
    }

    private void reject(HttpServletRequest request, HttpServletResponse response, int status, String code, String message) throws IOException {
        String requestId = PublicRequestLogContext.requestId(request);
        PublicRequestLogContext.error(request, code);
        response.setStatus(status);
        response.setContentType("application/json");
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        if (status == 401) response.setHeader("WWW-Authenticate", "Bearer");
        mapper.writeValue(response.getOutputStream(), new ErrorResponse(new ErrorDetail(code, message, List.of(), false), requestId));
    }
}
