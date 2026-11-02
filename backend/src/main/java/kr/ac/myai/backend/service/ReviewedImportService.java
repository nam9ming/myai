package kr.ac.myai.backend.service;

import kr.ac.myai.backend.importing.ReviewedBatch;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.repository.ReviewedImportRepository;
import kr.ac.myai.backend.extraction.ExtractionException;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DataAccessException;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.dao.TransientDataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.UUID;

@Service
@Profile("!fixture")
public class ReviewedImportService {
    private final ReviewedImportRepository repository;
    private final TransactionTemplate transaction;
    private final ExtractionImportService extractions;

    public ReviewedImportService(ReviewedImportRepository repository, PlatformTransactionManager manager, ExtractionImportService extractions) {
        this.repository = repository;
        this.extractions = extractions;
        this.transaction = new TransactionTemplate(manager);
        // 중복 경합의 복구 조회는 실패한 배치 트랜잭션 종료 후 수행한다.
        this.transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public record ImportResult(String importId, List<String> revisionIds, List<String> documentVersionIds, boolean alreadyImported) {
        public ImportResult {
            revisionIds = List.copyOf(revisionIds);
            documentVersionIds = List.copyOf(documentVersionIds);
        }
    }

    public ImportResult importBatch(ReviewedBatch batch, String actor) {
        if (actor == null || actor.isBlank() || actor.length() > 128 || actor.chars().anyMatch(Character::isISOControl)) {
            throw new ImportException("IMPORT_VALIDATION_ERROR", "import 담당자를 128자 이하로 지정해 주세요.", "actor");
        }
        try {
            var runReferences = extractions.verifyReferences(batch.events());
            try {
                return transaction.execute(status -> {
                    extractions.checkReferences(runReferences);
                    var existing = repository.findBatch(batch);
                    if (existing.isPresent()) return existing.get();
                    String importId = UUID.randomUUID().toString();
                    repository.beginBatch(importId, batch);
                    batch.documents().stream().sorted(Comparator.comparing(ReviewedBatch.Document::id).thenComparingLong(ReviewedBatch.Document::versionNo)).forEach(repository::saveDocument);
                    var eventIds = new HashSet<String>();
                    batch.events().forEach(event -> eventIds.add(event.id()));
                    for (var event : batch.events()) {
                        for (String duplicate : event.suspectedDuplicateIds()) {
                            if (!eventIds.contains(duplicate) && !repository.eventExists(duplicate)) throw reference("events.suspected_duplicate_ids");
                        }
                        repository.appendEvent(event, batch.dataKind(), actor);
                    }
                    var result = new ImportResult(importId, batch.events().stream().map(ReviewedBatch.Event::revisionId).toList(),
                            batch.documents().stream().map(ReviewedBatch.Document::versionId).toList(), false);
                    repository.completeBatch(result);
                    return result;
                });
            } catch (DuplicateKeyException ex) {
                return transaction.execute(status -> {
                    extractions.checkReferences(runReferences);
                    return repository.findBatch(batch).orElseThrow(this::conflict);
                });
            }
        } catch (ExtractionException ex) {
            if (ex.code().equals("EXTRACTION_CONFLICT")) throw conflict();
            throw reference("events.revision.originating_run_ids");
        } catch (DataIntegrityViolationException | TransientDataAccessException ex) {
            throw conflict();
        } catch (DataAccessException | TransactionException ex) {
            throw new ImportException("IMPORT_DATABASE_UNAVAILABLE", "DB 저장을 완료하지 못했습니다. 연결과 DB 상태를 확인해 주세요.", null);
        }
    }

    private ImportException conflict() {
        return new ImportException("IMPORT_CONFLICT", "동일 ID·버전의 변경 또는 동시 import와 충돌했습니다. 기존 자료는 보존됩니다.", null);
    }

    private ImportException reference(String field) {
        return new ImportException("IMPORT_VALIDATION_ERROR", "등록된 사건·원문 버전·검증된 AI 실행 참조가 필요합니다.", field);
    }
}
