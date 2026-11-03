package kr.ac.myai.backend.config;

import org.springframework.context.ApplicationContextInitializer;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.web.context.WebApplicationContext;

public class LocalExtractionStartupGuard implements ApplicationContextInitializer<ConfigurableApplicationContext> {
    @Override
    public void initialize(ConfigurableApplicationContext context) {
        var environment = context.getEnvironment();
        if (!environment.matchesProfiles("local-extraction")) return;
        if (environment.matchesProfiles("fixture", "public", "local-import", "local-publication", "local-export", "local-source-review")) throw new ModeException("spring.profiles.active");
        if (context instanceof WebApplicationContext || !environment.getProperty("spring.main.web-application-type", "none").equalsIgnoreCase("none")) {
            throw new ModeException("spring.main.web-application-type");
        }
    }

    public static final class ModeException extends IllegalStateException {
        private final String field;
        public ModeException(String field) { super("local-extraction은 웹 서버와 다른 실행 프로필 없이 사용해 주세요."); this.field = field; }
        public String field() { return field; }
    }
}
