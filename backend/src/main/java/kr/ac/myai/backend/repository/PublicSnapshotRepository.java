package kr.ac.myai.backend.repository;

import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

@Repository
@Profile("!fixture")
public class PublicSnapshotRepository {
    public static final int MAX_CITIZEN_HISTORY = 1000;
    private final JdbcTemplate jdbc;

    public PublicSnapshotRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public record Published(PublicationRepository.Snapshot snapshot, String schemaVersion, Instant createdAt, String currentId) { }
    public record Historic(String snapshotId, String revisionId, Instant publishedAt, String action) { }
    public record CitizenHistoric(String snapshotId, String revisionId, Instant publishedAt, String action, long version, String beforeId) { }
    public record CitizenHistory(long headVersion, long startVersion, long endVersion, List<CitizenHistoric> audits) { }

    public Optional<String> head(String channel) {
        return jdbc.query("SELECT snapshot_id FROM publication_heads WHERE channel_key = ?", (row, i) -> row.getString(1), channel).stream().findFirst();
    }

    public Optional<Published> published(String id) {
        return jdbc.query("""
                SELECT s.snapshot_id, s.mode, s.case_id, s.canonical_json, s.checksum, s.data_kind,
                       s.rules_version, s.dictionary_version, s.schema_version, s.created_at, h.snapshot_id
                FROM snapshots s
                LEFT JOIN publication_heads h ON h.channel_key = IF(s.mode = 'current', 'current', CONCAT('replay:', s.case_id))
                WHERE s.snapshot_id = ? AND s.schema_version <> 'citizen-snapshot-v1' AND EXISTS (
                    SELECT 1 FROM publication_audits a WHERE a.after_snapshot_id = s.snapshot_id
                    AND a.channel_key = IF(s.mode = 'current', 'current', CONCAT('replay:', s.case_id)) AND a.action = 'publish')
                """, (row, i) -> new Published(new PublicationRepository.Snapshot(row.getString(1), row.getString(2), row.getString(3),
                        row.getString(4), row.getString(5), row.getString(6), row.getString(7), row.getString(8)),
                        row.getString(9), row.getTimestamp(10).toInstant(), row.getString(11)), id).stream().findFirst();
    }

    public Optional<Published> citizenPublished(String id) {
        return jdbc.query("""
                SELECT s.snapshot_id, s.mode, s.case_id, s.canonical_json, s.checksum, s.data_kind,
                       s.rules_version, s.dictionary_version, s.schema_version, s.created_at, h.snapshot_id
                FROM snapshots s
                LEFT JOIN publication_heads h ON h.channel_key = 'citizen:current'
                WHERE s.snapshot_id = ? AND s.schema_version = 'citizen-snapshot-v1'
                  AND s.mode = 'current' AND s.case_id IS NULL AND EXISTS (
                    SELECT 1 FROM publication_audits a WHERE a.after_snapshot_id = s.snapshot_id
                    AND a.channel_key = 'citizen:current' AND a.action = 'publish')
                """, (row, i) -> new Published(new PublicationRepository.Snapshot(row.getString(1), row.getString(2), row.getString(3),
                        row.getString(4), row.getString(5), row.getString(6), row.getString(7), row.getString(8)),
                        row.getString(9), row.getTimestamp(10).toInstant(), row.getString(11)), id).stream().findFirst();
    }

    public List<String> replayHeads(String areaId, String dataKind) {
        return jdbc.query("""
                SELECT h.snapshot_id FROM publication_heads h JOIN snapshots s ON s.snapshot_id = h.snapshot_id
                WHERE h.channel_key LIKE 'replay:%' AND s.mode = 'replay' AND s.data_kind = ?
                  AND JSON_UNQUOTE(JSON_EXTRACT(s.canonical_json, '$.area_id')) = ? ORDER BY h.channel_key
                """, (row, i) -> row.getString(1), dataKind, areaId);
    }

    public List<Historic> history(String eventId, String channel, String selectedSnapshot) {
        return jdbc.query("""
                SELECT r.snapshot_id, r.revision_id, a.happened_at, a.action
                FROM snapshot_revisions r JOIN snapshots s ON s.snapshot_id = r.snapshot_id
                JOIN publication_audits a ON a.after_snapshot_id = r.snapshot_id
                JOIN snapshots chosen ON chosen.snapshot_id = ?
                WHERE r.event_id = ? AND a.channel_key = ?
                  AND s.mode = chosen.mode AND s.case_id <=> chosen.case_id AND s.data_kind = chosen.data_kind
                  AND JSON_EXTRACT(s.canonical_json, '$.area_id') = JSON_EXTRACT(chosen.canonical_json, '$.area_id')
                  AND (chosen.mode = 'current' OR (
                    JSON_EXTRACT(s.canonical_json, '$.anchor_date') = JSON_EXTRACT(chosen.canonical_json, '$.anchor_date')
                    AND JSON_EXTRACT(s.canonical_json, '$.reference_instant') = JSON_EXTRACT(chosen.canonical_json, '$.reference_instant')
                    AND JSON_EXTRACT(s.canonical_json, '$.knowledge_cutoff') = JSON_EXTRACT(chosen.canonical_json, '$.knowledge_cutoff')))
                  AND a.head_version <= (
                    SELECT MIN(p.head_version) FROM publication_audits p
                    WHERE p.channel_key = a.channel_key AND p.after_snapshot_id = chosen.snapshot_id AND p.action = 'publish')
                ORDER BY a.head_version, a.audit_id
                """, (row, i) -> new Historic(row.getString(1), row.getString(2), row.getTimestamp(3).toInstant(), row.getString(4)),
                selectedSnapshot, eventId, channel);
    }

    public CitizenHistory citizenHistory(String eventId, String selectedSnapshot, Long beforeVersion, int limit) {
        var head = jdbc.query("SELECT lock_version FROM publication_heads WHERE channel_key='citizen:current' AND snapshot_id=?",
                (row, i) -> row.getLong(1), selectedSnapshot).stream().findFirst();
        if (head.isEmpty()) return new CitizenHistory(-1, 0, -1, List.of());
        long end = beforeVersion == null ? head.get() : beforeVersion - 1;
        if (beforeVersion != null && beforeVersion <= 0 || end > head.get()) return new CitizenHistory(head.get(), 0, -1, List.of());
        long start = Math.max(0, end - limit + 1);
        var audits = jdbc.query("""
                SELECT a.after_snapshot_id, membership.revision_id, a.happened_at, a.action, a.head_version, a.before_snapshot_id
                FROM publication_audits a
                LEFT JOIN snapshot_revisions membership
                  ON membership.snapshot_id = a.after_snapshot_id AND membership.event_id = ?
                WHERE a.channel_key = 'citizen:current' AND a.head_version BETWEEN ? AND ?
                ORDER BY a.head_version, a.audit_id
                LIMIT ?
                """, (row, i) -> new CitizenHistoric(row.getString(1), row.getString(2), row.getTimestamp(3).toInstant(), row.getString(4), row.getLong(5), row.getString(6)),
                eventId, Math.max(0, start - 1), end, limit + 2);
        return new CitizenHistory(head.get(), start, end, audits);
    }
}
