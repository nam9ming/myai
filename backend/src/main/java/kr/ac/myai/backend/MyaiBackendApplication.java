package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.config.LocalExportStartupGuard;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.ConfigurableApplicationContext;

import java.util.UUID;

@SpringBootApplication
public class MyaiBackendApplication {
    public static void main(String[] args) {
        ConfigurableApplicationContext context;
        try { context = SpringApplication.run(MyaiBackendApplication.class, args); }
        catch (LocalExportStartupGuard.WebModeException ex) {
            var output = new ObjectMapper().createObjectNode().put("request_id", UUID.randomUUID().toString());
            var error = output.putObject("error").put("code", "EXPORT_VALIDATION_ERROR").put("message", ex.getMessage()).put("retryable", false);
            error.putArray("field_errors").addObject().put("field", "spring.main.web-application-type").put("message", ex.getMessage());
            System.out.println(output); System.exit(2); return;
        }
        if (context.getEnvironment().matchesProfiles("local-import", "local-publication", "local-export")) {
            System.exit(SpringApplication.exit(context));
        }
    }
}
