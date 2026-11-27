package kr.ac.myai.backend;

import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedBatch;
import kr.ac.myai.backend.repository.ReviewedImportRepository;
import kr.ac.myai.backend.service.ExtractionImportService;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.PlatformTransactionManager;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class ExtractionFailureMappingTest {
    @Test
    void runtimeFailureStaysRetryableWhileArchiveFailureStaysValidation() {
        var extractions = mock(ExtractionImportService.class);
        var batch = mock(ReviewedBatch.class);
        var service = new ReviewedImportService(mock(ReviewedImportRepository.class), mock(PlatformTransactionManager.class), extractions);

        // Python 실행 환경이 없으면 로컬 API가 503 재시도 가능으로 알리도록 원래 오류를 그대로 던진다.
        when(extractions.verifyReferences(batch)).thenThrow(new ExtractionException("EXTRACTION_RUNTIME_UNAVAILABLE", null, true));
        assertThatThrownBy(() -> service.importBatch(batch, "synthetic-reviewer"))
                .isInstanceOfSatisfying(ExtractionException.class, error -> org.assertj.core.api.Assertions
                        .assertThat(error.code()).isEqualTo("EXTRACTION_RUNTIME_UNAVAILABLE"));

        doThrow(new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false)).when(extractions).verifyReferences(batch);
        assertThatThrownBy(() -> service.importBatch(batch, "synthetic-reviewer"))
                .isInstanceOfSatisfying(ImportException.class, error -> org.assertj.core.api.Assertions
                        .assertThat(error.code()).isEqualTo("IMPORT_VALIDATION_ERROR"));
    }

    @Test
    void importCommandReportsPythonOutageAsRetryableExitFour() throws Exception {
        var mapper = new com.fasterxml.jackson.databind.ObjectMapper();
        var reader = mock(kr.ac.myai.backend.importing.ReviewedImportReader.class);
        var importer = mock(ReviewedImportService.class);
        var batch = mock(ReviewedBatch.class);
        when(reader.readJson(org.mockito.ArgumentMatchers.any())).thenReturn(mapper.createObjectNode().put("schema_version", "reviewed-import-v1"));
        when(reader.read(org.mockito.ArgumentMatchers.any(java.nio.file.Path.class), org.mockito.ArgumentMatchers.any(java.nio.file.Path.class))).thenReturn(batch);
        when(importer.importBatch(batch, "synthetic-reviewer")).thenThrow(new ExtractionException("EXTRACTION_RUNTIME_UNAVAILABLE", null, true));
        var environment = new org.springframework.mock.env.MockEnvironment().withProperty("myai.import.file", "/SYNTHETIC/batch.json")
                .withProperty("myai.import.source-root", "/SYNTHETIC/source").withProperty("myai.import.actor", "synthetic-reviewer");
        var command = new kr.ac.myai.backend.importing.LocalImportCommand(reader, importer, environment,
                mock(org.springframework.context.ApplicationContext.class), mapper, mock(kr.ac.myai.backend.service.HumanHandoffImportService.class));
        var out = new java.io.ByteArrayOutputStream(); var original = System.out;
        System.setOut(new java.io.PrintStream(out, true, java.nio.charset.StandardCharsets.UTF_8));
        try { command.run(null); } finally { System.setOut(original); }
        org.assertj.core.api.Assertions.assertThat(command.getExitCode()).isEqualTo(4);
        org.assertj.core.api.Assertions.assertThat(out.toString(java.nio.charset.StandardCharsets.UTF_8))
                .contains("EXTRACTION_RUNTIME_UNAVAILABLE", "\"retryable\":true");
    }
}
