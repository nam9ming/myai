package kr.ac.myai.backend.logging;

import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

@Component
@ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
@Order(Ordered.HIGHEST_PRECEDENCE)
public class PublicRequestLogFilter extends OncePerRequestFilter {
    private static final Logger log = LoggerFactory.getLogger(PublicRequestLogFilter.class);

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        long started = System.nanoTime();
        response.setHeader("X-Request-ID", PublicRequestLogContext.initialize(request).requestId);
        boolean completed = false;
        try {
            chain.doFilter(request, response);
            completed = true;
        } finally {
            // DispatcherServlet이 요청 컨텍스트를 해제한 뒤에도 원래 요청 속성은 남아 있다.
            var state = PublicRequestLogContext.state(request);
            String errorCode = state.errorCode;
            if (errorCode == null && !completed) errorCode = "INTERNAL_ERROR";
            if (errorCode == null && response.getStatus() >= 400) errorCode = "HTTP_" + response.getStatus();
            var row = JsonNodeFactory.instance.objectNode()
                    .put("request_id", state.requestId)
                    .put("error_code", errorCode)
                    .put("latency_ms", Math.max(0L, (System.nanoTime() - started) / 1_000_000L))
                    .put("snapshot_id", state.snapshotId)
                    .put("rules_version", state.rulesVersion);
            log.info("public_request {}", row);
        }
    }
}
