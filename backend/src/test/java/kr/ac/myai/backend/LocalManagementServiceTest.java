package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.validation.Validation;
import jakarta.validation.ValidatorFactory;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.local.LocalManagementService;
import kr.ac.myai.backend.local.LocalRequestStore;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.service.*;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.http.HttpStatus;
import org.springframework.mock.env.MockEnvironment;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class LocalManagementServiceTest {
    @TempDir Path root;
    final String actor = "synthetic-local-actor";
    final String eventId = "10000000-0000-4000-8000-000000000004";
    final String otherId = "20000000-0000-4000-8000-000000000004";
    final String runId = "71fb66f0-e610-4f9c-8f26-4bb77655ee8c";
    final ObjectMapper mapper = new ObjectMapper();
    final ReviewedImportReader reader = new ReviewedImportReader();
    final ReviewedImportService imports = mock(ReviewedImportService.class);
    final ExtractionImportService extractions = mock(ExtractionImportService.class);
    final HumanHandoffImportService handoffs = mock(HumanHandoffImportService.class);
    final PublicationService publication = mock(PublicationService.class);
    final ValidatorFactory validators = Validation.buildDefaultValidatorFactory();
    final ReviewedImportService.ImportResult imported = new ReviewedImportService.ImportResult(
            "30000000-0000-4000-8000-000000000001", List.of(),
            List.of("10000000-0000-4000-8000-000000000002"), false);
    Path sources, requests, archive, handoffRoot;
    LocalManagementService service;

    @BeforeEach
    void setup() throws Exception {
        root = root.toRealPath();
        sources = Files.createDirectory(root.resolve("sources"));
        Files.copy(Path.of("examples/synthetic-source.txt"), sources.resolve("synthetic-source.txt"));
        requests = Files.createDirectory(root.resolve("requests"),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        archive = root.resolve("extractions"); handoffRoot = root.resolve("handoffs");
        var environment = new MockEnvironment().withProperty("myai.local-api.actor", actor)
                .withProperty("myai.local-api.source-root", sources.toString())
                .withProperty("myai.local-api.extraction-root", archive.toString())
                .withProperty("myai.local-api.handoff-root", handoffRoot.toString());
        service = new LocalManagementService(reader, new PublicationCommandReader(reader, validators.getValidator()),
                imports, extractions, handoffs, publication, new LocalRequestStore(requests.toString()), environment);
    }

    @AfterEach void closeValidators() { validators.close(); }

    @Test
    void documentImportKeepsOriginalBytesAndCannotCreateEvents() throws Exception {
        byte[] body = bytes(fixture("source-import"));
        when(imports.importBatch(any(), eq(actor))).thenAnswer(invocation -> {
            var batch = (kr.ac.myai.backend.importing.ReviewedBatch) invocation.getArgument(0);
            assertThat(batch.schemaVersion()).isEqualTo("source-import-v1");
            assertThat(batch.events()).isEmpty();
            assertThat(batch.inputSha256()).isEqualTo(hash(body));
            retained(body);
            return imported;
        });
        var result = service.documents(body);
        assertThat(result.schemaVersion()).isEqualTo("local-management-result-v1");
        assertThat(result.requestSha256()).isEqualTo(hash(body));
        assertThat(result.data()).isEqualTo(imported);
        verifyNoInteractions(extractions, handoffs, publication);
    }

    @Test
    void documentRouteRejectsReviewedBatchBeforeSavingAnything() throws Exception {
        invalid(() -> service.documents(bytes(fixture("reviewed-import"))));
        noRequestsOrDomainCalls();
    }

    @Test
    void extractionDispatchPassesExplicitInputHashAndConfiguredRoot() throws Exception {
        byte[] body = bytes(extractionRequest());
        var result = new ExtractionImportService.Result(runId, "10000000-0000-4000-8000-000000000002",
                "failed", 1, "synthetic", "b".repeat(64), "c".repeat(64), false, true);
        when(extractions.importRun(runId, archive, actor, "a".repeat(64))).thenAnswer(invocation -> {
            retained(body); return result;
        });
        assertThat(service.extraction(body).data()).isEqualTo(result);
        verify(extractions, never()).importRun(anyString(), any(), anyString());
    }

    @Test
    void extractionRouteRejectsExtraKeysAndMissingOrMalformedHashWithoutSaving() throws Exception {
        var extra = extractionRequest().put("archive_root", "PRIVATE_PATH");
        var missing = extractionRequest(); missing.remove("expected_input_hash");
        for (var input : List.of(extra, missing, extractionRequest().putNull("expected_input_hash"),
                extractionRequest().put("expected_input_hash", "A".repeat(64)),
                extractionRequest().put("run_id", "../PRIVATE_PATH"))) {
            invalid(() -> service.extraction(bytes(input)));
        }
        noRequestsOrDomainCalls();
    }

    @Test
    void reviewRequiresTheOnlyEventToMatchTheUrlBeforeSaving() throws Exception {
        var input = fixture("reviewed-import");
        invalid(() -> service.review(otherId, bytes(input)));
        var another = input.path("events").get(0).deepCopy();
        ((ObjectNode) another).put("event_id", otherId);
        ((ObjectNode) another.path("revision")).put("revision_id", "20000000-0000-4000-8000-000000000005");
        input.withArray("events").add(another);
        invalid(() -> service.review(eventId, bytes(input)));
        noRequestsOrDomainCalls();
    }

    @Test
    void reviewedBatchAndMatchingSingleReviewKeepTheExistingRevisionContract() throws Exception {
        var input = fixture("reviewed-import");
        byte[] body = bytes(input);
        when(imports.importBatch(any(), eq(actor))).thenAnswer(invocation -> {
            var batch = (kr.ac.myai.backend.importing.ReviewedBatch) invocation.getArgument(0);
            assertThat(batch.events().getFirst().id()).isEqualTo(eventId);
            assertThat(batch.events().getFirst().expectedRevisionNo()).isZero();
            retained(body); return imported;
        });
        assertThat(service.review(eventId, body).data()).isEqualTo(imported);
        assertThat(service.reviews(body).data()).isEqualTo(imported);
    }

    @Test
    void multiEventHandoffUsesExplicitBatchRouteAndPreservesTheCompleteRequest() throws Exception {
        var request = handoffRequest();
        request.withArray("revisions").addObject().put("event_id", otherId)
                .put("revision_id", "20000000-0000-4000-8000-000000000005").put("expected_revision_no", 0);
        byte[] body = bytes(request);
        invalid(() -> service.review(eventId, body));
        noRequestsOrDomainCalls();
        when(handoffs.importBytes(any(), eq(sources), eq(handoffRoot), eq(actor))).thenAnswer(invocation -> {
            assertThat((byte[]) invocation.getArgument(0)).isEqualTo(body);
            return imported;
        });
        assertThat(service.reviews(body).data()).isEqualTo(imported);
        retained(body);
    }

    @Test
    void singleHandoffRejectsMismatchedUrlAndAcceptsItsExactEvent() throws Exception {
        byte[] body = bytes(handoffRequest());
        invalid(() -> service.review(otherId, body));
        noRequestsOrDomainCalls();
        when(handoffs.importBytes(any(), eq(sources), eq(handoffRoot), eq(actor))).thenReturn(imported);
        assertThat(service.review(eventId, body).data()).isEqualTo(imported);
        retained(body);
    }

    @Test
    void approvalAndRejectionAreOnlyAcceptedForTheirExactSingleEvent() throws Exception {
        var approve = fixture("approve");
        invalid(() -> service.review(otherId, bytes(approve)));
        invalid(() -> service.publish(bytes(approve)));
        invalid(() -> service.reviews(bytes(approve)));
        noRequestsOrDomainCalls();
        var result = new PublicationService.Result("approve", eventId, otherId, null, null, null, null);
        when(publication.execute(any(PublicationCommand.Decision.class), eq(sources), eq(actor))).thenReturn(result);
        assertThat(service.review(eventId, bytes(approve)).data()).isEqualTo(result);
        var reject = approve.deepCopy().put("action", "reject");
        service.review(eventId, bytes(reject));
        retained(bytes(approve)); retained(bytes(reject));
    }

    @Test
    void previewDoesNotCreateRequestFilesOrChangeTheRequestDirectory() throws Exception {
        var input = fixture("publish").put("action", "preview");
        var before = Files.getLastModifiedTime(requests);
        var result = new PublicationService.Result("preview", null, null, otherId, "a".repeat(64), null,
                mapper.createObjectNode().put("data_kind", "synthetic"));
        when(publication.execute(any(PublicationCommand.Publish.class), eq(sources), eq(actor))).thenReturn(result);
        assertThat(service.publish(bytes(input)).data()).isEqualTo(result);
        assertThat(Files.getLastModifiedTime(requests)).isEqualTo(before);
        try (var entries = Files.list(requests)) { assertThat(entries.toList()).isEmpty(); }
        verifyNoInteractions(imports, extractions, handoffs);
    }

    @Test
    void publishAndRollbackPreserveTheirOriginalCommandsBeforeDomainWork() throws Exception {
        for (String name : List.of("publish", "rollback")) {
            byte[] body = bytes(fixture(name));
            when(publication.execute(any(), eq(sources), eq(actor))).thenAnswer(invocation -> {
                retained(body);
                var command = (PublicationCommand) invocation.getArgument(0);
                assertThat(command.action()).isEqualTo(name);
                return new PublicationService.Result(name, null, null, otherId, "a".repeat(64), 2L, null);
            });
            assertThat(service.publish(body).requestSha256()).isEqualTo(hash(body));
        }
    }

    @Test
    void malformedJsonUtf8UnknownSchemaAndExtraInputAreNotArchived() throws Exception {
        for (byte[] body : List.of("{".getBytes(StandardCharsets.UTF_8),
                " \n\t".getBytes(StandardCharsets.UTF_8), "null".getBytes(StandardCharsets.UTF_8), "[]".getBytes(StandardCharsets.UTF_8),
                "{\"schema_version\":\"unknown\"}".getBytes(StandardCharsets.UTF_8),
                "{\"schema_version\":\"source-import-v1\",\"schema_version\":\"source-import-v1\"}".getBytes(StandardCharsets.UTF_8),
                (fixture("source-import") + "{}").getBytes(StandardCharsets.UTF_8),
                new byte[] {'{', '"', (byte) 0xc3, '(', '"', ':', '0', '}'})) {
            invalid(() -> service.documents(body));
        }
        noRequestsOrDomainCalls();
    }

    @Test
    void unsafeRequestStorageStopsAllDomainWork() throws Exception {
        Files.setPosixFilePermissions(requests, PosixFilePermissions.fromString("rwxr-xr-x"));
        assertThatThrownBy(() -> service.documents(bytes(fixture("source-import"))))
                .isInstanceOfSatisfying(ApiException.class,
                        error -> assertThat(error.code()).isEqualTo("LOCAL_API_IO_ERROR"));
        noRequestsOrDomainCalls();
    }

    @Test
    void knownDomainFailureRetainsOriginalRequestAndReturnsSafeTypedError() throws Exception {
        byte[] body = bytes(extractionRequest());
        when(extractions.importRun(runId, archive, actor, "a".repeat(64)))
                .thenThrow(new ExtractionException("EXTRACTION_ARCHIVE_INVALID", "PRIVATE_PATH", false));
        assertThatThrownBy(() -> service.extraction(body)).isInstanceOfSatisfying(ApiException.class, error -> {
            assertThat(error.status()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY);
            assertThat(error.code()).isEqualTo("EXTRACTION_ARCHIVE_INVALID");
            assertThat(error.field()).isNull();
            assertThat(error.getMessage()).doesNotContain("PRIVATE_PATH", root.toString());
        });
        retained(body);
    }

    @Test
    void archiveIoFailureKeepsItsExplicitRetryHint() throws Exception {
        byte[] body = bytes(extractionRequest());
        for (boolean retryable : new boolean[] {true, false}) {
            doThrow(new ExtractionException("EXTRACTION_IO_ERROR", null, retryable)).when(extractions)
                    .importRun(runId, archive, actor, "a".repeat(64));
            assertThatThrownBy(() -> service.extraction(body)).isInstanceOfSatisfying(ApiException.class, error -> {
                assertThat(error.status()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR);
                assertThat(error.code()).isEqualTo("EXTRACTION_IO_ERROR");
                assertThat(error.retryable()).isEqualTo(retryable);
            });
        }
    }

    @Test
    void domainErrorsKeepNotFoundConflictUnavailableAndInternalStatusesWithoutPrivateDetails() throws Exception {
        byte[] body = bytes(fixture("approve"));
        var codes = List.of("PUBLICATION_NOT_FOUND", "PUBLICATION_CONFLICT", "PUBLICATION_DATABASE_UNAVAILABLE", "PRIVATE_CODE");
        var statuses = List.of(HttpStatus.NOT_FOUND, HttpStatus.CONFLICT, HttpStatus.SERVICE_UNAVAILABLE, HttpStatus.INTERNAL_SERVER_ERROR);
        for (int i = 0; i < codes.size(); i++) {
            var expected = statuses.get(i);
            when(publication.execute(any(), eq(sources), eq(actor)))
                    .thenThrow(new PublicationException(codes.get(i), "PRIVATE_SQL " + root, "PRIVATE_PATH"));
            assertThatThrownBy(() -> service.review(eventId, body)).isInstanceOfSatisfying(ApiException.class, error -> {
                assertThat(error.status()).isEqualTo(expected);
                assertThat(error.retryable()).isEqualTo(expected == HttpStatus.SERVICE_UNAVAILABLE);
                assertThat(error.field()).isNull();
                assertThat(error.code()).doesNotContain("PRIVATE");
                assertThat(error.getMessage()).doesNotContain("PRIVATE", root.toString());
            });
        }
        when(imports.importBatch(any(), eq(actor))).thenThrow(new ImportException("IMPORT_CONFLICT", "PRIVATE_SQL", "PRIVATE_PATH"));
        assertThatThrownBy(() -> service.reviews(bytes(fixture("reviewed-import"))))
                .isInstanceOfSatisfying(ApiException.class, error -> assertThat(error.status()).isEqualTo(HttpStatus.CONFLICT));
    }

    private ObjectNode fixture(String name) throws Exception {
        return (ObjectNode) mapper.readTree(Path.of("examples/" + name + ".json").toFile());
    }
    private ObjectNode extractionRequest() {
        return mapper.createObjectNode().put("schema_version", "extraction-import-request-v1")
                .put("run_id", runId).put("expected_input_hash", "a".repeat(64));
    }
    private ObjectNode handoffRequest() {
        var request = mapper.createObjectNode().put("schema_version", "human-handoff-import-v1")
                .put("handoff_ref", "b".repeat(64)).put("receipt_sha256", "a".repeat(64)).put("reason", "합성 인계");
        request.putArray("revisions").addObject().put("event_id", eventId)
                .put("revision_id", "10000000-0000-4000-8000-000000000005").put("expected_revision_no", 0);
        return request;
    }
    private byte[] bytes(ObjectNode node) { return (" \n" + node.toPrettyString() + "\n ").getBytes(StandardCharsets.UTF_8); }
    private String hash(byte[] body) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(body));
    }
    private void retained(byte[] body) throws Exception { assertThat(requests.resolve(hash(body) + ".json")).hasBinaryContent(body); }
    private void noRequestsOrDomainCalls() throws Exception {
        try (var entries = Files.list(requests)) { assertThat(entries.toList()).isEmpty(); }
        verifyNoInteractions(imports, extractions, handoffs, publication);
    }
    private void invalid(org.assertj.core.api.ThrowableAssert.ThrowingCallable action) {
        assertThatThrownBy(action).isInstanceOfSatisfying(ApiException.class,
                error -> assertThat(error.status()).isEqualTo(HttpStatus.UNPROCESSABLE_ENTITY));
    }
}
