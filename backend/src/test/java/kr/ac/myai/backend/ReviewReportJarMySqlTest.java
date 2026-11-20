package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.service.ReviewedImportService;
import kr.ac.myai.backend.service.ExtractionImportService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.*;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

@SpringBootTest
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class ReviewReportJarMySqlTest {
    @TempDir Path root;
    @Autowired JdbcTemplate jdbc;
    @Autowired ReviewedImportReader reader;
    @Autowired ReviewedImportService importer;
    @Autowired ExtractionImportService extractions;
    final ObjectMapper mapper = new ObjectMapper();

    @DynamicPropertySource
    static void python(DynamicPropertyRegistry registry) {
        registry.add("app.calculation.workdir", () -> PythonProbe.REPO.toString());
        registry.add("app.calculation.python-executable", () -> PythonProbe.PYTHON);
    }

    @Test
    void actualJarDisplaysEveryChunkCycleWithoutChangingStoredData() throws Exception {
        var fixture = new SourceReviewFixtures(root, jdbc, reader, importer);
        var source = fixture.source(true);
        ChunkedArchiveFixtures.enlarge(SourceReviewFixtures.document(source), "block_index");
        fixture.register(source); String run = UUID.randomUUID().toString();
        Path prepared = fixture.archive(source, run);
        Path archive = ChunkedArchiveFixtures.archive(root.resolve("chunk-jar"), prepared.resolve(run).resolve("input.json"), run,
                SourceReviewFixtures.document(source).path("preprocessing_version").asText(), "retry");
        extractions.importRun(run, archive, "synthetic-registrant");
        var before = database();
        Path output = root.resolve("data/private/chunk-reports"); Files.createDirectories(output);
        Files.setPosixFilePermissions(output, PosixFilePermissions.fromString("rwx------"));
        var result = run("--myai.report.document-version-id=" + SourceReviewFixtures.version(source),
                "--myai.report.source-root=" + root, "--myai.report.directory=" + output);
        assertThat(result.exit()).isZero();
        Path file = output.resolve(result.json().path("result").path("file_name").asText());
        byte[] bytes = Files.readAllBytes(file);
        assertThat(result.json().path("result").path("checksum").asText()).isEqualTo(ReviewedImportReader.sha256(bytes));
        assertThat(new String(bytes, StandardCharsets.UTF_8)).contains("extraction-archive-v2", "chunk-plan.json", "total_calls",
                "attempt-1-chunk-000001.prompt", "attempt-2-chunk-000002.response", "attempt-2.output", "not_requested");
        assertThat(database()).isEqualTo(before);
        assertThat(Files.getPosixFilePermissions(file)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
    }

    @Test
    void actualJarWritesPrivateReceiptWithoutHonoringSchemaWriters() throws Exception {
        var fixture = new SourceReviewFixtures(root, jdbc, reader, importer);
        var source = fixture.source(true); fixture.register(source);
        jdbc.update("INSERT INTO extraction_runs(run_id,document_version_id,input_sha256,provider,model,prompt_version,status,registered_at) VALUES (?,?,?,'legacy','legacy','legacy','failed',CURRENT_TIMESTAMP(6))",
                UUID.randomUUID().toString(), SourceReviewFixtures.version(source), "1".repeat(64));
        Path output = root.resolve("data/private/reports"); Files.createDirectories(output);
        Files.setPosixFilePermissions(output, PosixFilePermissions.fromString("rwx------"));
        Path raw = root.resolve(SourceReviewFixtures.document(source).path("raw_asset_path").asText());
        byte[] original = Files.readAllBytes(raw); var before = database();
        Path forbiddenSql = root.resolve("forbidden.sql"); Files.writeString(forbiddenSql, "CREATE TABLE report_forbidden_initialization (id INT);");
        Path forbiddenScript = root.resolve("forbidden-generated.sql");
        var result = run("--myai.report.document-version-id=" + SourceReviewFixtures.version(source),
                "--myai.report.source-root=" + root, "--myai.report.directory=" + output,
                "--spring.flyway.enabled=true", "--spring.jpa.hibernate.ddl-auto=create",
                "--spring.jpa.generate-ddl=true", "--spring.jpa.properties.hibernate.hbm2ddl.auto=create-drop",
                "--spring.jpa.properties.jakarta.persistence.schema-generation.database.action=drop-and-create",
                "--spring.jpa.properties.jakarta.persistence.schema-generation.scripts.action=create",
                "--spring.jpa.properties.jakarta.persistence.schema-generation.scripts.create-target=" + forbiddenScript,
                "--spring.sql.init.mode=always", "--spring.sql.init.schema-locations=" + forbiddenSql.toUri());
        assertThat(result.exit()).isZero();
        assertThat(result.json().path("status").asText()).isEqualTo("succeeded");
        Path file = output.resolve(result.json().path("result").path("file_name").asText());
        byte[] bytes = Files.readAllBytes(file);
        assertThat(result.json().path("result").path("checksum").asText()).isEqualTo(ReviewedImportReader.sha256(bytes));
        assertThat(new String(bytes, StandardCharsets.UTF_8)).contains("pending", "cleaned_text", "not_requested");
        assertThat(Files.getPosixFilePermissions(file)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
        assertThat(database()).isEqualTo(before); assertThat(Files.readAllBytes(raw)).isEqualTo(original);
        assertThat(Files.exists(forbiddenScript)).isFalse();
        assertThat(result.stdout()).doesNotContain(root.toString(), "cleaned_text", "pending", System.getenv("DB_PASSWORD"));
    }

    @Test
    void mixedAndWebModesFailBeforeDatabaseAndStartupErrorsStaySafe() throws Exception {
        for (String option : List.of("--spring.profiles.active=local-review-report,fixture", "--spring.profiles.active=local-review-report,local-source-review", "--spring.main.web-application-type=servlet")) {
            var result = unavailable(option);
            assertThat(result.exit()).isEqualTo(2);
            assertThat(result.json().path("error").path("code").asText()).isEqualTo("REPORT_VALIDATION_ERROR");
        }
        var cold = unavailable(); assertThat(cold.exit()).isEqualTo(4);
        assertThat(cold.json().path("error").path("code").asText()).isEqualTo("REPORT_DATABASE_UNAVAILABLE");
        assertThat(cold.json().path("error").path("retryable").asBoolean()).isTrue();
        var driver = unavailable("--spring.datasource.driver-class-name=PRIVATE_DRIVER");
        assertThat(driver.exit()).isEqualTo(1);
        assertThat(driver.json().path("error").path("code").asText()).isEqualTo("REPORT_INTERNAL_ERROR");
    }

    private Result unavailable(String... settings) throws Exception {
        var options = new ArrayList<>(List.of("--spring.datasource.url=jdbc:mysql://127.0.0.1:1/unavailable?connectTimeout=500&socketTimeout=500",
                "--spring.datasource.username=PRIVATE_USER", "--spring.datasource.password=PRIVATE_PASSWORD", "--spring.datasource.hikari.connection-timeout=1000",
                "--myai.report.document-version-id=10000000-0000-4000-8000-000000000007", "--myai.report.source-root=" + root, "--myai.report.directory=" + root));
        options.addAll(List.of(settings)); return run(options.toArray(String[]::new));
    }

    private Result run(String... settings) throws Exception {
        var command = new ArrayList<>(List.of(Path.of(System.getProperty("java.home"), "bin", "java").toString(), "-jar", "build/libs/myai-backend-0.1.0.jar", "--spring.profiles.active=local-review-report"));
        command.addAll(List.of(settings));
        Path stdout = root.resolve(UUID.randomUUID() + ".stdout"), stderr = root.resolve(UUID.randomUUID() + ".stderr");
        var builder = new ProcessBuilder(command).redirectOutput(stdout.toFile()).redirectError(stderr.toFile());
        builder.environment().put("MYAI_PYTHON_EXECUTABLE", PythonProbe.PYTHON);
        builder.environment().put("MYAI_PYTHON_WORKDIR", PythonProbe.REPO.toString());
        var process = builder.start();
        boolean ended = process.waitFor(30, TimeUnit.SECONDS);
        if (!ended) { process.destroyForcibly(); process.waitFor(10, TimeUnit.SECONDS); }
        assertThat(ended).as("report process exited").isTrue();
        String text = Files.readString(stdout);
        assertThat(text.lines().count()).isEqualTo(1); assertThat(text).doesNotContain("PRIVATE_", "jdbc:mysql", "Exception");
        return new Result(process.exitValue(), mapper.readTree(text), text);
    }

    private Map<String, String> database() {
        var result = new TreeMap<String, String>();
        for (String table : jdbc.queryForList("SELECT TABLE_NAME FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE() ORDER BY TABLE_NAME", String.class)) {
            var rows = jdbc.queryForList("SELECT * FROM `" + table + "`").stream().map(row -> {
                var cells = new TreeMap<String, String>(); row.forEach((key, value) -> cells.put(key, value == null ? null : value.toString()));
                return mapper.valueToTree(cells).toString();
            }).sorted().toList();
            result.put(table, rows.toString());
        }
        return result;
    }
    private record Result(int exit, JsonNode json, String stdout) {}
}
