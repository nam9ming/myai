package kr.ac.myai.backend;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class MySqlFoundationTest {
    @Autowired JdbcTemplate jdbc;
    @Autowired Flyway flyway;
    @Autowired MockMvc mvc;

    @Test
    void shouldMigrateOnceWithUtcAndRepeatableRead() {
        var tables = jdbc.queryForList("SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()", String.class);
        assertThat(tables).contains("test_points", "place_dictionary", "documents", "document_versions", "source_checks",
                "extraction_runs", "events", "event_revisions", "review_audits", "snapshots", "snapshot_revisions",
                "publication_heads", "import_batches");
        assertThat(flyway.migrate().migrationsExecuted).isZero();
        assertThat(jdbc.queryForObject("SELECT @@session.time_zone", String.class)).isIn("+00:00", "UTC");
        assertThat(jdbc.queryForObject("SELECT @@session.transaction_isolation", String.class)).isEqualTo("REPEATABLE-READ");
    }

    @Test
    @Transactional
    void shouldPreserveCanonicalUtf8AndRejectInvalidReferences() throws Exception {
        String id = UUID.randomUUID().toString();
        String canonical = "{\"한글\":\"가상 😀\", \"unknown\":null, \"events\":[]}";
        String checksum = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(canonical.getBytes(StandardCharsets.UTF_8)));
        jdbc.update("INSERT INTO snapshots(snapshot_id, mode, schema_version, rules_version, dictionary_version, canonical_json, checksum, metadata_json, data_kind) VALUES (?, 'current', 'snapshot-v1', 'rules-v1', 'dictionary-v1', ?, ?, '{}', 'synthetic')", id, canonical, checksum);
        assertThat(jdbc.queryForObject("SELECT canonical_json FROM snapshots WHERE snapshot_id = ?", String.class, id)).isEqualTo(canonical);
        assertThat(jdbc.queryForObject("SELECT checksum FROM snapshots WHERE snapshot_id = ?", String.class, id)).isEqualTo(checksum);
        assertThatThrownBy(() -> jdbc.update("INSERT INTO publication_heads(channel_key, snapshot_id) VALUES ('current', ?)", UUID.randomUUID().toString()))
                .isInstanceOf(DataIntegrityViolationException.class);
        assertThatThrownBy(() -> jdbc.update("INSERT INTO import_batches(import_id, source_kind, input_sha256, schema_version, status) VALUES (?, 'reviewed', ?, 'v1', 'received'), (?, 'reviewed', ?, 'v1', 'received')",
                UUID.randomUUID().toString(), checksum, UUID.randomUUID().toString(), checksum)).isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    void shouldNotExposeFixturesWhenRealDataIsNotReady() throws Exception {
        mvc.perform(get("/api/v1/config")).andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.error.code").value("PUBLIC_DATA_NOT_READY"))
                .andExpect(jsonPath("$.data").doesNotExist());
    }
}
