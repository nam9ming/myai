package kr.ac.myai.backend.service;

import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.repository.ExtractionRunRepository;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.TransactionException;
import org.springframework.transaction.support.TransactionTemplate;

import java.nio.file.Path;

@Service
@Profile("!fixture")
public class ExtractionImportService {
    private final ExtractionArchiveReader archives;
    private final ExtractionRunRepository repository;
    private final TransactionTemplate transaction;

    public ExtractionImportService(ExtractionArchiveReader archives, ExtractionRunRepository repository, PlatformTransactionManager manager) {
        this.archives = archives; this.repository = repository; this.transaction = new TransactionTemplate(manager);
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
}
