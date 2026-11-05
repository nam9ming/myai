package kr.ac.myai.backend.repository;

import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.extraction.VerifiedExtraction;
import kr.ac.myai.backend.handoff.VerifiedHandoff;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.service.ExtractionImportService.Result;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.util.LinkedHashMap;
import java.util.Objects;
import java.util.Optional;

@Repository
@Profile("!fixture")
public class ExtractionRunRepository {
    private static final String DOCUMENT = "SELECT document_version_id, document_id, version_no, text_sha256, metadata_json, private_content_ref FROM document_versions WHERE document_version_id=?";
    private final JdbcTemplate jdbc;
    private final ReviewedImportReader json;

    public ExtractionRunRepository(JdbcTemplate jdbc, ReviewedImportReader json) { this.jdbc = jdbc; this.json = json; }

    public void checkDocument(VerifiedExtraction run) {
        var rows = jdbc.query("SELECT metadata_json FROM document_versions WHERE document_version_id=?",
                (row, index) -> row.getString(1), run.documentVersionId());
        if (rows.isEmpty()) throw new ExtractionException("EXTRACTION_VALIDATION_ERROR", "document_version_id", false);
        var saved = json.parseJson(rows.getFirst().getBytes(java.nio.charset.StandardCharsets.UTF_8));
        var doc = saved.path("document");
        var expected = JsonNodeFactory.instance.objectNode();
        expected.set("data_kind", saved.path("data_kind"));
        for (String field : new String[]{"document_version_id", "title", "published_date"}) expected.set(field, doc.path(field));
        expected.set("blocks", doc.path("block_index"));
        require(expected.equals(run.input()) && doc.path("preprocessing_version").equals(run.metadata().path("preprocessing_version")));
    }

    public Optional<Result> existing(VerifiedExtraction run) {
        var rows = jdbc.queryForList("SELECT * FROM extraction_runs WHERE run_id=?", run.runId());
        if (rows.isEmpty()) return Optional.empty();
        requireSame(run, rows.getFirst());
        return Optional.of(result(run, true));
    }

    private void requireSame(VerifiedExtraction run, java.util.Map<String, Object> row) {
        var fields = new LinkedHashMap<String, String>();
        fields.put("document_version_id", run.documentVersionId()); fields.put("input_sha256", run.inputSha256());
        fields.put("output_sha256", run.outputSha256()); fields.put("status", run.status());
        fields.put("raw_ref", run.directory().toString()); fields.put("data_kind", run.dataKind());
        fields.put("metadata_json", run.metadataJson()); fields.put("metadata_sha256", run.metadataSha256());
        fields.put("receipt_json", run.receiptJson()); fields.put("receipt_sha256", run.receiptSha256());
        for (String field : new String[]{"provider", "prompt_version", "model_version", "schema_version", "preprocessing_version", "execution_mode"}) fields.put(field, run.nullable(field));
        fields.put("model", run.nullable("model_label"));
        fields.forEach((key, value) -> require(Objects.equals(row.get(key), value)));
        require(row.get("attempts") instanceof Number count && count.intValue() == run.attempts());
    }

    public record Reference(String runId, String documentVersionId, String rowSha256, String documentRowSha256) {
        public Reference(String runId, String documentVersionId, String rowSha256) {
            this(runId, documentVersionId, rowSha256, null);
        }
    }

    public String referenceDirectory(String id) {
        var paths = jdbc.query("SELECT raw_ref FROM extraction_runs WHERE run_id=? AND status='validated' AND schema_version='extract-schema-v1' AND metadata_sha256 IS NOT NULL AND receipt_sha256 IS NOT NULL",
                (row, index) -> row.getString(1), id);
        if (paths.size() != 1 || paths.getFirst() == null) throw new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false);
        return paths.getFirst();
    }

    public Reference verifiedReference(VerifiedExtraction run) {
        var rows = jdbc.queryForList("SELECT * FROM extraction_runs WHERE run_id=?", run.runId());
        require(rows.size() == 1 && run.status().equals("validated"));
        requireSame(run, rows.getFirst());
        return new Reference(run.runId(), run.documentVersionId(), rowHash(rows.getFirst()));
    }

    public String handoffParentDirectory(String id, VerifiedHandoff handoff) {
        require(id.equals(handoff.projection().path("parent").path("run_id").asText()));
        var paths = jdbc.query("SELECT raw_ref FROM extraction_runs WHERE run_id=? AND status IN ('validated','failed') AND schema_version='extract-schema-v1' AND metadata_sha256 IS NOT NULL AND receipt_sha256 IS NOT NULL",
                (row, index) -> row.getString(1), id);
        require(paths.size() == 1 && paths.getFirst() != null);
        return paths.getFirst();
    }

    public Reference verifiedHandoffParent(VerifiedExtraction run, VerifiedHandoff handoff) {
        var projection = handoff.projection();
        var parent = projection.path("parent");
        require(run.runId().equals(parent.path("run_id").asText()) && run.status().equals(parent.path("status").asText())
                && run.nullable("execution_mode").equals(parent.path("execution_mode").asText())
                && run.receiptSha256().equals(parent.path("receipt_sha256").asText())
                && run.dataKind().equals(projection.path("data_kind").asText()));
        var rows = jdbc.queryForList("SELECT * FROM extraction_runs WHERE run_id=?", run.runId());
        require(rows.size() == 1);
        requireSame(run, rows.getFirst());
        require(projection.path("documents").isArray() && projection.path("documents").size() == 1);
        var document = projection.path("documents").get(0);
        require(document.path("document_version_id").asText().equals(run.documentVersionId()));
        var documents = jdbc.queryForList(DOCUMENT, run.documentVersionId());
        require(documents.size() == 1);
        var row = documents.getFirst();
        var expected = JsonNodeFactory.instance.objectNode().put("data_kind", run.dataKind());
        expected.set("document", document);
        require(expected.equals(json.parseJson(((String) row.get("metadata_json")).getBytes(java.nio.charset.StandardCharsets.UTF_8)))
                && document.path("document_id").asText().equals(row.get("document_id"))
                && document.path("version_no").asLong() == ((Number) row.get("version_no")).longValue()
                && document.path("text_sha256").asText().equals(row.get("text_sha256"))
                && document.path("raw_asset_path").asText().equals(row.get("private_content_ref")));
        return new Reference(run.runId(), run.documentVersionId(), rowHash(rows.getFirst()), rowHash(row));
    }

    public void checkReference(Reference reference) {
        var rows = jdbc.queryForList("SELECT * FROM extraction_runs WHERE run_id=? FOR SHARE", reference.runId());
        require(rows.size() == 1 && rowHash(rows.getFirst()).equals(reference.rowSha256()));
        if (reference.documentRowSha256() != null) {
            var documents = jdbc.queryForList(DOCUMENT + " FOR SHARE", reference.documentVersionId());
            require(documents.size() == 1 && rowHash(documents.getFirst()).equals(reference.documentRowSha256()));
        }
    }

    private String rowHash(java.util.Map<String, Object> row) {
        var payload = JsonNodeFactory.instance.objectNode();
        row.forEach((key, value) -> payload.put(key, value == null ? null : value.toString()));
        return ReviewedImportReader.sha256(payload.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
    }

    public void insert(VerifiedExtraction run, String actor) {
        jdbc.update("""
                INSERT INTO extraction_runs(run_id,document_version_id,input_sha256,output_sha256,provider,model,prompt_version,status,raw_ref,
                    model_version,schema_version,preprocessing_version,execution_mode,attempts,data_kind,metadata_json,metadata_sha256,receipt_json,receipt_sha256,registered_by,registered_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP(6))
                """, run.runId(), run.documentVersionId(), run.inputSha256(), run.outputSha256(), run.nullable("provider"), run.nullable("model_label"),
                run.nullable("prompt_version"), run.status(), run.directory().toString(), run.nullable("model_version"), run.nullable("schema_version"),
                run.nullable("preprocessing_version"), run.nullable("execution_mode"), run.attempts(), run.dataKind(), run.metadataJson(),
                run.metadataSha256(), run.receiptJson(), run.receiptSha256(), actor);
    }

    public Result result(VerifiedExtraction run, boolean alreadyRegistered) {
        return new Result(run.runId(), run.documentVersionId(), run.status(), run.attempts(), run.dataKind(), run.metadataSha256(), run.receiptSha256(), alreadyRegistered, true);
    }

    private static void require(boolean condition) {
        if (!condition) throw new ExtractionException("EXTRACTION_CONFLICT", null, false);
    }
}
