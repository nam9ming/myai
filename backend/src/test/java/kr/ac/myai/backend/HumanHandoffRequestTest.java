package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.handoff.HumanHandoffArchiveReader;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.ReviewedImportRepository;
import kr.ac.myai.backend.service.HumanHandoffImportService;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class HumanHandoffRequestTest {
    @TempDir Path root;

    @ParameterizedTest
    @ValueSource(strings = {"\u00a0", "\u0085", "\u2007", "\u202f"})
    void rejectsUnicodeWhitespaceReasonBeforeOpeningArchives(String reason) throws Exception {
        var mapper = new ObjectMapper();
        var archives = mock(HumanHandoffArchiveReader.class);
        var service = new HumanHandoffImportService(archives, new ReviewedImportReader(), mock(ReviewedImportRepository.class),
                mock(ReviewedImportService.class), mapper);
        var request = mapper.createObjectNode().put("schema_version", "human-handoff-import-v1")
                .put("handoff_ref", "a".repeat(64)).put("receipt_sha256", "b".repeat(64)).put("reason", reason);
        request.putArray("revisions");
        Path file = Files.writeString(root.resolve("request.json"), request.toString());
        assertThatThrownBy(() -> service.importFile(file, root, root, "synthetic-operator"))
                .isInstanceOfSatisfying(ImportException.class, error -> {
                    assertThat(error.code()).isEqualTo("IMPORT_VALIDATION_ERROR");
                    assertThat(error.field()).isEqualTo("reason");
                });
        verifyNoInteractions(archives);
    }
}
