package kr.ac.myai.backend.config;

import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.service.ExtractionImportService;
import org.springframework.context.ApplicationContextInitializer;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.util.unit.DataSize;
import org.springframework.web.context.WebApplicationContext;

import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;

public class LocalApiStartupGuard implements ApplicationContextInitializer<ConfigurableApplicationContext> {
    @Override
    public void initialize(ConfigurableApplicationContext context) {
        var environment = context.getEnvironment();
        validateEnvironment(environment);
        if (environment.matchesProfiles("local-api") && !(context instanceof WebApplicationContext)) {
            throw new ModeException("spring.main.web-application-type");
        }
    }

    public void validateEnvironment(ConfigurableEnvironment environment) {
        if (!environment.matchesProfiles("local-api")) return;
        String[] profiles = environment.getActiveProfiles().length == 0 ? environment.getDefaultProfiles() : environment.getActiveProfiles();
        if (Arrays.stream(profiles).anyMatch(profile -> !profile.equals("local-api"))) throw new ModeException("spring.profiles.active");
        if (!environment.getProperty("spring.main.web-application-type", "servlet").equalsIgnoreCase("servlet")) {
            throw new ModeException("spring.main.web-application-type");
        }
        if (!"127.0.0.1".equals(environment.getProperty("server.address"))) throw new ModeException("server.address");
        if (!"NONE".equalsIgnoreCase(environment.getProperty("server.forward-headers-strategy"))) {
            throw new ModeException("server.forward-headers-strategy");
        }
        try {
            int port = Integer.parseInt(environment.getProperty("server.port", "8081"));
            if (port < 0 || port > 65535) throw new NumberFormatException();
        } catch (NumberFormatException error) {
            throw new ModeException("server.port");
        }
        for (String flag : List.of("enabled", "resolve-lazily")) {
            String field = "spring.servlet.multipart." + flag;
            if (!"true".equalsIgnoreCase(environment.getProperty(field))) throw new ModeException(field);
        }
        multipartSize(environment, "max-file-size", 20L * 1024 * 1024, 20L * 1024 * 1024);
        multipartSize(environment, "max-request-size", 21L * 1024 * 1024, 21L * 1024 * 1024);
        multipartSize(environment, "file-size-threshold", 21L * 1024 * 1024, Integer.MAX_VALUE);
        var system = environment.getPropertySources().get(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
        for (String suffix : List.of("TOKEN", "ACTOR", "SOURCE_ROOT", "EXTRACTION_ROOT", "HANDOFF_ROOT", "REQUEST_ROOT")) {
            String name = "MYAI_LOCAL_API_" + suffix;
            String field = "myai.local-api." + suffix.toLowerCase(Locale.ROOT).replace('_', '-');
            Object supplied = system == null ? null : system.getProperty(name);
            if (!(supplied instanceof String value) || value.isBlank()) throw new ModeException(field);
            if (!value.equals(environment.getProperty(name)) || !value.equals(environment.getProperty(field, value))) {
                throw new ModeException(field);
            }
            if (suffix.equals("TOKEN") && !value.matches("[A-Za-z0-9_-]{32,128}")) throw new ModeException(field);
            if (suffix.equals("ACTOR")) {
                try {
                    ExtractionImportService.validateActor(value);
                } catch (ExtractionException error) {
                    throw new ModeException(field);
                }
            }
            if (suffix.endsWith("_ROOT")) {
                try {
                    if (!Path.of(value).isAbsolute()) throw new ModeException(field);
                } catch (InvalidPathException error) {
                    throw new ModeException(field);
                }
            }
        }
    }

    private void multipartSize(ConfigurableEnvironment environment, String name, long minimum, long maximum) {
        String field = "spring.servlet.multipart." + name;
        try {
            long bytes = DataSize.parse(environment.getProperty(field, "")).toBytes();
            if (bytes < minimum || bytes > maximum) throw new ModeException(field);
        } catch (IllegalArgumentException | ArithmeticException error) {
            throw new ModeException(field);
        }
    }

    public static final class ModeException extends IllegalStateException {
        private final String field;
        public ModeException(String field) { super("local-api 실행 설정을 확인해 주세요."); this.field = field; }
        public String field() { return field; }
    }
}
