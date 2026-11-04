package kr.ac.myai.backend;

import kr.ac.myai.backend.config.LocalReviewReportStartupGuard;
import org.junit.jupiter.api.Test;
import org.springframework.context.support.GenericApplicationContext;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.web.context.support.GenericWebApplicationContext;

import static org.assertj.core.api.Assertions.*;

class ReviewReportStartupTest {
    final LocalReviewReportStartupGuard guard = new LocalReviewReportStartupGuard();

    @Test
    void rejectsEveryOtherProfileAndWebBeforeInitialization() {
        for (String other : new String[]{"public", "fixture", "local-import", "local-publication", "local-export", "local-extraction", "local-source-review", "unknown"}) {
            try (var context = new GenericApplicationContext()) {
                var environment = new MockEnvironment(); environment.setActiveProfiles("local-review-report", other); context.setEnvironment(environment);
                assertThatThrownBy(() -> guard.initialize(context)).isInstanceOf(LocalReviewReportStartupGuard.ModeException.class);
            }
        }
        try (var context = new GenericWebApplicationContext()) {
            var environment = new MockEnvironment(); environment.setActiveProfiles("local-review-report"); context.setEnvironment(environment);
            assertThatThrownBy(() -> guard.initialize(context)).isInstanceOf(LocalReviewReportStartupGuard.ModeException.class);
        }
        try (var context = new GenericApplicationContext()) {
            var environment = new MockEnvironment().withProperty("spring.main.web-application-type", "reactive");
            environment.setActiveProfiles("local-review-report"); context.setEnvironment(environment);
            assertThatThrownBy(() -> guard.initialize(context)).isInstanceOf(LocalReviewReportStartupGuard.ModeException.class);
        }
    }

    @Test
    void forcesFlywayOffEvenWhenExplicitlyEnabledAndLeavesOtherModesAlone() {
        try (var context = new GenericApplicationContext()) {
            var environment = new MockEnvironment().withProperty("spring.flyway.enabled", "true"); context.setEnvironment(environment);
            guard.initialize(context); assertThat(environment.getProperty("spring.flyway.enabled")).isEqualTo("true");
            environment.setActiveProfiles("local-review-report"); guard.initialize(context);
            assertThat(environment.getProperty("spring.flyway.enabled")).isEqualTo("false");
        }
    }

    @Test
    void overridesEverySchemaWriterAndDefaultMixedProfiles() {
        try (var context = new GenericApplicationContext()) {
            var environment = new MockEnvironment().withProperty("spring.jpa.hibernate.ddl-auto", "create")
                    .withProperty("spring.jpa.generate-ddl", "true").withProperty("spring.sql.init.mode", "always")
                    .withProperty("spring.jpa.properties.hibernate.hbm2ddl.auto", "create-drop")
                    .withProperty("spring.jpa.properties.jakarta.persistence.schema-generation.database.action", "drop-and-create")
                    .withProperty("spring.jpa.properties.jakarta.persistence.schema-generation.scripts.action", "create");
            environment.setActiveProfiles("local-review-report"); context.setEnvironment(environment); guard.initialize(context);
            assertThat(environment.getProperty("spring.jpa.hibernate.ddl-auto")).isEqualTo("validate");
            assertThat(environment.getProperty("spring.jpa.properties.hibernate.hbm2ddl.auto")).isEqualTo("validate");
            assertThat(environment.getProperty("spring.jpa.generate-ddl")).isEqualTo("false");
            assertThat(environment.getProperty("spring.sql.init.mode")).isEqualTo("never");
            assertThat(environment.getProperty("spring.jpa.properties.jakarta.persistence.schema-generation.database.action")).isEqualTo("none");
            assertThat(environment.getProperty("spring.jpa.properties.jakarta.persistence.schema-generation.scripts.action")).isEqualTo("none");
            assertThat(environment.getProperty("spring.datasource.hikari.read-only")).isEqualTo("true");
            assertThat(environment.getProperty("spring.autoconfigure.exclude")).contains("HibernateJpaAutoConfiguration", "JpaRepositoriesAutoConfiguration");
        }
        try (var context = new GenericApplicationContext()) {
            var environment = new MockEnvironment(); environment.setDefaultProfiles("local-review-report", "fixture"); context.setEnvironment(environment);
            assertThatThrownBy(() -> guard.initialize(context)).isInstanceOf(LocalReviewReportStartupGuard.ModeException.class);
        }
    }
}
