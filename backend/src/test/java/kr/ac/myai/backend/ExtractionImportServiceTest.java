package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.extraction.VerifiedExtraction;
import kr.ac.myai.backend.handoff.HumanHandoffArchiveReader;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.ExtractionRunRepository;
import kr.ac.myai.backend.service.ExtractionImportService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.NullAndEmptySource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

import java.nio.file.Path;
import java.util.Optional;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class ExtractionImportServiceTest {
    @TempDir Path root;
    final String runId = "71fb66f0-e610-4f9c-8f26-4bb77655ee8c";
    final String inputHash = "a".repeat(64);
    final ExtractionArchiveReader archives = mock(ExtractionArchiveReader.class);
    final ExtractionRunRepository repository = mock(ExtractionRunRepository.class);
    final PlatformTransactionManager manager = mock(PlatformTransactionManager.class);
    final ExtractionImportService service = new ExtractionImportService(archives, repository, manager,
            mock(HumanHandoffArchiveReader.class), new ReviewedImportReader());

    @Test
    void mismatchingExpectedInputHashCannotStartDatabaseWork() {
        when(archives.read(runId, root)).thenReturn(verified());
        assertThatThrownBy(() -> service.importRun(runId, root, "synthetic-actor", "b".repeat(64)))
                .isInstanceOfSatisfying(ExtractionException.class, error -> {
                    assertThat(error.code()).isEqualTo("EXTRACTION_VALIDATION_ERROR");
                    assertThat(error.field()).isEqualTo("expected_input_hash");
                    assertThat(error.retryable()).isFalse();
                });
        verifyNoInteractions(repository, manager);
    }

    @ParameterizedTest
    @NullAndEmptySource
    @ValueSource(strings = {"short", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "gggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggggg"})
    void malformedExpectedHashIsRejectedBeforeArchiveOrDatabase(String hash) {
        assertThatThrownBy(() -> service.importRun(runId, root, "synthetic-actor", hash))
                .isInstanceOfSatisfying(ExtractionException.class,
                        error -> assertThat(error.field()).isEqualTo("expected_input_hash"));
        verifyNoInteractions(archives, repository, manager);
    }

    @Test
    void matchingExpectedHashCommitsTheVerifiedRun() {
        var run = verified();
        var status = new SimpleTransactionStatus();
        var result = new ExtractionImportService.Result(runId, run.documentVersionId(), "failed", 1,
                "synthetic", "c".repeat(64), "d".repeat(64), false, true);
        when(archives.read(runId, root)).thenReturn(run);
        when(manager.getTransaction(any())).thenReturn(status);
        when(repository.existing(run)).thenReturn(Optional.empty());
        when(repository.result(run, false)).thenReturn(result);

        assertThat(service.importRun(runId, root, "synthetic-actor", inputHash)).isEqualTo(result);
        var order = inOrder(repository, manager);
        order.verify(repository).checkDocument(run);
        order.verify(repository).insert(run, "synthetic-actor");
        order.verify(manager).commit(status);
    }

    @Test
    void legacyThreeArgumentImportKeepsItsOriginalArchiveAndTransactionFlow() {
        var run = verified();
        var status = new SimpleTransactionStatus();
        var result = new ExtractionImportService.Result(runId, run.documentVersionId(), "failed", 1,
                "synthetic", "c".repeat(64), "d".repeat(64), true, true);
        when(archives.read(runId, root)).thenReturn(run);
        when(manager.getTransaction(any())).thenReturn(status);
        when(repository.existing(run)).thenReturn(Optional.of(result));

        assertThat(service.importRun(runId, root, "synthetic-actor")).isEqualTo(result);
        verify(repository, never()).insert(any(), any());
        verify(manager).commit(status);
    }

    private VerifiedExtraction verified() {
        var mapper = new ObjectMapper();
        var receipt = mapper.createObjectNode().put("run_id", runId)
                .put("document_version_id", "20000000-0000-4000-8000-000000000002")
                .put("status", "failed").put("data_kind", "synthetic").put("input_sha256", inputHash)
                .put("metadata_sha256", "c".repeat(64));
        receipt.putArray("attempts").addObject().put("attempt_no", 1).put("error_code", "JSON_INVALID");
        return new VerifiedExtraction(root.resolve(runId), mapper.createObjectNode(), mapper.createObjectNode(),
                receipt, "{}", receipt.toString(), "d".repeat(64));
    }
}
