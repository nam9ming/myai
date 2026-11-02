package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;

@SpringBootTest
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class ExtractionRunMySqlTest {
    @Autowired JdbcTemplate jdbc;
    @Autowired ReviewedImportReader reader;
    @Autowired ReviewedImportService importer;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();

    @Test
    void sourceOnlyImportIsIdempotentAndNeverCreatesAnEventOrPublication() throws Exception {
        var input = source();
        var batch = reader.read(Files.writeString(root.resolve("source.json"), input.toString()), root);
        var before = counts();
        var first = importer.importBatch(batch, "synthetic-source-collector");
        var repeated = importer.importBatch(batch, "another-collector");
        assertThat(first.revisionIds()).isEmpty(); assertThat(repeated.alreadyImported()).isTrue();
        assertThat(repeated.importId()).isEqualTo(first.importId()); assertThat(counts()).isEqualTo(before);
        assertThat(jdbc.queryForObject("SELECT source_kind FROM import_batches WHERE import_id = ?", String.class, first.importId())).isEqualTo("source");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM document_versions WHERE document_version_id = ?", Long.class, batch.documents().getFirst().versionId())).isEqualTo(1);
    }

    @Test
    void migrationPreservesLegacyRowsAndAcceptsNullableExactMetadata() throws Exception {
        var input = source();
        var batch = reader.read(Files.writeString(root.resolve("source.json"), input.toString()), root);
        importer.importBatch(batch, "synthetic-source-collector");
        String table = "legacy_run_" + UUID.randomUUID().toString().replace("-", "");
        String v1 = Files.readString(Path.of("src/main/resources/db/migration/V1__create_review_and_publication_schema.sql"));
        String ddl = v1.substring(v1.indexOf("CREATE TABLE extraction_runs"), v1.indexOf("CREATE TABLE events"));
        jdbc.execute(ddl.replace("extraction_runs", table).strip());
        String id = UUID.randomUUID().toString();
        try {
            jdbc.update("INSERT INTO " + table + "(run_id,document_version_id,input_sha256,provider,model,prompt_version,status) VALUES (?,?,?,'legacy-provider','legacy-model','legacy-prompt','validated')",
                    id, batch.documents().getFirst().versionId(), "1".repeat(64));
            String migration = Files.readString(Path.of("src/main/resources/db/migration/V3__extend_extraction_run_metadata.sql"));
            for (String statement : migration.replace("extraction_runs", table).split(";")) if (!statement.isBlank()) jdbc.execute(statement);
            var row = jdbc.queryForMap("SELECT * FROM " + table + " WHERE run_id = ?", id);
            assertThat(row.get("provider")).isEqualTo("legacy-provider"); assertThat(row.get("model")).isEqualTo("legacy-model");
            assertThat(row.get("metadata_json")).isNull(); assertThat(row.get("receipt_json")).isNull();
            String raw = "{\"cost\":0.1234567890123456789,\"finished_at\":\"2026-11-03T01:00:00.123456789Z\",\"unknown\":null,\"한글\":\"😀\"}";
            jdbc.update("UPDATE " + table + " SET provider=NULL, model=NULL, metadata_json=?, metadata_sha256=? WHERE run_id=?", raw, ReviewedImportReader.sha256(raw.getBytes(java.nio.charset.StandardCharsets.UTF_8)), id);
            assertThat(jdbc.queryForObject("SELECT metadata_json FROM " + table + " WHERE run_id=?", String.class, id)).isEqualTo(raw);
        } finally { jdbc.execute("DROP TABLE " + table); }
    }

    private List<Long> counts() {
        return List.of("events", "event_revisions", "snapshots", "publication_heads").stream()
                .map(table -> jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Long.class)).toList();
    }

    ObjectNode source() throws Exception {
        Files.copy(Path.of("examples/synthetic-source.txt"), root.resolve("synthetic-source.txt"));
        var input = (ObjectNode) mapper.readTree(Path.of("examples/reviewed-import.json").toFile());
        input.put("schema_version", "source-import-v1"); input.putArray("evidence"); input.putArray("events");
        var doc = (ObjectNode) input.path("documents").get(0);
        doc.put("document_id", UUID.randomUUID().toString()).put("document_version_id", UUID.randomUUID().toString());
        for (var check : doc.path("checks")) ((ObjectNode) check).put("check_id", UUID.randomUUID().toString());
        return input;
    }
}
