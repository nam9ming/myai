package kr.ac.myai.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.handoff.HandoffReference;
import kr.ac.myai.backend.handoff.HumanHandoffArchiveReader;
import kr.ac.myai.backend.handoff.VerifiedHandoff;
import kr.ac.myai.backend.importing.HumanReviewChanges;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedBatch;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.ReviewedImportRepository;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.TransientDataAccessException;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

@Service
@Profile("!fixture")
public class HumanHandoffImportService {
    private static final int LIMIT = 8 * 1024 * 1024;
    private static final List<String> WORKFLOW = List.of("revision_id", "revision_no", "origin", "review_status",
            "publication_intent", "reviewer_id", "reviewed_at", "human_overrides");
    private final HumanHandoffArchiveReader archives;
    private final ReviewedImportReader reader;
    private final ReviewedImportRepository repository;
    private final ReviewedImportService importer;
    private final ObjectMapper mapper;

    public HumanHandoffImportService(HumanHandoffArchiveReader archives, ReviewedImportReader reader,
                                     ReviewedImportRepository repository, ReviewedImportService importer, ObjectMapper mapper) {
        this.archives = archives; this.reader = reader; this.repository = repository; this.importer = importer; this.mapper = mapper;
    }

    public ReviewedImportService.ImportResult importFile(Path file, Path sourceRoot, Path handoffRoot, String actor) {
        try {
            ExtractionImportService.validateActor(actor);
            byte[] bytes = read(file);
            JsonNode request = reader.parseJson(bytes);
            shape(request, "schema_version handoff_ref receipt_sha256 reason revisions");
            check(request.path("schema_version").asText().equals("human-handoff-import-v1"), "schema_version");
            String reason = text(request, "reason", LIMIT);
            var handoff = archives.read(text(request, "handoff_ref", 64), text(request, "receipt_sha256", 64), handoffRoot);
            var projection = handoff.projection();
            String run = projection.path("parent").path("run_id").asText();
            JsonNode mappings = request.path("revisions");
            check(mappings.isArray() && mappings.size() == projection.path("events").size(), "revisions");
            var byEvent = new HashMap<String, JsonNode>();
            var revisionIds = new HashSet<String>();
            for (var value : mappings) {
                shape(value, "event_id revision_id expected_revision_no");
                check(byEvent.putIfAbsent(uuid(value, "event_id"), value) == null && revisionIds.add(uuid(value, "revision_id")), "revisions");
                check(value.path("expected_revision_no").isIntegralNumber() && value.path("expected_revision_no").canConvertToLong()
                        && value.path("expected_revision_no").longValue() >= 0 && value.path("expected_revision_no").longValue() < Long.MAX_VALUE,
                        "revisions.expected_revision_no");
            }
            var envelope = mapper.createObjectNode().put("schema_version", "reviewed-import-v1");
            envelope.set("data_kind", projection.path("data_kind"));
            envelope.set("documents", projection.path("documents"));
            envelope.set("evidence", projection.path("evidence"));
            var selectedProofs = envelope.putArray("human_handoffs");
            selectedProofs.add(reference(handoff.reference()));
            var events = envelope.putArray("events");
            Instant at = Instant.now().truncatedTo(ChronoUnit.MICROS);
            var previous = new HashMap<String, JsonNode>();
            for (var projected : projection.path("events")) {
                String id = projected.path("event_id").asText();
                var mapping = byEvent.remove(id);
                check(mapping != null, "revisions.event_id");
                long expected = mapping.path("expected_revision_no").longValue();
                // 명시한 역사 revision을 읽어 재입력도 현재 포인터와 무관하게 준비한다.
                var before = repository.previousPayload(id, expected);
                guardReplacement(before, projected);
                previous.put(id, before);
                ObjectNode event = projected.deepCopy();
                event.remove("facts");
                event.put("expected_revision_no", expected);
                ObjectNode revision = projected.path("facts").deepCopy();
                revision.put("revision_id", mapping.path("revision_id").asText()).put("revision_no", expected + 1)
                        .put("origin", "ai_reviewed").put("review_status", "needs_review").put("publication_intent", "hidden")
                        .put("reviewer_id", actor).put("reviewed_at", at.toString()).putArray("human_overrides");
                event.set("revision", revision);
                events.add(event);
            }
            check(byEvent.isEmpty(), "revisions.event_id");
            var prepared = reader.prepareHandoff(envelope, sourceRoot, ReviewedImportReader.sha256(bytes), run);
            var completed = new ArrayList<ReviewedBatch.Event>();
            for (var event : prepared.events()) {
                ObjectNode payload = (ObjectNode) reader.parseJson(event.payloadJson().getBytes(StandardCharsets.UTF_8));
                JsonNode before = previous.get(event.id());
                var proofs = payload.putArray("human_handoffs");
                if (before != null) before.path("human_handoffs").forEach(value -> proofs.add(value.deepCopy()));
                JsonNode selected = reference(handoff.reference());
                boolean present = false;
                for (var value : proofs) present |= value.equals(selected);
                if (!present) proofs.add(selected);
                HumanReviewChanges.record(before, payload, actor, at, reason);
                String saved = payload.toString();
                byte[] savedBytes = saved.getBytes(StandardCharsets.UTF_8);
                check(savedBytes.length <= LIMIT, "events");
                completed.add(new ReviewedBatch.Event(event.id(), event.revisionId(), event.revisionNo(), event.expectedRevisionNo(), saved,
                        ReviewedImportReader.sha256(savedBytes), event.reviewStatus(), event.publicationIntent(), event.reviewerId(), event.reviewedAt(),
                        event.originatingRunIds(), event.sourceVersionIds(), event.suspectedDuplicateIds()));
            }
            var batch = new ReviewedBatch(prepared.schemaVersion(), prepared.inputSha256(), prepared.dataKind(), prepared.documents(), completed,
                    prepared.originatingRunId(), null, selectedProofs.toString());
            return importer.importBatch(batch, actor);
        } catch (DataIntegrityViolationException | TransientDataAccessException ex) {
            throw new ImportException("IMPORT_CONFLICT", "검토 자료가 변경되거나 저장 제약과 충돌했습니다.", null);
        } catch (DataAccessException ex) {
            throw new ImportException("IMPORT_DATABASE_UNAVAILABLE", "DB 연결과 상태를 확인해 주세요.", null);
        } catch (ExtractionException ex) {
            throw new ImportException("IMPORT_VALIDATION_ERROR", "인계 원본·실행 환경·담당자 설정을 검증할 수 없습니다.", "human_handoffs");
        } catch (IOException | IllegalArgumentException ex) {
            throw new ImportException("IMPORT_VALIDATION_ERROR", "인계 입력·원문·보관 경로를 읽고 검증할 수 없습니다.", "file");
        }
    }

    private void guardReplacement(JsonNode previous, JsonNode projected) {
        if (previous == null) return;
        var revision = previous.path("revision");
        if (revision.path("origin").asText().equals("ai_draft") && revision.path("review_status").asText().equals("draft")) {
            conflict(previous.path("event").path("area_id").equals(projected.path("area_id"))
                    && previous.path("event").path("split_group_id").equals(projected.path("split_group_id")));
            return;
        }
        conflict(revision.path("origin").asText().equals("ai_reviewed") && revision.path("review_status").asText().equals("needs_review")
                && revision.path("publication_intent").asText().equals("hidden"));
        ObjectNode facts = revision.deepCopy();
        facts.remove(WORKFLOW);
        boolean unmodified = false;
        for (var reference : HandoffReference.list(previous.path("human_handoffs"))) {
            var image = archives.read(reference);
            for (var event : image.projection().path("events")) {
                ObjectNode top = event.deepCopy(); top.remove("facts");
                if (top.equals(previous.path("event")) && event.path("facts").equals(facts)
                        && image.projection().path("evidence").equals(previous.path("evidence"))) unmodified = true;
            }
        }
        conflict(unmodified);
    }

    private ObjectNode reference(HandoffReference reference) {
        return mapper.createObjectNode().put("directory", reference.directory()).put("handoff_ref", reference.handoffRef())
                .put("receipt_sha256", reference.receiptSha256());
    }

    private byte[] read(Path file) throws IOException {
        check(Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS), "file");
        try (var stream = Files.newInputStream(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = stream.readNBytes(LIMIT + 1);
            check(bytes.length > 0 && bytes.length <= LIMIT, "file");
            return bytes;
        }
    }

    private void shape(JsonNode node, String fields) {
        var keys = new HashSet<String>(); node.fieldNames().forEachRemaining(keys::add);
        check(node.isObject() && keys.equals(Set.of(fields.split(" "))), "file");
    }

    private String text(JsonNode node, String field, int limit) {
        var value = node.path(field);
        check(value.isTextual() && value.textValue().length() <= limit
                && value.textValue().codePoints().anyMatch(c -> !Character.isWhitespace(c) && !Character.isSpaceChar(c) && c != 0x85), field);
        return value.textValue();
    }

    private String uuid(JsonNode node, String field) {
        String value = text(node, field, 36);
        check(value.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"), field);
        return value;
    }

    private void conflict(boolean condition) {
        if (!condition) throw new ImportException("IMPORT_CONFLICT", "기존 검토본·예상 revision과 충돌합니다. 보정한 사실은 명시적으로 검토해 주세요.", "events.expected_revision_no");
    }

    private void check(boolean condition, String field) {
        if (!condition) throw new ImportException("IMPORT_VALIDATION_ERROR", "인계 입력의 형식·사건 대응을 확인해 주세요.", field);
    }
}
