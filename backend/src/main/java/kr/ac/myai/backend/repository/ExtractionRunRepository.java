package kr.ac.myai.backend.repository;

import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.extraction.VerifiedExtraction;
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
        var row = rows.getFirst();
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
        return Optional.of(result(run, true));
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
