package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class CitizenPublicationJarMySqlTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();

    @Test
    void actualJarPreviewsWithSelectOnlyAccountAndPreservesExportReportAndRollbackBytes() throws Exception {
        Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwx------"));
        Path databaseRoot = Files.createDirectory(root.resolve("database"), PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        try (var database = RecoveryDatabase.start(databaseRoot)) {
            Path sources = Files.createDirectory(root.resolve("sources"));
            Path source = Files.copy(Path.of("examples/citizen-source.txt"), sources.resolve("citizen-source.txt"));
            Path input = write((ObjectNode) mapper.readTree(Path.of("examples/citizen-reviewed-import.json").toFile()));
            run(database, database.username(), database.password(), "local-import", "--myai.import.file=" + input,
                    "--myai.import.source-root=" + sources, "--myai.import.actor=synthetic-importer");
            Path decision = write((ObjectNode) mapper.readTree(Path.of("examples/citizen-approve.json").toFile()));
            var approved = run(database, database.username(), database.password(), "local-publication", "--myai.publication.file=" + decision,
                    "--myai.publication.source-root=" + sources, "--myai.publication.actor=synthetic-reviewer");
            String revision = approved.path("result").path("revision_id").asText();
            String readUser = "city_ro_" + UUID.randomUUID().toString().replace("-", "").substring(0, 12);
            String readPassword = UUID.randomUUID().toString().replace("-", "");
            createReadOnly(database, readUser, readPassword);

            var command = mapper.createObjectNode().put("schema_version", "citizen-publication-command-v1")
                    .put("action", "preview").put("reason", "합성 시민 발행 검증").put("data_kind", "synthetic").putNull("expected_head_version");
            command.putArray("revision_ids").add(revision);
            Path request = write(command);
            var before = rows(database);
            var preview = run(database, readUser, readPassword, "local-publication", "--spring.flyway.enabled=false",
                    "--myai.publication.file=" + request, "--myai.publication.source-root=" + sources, "--myai.publication.actor=synthetic-preview");
            assertThat(preview.path("result").path("preview").path("notice_count").asInt(-1)).isEqualTo(1);
            assertThat(rows(database)).isEqualTo(before);

            command.put("action", "publish"); request = write(command);
            var published = run(database, database.username(), database.password(), "local-publication", "--myai.publication.file=" + request,
                    "--myai.publication.source-root=" + sources, "--myai.publication.actor=synthetic-publisher");
            String id = published.path("result").path("snapshot_id").asText();
            String canonical = database.jdbc().queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id=?", String.class, id);
            String checksum = published.path("result").path("checksum").asText();
            assertThat(checksum).isEqualTo(ReviewedImportReader.sha256(canonical.getBytes(StandardCharsets.UTF_8)));
            Path exports = Files.createDirectory(root.resolve("exports"));
            var exported = run(database, readUser, readPassword, "local-export", "--myai.export.snapshot-id=" + id,
                    "--myai.export.directory=" + exports);
            assertThat(Files.readAllBytes(exports.resolve(exported.path("result").path("file_name").asText())))
                    .isEqualTo(canonical.getBytes(StandardCharsets.UTF_8));

            command.put("action", "preview").put("expected_head_version", 0);
            Path previewFile = write(command);
            Path reports = Files.createDirectories(sources.resolve("data/private/reports"));
            Files.setPosixFilePermissions(reports, PosixFilePermissions.fromString("rwx------"));
            String document = mapper.readTree(input.toFile()).path("documents").get(0).path("document_version_id").asText();
            before = rows(database);
            var reported = run(database, readUser, readPassword, "local-review-report", "--myai.report.document-version-id=" + document,
                    "--myai.report.source-root=" + sources, "--myai.report.directory=" + reports, "--myai.report.preview-file=" + previewFile);
            String report = Files.readString(reports.resolve(reported.path("result").path("file_name").asText()));
            assertThat(report).contains("citizen-snapshot-v1", "citizen:current", "unchanged_events");
            assertThat(rows(database)).isEqualTo(before);

            command.put("action", "publish").putArray("revision_ids");
            run(database, database.username(), database.password(), "local-publication", "--myai.publication.file=" + write(command),
                    "--myai.publication.source-root=" + sources, "--myai.publication.actor=synthetic-publisher");
            Files.delete(source);
            var rollback = mapper.createObjectNode().put("schema_version", "citizen-publication-command-v1").put("action", "rollback")
                    .put("reason", "합성 이전 공개본 복구").put("snapshot_id", id).put("expected_head_version", 1);
            var restored = run(database, database.username(), database.password(), "local-publication", "--myai.publication.file=" + write(rollback),
                    "--myai.publication.actor=synthetic-rollback");
            assertThat(restored.path("result").path("head_version").asLong(-1)).isEqualTo(2);
            assertThat(database.jdbc().queryForObject("SELECT snapshot_id FROM publication_heads WHERE channel_key='citizen:current'", String.class)).isEqualTo(id);
            assertThat(database.jdbc().queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id=?", String.class, id)).isEqualTo(canonical);
            assertThat(database.jdbc().queryForObject("SELECT checksum FROM snapshots WHERE snapshot_id=?", String.class, id)).isEqualTo(checksum);
            assertThat(database.jdbc().queryForObject("SELECT COUNT(*) FROM publication_heads WHERE channel_key='current'", Long.class)).isZero();
        }
    }

    private Path write(ObjectNode value) throws Exception { return Files.writeString(root.resolve(UUID.randomUUID() + ".json"), value.toString()); }

    private JsonNode run(RecoveryDatabase database, String username, String password, String profile, String... options) throws Exception {
        Path out = root.resolve(UUID.randomUUID() + ".out"), err = root.resolve(UUID.randomUUID() + ".err");
        var command = new ArrayList<String>(List.of(Path.of(System.getProperty("java.home"), "bin", "java").toString(), "-jar",
                Path.of("build/libs/myai-backend-0.1.0.jar").toAbsolutePath().toString(), "--spring.profiles.active=" + profile));
        command.addAll(List.of(options));
        var builder = new ProcessBuilder(command).directory(PythonProbe.REPO.toFile()).redirectOutput(out.toFile()).redirectError(err.toFile());
        var env = builder.environment(); env.clear(); env.put("LANG", "C.UTF-8");
        env.put("PATH", System.getenv("PATH")); env.put("DB_URL", database.url()); env.put("DB_USERNAME", username); env.put("DB_PASSWORD", password);
        env.put("MYAI_PYTHON_EXECUTABLE", PythonProbe.PYTHON); env.put("MYAI_PYTHON_WORKDIR", PythonProbe.REPO.toString());
        var process = builder.start();
        try {
            assertThat(process.waitFor(50, TimeUnit.SECONDS)).as("JAR 실행 제한").isTrue();
            assertThat(process.exitValue()).as(Files.readString(err) + Files.readString(out)).isZero();
            var result = mapper.readTree(out.toFile()); assertThat(result.path("status").asText()).isEqualTo("succeeded"); return result;
        } finally { if (process.isAlive()) { process.destroyForcibly(); process.waitFor(10, TimeUnit.SECONDS); } }
    }

    private void createReadOnly(RecoveryDatabase database, String username, String password) throws Exception {
        Path out = root.resolve("grant.out"), err = root.resolve("grant.err");
        var process = new ProcessBuilder("docker", "exec", "--interactive", database.id(), "sh", "-c",
                "MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\" exec mysql --user=root --default-character-set=utf8mb4")
                .redirectOutput(out.toFile()).redirectError(err.toFile()).start();
        try {
            try (var input = process.getOutputStream()) {
                input.write(("CREATE USER '" + username + "'@'%' IDENTIFIED BY '" + password + "'; GRANT SELECT ON myai_recovery.* TO '"
                        + username + "'@'%';").getBytes(StandardCharsets.UTF_8));
            }
            assertThat(process.waitFor(15, TimeUnit.SECONDS)).isTrue(); assertThat(process.exitValue()).as(Files.readString(err)).isZero();
        } finally { if (process.isAlive()) { process.destroyForcibly(); process.waitFor(5, TimeUnit.SECONDS); } }
    }

    private Map<String, List<Map<String, Object>>> rows(RecoveryDatabase database) {
        var result = new LinkedHashMap<String, List<Map<String, Object>>>();
        for (String table : database.jdbc().queryForList("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME", String.class)) {
            assertThat(table).matches("[a-z_]+");
            result.put(table, database.jdbc().queryForList("SELECT * FROM `" + table + "` ORDER BY 1"));
        }
        return result;
    }
}
