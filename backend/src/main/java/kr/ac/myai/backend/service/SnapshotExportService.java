package kr.ac.myai.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.repository.PublicSnapshotRepository;
import kr.ac.myai.backend.repository.PublicationRepository;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.RecoverableDataAccessException;
import org.springframework.dao.TransientDataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.CannotCreateTransactionException;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.DateTimeException;
import java.time.Instant;
import java.util.*;

@Service
@Profile("!fixture")
public class SnapshotExportService {
    private static final int LIMIT = 8 * 1024 * 1024;
    private static final String FIELD_VALUE = "value knowledge evidence_ids reason";
    // 공개 producer에 내부 필드가 추가되어도 파일로 조용히 내보내지 않는다.
    private static final Map<String, String> FIELDS = Map.ofEntries(
            Map.entry("", "schema_version snapshot_id created_at data_kind mode rules_version dictionary_version area_id timezone window_days radius_m area case_id anchor_date reference_instant knowledge_cutoff history_fidelity point_ids points revision_ids event_public_payloads sources document_count event_count collection_range last_check_min last_check_max"),
            Map.entry("area", "area_id name description"), Map.entry("collection_range", "from to"),
            Map.entry("points[]", "point_id area_id label longitude latitude version dictionary_version verification_status active is_test_reference"),
            Map.entry("event_public_payloads[]", "event_id revision_id title types applicability exceptions route_names stop_names directions lifecycle lifecycle_evidence_ids source_version_ids area_membership document_links relations occurrences locations evidence"),
            Map.entry("event_public_payloads[].applicability", FIELD_VALUE), Map.entry("event_public_payloads[].exceptions", FIELD_VALUE),
            Map.entry("event_public_payloads[].route_names", FIELD_VALUE), Map.entry("event_public_payloads[].stop_names", FIELD_VALUE),
            Map.entry("event_public_payloads[].directions", FIELD_VALUE),
            Map.entry("event_public_payloads[].document_links[]", "document_id role evidence_ids"),
            Map.entry("event_public_payloads[].relations[]", "from_document_id to_document_id type reason created_at"),
            Map.entry("event_public_payloads[].occurrences[]", "occurrence_id date_start date_end time_start time_end end_day_offset precision recurrence_dates location_ids evidence_ids knowledge"),
            Map.entry("event_public_payloads[].locations[]", "location_id name address kind status geometry coverage evidence_ids"),
            Map.entry("event_public_payloads[].locations[].name", FIELD_VALUE), Map.entry("event_public_payloads[].locations[].address", FIELD_VALUE),
            Map.entry("event_public_payloads[].locations[].geometry", "type coordinates"),
            Map.entry("event_public_payloads[].evidence[]", "evidence_id document_version_id block_id quote start_char end_char text_sha256"),
            Map.entry("sources[]", "document_id document_version_id publisher official_url title official_number published_date collected_at text_sha256 current_last_verified_at current_latest_check_attempt_at current_check_result checks last_verified_at latest_check_attempt_at check_result"),
            Map.entry("sources[].checks[]", "checked_at result text_sha256"));

    private final PublicSnapshotRepository repository;
    private final PublicationContent content;
    private final TransactionTemplate reads;

    public SnapshotExportService(PublicSnapshotRepository repository, PublicationContent content, PlatformTransactionManager transactions) {
        this.repository = repository; this.content = content; reads = new TransactionTemplate(transactions);
        reads.setReadOnly(true); reads.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        reads.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public record Result(String snapshotId, String checksum, String fileName, boolean alreadyExported) {}

    public Result export(UUID snapshotId, Path directory) {
        PublicationRepository.Snapshot row;
        try { row = reads.execute(status -> read(snapshotId.toString())); }
        catch (DataAccessResourceFailureException | RecoverableDataAccessException | TransientDataAccessException | CannotCreateTransactionException ex) {
            throw error("EXPORT_DATABASE_UNAVAILABLE", "공개 snapshot 저장소에 연결할 수 없습니다.");
        }
        String name = row.id() + "-" + row.checksum() + ".json";
        try {
            Path root = directory.toRealPath();
            if (!Files.isDirectory(root)) throw new IOException();
            boolean existing = write(root.resolve(name), row.canonical().getBytes(StandardCharsets.UTF_8), row.checksum());
            return new Result(row.id(), row.checksum(), name, existing);
        } catch (IOException | UnsupportedOperationException | SecurityException ex) {
            throw error("EXPORT_IO_ERROR", "파일을 저장하지 못했습니다. DB 공개본은 유지됩니다. 출력 디렉터리를 확인한 뒤 같은 ID로 재시도해 주세요.");
        }
    }

    private PublicationRepository.Snapshot read(String id) {
        var published = repository.published(id).orElseThrow(() -> error("EXPORT_NOT_FOUND", "이미 공개한 snapshot ID를 지정해 주세요."));
        var row = published.snapshot();
        try {
            content.check(row.id().equals(id), "snapshot_id");
            content.verifySnapshot(row, row.mode().equals("current") ? "current" : "replay:" + row.caseId());
            JsonNode snapshot = content.parse(row.canonical());
            content.check(published.schemaVersion().equals("snapshot-v1") && Instant.parse(snapshot.path("created_at").asText()).equals(published.createdAt()), "snapshot");
            publicFields(snapshot, "");
            content.check(snapshot.path("points").size() == 5 && snapshot.path("event_count").asInt(-1) == snapshot.path("event_public_payloads").size(), "snapshot");
            return row;
        } catch (PublicationException | ImportException | DateTimeException ex) {
            throw error("EXPORT_INVALID_SNAPSHOT", "공개 snapshot의 무결성·공개 필드 범위를 확인할 수 없습니다.");
        }
    }

    private void publicFields(JsonNode node, String path) {
        if (node.isNull() && path.equals("event_public_payloads[].locations[].geometry")) return;
        String fields = FIELDS.get(path);
        if (fields != null) {
            var actual = new HashSet<String>(); node.fieldNames().forEachRemaining(actual::add);
            content.check(node.isObject() && actual.equals(Set.of(fields.split(" "))), "snapshot");
            node.fieldNames().forEachRemaining(field -> publicFields(node.get(field), path.isEmpty() ? field : path + "." + field));
        } else if (node.isArray() || FIELDS.containsKey(path + "[]")) {
            content.check(node.isArray(), "snapshot");
            node.forEach(value -> publicFields(value, path + "[]"));
        } else content.check(!node.isObject(), "snapshot");
    }

    private boolean write(Path target, byte[] bytes, String checksum) throws IOException {
        if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) return existing(target, checksum);
        Path temporary = Files.createTempFile(target.getParent(), ".snapshot-", ".tmp");
        try {
            Files.write(temporary, bytes, StandardOpenOption.WRITE);
            try { Files.createLink(target, temporary); return false; }
            catch (FileAlreadyExistsException ex) { return existing(target, checksum); }
        } finally { Files.deleteIfExists(temporary); }
    }

    private boolean existing(Path target, String checksum) throws IOException {
        if (Files.isRegularFile(target, LinkOption.NOFOLLOW_LINKS)) {
            try (var input = Files.newInputStream(target, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                byte[] bytes = input.readNBytes(LIMIT + 1);
                if (bytes.length <= LIMIT && ReviewedImportReader.sha256(bytes).equals(checksum)) return true;
            }
        }
        throw error("EXPORT_FILE_CONFLICT", "출력 이름에 다른 파일이나 링크가 있습니다. 기존 항목을 보존했습니다. 출력 디렉터리를 확인해 주세요.");
    }

    private PublicationException error(String code, String message) { return new PublicationException(code, message, null); }
}
