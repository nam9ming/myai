package kr.ac.myai.backend.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;

import java.time.Clock;

@Configuration
@Profile("!fixture")
public class CalculationConfig {
    @Bean
    public Clock calculationClock() { return Clock.systemUTC(); }
}
