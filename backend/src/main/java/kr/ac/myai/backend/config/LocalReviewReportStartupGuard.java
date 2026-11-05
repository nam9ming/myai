package kr.ac.myai.backend.config;

import org.springframework.context.ApplicationContextInitializer;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.Ordered;
import org.springframework.core.env.MapPropertySource;
import org.springframework.web.context.WebApplicationContext;

import java.util.Arrays;
import java.util.Map;

public class LocalReviewReportStartupGuard implements ApplicationContextInitializer<ConfigurableApplicationContext>, Ordered {
    @Override public int getOrder() { return Ordered.HIGHEST_PRECEDENCE; }

    @Override public void initialize(ConfigurableApplicationContext context) {
        var environment = context.getEnvironment();
        if (!environment.matchesProfiles("local-review-report")) return;
        String[] profiles = environment.getActiveProfiles().length == 0 ? environment.getDefaultProfiles() : environment.getActiveProfiles();
        if (Arrays.stream(profiles).anyMatch(profile -> !profile.equals("local-review-report"))) throw new ModeException("spring.profiles.active");
        if (context instanceof WebApplicationContext || !environment.getProperty("spring.main.web-application-type", "none").equalsIgnoreCase("none")) throw new ModeException("spring.main.web-application-type");
        environment.getPropertySources().addFirst(new MapPropertySource("local-review-report-read-only", Map.of(
                "spring.flyway.enabled", false,
                "spring.jpa.hibernate.ddl-auto", "validate",
                "spring.jpa.properties.hibernate.hbm2ddl.auto", "validate",
                "spring.jpa.generate-ddl", false,
                "spring.sql.init.mode", "never",
                "spring.jpa.properties.jakarta.persistence.schema-generation.database.action", "none",
                "spring.jpa.properties.jakarta.persistence.schema-generation.scripts.action", "none",
                "spring.autoconfigure.exclude", "org.springframework.boot.autoconfigure.orm.jpa.HibernateJpaAutoConfiguration,org.springframework.boot.autoconfigure.data.jpa.JpaRepositoriesAutoConfiguration",
                "spring.datasource.hikari.read-only", true)));
    }

    public static class ModeException extends IllegalStateException {
        private final String field;
        public ModeException(String field) { super("local-review-report는 웹 서버와 다른 실행 프로필 없이 사용해 주세요."); this.field = field; }
        public String field() { return field; }
    }
}
