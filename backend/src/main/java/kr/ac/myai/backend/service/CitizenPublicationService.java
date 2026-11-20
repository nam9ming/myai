package kr.ac.myai.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.importing.ReviewedBatch;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.CitizenPublicationContent;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.repository.PublicSnapshotRepository;
import kr.ac.myai.backend.repository.PublicationRepository;
import kr.ac.myai.backend.repository.SourceReviewRepository;
import kr.ac.myai.backend.source.SourceView;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

import java.nio.file.Path;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.TreeMap;

@Service
@Profile("!fixture")
public class CitizenPublicationService {
    private final PublicationRepository repository;
    private final PublicSnapshotRepository published;
    private final PublicationContent content;
    private final CitizenPublicationContent citizenContent;
    private final SourceReviewRepository sourceReviews;
    private final ExtractionImportService extractions;
    private final TransactionTemplate transaction;
    private final TransactionTemplate previewTransaction;

    public CitizenPublicationService(PublicationRepository repository, PublicSnapshotRepository published,
                                     PublicationContent content, CitizenPublicationContent citizenContent,
                                     SourceReviewRepository sourceReviews, ExtractionImportService extractions,
                                     PlatformTransactionManager manager) {
        this.repository = repository; this.published = published; this.content = content; this.citizenContent = citizenContent;
        this.sourceReviews = sourceReviews; this.extractions = extractions;
        transaction = new TransactionTemplate(manager);
        transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        previewTransaction = new TransactionTemplate(manager);
        previewTransaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        previewTransaction.setReadOnly(true);
    }

    public PublicationService.Result execute(PublicationCommand command, Path root, String actor) {
        if (command instanceof PublicationCommand.CitizenPublish publish) return publish(publish, root, actor);
        if (command instanceof PublicationCommand.CitizenRollback rollback) return rollback(rollback, actor);
        throw new PublicationException("PUBLICATION_VALIDATION_ERROR", "시민 공개 명령을 확인해 주세요.", "schema_version");
    }

    private PublicationService.Result publish(PublicationCommand.CitizenPublish command, Path root, String actor) {
        var revisions = command.revisionIds().stream().map(id -> repository.revision(id.toString()))
                .sorted(Comparator.comparing(PublicationRepository.Revision::eventId)).toList();
        var documents = new TreeMap<String, SourceView>();
        var events = new ArrayList<ReviewedBatch.Event>();
        for (var revision : revisions) {
            conflict(revision.currentId().equals(revision.id()) && revision.status().equals("approved") && revision.intent().equals("public"), "revision_ids");
            var payload = content.payload(revision);
            content.check(ReviewedImportReader.schemaForPayload(payload).equals(ReviewedImportReader.CITIZEN_IMPORT_VERSION), "revision_ids");
            content.check(payload.path("data_kind").asText().equals(command.dataKind()), "data_kind");
            var sources = strings(payload.path("revision").path("source_version_ids")).stream().sorted()
                    .map(id -> documents.computeIfAbsent(id, key -> sourceReviews.view(repository.document(key)))).toList();
            // shortcut: 사건별 원문 재검증은 소규모 수동 배치용이며 대량 공개 시 공통 검증을 합친다.
            events.add(content.validate(payload, sources, root));
        }
        boolean preview = command.action().equals("preview");
        var references = preview ? extractions.verifyReadOnlyReferences(events) : extractions.verifyReferences(events);
        String id = java.util.UUID.randomUUID().toString(); Instant now = Instant.now().truncatedTo(ChronoUnit.MICROS);
        for (var event : events) content.check(event.reviewedAt() != null && !event.reviewedAt().isAfter(now), "reviewed_at");
        var snapshot = citizenContent.snapshot(command, revisions, documents, id, now);
        if (preview) return previewTransaction.execute(status -> {
            extractions.checkReferences(references);
            documents.values().forEach(sourceReviews::lockView);
            return new PublicationService.Result("preview", null, null, id, snapshot.checksum(), null, content.parse(snapshot.canonical()));
        });
        return transaction.execute(status -> {
            extractions.checkReferences(references);
            for (var document : documents.values()) {
                repository.lockDocument(document.original());
                sourceReviews.lockView(document);
            }
            revisions.forEach(repository::lockRevision);
            repository.insertSnapshot(snapshot, revisions, now, CitizenPublicationContent.SCHEMA_VERSION);
            var change = repository.switchHead(CitizenPublicationContent.CHANNEL, id, command.expectedHeadVersion(), now);
            repository.audit(CitizenPublicationContent.CHANNEL, "publish", id, change, command.reason(), actor, now);
            return new PublicationService.Result("publish", null, null, id, snapshot.checksum(), change.version(), null);
        });
    }

    private PublicationService.Result rollback(PublicationCommand.CitizenRollback command, String actor) {
        String id = command.snapshotId().toString();
        verifiedPublished(id);
        Instant now = Instant.now().truncatedTo(ChronoUnit.MICROS);
        return transaction.execute(status -> {
            var snapshot = verifiedPublished(id);
            var change = repository.switchHead(CitizenPublicationContent.CHANNEL, id, command.expectedHeadVersion(), now);
            repository.audit(CitizenPublicationContent.CHANNEL, "rollback", id, change, command.reason(), actor, now);
            return new PublicationService.Result("rollback", null, null, id, snapshot.checksum(), change.version(), null);
        });
    }

    private PublicationRepository.Snapshot verifiedPublished(String id) {
        var selected = published.citizenPublished(id).orElseThrow(() ->
                new PublicationException("PUBLICATION_NOT_FOUND", "실제 공개한 시민 snapshot을 찾을 수 없습니다.", "snapshot_id"));
        citizenContent.verifySnapshot(selected.snapshot(), selected.schemaVersion(), selected.createdAt());
        return selected.snapshot();
    }

    private List<String> strings(JsonNode array) {
        var values = new ArrayList<String>(); array.forEach(value -> values.add(value.asText())); return values;
    }

    private void conflict(boolean condition, String field) {
        if (!condition) throw new PublicationException("PUBLICATION_CONFLICT", "예상 revision 또는 시민 공개 상태와 충돌합니다. 최신 상태를 확인해 주세요.", field);
    }
}
