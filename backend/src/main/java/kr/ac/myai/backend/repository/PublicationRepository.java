package kr.ac.myai.backend.repository;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationException;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

@Repository
@Profile("!fixture")
public class PublicationRepository {
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final ReviewedImportReader json;

    public PublicationRepository(JdbcTemplate jdbc, ObjectMapper mapper, ReviewedImportReader json) {
        this.jdbc = jdbc; this.mapper = mapper; this.json = json;
    }

    public record Revision(String id, String eventId, long number, String status, String intent,
                           String payload, String hash, String currentId, long lockVersion) { }
    public record Document(String id, String versionId, long number, String textHash, String metadata, String privateRef) { }
    public record Snapshot(String id, String mode, String caseId, String canonical, String checksum,
                           String kind, String rulesVersion, String dictionaryVersion) { }
    public record HeadChange(String before, long version) { }

    private static final String REVISION = "SELECT r.revision_id, r.event_id, r.revision_no, r.review_status, r.publication_intent, r.payload_json, r.payload_sha256, e.current_review_revision_id, e.lock_version FROM event_revisions r JOIN events e ON e.event_id = r.event_id ";

    public Revision current(String eventId) {
        return jdbc.query(REVISION + "WHERE e.event_id = ? AND r.revision_id = e.current_review_revision_id", this::mapRevision, eventId)
                .stream().findFirst().orElseThrow(() -> missing("event_id"));
    }

    public Revision revision(String id) {
        return jdbc.query(REVISION + "WHERE r.revision_id = ?", this::mapRevision, id).stream().findFirst().orElseThrow(() -> missing("revision_ids"));
    }

    public void lockRevision(Revision expected) {
        var current = jdbc.query(REVISION + "WHERE r.revision_id = ? FOR UPDATE", this::mapRevision, expected.id()).stream().findFirst().orElseThrow(() -> missing("revision_ids"));
        require(current.currentId().equals(expected.id()) && current.lockVersion() == expected.lockVersion()
                && current.hash().equals(expected.hash()) && current.status().equals(expected.status()) && current.intent().equals(expected.intent()), "revision_ids");
    }

    public Document document(String id) {
        return jdbc.query("SELECT document_id, document_version_id, version_no, text_sha256, metadata_json, private_content_ref FROM document_versions WHERE document_version_id = ?",
                (row, index) -> new Document(row.getString(1), row.getString(2), row.getLong(3), row.getString(4), row.getString(5), row.getString(6)), id)
                .stream().findFirst().orElseThrow(() -> missing("source_version_ids"));
    }

    public void lockDocument(Document expected) {
        var rows = jdbc.queryForList("SELECT metadata_json, text_sha256, private_content_ref FROM document_versions WHERE document_version_id = ? FOR UPDATE", expected.versionId());
        require(rows.size() == 1, "source_version_ids");
        var current = rows.getFirst();
        require(expected.textHash().equals(current.get("text_sha256")) && java.util.Objects.equals(expected.privateRef(), current.get("private_content_ref"))
                && json.parseJson(expected.metadata().getBytes(StandardCharsets.UTF_8)).equals(json.parseJson(((String) current.get("metadata_json")).getBytes(StandardCharsets.UTF_8))), "documents");
    }

    public void savePoint(PublicationCommand.Point point, String kind) {
        var existing = jdbc.queryForList("SELECT area_id, evidence_json, version, data_kind FROM test_points WHERE point_id = ?", point.pointId().toString());
        var metadata = mapper.valueToTree(point);
        if (existing.isEmpty()) {
            require(point.version() == 1, "points.version");
            jdbc.update("INSERT INTO test_points(point_id, area_id, label, longitude, latitude, evidence_json, version, data_kind) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    point.pointId().toString(), point.areaId().toString(), point.label(), point.lon(), point.lat(), metadata.toString(), point.version(), kind);
            return;
        }
        var before = existing.getFirst();
        require(before.get("data_kind").equals(kind) && before.get("area_id").equals(point.areaId().toString()), "points.data_kind");
        long version = ((Number) before.get("version")).longValue();
        var prior = json.parseJson(((String) before.get("evidence_json")).getBytes(StandardCharsets.UTF_8));
        if (version == point.version() && prior.equals(json.parseJson(metadata.toString().getBytes(StandardCharsets.UTF_8)))) return;
        require(version < Long.MAX_VALUE && point.version() == version + 1, "points.version");
        require(jdbc.update("UPDATE test_points SET label = ?, longitude = ?, latitude = ?, evidence_json = ?, version = ? WHERE point_id = ? AND version = ?",
                point.label(), point.lon(), point.lat(), metadata.toString(), point.version(), point.pointId().toString(), version) == 1, "points.version");
    }

    public void insertSnapshot(Snapshot snapshot, List<Revision> revisions, Instant createdAt) {
        jdbc.update("INSERT INTO snapshots(snapshot_id, mode, case_id, schema_version, rules_version, dictionary_version, canonical_json, checksum, metadata_json, created_at, data_kind) VALUES (?, ?, ?, 'snapshot-v1', ?, ?, ?, ?, '{}', ?, ?)",
                snapshot.id(), snapshot.mode(), snapshot.caseId(), snapshot.rulesVersion(), snapshot.dictionaryVersion(), snapshot.canonical(), snapshot.checksum(), Timestamp.from(createdAt), snapshot.kind());
        for (var revision : revisions) jdbc.update("INSERT INTO snapshot_revisions(snapshot_id, event_id, revision_id) VALUES (?, ?, ?)", snapshot.id(), revision.eventId(), revision.id());
    }

    public Snapshot snapshot(String id) {
        return jdbc.query("SELECT snapshot_id, mode, case_id, canonical_json, checksum, data_kind, rules_version, dictionary_version FROM snapshots WHERE snapshot_id = ?",
                (row, index) -> new Snapshot(row.getString(1), row.getString(2), row.getString(3), row.getString(4), row.getString(5), row.getString(6), row.getString(7), row.getString(8)), id)
                .stream().findFirst().orElseThrow(() -> missing("snapshot_id"));
    }

    public boolean wasPublished(String channel, String snapshot) {
        return Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM publication_audits WHERE channel_key = ? AND after_snapshot_id = ? AND action = 'publish')", Boolean.class, channel, snapshot));
    }

    public HeadChange switchHead(String channel, String snapshot, Long expected, Instant now) {
        var rows = jdbc.queryForList("SELECT snapshot_id, lock_version FROM publication_heads WHERE channel_key = ? FOR UPDATE", channel);
        if (rows.isEmpty()) {
            require(expected == null, "expected_head_version");
            jdbc.update("INSERT INTO publication_heads(channel_key, snapshot_id, lock_version, changed_at) VALUES (?, ?, 0, ?)", channel, snapshot, Timestamp.from(now));
            return new HeadChange(null, 0);
        }
        var before = rows.getFirst();
        long version = ((Number) before.get("lock_version")).longValue();
        require(expected != null && expected == version && version < Long.MAX_VALUE, "expected_head_version");
        require(jdbc.update("UPDATE publication_heads SET snapshot_id = ?, lock_version = lock_version + 1, changed_at = ? WHERE channel_key = ? AND lock_version = ?",
                snapshot, Timestamp.from(now), channel, version) == 1, "expected_head_version");
        return new HeadChange((String) before.get("snapshot_id"), version + 1);
    }

    public void audit(String channel, String action, String snapshot, HeadChange change, String reason, String actor, Instant now) {
        jdbc.update("INSERT INTO publication_audits(audit_id, channel_key, action, before_snapshot_id, after_snapshot_id, head_version, reason, actor, happened_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                UUID.randomUUID().toString(), channel, action, change.before(), snapshot, change.version(), reason, actor, Timestamp.from(now));
    }

    private Revision mapRevision(ResultSet row, int index) throws SQLException {
        return new Revision(row.getString(1), row.getString(2), row.getLong(3), row.getString(4), row.getString(5), row.getString(6), row.getString(7), row.getString(8), row.getLong(9));
    }

    private void require(boolean condition, String field) {
        if (!condition) throw new PublicationException("PUBLICATION_CONFLICT", "예상 revision·공개 포인터·지점 버전과 충돌합니다. 최신 상태를 확인해 주세요.", field);
    }

    private PublicationException missing(String field) {
        return new PublicationException("PUBLICATION_NOT_FOUND", "등록된 검토본 또는 snapshot을 찾을 수 없습니다.", field);
    }
}
