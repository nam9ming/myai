package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.validation.Validation;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.repository.PublicationRepository;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataIntegrityViolationException;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.sql.SQLException;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;

@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class CitizenSnapshotMigrationTest {
    @TempDir Path root;

    @Test
    void upgradesV4WithoutRewritingPublishedBytesAndKeepsFamilyVersionConstraints() throws Exception {
        Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwx------"));
        try (var database = RecoveryDatabase.start(root.toRealPath()); var factory = Validation.buildDefaultValidatorFactory()) {
            Flyway.configure().dataSource(database.url(), database.username(), database.password()).target("4").load().migrate();
            var jdbc = database.jdbc();
            var mapper = new ObjectMapper().findAndRegisterModules().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
            var reader = new ReviewedImportReader();
            var content = new PublicationContent(reader, mapper);
            var repository = new PublicationRepository(jdbc, mapper, reader);
            var input = (ObjectNode) mapper.readTree(Path.of("examples/publish.json").toFile());
            input.putArray("revision_ids");
            var command = (PublicationCommand.Publish) new PublicationCommandReader(reader, factory.getValidator())
                    .read(input.toString().getBytes(StandardCharsets.UTF_8));
            Instant at = Instant.parse("2026-11-02T03:00:00Z");
            var legacy = content.snapshot(command, List.of(), Map.of(), UUID.randomUUID().toString(), at);
            command.points().forEach(point -> repository.savePoint(point, command.dataKind()));
            repository.insertSnapshot(legacy, List.of(), at);
            var head = repository.switchHead("current", legacy.id(), null, at);
            repository.audit("current", "publish", legacy.id(), head, "합성 V4 공개본", "synthetic-migration", at);
            var before = jdbc.queryForList("SELECT * FROM snapshots ORDER BY snapshot_id");
            var points = jdbc.queryForList("SELECT * FROM test_points ORDER BY point_id");
            var heads = jdbc.queryForList("SELECT * FROM publication_heads ORDER BY channel_key");
            var audits = jdbc.queryForList("SELECT * FROM publication_audits ORDER BY audit_id");
            var history = jdbc.queryForList("SELECT * FROM flyway_schema_history WHERE version IN ('1','2','3','4') ORDER BY installed_rank");

            assertThat(history).hasSize(4);
            assertThatThrownBy(() -> insert(jdbc, "citizen-snapshot-v1", null, null)).isInstanceOf(DataIntegrityViolationException.class);
            Flyway.configure().dataSource(database.url(), database.username(), database.password()).load().migrate();

            assertThat(jdbc.queryForList("SELECT * FROM snapshots ORDER BY snapshot_id")).isEqualTo(before);
            assertThat(jdbc.queryForList("SELECT * FROM test_points ORDER BY point_id")).isEqualTo(points);
            assertThat(jdbc.queryForList("SELECT * FROM publication_heads ORDER BY channel_key")).isEqualTo(heads);
            assertThat(jdbc.queryForList("SELECT * FROM publication_audits ORDER BY audit_id")).isEqualTo(audits);
            assertThat(jdbc.queryForList("SELECT * FROM flyway_schema_history WHERE version IN ('1','2','3','4') ORDER BY installed_rank")).isEqualTo(history);
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM flyway_schema_history WHERE version='5' AND success=1", Long.class)).isEqualTo(1);
            content.verifySnapshot(repository.snapshot(legacy.id()), "current");
            insert(jdbc, "citizen-snapshot-v1", null, null);
            for (String schema : List.of("snapshot-v1", "legacy-other-version")) {
                rejectsVersionFamily(jdbc, schema, null, null);
            }
            rejectsVersionFamily(jdbc, "citizen-snapshot-v1", "fake-rules", "fake-dictionary");
        }
    }

    private void rejectsVersionFamily(org.springframework.jdbc.core.JdbcTemplate jdbc, String schema, String rules, String dictionary) {
        assertThatThrownBy(() -> insert(jdbc, schema, rules, dictionary)).isInstanceOf(DataAccessException.class)
                .hasRootCauseInstanceOf(SQLException.class).rootCause().isInstanceOfSatisfying(SQLException.class, cause -> {
                    assertThat(cause.getErrorCode()).isEqualTo(3819);
                    assertThat(cause.getMessage()).contains("chk_snapshot_version_family");
                });
    }

    private void insert(org.springframework.jdbc.core.JdbcTemplate jdbc, String schema, String rules, String dictionary) {
        String canonical = "{}";
        jdbc.update("INSERT INTO snapshots(snapshot_id,mode,schema_version,rules_version,dictionary_version,canonical_json,checksum,metadata_json,data_kind) VALUES (?,'current',?,?,?,?,?,'{}','synthetic')",
                UUID.randomUUID().toString(), schema, rules, dictionary, canonical,
                ReviewedImportReader.sha256(canonical.getBytes(StandardCharsets.UTF_8)));
    }
}
