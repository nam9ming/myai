package kr.ac.myai.backend.repository;

import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

@Repository
@Profile("!fixture")
public class PublicSnapshotRepository {
    private final JdbcTemplate jdbc;

    public PublicSnapshotRepository(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public record Published(PublicationRepository.Snapshot snapshot, String schemaVersion, Instant createdAt, String currentId) { }
    public record Historic(String snapshotId, String revisionId, Instant publishedAt) { }

    public Optional<String> head(String channel) {
        return jdbc.query("SELECT snapshot_id FROM publication_heads WHERE channel_key = ?", (row, i) -> row.getString(1), channel).stream().findFirst();
    }

    public Optional<Published> published(String id) {
        return jdbc.query("""
                SELECT s.snapshot_id, s.mode, s.case_id, s.canonical_json, s.checksum, s.data_kind,
                       s.rules_version, s.dictionary_version, s.schema_version, s.created_at, h.snapshot_id
                FROM snapshots s
                LEFT JOIN publication_heads h ON h.channel_key = IF(s.mode = 'current', 'current', CONCAT('replay:', s.case_id))
                WHERE s.snapshot_id = ? AND EXISTS (
                    SELECT 1 FROM publication_audits a WHERE a.after_snapshot_id = s.snapshot_id
                    AND a.channel_key = IF(s.mode = 'current', 'current', CONCAT('replay:', s.case_id)) AND a.action = 'publish')
                """, (row, i) -> new Published(new PublicationRepository.Snapshot(row.getString(1), row.getString(2), row.getString(3),
                        row.getString(4), row.getString(5), row.getString(6), row.getString(7), row.getString(8)),
                        row.getString(9), row.getTimestamp(10).toInstant(), row.getString(11)), id).stream().findFirst();
    }

    public List<String> replayHeads() {
        return jdbc.query("SELECT snapshot_id FROM publication_heads WHERE channel_key LIKE 'replay:%' ORDER BY channel_key", (row, i) -> row.getString(1));
    }

    public List<Historic> history(String eventId, String channel, Instant cutoff) {
        return jdbc.query("""
                SELECT s.snapshot_id, r.revision_id, MIN(a.happened_at) AS published_at
                FROM snapshot_revisions r JOIN snapshots s ON s.snapshot_id = r.snapshot_id
                JOIN publication_audits a ON a.after_snapshot_id = s.snapshot_id
                WHERE r.event_id = ? AND a.channel_key = ? AND a.action = 'publish'
                  AND s.created_at <= ? AND a.happened_at <= ?
                GROUP BY s.snapshot_id, r.revision_id ORDER BY published_at, s.snapshot_id
                """, (row, i) -> new Historic(row.getString(1), row.getString(2), row.getTimestamp(3).toInstant()),
                eventId, channel, Timestamp.from(cutoff), Timestamp.from(cutoff));
    }
}
