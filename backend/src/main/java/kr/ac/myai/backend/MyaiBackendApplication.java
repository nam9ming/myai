package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.config.LocalExportStartupGuard;
import kr.ac.myai.backend.config.LocalExtractionStartupGuard;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.event.ApplicationEnvironmentPreparedEvent;
import org.springframework.context.ApplicationListener;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.core.env.ConfigurableEnvironment;

import java.sql.SQLException;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

@SpringBootApplication
public class MyaiBackendApplication {
    public static void main(String[] args) {
        ConfigurableApplicationContext context;
        var environment = new AtomicReference<ConfigurableEnvironment>();
        var application = new SpringApplication(MyaiBackendApplication.class);
        application.addListeners((ApplicationListener<ApplicationEnvironmentPreparedEvent>) event -> environment.set(event.getEnvironment()));
        try { context = application.run(args); }
        catch (LocalExportStartupGuard.WebModeException ex) {
            fail("EXPORT_VALIDATION_ERROR", ex.getMessage(), "spring.main.web-application-type", false, 2); return;
        }
        catch (LocalExtractionStartupGuard.ModeException ex) {
            fail("EXTRACTION_VALIDATION_ERROR", ex.getMessage(), ex.field(), false, 2); return;
        }
        catch (RuntimeException ex) {
            if (environment.get() == null || !environment.get().matchesProfiles("local-extraction")) throw ex;
            boolean database = false, retryable = false;
            for (Throwable cause = ex; cause != null; cause = cause.getCause()) {
                if (cause instanceof SQLException sql) {
                    boolean connection = sql.getSQLState() != null && sql.getSQLState().startsWith("08");
                    database |= connection || sql.getErrorCode() == 1045 || sql.getErrorCode() == 1049;
                    retryable |= connection;
                }
            }
            fail(database ? "EXTRACTION_DATABASE_UNAVAILABLE" : "EXTRACTION_INTERNAL_ERROR",
                    "AI 실행 기록 명령을 시작하지 못했습니다. DB·실행 설정을 확인해 주세요.", null, retryable, database ? 4 : 1);
            return;
        }
        if (context.getEnvironment().matchesProfiles("local-import", "local-publication", "local-export", "local-extraction")) {
            System.exit(SpringApplication.exit(context));
        }
    }

    private static void fail(String code, String message, String field, boolean retryable, int exitCode) {
        var output = new ObjectMapper().createObjectNode().put("request_id", UUID.randomUUID().toString());
        var error = output.putObject("error").put("code", code).put("message", message).put("retryable", retryable);
        var fields = error.putArray("field_errors");
        if (field != null) fields.addObject().put("field", field).put("message", message);
        System.out.println(output); System.exit(exitCode);
    }
}
