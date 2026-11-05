package kr.ac.myai.backend.config;

import org.springframework.context.ApplicationContextInitializer;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.MapPropertySource;
import org.springframework.web.context.WebApplicationContext;

import java.util.Map;

public class LocalExportStartupGuard implements ApplicationContextInitializer<ConfigurableApplicationContext> {
    @Override
    public void initialize(ConfigurableApplicationContext context) {
        var environment = context.getEnvironment();
        if (!environment.matchesProfiles("local-export")) return;
        if (context instanceof WebApplicationContext || !environment.getProperty("spring.main.web-application-type", "none").equalsIgnoreCase("none")) {
            throw new WebModeException();
        }
        // 실행 인자·환경변수가 읽기 전용 export의 migration을 다시 켜지 못하게 한다.
        environment.getPropertySources().addFirst(new MapPropertySource("local-export-read-only", Map.of("spring.flyway.enabled", false)));
    }

    public static final class WebModeException extends IllegalStateException {
        public WebModeException() { super("local-export는 웹 서버 없이 실행해야 합니다."); }
    }
}
