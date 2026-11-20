package kr.ac.myai.backend.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.SourceReviewRepository;
import kr.ac.myai.backend.source.SourceReviewCommandReader;
import kr.ac.myai.backend.source.SourceReviewException;
import kr.ac.myai.backend.source.SourceView;
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
import java.sql.SQLException;

@Service
@Profile("!fixture")
public class SourceReviewService {
    private final SourceReviewCommandReader commands;
    private final SourceReviewRepository repository;
    private final ReviewedImportReader json;
    private final ObjectMapper mapper;
    private final TransactionTemplate write;

    public SourceReviewService(SourceReviewCommandReader commands, SourceReviewRepository repository, ReviewedImportReader json,
                               ObjectMapper mapper, PlatformTransactionManager manager) {
        this.commands = commands; this.repository = repository; this.json = json; this.mapper = mapper;
        write = new TransactionTemplate(manager);
        write.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public record Result(String reviewId, String documentVersionId, long reviewNo, String recordSha256, boolean alreadyRecorded) { }

    public Result review(Path file, Path sourceRoot, String actor) {
        SourceReviewCommandReader.actor(actor);
        var request = commands.read(file);
        try {
            var prepared = repository.prepare(request);
            if (prepared.existing() != null) return write.execute(status -> repository.append(prepared.view(), request, actor));
            if (request.expectedReviewNo() != prepared.view().reviewNo()) throw conflict("expected_review_no");
            if (!request.expectedTextSha256().equals(prepared.view().original().textHash())) throw conflict("expected_text_sha256");
            if (request.check() != null && request.check().result().equals("verified")) verifySource(prepared.view(), sourceRoot);
            return write.execute(status -> repository.append(prepared.view(), request, actor));
        } catch (ImportException | IllegalArgumentException ex) {
            throw new SourceReviewException("SOURCE_REVIEW_VALIDATION_ERROR", "source_root");
        } catch (DataAccessException | TransactionException ex) {
            boolean database = false, retryable = false;
            for (Throwable cause = ex; cause != null; cause = cause.getCause()) {
                if (cause instanceof SQLException sql) {
                    boolean connection = sql.getSQLState() != null && sql.getSQLState().startsWith("08");
                    database |= connection || sql.getErrorCode() == 1044 || sql.getErrorCode() == 1045 || sql.getErrorCode() == 1049;
                    retryable |= connection;
                }
            }
            if (database) throw new SourceReviewException("SOURCE_REVIEW_DATABASE_UNAVAILABLE", null, retryable);
            if (ex instanceof DataIntegrityViolationException || ex instanceof TransientDataAccessException) throw conflict(null);
            throw new SourceReviewException("SOURCE_REVIEW_INTERNAL_ERROR", null);
        }
    }

    private void verifySource(SourceView view, Path root) {
        if (root == null) throw new SourceReviewException("SOURCE_REVIEW_VALIDATION_ERROR", "source_root");
        var metadata = json.parseJson(view.original().metadata().getBytes(StandardCharsets.UTF_8));
        var source = mapper.createObjectNode().put("schema_version", "source-import-v1").put("data_kind", metadata.path("data_kind").textValue());
        source.putArray("documents").add(metadata.path("document"));
        source.putArray("evidence"); source.putArray("events");
        json.validateStored(source, root);
    }

    private SourceReviewException conflict(String field) { return new SourceReviewException("SOURCE_REVIEW_CONFLICT", field); }
}
