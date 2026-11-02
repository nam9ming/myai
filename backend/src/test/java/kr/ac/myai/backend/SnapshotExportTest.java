package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.repository.PublicSnapshotRepository;
import kr.ac.myai.backend.repository.PublicationRepository;
import kr.ac.myai.backend.service.SnapshotExportService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class SnapshotExportTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final PublicSnapshotRepository repository = mock(PublicSnapshotRepository.class);
    final PlatformTransactionManager transactions = mock(PlatformTransactionManager.class);
    final SnapshotExportService service = new SnapshotExportService(repository, new PublicationContent(new ReviewedImportReader(), mapper), transactions);
    PublicSnapshotRepository.Published published;
    UUID id;

    @BeforeEach
    void setup() throws Exception {
        published = CalculationFixtures.published(CalculationFixtures.snapshot(mapper), mapper); id = UUID.fromString(published.snapshot().id());
        when(transactions.getTransaction(any())).thenAnswer(call -> new SimpleTransactionStatus());
        when(repository.published(id.toString())).thenReturn(Optional.of(published));
    }

    @Test
    void writesOriginalUtf8OnlyAfterReadCommitAndReusesExactFile() throws Exception {
        doAnswer(call -> { try (var files = Files.list(root)) { assertThat(files.toList()).isEmpty(); } return null; }).when(transactions).commit(any());
        var result = service.export(id, root);
        assertThat(result.snapshotId()).isEqualTo(id.toString()); assertThat(result.checksum()).isEqualTo(published.snapshot().checksum());
        assertThat(result.fileName()).isEqualTo(id + "-" + result.checksum() + ".json"); assertThat(result.alreadyExported()).isFalse();
        Path file = root.resolve(result.fileName()); byte[] bytes = Files.readAllBytes(file);
        assertThat(bytes).isEqualTo(published.snapshot().canonical().getBytes(StandardCharsets.UTF_8));
        assertThat(ReviewedImportReader.sha256(bytes)).isEqualTo(result.checksum());
        assertThat(new String(bytes, StandardCharsets.UTF_8)).contains("합성 공지 😀");
        reset(transactions); when(transactions.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        var modified = Files.getLastModifiedTime(file);
        assertThat(service.export(id, root).alreadyExported()).isTrue(); assertThat(Files.getLastModifiedTime(file)).isEqualTo(modified);
        assertFiles(result.fileName());
    }

    @Test
    void concurrentExportsCreateOneCompleteImmutableFile() throws Exception {
        var barrier = new CyclicBarrier(2);
        try (var pool = Executors.newFixedThreadPool(2)) {
            Callable<SnapshotExportService.Result> action = () -> { barrier.await(3, TimeUnit.SECONDS); return service.export(id, root); };
            var a = pool.submit(action); var b = pool.submit(action); var results = List.of(a.get(5, TimeUnit.SECONDS), b.get(5, TimeUnit.SECONDS));
            assertThat(results).extracting(SnapshotExportService.Result::alreadyExported).containsExactlyInAnyOrder(false, true);
            assertThat(Files.readAllBytes(root.resolve(results.getFirst().fileName()))).isEqualTo(published.snapshot().canonical().getBytes(StandardCharsets.UTF_8));
            assertFiles(results.getFirst().fileName());
        }
    }

    @Test
    void preservesConflictingFilesDirectoriesAndSymlinks() throws Exception {
        Path target = target(); Files.writeString(target, "PRIVATE_EXISTING");
        failure("EXPORT_FILE_CONFLICT", () -> service.export(id, root)); assertThat(Files.readString(target)).isEqualTo("PRIVATE_EXISTING");
        Files.delete(target); Files.createDirectory(target);
        failure("EXPORT_FILE_CONFLICT", () -> service.export(id, root)); assertThat(Files.isDirectory(target)).isTrue(); Files.delete(target);
        Path outside = Files.writeString(root.resolve("operator-file"), "PRIVATE_EXISTING"); Files.createSymbolicLink(target, outside);
        failure("EXPORT_FILE_CONFLICT", () -> service.export(id, root)); assertThat(Files.isSymbolicLink(target)).isTrue();
        assertThat(Files.readString(outside)).isEqualTo("PRIVATE_EXISTING"); assertFiles(target.getFileName().toString(), "operator-file");
    }

    @Test
    void fileFailureCanRetryWithoutAnyDatabaseMutation() throws Exception {
        Path directory = root.resolve("later"); failure("EXPORT_IO_ERROR", () -> service.export(id, directory));
        Files.createDirectory(directory); var result = service.export(id, directory); assertThat(result.alreadyExported()).isFalse();
        verify(repository, times(2)).published(id.toString()); verifyNoMoreInteractions(repository);
    }

    @Test
    void exportsPreviouslyPublishedSnapshotWithoutReadingCurrentSources() throws Exception {
        when(repository.published(id.toString())).thenReturn(Optional.of(new PublicSnapshotRepository.Published(published.snapshot(), published.schemaVersion(), published.createdAt(), UUID.randomUUID().toString())));
        assertThat(service.export(id, root).snapshotId()).isEqualTo(id.toString());
        verify(repository).published(id.toString()); verifyNoMoreInteractions(repository);
    }

    @Test
    void rejectsUnpublishedMissingAndUnavailableDatabaseBeforeFiles() throws Exception {
        when(repository.published(id.toString())).thenReturn(Optional.empty());
        failure("EXPORT_NOT_FOUND", () -> service.export(id, root)); assertFiles();
        when(repository.published(id.toString())).thenThrow(new DataAccessResourceFailureException("PRIVATE_SQL"));
        failure("EXPORT_DATABASE_UNAVAILABLE", () -> service.export(id, root)); assertFiles();
    }

    @Test
    void rejectsChecksumAndStoredMetadataMismatch() throws Exception {
        var row = published.snapshot();
        when(repository.published(id.toString())).thenReturn(Optional.of(new PublicSnapshotRepository.Published(new PublicationRepository.Snapshot(row.id(), row.mode(), row.caseId(), row.canonical(), "0".repeat(64), row.kind(), row.rulesVersion(), row.dictionaryVersion()), published.schemaVersion(), published.createdAt(), row.id())));
        failure("EXPORT_INVALID_SNAPSHOT", () -> service.export(id, root)); assertFiles();
        when(repository.published(id.toString())).thenReturn(Optional.of(new PublicSnapshotRepository.Published(row, "snapshot-v2", published.createdAt(), row.id())));
        failure("EXPORT_INVALID_SNAPSHOT", () -> service.export(id, root)); assertFiles();
        when(repository.published(id.toString())).thenReturn(Optional.of(new PublicSnapshotRepository.Published(row, "snapshot-v1", published.createdAt().plusSeconds(1), row.id())));
        failure("EXPORT_INVALID_SNAPSHOT", () -> service.export(id, root)); assertFiles();
    }

    @Test
    void rejectsPrivateFieldsEvenWithMatchingChecksum() throws Exception {
        for (String path : List.of("", "/points/0", "/sources/0", "/sources/0/checks/0", "/event_public_payloads/0",
                "/event_public_payloads/0/locations/0", "/event_public_payloads/0/evidence/0", "/event_public_payloads/0/applicability")) {
            var snapshot = CalculationFixtures.snapshot(mapper); ((ObjectNode) snapshot.at(path)).put("raw_output", "PRIVATE_VALUE");
            when(repository.published(id.toString())).thenReturn(Optional.of(CalculationFixtures.published(snapshot, mapper)));
            failure("EXPORT_INVALID_SNAPSHOT", () -> service.export(id, root)); assertFiles();
        }
        var snapshot = CalculationFixtures.snapshot(mapper);
        ((ObjectNode) snapshot.path("event_public_payloads").get(0).path("applicability")).putObject("value").put("actor", "PRIVATE_VALUE");
        when(repository.published(id.toString())).thenReturn(Optional.of(CalculationFixtures.published(snapshot, mapper)));
        failure("EXPORT_INVALID_SNAPSHOT", () -> service.export(id, root)); assertFiles();
    }

    private Path target() { return root.resolve(id + "-" + published.snapshot().checksum() + ".json"); }
    private void assertFiles(String... names) throws Exception {
        try (var files = Files.list(root)) { assertThat(files.map(p -> p.getFileName().toString()).toList()).containsExactlyInAnyOrder(names); }
    }
    private void failure(String code, org.assertj.core.api.ThrowableAssert.ThrowingCallable call) {
        assertThatThrownBy(call).isInstanceOfSatisfying(PublicationException.class, error -> {
            assertThat(error.code()).isEqualTo(code); assertThat(error.getMessage()).doesNotContain("PRIVATE_", root.toString());
        });
    }
}
