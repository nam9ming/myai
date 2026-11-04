package kr.ac.myai.backend.service;

import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.handoff.HandoffReference;
import kr.ac.myai.backend.handoff.HumanHandoffArchiveReader;
import kr.ac.myai.backend.handoff.VerifiedHandoff;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.ExtractionRunRepository;
import kr.ac.myai.backend.importing.ReviewedBatch;
import kr.ac.myai.backend.repository.ExtractionRunRepository.Reference;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.support.TransactionTemplate;

import java.nio.file.Path;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
@Profile("!fixture")
public class ExtractionImportService {
    private final ExtractionArchiveReader archives;
    private final ExtractionRunRepository repository;
    private final TransactionTemplate transaction;
    private final HumanHandoffArchiveReader handoffs;
    private final ReviewedImportReader json;

    public ExtractionImportService(ExtractionArchiveReader archives, ExtractionRunRepository repository, PlatformTransactionManager manager,
                                   HumanHandoffArchiveReader handoffs, ReviewedImportReader json) {
        this.archives = archives; this.repository = repository; this.transaction = new TransactionTemplate(manager);
        this.handoffs = handoffs; this.json = json;
        transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public record Result(String runId, String documentVersionId, String status, int attempts, String dataKind,
                         String metadataSha256, String receiptSha256, boolean alreadyRegistered, boolean reviewRequired) { }

    public Result importRun(String runId, Path root, String actor) {
        validateActor(actor);
        var run = archives.read(runId, root);
        try {
            try {
                return transaction.execute(status -> {
                    repository.checkDocument(run);
                    var existing = repository.existing(run);
                    if (existing.isPresent()) return existing.get();
                    repository.insert(run, actor);
                    return repository.result(run, false);
                });
            } catch (DuplicateKeyException ex) {
                // 실패 트랜잭션의 RR snapshot을 재사용하지 않고 승자 행을 새로 조회한다.
                return transaction.execute(status -> {
                    repository.checkDocument(run);
                    return repository.existing(run).orElseThrow(() -> new ExtractionException("EXTRACTION_CONFLICT", null, false));
                });
            }
        } catch (DataIntegrityViolationException ex) {
            throw new ExtractionException("EXTRACTION_CONFLICT", null, false);
        } catch (DataAccessResourceFailureException | TransientDataAccessException | TransactionException ex) {
            throw new ExtractionException("EXTRACTION_DATABASE_UNAVAILABLE", null, true);
        } catch (DataAccessException ex) {
            throw new ExtractionException("EXTRACTION_INTERNAL_ERROR", null, false);
        }
    }

    public static void validateActor(String actor) {
        if (actor == null || actor.isBlank() || actor.length() > 128 || actor.chars().anyMatch(Character::isISOControl)) {
            throw new ExtractionException("EXTRACTION_VALIDATION_ERROR", "actor", false);
        }
    }

    public List<Reference> verifyReferences(List<ReviewedBatch.Event> events) {
        return verifyReferences(events, null, List.of());
    }

    public List<Reference> verifyReadOnlyReferences(List<ReviewedBatch.Event> events) {
        return verifyReferences(events, null, List.of(), List.of(), true);
    }

    public List<Reference> verifyReferences(List<ReviewedBatch.Event> events, String batchRun, List<String> batchDocuments) {
        return verifyReferences(events, batchRun, batchDocuments, List.of());
    }

    public List<Reference> verifyReferences(ReviewedBatch batch) {
        var references = batch.handoffJson() == null ? List.<HandoffReference>of()
                : HandoffReference.list(json.parseJson(batch.handoffJson().getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        return verifyReferences(batch.events(), batch.originatingRunId(), batch.documents().stream().map(ReviewedBatch.Document::versionId).toList(), references);
    }

    private List<Reference> verifyReferences(List<ReviewedBatch.Event> events, String batchRun, List<String> batchDocuments,
                                            List<HandoffReference> batchHandoffs) {
        return verifyReferences(events, batchRun, batchDocuments, batchHandoffs, false);
    }

    private List<Reference> verifyReferences(List<ReviewedBatch.Event> events, String batchRun, List<String> batchDocuments,
                                            List<HandoffReference> batchHandoffs, boolean readOnly) {
        var verified = new LinkedHashMap<String, Reference>();
        var images = new LinkedHashMap<HandoffReference, VerifiedHandoff>();
        for (var event : events) {
            var payload = json.parseJson(event.payloadJson().getBytes(java.nio.charset.StandardCharsets.UTF_8));
            var proofs = new LinkedHashMap<String, VerifiedHandoff>();
            for (var reference : HandoffReference.list(payload.path("human_handoffs"))) {
                var image = images.computeIfAbsent(reference, handoffs::read);
                String run = image.projection().path("parent").path("run_id").asText();
                boolean hasEvent = false;
                for (var projected : image.projection().path("events")) hasEvent |= projected.path("event_id").asText().equals(event.id());
                if (!hasEvent || !event.originatingRunIds().contains(run)
                        || !event.sourceVersionIds().contains(image.projection().path("documents").get(0).path("document_version_id").asText())) {
                    throw new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false);
                }
                proofs.put(run, image);
                verifyReference(run, event.sourceVersionIds(), verified, image, readOnly);
            }
            for (String id : event.originatingRunIds()) {
                // 사건별 증거를 먼저 검사하며 다른 사건의 run 캐시로 failed를 허용하지 않는다.
                if (!proofs.containsKey(id)) verifyReference(id, event.sourceVersionIds(), verified, null, readOnly);
            }
        }
        for (var reference : batchHandoffs) {
            var image = images.computeIfAbsent(reference, handoffs::read);
            String run = image.projection().path("parent").path("run_id").asText();
            if (batchRun != null && !batchRun.equals(run)) throw new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false);
            verifyReference(run, batchDocuments, verified, image, readOnly);
        }
        if (batchRun != null && batchHandoffs.isEmpty()) verifyReference(batchRun, batchDocuments, verified, null, readOnly);
        return verified.values().stream().sorted(Comparator.comparing(Reference::runId)).toList();
    }

    private void verifyReference(String id, List<String> documents, Map<String, Reference> verified, VerifiedHandoff handoff,
                                 boolean readOnly) {
        var reference = verified.get(id);
        Path directory;
        try { directory = Path.of(handoff == null ? repository.referenceDirectory(id) : repository.handoffParentDirectory(id, handoff)); }
            catch (IllegalArgumentException ex) { throw new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false); }
            if (!directory.isAbsolute() || directory.getFileName() == null || !directory.getFileName().toString().equals(id)) {
                throw new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false);
            }
        if (reference == null || handoff != null) {
            var run = readOnly ? archives.readSealed(id, directory.getParent()) : archives.read(id, directory.getParent());
            repository.checkDocument(run);
            reference = handoff == null ? repository.verifiedReference(run) : repository.verifiedHandoffParent(run, handoff);
            verified.put(id, reference);
        }
        if (!documents.contains(reference.documentVersionId())) {
            throw new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false);
        }
    }

    public void checkReferences(List<Reference> references) { references.forEach(repository::checkReference); }

    public void verifyDraft(ReviewedBatch batch) {
        if (!batch.schemaVersion().equals("ai-draft-import-v1")) return;
        try {
            Path directory = Path.of(repository.referenceDirectory(batch.originatingRunId()));
            archives.checkDraft(batch.originatingRunId(), directory.getParent(), batch.draftJson());
        } catch (IllegalArgumentException ex) {
            throw new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false);
        }
    }
}
