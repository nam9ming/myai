package kr.ac.myai.backend.repository;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.service.SourceReviewService;
import kr.ac.myai.backend.source.SourceReviewCommandReader.Request;
import kr.ac.myai.backend.source.SourceReviewException;
import kr.ac.myai.backend.source.SourceReviewState;
import kr.ac.myai.backend.source.SourceReviewState.Stored;
import kr.ac.myai.backend.source.SourceView;
import org.springframework.context.annotation.Profile;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.nio.charset.StandardCharsets;
import java.sql.Timestamp;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

@Repository
@Profile("!fixture")
public class SourceReviewRepository {
    private static final String DOCUMENT = "SELECT document_id, document_version_id, version_no, text_sha256, metadata_json, private_content_ref FROM document_versions WHERE document_version_id = ?";
    private static final String RECORD = "SELECT review_id, document_version_id, review_no, input_sha256, record_json, record_sha256 FROM source_reviews ";
    private final JdbcTemplate jdbc;
    private final ReviewedImportReader json;
    private final SourceReviewState state;
    private final TransactionTemplate read;

    public SourceReviewRepository(JdbcTemplate jdbc, ReviewedImportReader json, SourceReviewState state, PlatformTransactionManager manager) {
        this.jdbc = jdbc; this.json = json; this.state = state;
        read = new TransactionTemplate(manager);
        read.setReadOnly(true);
        read.setIsolationLevel(TransactionDefinition.ISOLATION_REPEATABLE_READ);
        read.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public record Prepared(SourceView view, Stored existing) { }
    private record CheckRow(String id, String version, Instant at, String result, String lastSuccess, String note) { }

    public SourceView view(PublicationRepository.Document original) {
        return read.execute(status -> {
            var current = document(original.versionId(), "");
            sameDocument(original, current);
            return currentView(current, "");
        });
    }

    public Prepared prepare(Request request) {
        return read.execute(status -> {
            var current = currentView(document(request.documentVersionId(), ""), "");
            return new Prepared(current, existing(request, ""));
        });
    }

    public void lockView(SourceView expected) {
        require(TransactionSynchronizationManager.isActualTransactionActive(), null);
        var original = document(expected.original().versionId(), " FOR SHARE");
        sameDocument(expected.original(), original);
        var current = currentView(original, " FOR SHARE");
        require(current.reviewNo() == expected.reviewNo() && Objects.equals(current.reviewSha256(), expected.reviewSha256())
                && metadata(current.effectiveMetadata()).equals(metadata(expected.effectiveMetadata()))
                && current.checkRecordedAt().equals(expected.checkRecordedAt()), "source_reviews");
    }

    public SourceReviewService.Result append(SourceView expected, Request request, String actor) {
        require(TransactionSynchronizationManager.isActualTransactionActive(), null);
        var original = document(request.documentVersionId(), " FOR UPDATE");
        sameDocument(expected.original(), original);
        var records = records(original.versionId(), " FOR UPDATE");
        var current = checkedView(original, records, " FOR UPDATE");
        var existing = existing(request, " FOR UPDATE");
        if (existing != null) return result(existing, true);
        require(current.reviewNo() == request.expectedReviewNo(), "expected_review_no");
        require(original.textHash().equals(request.expectedTextSha256()), "expected_text_sha256");
        var next = state.append(current, request, actor, Instant.now().truncatedTo(ChronoUnit.MICROS));
        var appended = new ArrayList<>(records); appended.add(next);
        var after = state.view(original, appended);
        if (request.check() != null) {
            var checks = expectedChecks(after);
            var check = checks.get(request.reviewId());
            jdbc.update("INSERT INTO source_checks(check_id, document_version_id, checked_at, result, last_success_ref, note) VALUES (?, ?, ?, ?, ?, ?)",
                    check.id(), check.version(), Timestamp.from(check.at()), check.result(), check.lastSuccess(), check.note());
        }
        jdbc.update("INSERT INTO source_reviews(review_id, document_version_id, review_no, input_sha256, record_json, record_sha256) VALUES (?, ?, ?, ?, ?, ?)",
                next.reviewId(), next.documentVersionId(), next.reviewNo(), next.inputSha256(), next.recordJson(), next.recordSha256());
        return result(next, false);
    }

    private static SourceReviewService.Result result(Stored stored, boolean existing) {
        return new SourceReviewService.Result(stored.reviewId(), stored.documentVersionId(), stored.reviewNo(), stored.recordSha256(), existing);
    }

    private PublicationRepository.Document document(String version, String lock) {
        return jdbc.query(DOCUMENT + lock,
                (row, index) -> new PublicationRepository.Document(row.getString(1), row.getString(2), row.getLong(3), row.getString(4), row.getString(5), row.getString(6)), version)
                .stream().findFirst().orElseThrow(() -> new SourceReviewException("SOURCE_REVIEW_CONFLICT", "document_version_id"));
    }

    private List<Stored> records(String version, String lock) {
        return jdbc.query(RECORD + "WHERE document_version_id = ? ORDER BY review_no" + lock,
                (row, index) -> new Stored(row.getString(1), row.getString(2), row.getLong(3), row.getString(4), row.getString(5), row.getString(6)), version);
    }

    private Stored existing(Request request, String lock) {
        var existing = jdbc.query(RECORD + "WHERE review_id = ?" + lock,
                (row, index) -> new Stored(row.getString(1), row.getString(2), row.getLong(3), row.getString(4), row.getString(5), row.getString(6)), request.reviewId());
        if (existing.isEmpty()) return null;
        var stored = existing.getFirst();
        require(stored.documentVersionId().equals(request.documentVersionId()) && stored.inputSha256().equals(request.inputSha256())
                && metadata(stored.recordJson()).path("input_json").asText().equals(request.inputJson()), "review_id");
        return stored;
    }

    private SourceView currentView(PublicationRepository.Document original, String lock) {
        return checkedView(original, records(original.versionId(), lock), lock);
    }

    private SourceView checkedView(PublicationRepository.Document original, List<Stored> records, String lock) {
        var view = state.view(original, records);
        var expected = expectedChecks(view);
        var actual = jdbc.query("SELECT check_id, document_version_id, checked_at, result, last_success_ref, note FROM source_checks WHERE document_version_id = ? ORDER BY check_id" + lock,
                (row, index) -> new CheckRow(row.getString(1), row.getString(2), row.getTimestamp(3).toInstant(), row.getString(4), row.getString(5), row.getString(6)), original.versionId());
        require(actual.size() == expected.size() && actual.stream().allMatch(check -> check.equals(expected.get(check.id()))), "source_checks");
        return view;
    }

    private Map<String, CheckRow> expectedChecks(SourceView view) {
        var expected = new HashMap<String, CheckRow>();
        String lastSuccess = null;
        for (var check : metadata(view.effectiveMetadata()).path("document").path("checks")) {
            String id = check.path("check_id").textValue();
            var row = new CheckRow(id, view.original().versionId(), Instant.parse(check.path("checked_at").textValue()),
                    check.path("result").textValue(), lastSuccess, check.path("note").textValue());
            require(expected.put(id, row) == null, "source_checks");
            if (row.result().equals("verified")) lastSuccess = id;
        }
        return expected;
    }

    private JsonNode metadata(String value) {
        try { return json.parseJson(value.getBytes(StandardCharsets.UTF_8)); }
        catch (ImportException | IllegalArgumentException ex) { throw new SourceReviewException("SOURCE_REVIEW_CONFLICT", "documents"); }
    }

    private void sameDocument(PublicationRepository.Document expected, PublicationRepository.Document current) {
        try { require(state.documentSha(expected).equals(state.documentSha(current)), "documents"); }
        catch (SourceReviewException | IllegalArgumentException ex) { throw new SourceReviewException("SOURCE_REVIEW_CONFLICT", "documents"); }
    }

    private static void require(boolean condition, String field) {
        if (!condition) throw new SourceReviewException("SOURCE_REVIEW_CONFLICT", field);
    }
}
