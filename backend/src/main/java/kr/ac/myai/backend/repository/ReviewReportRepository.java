package kr.ac.myai.backend.repository;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationException;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

import java.nio.charset.StandardCharsets;
import java.sql.ResultSet;
import java.time.Instant;
import java.util.*;

/** 보고서에 필요한 저장 원문을 한 읽기 snapshot에서 수집한다. */
@Repository
@Profile("!fixture")
public class ReviewReportRepository {
    private static final long LIMIT = 64L * 1024 * 1024;
    private final JdbcTemplate jdbc;
    private final ObjectMapper mapper;
    private final ReviewedImportReader json;
    private final TransactionTemplate reads;

    public ReviewReportRepository(JdbcTemplate jdbc, ObjectMapper mapper, ReviewedImportReader json, PlatformTransactionManager manager) {
        this.jdbc = jdbc; this.mapper = mapper; this.json = json;
        reads = new TransactionTemplate(manager);
        reads.setReadOnly(true);
        reads.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        reads.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public ObjectNode capture(UUID versionId) {
        if (versionId == null) throw error("REPORT_VALIDATION_ERROR", "document_version_id");
        return reads.execute(status -> {
            long[] bytes = {0};
            var chosen = rows("SELECT * FROM document_versions WHERE document_version_id=?", bytes, versionId.toString());
            if (chosen.isEmpty()) throw error("REPORT_NOT_FOUND", "document_version_id");
            var revisions = rows("""
                    SELECT r.*, e.current_review_revision_id, e.lock_version FROM event_revisions r
                    JOIN events e ON e.event_id=r.event_id WHERE EXISTS (
                      SELECT 1 FROM event_revisions linked WHERE linked.event_id=r.event_id
                      AND JSON_CONTAINS(linked.payload_json, JSON_QUOTE(?), '$.revision.source_version_ids')=1)
                    ORDER BY r.event_id,r.revision_no
                    """, bytes, versionId.toString());
            var events = new TreeSet<String>(); var versions = new TreeSet<String>(); versions.add(versionId.toString());
            for (var row : revisions) {
                events.add(row.path("event_id").asText());
                try {
                    JsonNode payload = json.parseJson(row.path("payload_json").asText().getBytes(StandardCharsets.UTF_8));
                    var refs = payload.path("revision").path("source_version_ids");
                    if (refs.isArray()) for (var ref : refs) if (ref.isTextual() && ref.asText().matches("[0-9a-f-]{36}")) versions.add(ref.asText());
                } catch (RuntimeException ignored) { /* 손상된 payload도 원래 행으로 남긴다. */ }
            }
            if (versions.size() > 1000) throw error("REPORT_TOO_LARGE", "documents");
            var documents = rows("SELECT * FROM document_versions WHERE document_version_id IN (" + marks(versions) + ") ORDER BY document_version_id", bytes, versions.toArray());
            var checks = rows("SELECT * FROM source_checks WHERE document_version_id IN (" + marks(versions) + ") ORDER BY document_version_id,checked_at,check_id", bytes, versions.toArray());
            var sourceReviews = rows("SELECT * FROM source_reviews WHERE document_version_id IN (" + marks(versions) + ") ORDER BY document_version_id,review_no", bytes, versions.toArray());
            var runs = rows("SELECT * FROM extraction_runs WHERE document_version_id IN (" + marks(versions) + ") ORDER BY document_version_id,run_id", bytes, versions.toArray());
            var imports = rows("""
                    SELECT b.*, d.document_version_id AS report_document_version_id
                    FROM document_versions d JOIN import_batches b ON (
                      JSON_CONTAINS(b.result_refs_json, JSON_QUOTE(d.document_version_id), '$.document_version_ids')=1
                      OR EXISTS (SELECT 1 FROM extraction_runs x WHERE x.document_version_id=d.document_version_id
                        AND x.run_id=JSON_UNQUOTE(JSON_EXTRACT(b.result_refs_json, '$.originating_run_id'))))
                    WHERE b.source_kind='human_handoff' AND d.document_version_id IN (
                    """ + marks(versions) + ") ORDER BY d.document_version_id,b.import_id", bytes, versions.toArray());
            ArrayNode audits = mapper.createArrayNode(), snapshots = mapper.createArrayNode(), memberships = mapper.createArrayNode(), publication = mapper.createArrayNode(), heads = mapper.createArrayNode();
            if (!events.isEmpty()) {
                audits = rows("SELECT * FROM review_audits WHERE event_id IN (" + marks(events) + ") ORDER BY happened_at,audit_id", bytes, events.toArray());
                String relevant = "SELECT sr.snapshot_id FROM snapshot_revisions sr WHERE sr.event_id IN (" + marks(events) + ")";
                publication = rows("SELECT * FROM publication_audits WHERE before_snapshot_id IN (" + relevant + ") OR after_snapshot_id IN (" + relevant + ") ORDER BY channel_key,head_version,audit_id", bytes, doubled(events));
                var snapshotIds = new TreeSet<String>(); var channels = new TreeSet<String>();
                for (var audit : publication) for (String key : List.of("before_snapshot_id", "after_snapshot_id")) if (!audit.path(key).isNull()) snapshotIds.add(audit.path(key).asText());
                publication.forEach(audit -> channels.add(audit.path("channel_key").asText()));
                if (!channels.isEmpty()) {
                    heads = rows("SELECT * FROM publication_heads WHERE channel_key IN (" + marks(channels) + ") ORDER BY channel_key", bytes, channels.toArray());
                    heads.forEach(head -> snapshotIds.add(head.path("snapshot_id").asText()));
                }
                if (!snapshotIds.isEmpty()) {
                    snapshots = rows("SELECT * FROM snapshots WHERE snapshot_id IN (" + marks(snapshotIds) + ") ORDER BY snapshot_id", bytes, snapshotIds.toArray());
                    memberships = rows("SELECT * FROM snapshot_revisions WHERE snapshot_id IN (" + marks(snapshotIds) + ") ORDER BY snapshot_id,event_id", bytes, snapshotIds.toArray());
                }
            }
            var result = mapper.createObjectNode();
            result.putObject("capture").put("captured_at", Instant.now().toString()).put("isolation", "REPEATABLE_READ")
                    .put("read_only", true).put("validation_same_snapshot", false)
                    .put("validation_scope", "파일·운영 상태·preview는 capture 이후 별도 시점의 읽기 전용 검사입니다.");
            result.set("documents", documents); result.set("source_checks", checks); result.set("source_reviews", sourceReviews);
            result.set("extractions", runs); result.set("imports", imports); result.set("revisions", revisions); result.set("review_audits", audits);
            var published = result.putObject("publication"); published.set("audits", publication); published.set("snapshots", snapshots);
            published.set("memberships", memberships); published.set("heads", heads);
            return result;
        });
    }

    public ObjectNode previewBaseline(String channel) {
        if (channel == null || !channel.matches("current|replay:[0-9a-f-]{36}")) throw error("REPORT_PREVIEW_INVALID", "channel");
        return reads.execute(status -> {
            long[] bytes = {0};
            var result = mapper.createObjectNode().put("isolation", "REPEATABLE_READ").put("read_only", true)
                    .put("same_snapshot_as_capture", false);
            var heads = rows("SELECT * FROM publication_heads WHERE channel_key=?", bytes, channel);
            if (heads.isEmpty()) result.put("status", "none").putNull("head").putNull("snapshot");
            else {
                var head = heads.get(0); result.set("head", head);
                var snapshots = rows("""
                        SELECT s.* FROM snapshots s WHERE s.snapshot_id=? AND EXISTS (
                          SELECT 1 FROM publication_audits a WHERE a.after_snapshot_id=s.snapshot_id
                          AND a.action='publish' AND a.channel_key=?)
                        """, bytes, head.path("snapshot_id").asText(), channel);
                if (snapshots.isEmpty()) throw error("REPORT_BASELINE_INVALID", "snapshot_id");
                result.put("status", "present"); result.set("snapshot", snapshots.get(0));
            }
            result.put("read_at", Instant.now().toString()); return result;
        });
    }

    private ArrayNode rows(String sql, long[] bytes, Object... arguments) {
        return jdbc.query(connection -> {
            var statement = connection.prepareStatement(sql + " LIMIT 1001", ResultSet.TYPE_FORWARD_ONLY, ResultSet.CONCUR_READ_ONLY);
            // Connector/J의 전체 결과 선적재를 피하고 누적 예산을 읽는 도중 적용한다.
            statement.setFetchSize(Integer.MIN_VALUE);
            for (int index = 0; index < arguments.length; index++) statement.setObject(index + 1, arguments[index]);
            return statement;
        }, result -> {
            var rows = mapper.createArrayNode(); var metadata = result.getMetaData();
            while (result.next()) {
                if (rows.size() == 1000) throw error("REPORT_TOO_LARGE", "rows");
                var row = rows.addObject();
                for (int column = 1; column <= metadata.getColumnCount(); column++) {
                    String name = metadata.getColumnLabel(column); Object value = result.getObject(column);
                    if (value == null) row.putNull(name);
                    else if (value instanceof Number number) row.set(name, mapper.valueToTree(number));
                    else row.put(name, result.getString(column));
                }
                bytes[0] += row.toString().getBytes(StandardCharsets.UTF_8).length;
                if (bytes[0] > LIMIT) throw error("REPORT_TOO_LARGE", "database");
            }
            return rows;
        });
    }

    private static String marks(Collection<?> values) { return String.join(",", Collections.nCopies(values.size(), "?")); }
    private static Object[] doubled(Collection<?> values) { var result = new ArrayList<Object>(values); result.addAll(values); return result.toArray(); }
    private static PublicationException error(String code, String field) { return new PublicationException(code, "검토 보고서의 문서·행 수·크기 범위를 확인해 주세요.", field); }
}
