package kr.ac.myai.backend;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class MyaiBackendApplication {
    public static void main(String[] args) {
        var context = SpringApplication.run(MyaiBackendApplication.class, args);
        if (context.getEnvironment().matchesProfiles("local-import", "local-publication")) {
            System.exit(SpringApplication.exit(context));
        }
    }
}
