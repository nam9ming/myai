package kr.ac.myai.backend.repository;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedBatch;
import kr.ac.myai.backend.service.ReviewedImportService.ImportResult;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

@Repository
@Profile("!fixture")
public class ReviewedImportRepository {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;

    public ReviewedImportRepository(JdbcTemplate jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    public Optional<ImportResult> findBatch(ReviewedBatch batch) {
        return jdbc.query("SELECT import_id, status, result_refs_json FROM import_batches WHERE source_kind = ? AND input_sha256 = ? AND schema_version = ?",
                (row, index) -> {
                    require(row.getString("status").equals("succeeded"), "import_batches");
                    JsonNode refs = json(row.getString("result_refs_json"));
                    return new ImportResult(row.getString("import_id"), strings(refs.path("revision_ids")), strings(refs.path("document_version_ids")), true);
                }, sourceKind(batch), batch.inputSha256(), batch.schemaVersion()).stream().findFirst();
    }

    public void beginBatch(String id, ReviewedBatch batch) {
        jdbc.update("INSERT INTO import_batches(import_id, source_kind, input_sha256, schema_version, status) VALUES (?, ?, ?, ?, 'received')",
                id, sourceKind(batch), batch.inputSha256(), batch.schemaVersion());
    }

    private String sourceKind(ReviewedBatch batch) { return batch.schemaVersion().equals("source-import-v1") ? "source" : "reviewed"; }

    public void completeBatch(ImportResult result) {
        var refs = mapper.createObjectNode();
        var revisions = refs.putArray("revision_ids");
        result.revisionIds().forEach(revisions::add);
        var documents = refs.putArray("document_version_ids");
        result.documentVersionIds().forEach(documents::add);
        require(jdbc.update("UPDATE import_batches SET status = 'succeeded', result_refs_json = ? WHERE import_id = ? AND status = 'received'",
                refs.toString(), result.importId()) == 1, "import_batches");
    }

    public void saveDocument(ReviewedBatch.Document doc) {
        var existing = jdbc.queryForList("SELECT document_id, version_no, text_sha256, metadata_json, private_content_ref FROM document_versions WHERE document_version_id = ?", doc.versionId());
        if (!existing.isEmpty()) {
            var version = existing.getFirst();
            require(doc.id().equals(version.get("document_id")) && doc.versionNo() == ((Number) version.get("version_no")).longValue()
                    && doc.textSha256().equals(version.get("text_sha256")) && doc.privateContentRef().equals(version.get("private_content_ref"))
                    && json(doc.metadataJson()).equals(json((String) version.get("metadata_json"))), "documents.document_version_id");
            return;
        }
        var documents = jdbc.queryForList("SELECT source_url FROM documents WHERE document_id = ?", doc.id());
        if (documents.isEmpty()) {
            jdbc.update("INSERT INTO documents(document_id, source_url, source_external_id, source_type) VALUES (?, ?, NULL, 'official_notice')", doc.id(), doc.sourceUrl());
        } else require(doc.sourceUrl().equals(documents.getFirst().get("source_url")), "documents.document_id");
        var latest = jdbc.queryForList("SELECT version_no, metadata_json FROM document_versions WHERE document_id = ? ORDER BY version_no DESC LIMIT 1", doc.id());
        long previous = latest.isEmpty() ? 0 : ((Number) latest.getFirst().get("version_no")).longValue();
        require(previous < Long.MAX_VALUE && doc.versionNo() == previous + 1, "documents.version_no");
        if (!latest.isEmpty()) require(json((String) latest.getFirst().get("metadata_json")).path("data_kind").equals(json(doc.metadataJson()).path("data_kind")), "data_kind");
        jdbc.update("INSERT INTO document_versions(document_version_id, document_id, version_no, text_sha256, metadata_json, private_content_ref) VALUES (?, ?, ?, ?, ?, ?)",
                doc.versionId(), doc.id(), doc.versionNo(), doc.textSha256(), doc.metadataJson(), doc.privateContentRef());
        for (var check : doc.checks()) {
            jdbc.update("INSERT INTO source_checks(check_id, document_version_id, checked_at, result, last_success_ref, note) VALUES (?, ?, ?, ?, ?, ?)",
                    check.id(), doc.versionId(), Timestamp.from(check.checkedAt()), check.result(), check.lastSuccessRef(), check.note());
        }
    }

    public boolean eventExists(String id) {
        return Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM events WHERE event_id = ?)", Boolean.class, id));
    }

    public boolean runMatches(String id, List<String> sources) {
        var versions = jdbc.query("SELECT document_version_id FROM extraction_runs WHERE run_id = ? AND status = 'validated' AND schema_version = 'extract-schema-v1' AND metadata_sha256 IS NOT NULL AND receipt_sha256 IS NOT NULL", (row, index) -> row.getString(1), id);
        return versions.size() == 1 && sources.contains(versions.getFirst());
    }

    public void appendEvent(ReviewedBatch.Event event, String kind, String actor) {
        require((event.reviewStatus().equals("draft") || event.reviewStatus().equals("needs_review")) && event.publicationIntent().equals("hidden"), "review_status");
        append(event, kind, actor, "import", "검토 JSON 로컬 import", json(event.payloadJson()).path("evidence").toString());
    }

    public void appendDecision(ReviewedBatch.Event event, String kind, String actor, String reason, String evidenceJson) {
        append(event, kind, actor, event.reviewStatus().equals("approved") ? "approve" : "reject", reason, evidenceJson);
    }

    private void append(ReviewedBatch.Event event, String kind, String actor, String action, String reason, String evidenceJson) {
        var states = jdbc.queryForList("SELECT e.current_review_revision_id, e.lock_version, r.revision_no, r.payload_json FROM events e LEFT JOIN event_revisions r ON r.revision_id = e.current_review_revision_id WHERE e.event_id = ?", event.id());
        String before = null;
        long lockVersion = 0;
        if (states.isEmpty()) {
            require(event.expectedRevisionNo() == 0, "events.expected_revision_no");
            jdbc.update("INSERT INTO events(event_id) VALUES (?)", event.id());
        } else {
            var state = states.getFirst();
            before = (String) state.get("current_review_revision_id");
            require(before != null && state.get("revision_no") != null && ((Number) state.get("revision_no")).longValue() == event.expectedRevisionNo(), "events.expected_revision_no");
            require(json((String) state.get("payload_json")).path("data_kind").asText().equals(kind), "data_kind");
            lockVersion = ((Number) state.get("lock_version")).longValue();
        }
        require(lockVersion < Long.MAX_VALUE, "events.lock_version");
        jdbc.update("INSERT INTO event_revisions(revision_id, event_id, revision_no, review_status, publication_intent, payload_json, payload_sha256, reviewed_at, reviewed_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                event.revisionId(), event.id(), event.revisionNo(), event.reviewStatus(), event.publicationIntent(), event.payloadJson(), event.payloadSha256(),
                event.reviewedAt() == null ? null : Timestamp.from(event.reviewedAt()), event.reviewerId());
        require(jdbc.update("UPDATE events SET current_review_revision_id = ?, lock_version = lock_version + 1 WHERE event_id = ? AND lock_version = ?",
                event.revisionId(), event.id(), lockVersion) == 1, "events.lock_version");
        jdbc.update("INSERT INTO review_audits(audit_id, event_id, revision_id, action, before_ref, after_ref, reason, evidence_json, actor, happened_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                UUID.randomUUID().toString(), event.id(), event.revisionId(), action, before, event.revisionId(), reason, evidenceJson, actor, Timestamp.from(Instant.now()));
    }

    private JsonNode json(String value) {
        try { return mapper.readTree(Objects.requireNonNull(value)); }
        catch (JsonProcessingException ex) { throw new IllegalStateException("저장된 import JSON을 읽을 수 없습니다."); }
    }

    private List<String> strings(JsonNode array) {
        List<String> result = new ArrayList<>();
        array.forEach(value -> result.add(value.asText()));
        return result;
    }

    private void require(boolean condition, String field) {
        if (!condition) throw new ImportException("IMPORT_CONFLICT", "기존 문서·revision 또는 예상 버전과 충돌합니다. 최신 상태를 확인해 주세요.", field);
    }
}
