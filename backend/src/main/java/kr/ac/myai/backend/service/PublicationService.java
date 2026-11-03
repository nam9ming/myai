package kr.ac.myai.backend.service;

import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.importing.ReviewedBatch;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.PublicationRepository;
import kr.ac.myai.backend.repository.ReviewedImportRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.TransientDataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.support.TransactionTemplate;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.*;

@Service
@Profile("!fixture")
public class PublicationService {
    private final PublicationRepository repository;
    private final ReviewedImportRepository reviews;
    private final PublicationContent content;
    private final ObjectMapper mapper;
    private final TransactionTemplate transaction;
    private final ExtractionImportService extractions;

    public PublicationService(PublicationRepository repository, ReviewedImportRepository reviews, PublicationContent content,
                              ObjectMapper mapper, PlatformTransactionManager manager, ExtractionImportService extractions) {
        this.repository = repository; this.reviews = reviews; this.content = content; this.mapper = mapper;
        this.extractions = extractions;
        this.transaction = new TransactionTemplate(manager);
        this.transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public record Result(String action, String eventId, String revisionId, String snapshotId, String checksum, Long headVersion, JsonNode preview) { }

    public Result execute(PublicationCommand command, Path sourceRoot, String actor) {
        content.check(actor != null && !actor.isBlank() && actor.length() <= 128 && actor.chars().noneMatch(Character::isISOControl), "actor");
        try {
            if (command instanceof PublicationCommand.Decision decision) return decide(decision, sourceRoot, actor);
            if (command instanceof PublicationCommand.Publish publish) return publish(publish, sourceRoot, actor);
            return rollback((PublicationCommand.Rollback) command, actor);
        } catch (ImportException ex) {
            if (ex.code().equals("IMPORT_CONFLICT")) throw new PublicationException("PUBLICATION_CONFLICT", "검토 revision이 변경되었습니다. 최신 상태를 확인해 주세요.", ex.field());
            throw new PublicationException("PUBLICATION_VALIDATION_ERROR", ex.getMessage(), ex.field());
        } catch (ExtractionException ex) {
            throw new PublicationException(ex.code().equals("EXTRACTION_CONFLICT") ? "PUBLICATION_CONFLICT" : "PUBLICATION_VALIDATION_ERROR",
                    "AI 원본 또는 등록 기록을 다시 검증할 수 없습니다. 기존 검토·공개 상태는 보존됩니다.", "originating_run_ids");
        } catch (DataIntegrityViolationException | TransientDataAccessException ex) {
            throw new PublicationException("PUBLICATION_CONFLICT", "동시 변경 또는 저장 제약과 충돌했습니다. 이전 공개본은 보존됩니다.", null);
        } catch (DataAccessException | TransactionException ex) {
            throw new PublicationException("PUBLICATION_DATABASE_UNAVAILABLE", "DB 작업을 완료하지 못했습니다. 연결과 DB 상태를 확인해 주세요.", null);
        }
    }

    private Result decide(PublicationCommand.Decision command, Path root, String actor) {
        var original = repository.current(command.eventId().toString());
        conflict(original.number() == command.expectedRevisionNo(), "expected_revision_no");
        JsonNode payload = content.payload(original);
        var knownEvidence = new HashSet<String>();
        payload.path("evidence").forEach(item -> knownEvidence.add(item.path("evidence_id").asText()));
        content.check(knownEvidence.containsAll(command.evidenceIds()), "evidence_ids");
        boolean approve = command.action().equals("approve");
        boolean rawDraft = payload.path("revision").path("origin").asText().equals("ai_draft");
        content.check(!approve || !rawDraft, "origin");
        content.check(!command.evidenceIds().isEmpty() || !approve && rawDraft, "evidence_ids");
        conflict(!original.status().equals(approve ? "approved" : "rejected"), "review_status");
        var documents = approve ? documents(payload) : List.<PublicationRepository.Document>of();
        ObjectNode updated = payload.deepCopy(); var revision = (ObjectNode) updated.path("revision");
        String id = UUID.randomUUID().toString(); Instant now = now();
        revision.put("revision_id", id).put("revision_no", original.number() + 1).put("review_status", approve ? "approved" : "rejected")
                .put("publication_intent", approve ? "public" : "hidden").put("reviewer_id", actor).put("reviewed_at", now.toString());
        ReviewedBatch.Event event;
        if (approve) event = content.validate(updated, documents, root);
        else {
            String json = updated.toString();
            event = new ReviewedBatch.Event(original.eventId(), id, original.number() + 1, original.number(), json,
                    ReviewedImportReader.sha256(json.getBytes(StandardCharsets.UTF_8)), "rejected", "hidden", actor, now,
                    strings(revision.path("originating_run_ids")), strings(revision.path("source_version_ids")), strings(updated.path("event").path("suspected_duplicate_ids")));
        }
        var evidence = mapper.createArrayNode();
        command.evidenceIds().forEach(evidence::add);
        var runReferences = extractions.verifyReferences(approve ? List.of(event) : List.of());
        return transaction.execute(status -> {
            extractions.checkReferences(runReferences);
            lockDocuments(documents);
            repository.lockRevision(original);
            reviews.appendDecision(event, payload.path("data_kind").asText(), actor, command.reason(), evidence.toString());
            return new Result(command.action(), original.eventId(), id, null, null, null, null);
        });
    }

    private Result publish(PublicationCommand.Publish command, Path root, String actor) {
        var revisions = command.revisionIds().stream().map(id -> repository.revision(id.toString())).sorted(Comparator.comparing(PublicationRepository.Revision::eventId)).toList();
        var documents = new TreeMap<String, PublicationRepository.Document>();
        var events = new ArrayList<ReviewedBatch.Event>();
        for (var revision : revisions) {
            conflict(revision.currentId().equals(revision.id()) && revision.status().equals("approved") && revision.intent().equals("public"), "revision_ids");
            var payload = content.payload(revision); var sources = documents(payload);
            // shortcut: 사건별 원문 재검증은 소규모 수동 배치용이며 대량 공개 시 공통 원문 검증을 합친다.
            events.add(content.validate(payload, sources, root));
            sources.forEach(source -> documents.put(source.versionId(), source));
        }
        var runReferences = extractions.verifyReferences(events);
        String id = UUID.randomUUID().toString(); Instant now = now();
        var snapshot = content.snapshot(command, revisions, documents, id, now);
        if (command.action().equals("preview")) return new Result("preview", null, null, id, snapshot.checksum(), null, content.parse(snapshot.canonical()));
        String channel = channel(command.mode(), command.caseId());
        return transaction.execute(status -> {
            extractions.checkReferences(runReferences);
            lockDocuments(new ArrayList<>(documents.values()));
            revisions.forEach(repository::lockRevision);
            command.points().stream().sorted(Comparator.comparing(p -> p.pointId().toString())).forEach(point -> repository.savePoint(point, command.dataKind()));
            repository.insertSnapshot(snapshot, revisions, now);
            var change = repository.switchHead(channel, id, command.expectedHeadVersion(), now);
            repository.audit(channel, "publish", id, change, command.reason(), actor, now);
            return new Result("publish", null, null, id, snapshot.checksum(), change.version(), null);
        });
    }

    private Result rollback(PublicationCommand.Rollback command, String actor) {
        String channel = channel(command.mode(), command.caseId());
        var snapshot = repository.snapshot(command.snapshotId().toString());
        content.verifySnapshot(snapshot, channel);
        content.check(repository.wasPublished(channel, snapshot.id()), "snapshot_id");
        Instant now = now();
        return transaction.execute(status -> {
            content.verifySnapshot(repository.snapshot(snapshot.id()), channel);
            var change = repository.switchHead(channel, snapshot.id(), command.expectedHeadVersion(), now);
            repository.audit(channel, "rollback", snapshot.id(), change, command.reason(), actor, now);
            return new Result("rollback", null, null, snapshot.id(), snapshot.checksum(), change.version(), null);
        });
    }

    private List<PublicationRepository.Document> documents(JsonNode payload) {
        return strings(payload.path("revision").path("source_version_ids")).stream().map(repository::document).sorted(Comparator.comparing(PublicationRepository.Document::versionId)).toList();
    }

    private void lockDocuments(List<PublicationRepository.Document> documents) { documents.forEach(repository::lockDocument); }
    private Instant now() { return Instant.now().truncatedTo(ChronoUnit.MICROS); }
    private String channel(String mode, UUID caseId) { return mode.equals("current") ? "current" : "replay:" + caseId; }
    private List<String> strings(JsonNode array) { List<String> values = new ArrayList<>(); array.forEach(value -> values.add(value.asText())); return values; }
    private void conflict(boolean condition, String field) {
        if (!condition) throw new PublicationException("PUBLICATION_CONFLICT", "예상 revision 또는 공개 상태와 충돌합니다. 최신 상태를 확인해 주세요.", field);
    }
}
