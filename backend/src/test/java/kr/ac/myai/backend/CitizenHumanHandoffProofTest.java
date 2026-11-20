package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.extraction.VerifiedExtraction;
import kr.ac.myai.backend.handoff.HumanHandoffArchiveReader;
import kr.ac.myai.backend.handoff.VerifiedHandoff;
import kr.ac.myai.backend.importing.ReviewedBatch;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.ExtractionRunRepository;
import kr.ac.myai.backend.service.ExtractionImportService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;

import java.nio.file.Path;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class CitizenHumanHandoffProofTest {
    private static final String RUN = "10000000-0000-4000-8000-000000000001";
    private static final String DOCUMENT = "10000000-0000-4000-8000-000000000002";
    private static final String EVENT = "10000000-0000-4000-8000-000000000003";
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final ReviewedImportReader json = new ReviewedImportReader();
    final ExtractionArchiveReader archives = mock(ExtractionArchiveReader.class);
    final ExtractionRunRepository repository = mock(ExtractionRunRepository.class);
    final HumanHandoffArchiveReader handoffs = mock(HumanHandoffArchiveReader.class);
    final ExtractionImportService service = new ExtractionImportService(archives, repository,
            mock(PlatformTransactionManager.class), handoffs, json);

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void eventProofCannotCrossCitizenAndLegacyFamilies(boolean citizenEvent) {
        var image = image(!citizenEvent); bind(image);
        invalid(() -> service.verifyReferences(List.of(event(EVENT, citizenEvent, image, true))));
    }

    @Test
    void failedParentProofCannotAuthorizeAnotherEventSharingItsVerifiedRun() {
        var image = image(true); bind(image);
        invalid(() -> service.verifyReferences(List.of(event(EVENT, true, image, true),
                event("10000000-0000-4000-8000-000000000004", true, image, true))));
    }

    @Test
    void failedParentCachedForOneEventDoesNotReplaceAnotherEventsMissingProof() {
        var image = image(true); bind(image);
        when(repository.referenceDirectory(RUN)).thenThrow(new ExtractionException("EXTRACTION_ARCHIVE_INVALID", null, false));
        invalid(() -> service.verifyReferences(List.of(event(EVENT, true, image, true),
                event("10000000-0000-4000-8000-000000000004", true, image, false))));
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void everyCitizenRunRequiresItsOwnSameEventCitizenProofEvenForValidatedLegacyRuns(boolean appendToValidProof) {
        var image = image(true); bind(image);
        String legacyId = "10000000-0000-4000-8000-000000000007";
        var legacy = legacyRun(legacyId);
        when(repository.referenceDirectory(legacyId)).thenReturn(root.resolve(legacyId).toString());
        when(archives.read(legacyId, root)).thenReturn(legacy);
        when(archives.readSealed(legacyId, root)).thenReturn(legacy);
        when(repository.verifiedReference(legacy)).thenReturn(new ExtractionRunRepository.Reference(legacyId, DOCUMENT, "9".repeat(64)));
        var original = event(EVENT, true, image, appendToValidProof);
        var event = new ReviewedBatch.Event(original.id(), original.revisionId(), original.revisionNo(), original.expectedRevisionNo(),
                original.payloadJson(), original.payloadSha256(), original.reviewStatus(), original.publicationIntent(), original.reviewerId(),
                original.reviewedAt(), appendToValidProof ? List.of(RUN, legacyId) : List.of(legacyId), original.sourceVersionIds(), List.of());
        invalid(() -> service.verifyReferences(List.of(event)));
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void alreadyRegisteredParentsUseSealedVerificationWithoutFreezeOrCopy(boolean citizen) {
        ExtractionRunRepository.Reference reference;
        ReviewedBatch.Event event;
        if (citizen) {
            var image = image(true); reference = bind(image); event = event(EVENT, true, image, true);
            when(archives.readSealed(RUN, root)).thenReturn(run());
        } else {
            var run = legacyRun(RUN); reference = new ExtractionRunRepository.Reference(RUN, DOCUMENT, "9".repeat(64));
            when(repository.referenceDirectory(RUN)).thenReturn(root.resolve(RUN).toString());
            when(archives.read(RUN, root)).thenReturn(run);
            when(archives.readSealed(RUN, root)).thenReturn(run);
            when(repository.verifiedReference(run)).thenReturn(reference);
            event = event(EVENT, false, image(false), false);
        }
        assertThat(service.verifyReferences(List.of(event))).containsExactly(reference);
        verify(archives).readSealed(RUN, root);
        verify(archives, never()).read(RUN, root);
    }

    @ParameterizedTest
    @ValueSource(strings = {"citizen-human-handoff-import-v1", "citizen-reviewed-import-v1"})
    void citizenBatchRetainsVerifiedProofForBothInitialHandoffAndOrdinaryFollowup(String schema) {
        var image = image(true); var reference = bind(image);
        assertThat(service.verifyReferences(batch(schema, image))).containsExactly(reference);
    }

    @ParameterizedTest
    @ValueSource(strings = {"citizen-human-handoff-import-v1", "citizen-reviewed-import-v1"})
    void emptyCitizenBatchCannotAttachLegacyProof(String schema) {
        var image = image(false); bind(image);
        invalid(() -> service.verifyReferences(batch(schema, image)));
    }

    @ParameterizedTest
    @ValueSource(strings = {"legacy_schema", "api", "archive_v2"})
    void verifiedCitizenParentRejectsWrongSchemaExecutionModeAndArchiveVersionBeforeDatabase(String defect) {
        var run = run();
        if (defect.equals("legacy_schema")) ((ObjectNode) run.metadata()).put("schema_version", "extract-schema-v1");
        if (defect.equals("api")) ((ObjectNode) run.metadata()).put("execution_mode", "api");
        if (defect.equals("archive_v2")) ((ObjectNode) run.receipt()).put("format_version", "extraction-archive-v2");
        var jdbc = mock(JdbcTemplate.class);
        var real = new ExtractionRunRepository(jdbc, json);
        assertThatThrownBy(() -> real.verifiedHandoffParent(run, image(true))).isInstanceOfSatisfying(ExtractionException.class,
                error -> assertThat(error.code()).isEqualTo("EXTRACTION_CONFLICT"));
        verifyNoInteractions(jdbc);
    }

    private ExtractionRunRepository.Reference bind(VerifiedHandoff image) {
        var run = run(); var reference = new ExtractionRunRepository.Reference(RUN, DOCUMENT, "d".repeat(64), "e".repeat(64));
        when(handoffs.read(image.reference())).thenReturn(image);
        when(repository.handoffParentDirectory(RUN, image)).thenReturn(root.resolve(RUN).toString());
        when(archives.readSealed(RUN, root)).thenReturn(run);
        when(repository.verifiedHandoffParent(run, image)).thenReturn(reference);
        return reference;
    }

    private VerifiedHandoff image(boolean citizen) {
        var projection = mapper.createObjectNode().put("schema_version", citizen ? "citizen-human-handoff-projection-v1" : "human-handoff-projection-v1");
        projection.putObject("parent").put("run_id", RUN).put("status", "failed").put("execution_mode", "manual_import").put("receipt_sha256", "b".repeat(64));
        projection.putArray("documents").addObject().put("document_version_id", DOCUMENT);
        projection.putArray("events").addObject().put("event_id", EVENT);
        var review = mapper.createObjectNode(); review.putObject("output").put("schema_version", citizen ? "extract-citizen-v1" : "extract-schema-v1");
        var receipt = mapper.createObjectNode().put("handoff_ref", "a".repeat(64));
        return new VerifiedHandoff(root.resolve("a".repeat(64)), projection, review, receipt, "c".repeat(64));
    }

    private VerifiedExtraction run() {
        var receipt = mapper.createObjectNode().put("format_version", "extraction-archive-v1").put("run_id", RUN)
                .put("document_version_id", DOCUMENT).put("status", "failed").put("data_kind", "synthetic");
        var metadata = mapper.createObjectNode().put("schema_version", "extract-citizen-v1").put("execution_mode", "manual_import");
        return new VerifiedExtraction(root.resolve(RUN), mapper.createObjectNode(), metadata, receipt, metadata.toString(), receipt.toString(), "b".repeat(64));
    }

    private VerifiedExtraction legacyRun(String id) {
        var receipt = mapper.createObjectNode().put("format_version", "extraction-archive-v1").put("run_id", id)
                .put("document_version_id", DOCUMENT).put("status", "validated").put("data_kind", "synthetic");
        var metadata = mapper.createObjectNode().put("schema_version", "extract-schema-v1").put("execution_mode", "manual_import");
        return new VerifiedExtraction(root.resolve(id), mapper.createObjectNode(), metadata, receipt, metadata.toString(), receipt.toString(), "b".repeat(64));
    }

    private ReviewedBatch.Event event(String id, boolean citizen, VerifiedHandoff image, boolean proof) {
        var payload = mapper.createObjectNode();
        if (citizen) payload.put("schema_version", "citizen-revision-v1");
        if (proof) payload.putArray("human_handoffs").add(proof(image));
        return new ReviewedBatch.Event(id, "10000000-0000-4000-8000-000000000005", 1, 0, payload.toString(), "f".repeat(64),
                "needs_review", "hidden", null, null, List.of(RUN), List.of(DOCUMENT), List.of());
    }

    private ReviewedBatch batch(String schema, VerifiedHandoff image) {
        var document = new ReviewedBatch.Document("10000000-0000-4000-8000-000000000006", DOCUMENT, 1,
                "https://example.org/synthetic", "f".repeat(64), "{}", "synthetic-source.txt", List.of());
        return new ReviewedBatch(schema, "f".repeat(64), "synthetic", List.of(document), List.of(), RUN, null,
                mapper.createArrayNode().add(proof(image)).toString());
    }

    private ObjectNode proof(VerifiedHandoff image) {
        var reference = image.reference();
        return mapper.createObjectNode().put("directory", reference.directory()).put("handoff_ref", reference.handoffRef())
                .put("receipt_sha256", reference.receiptSha256());
    }

    private void invalid(org.assertj.core.api.ThrowableAssert.ThrowingCallable action) {
        assertThatThrownBy(action).isInstanceOfSatisfying(ExtractionException.class,
                error -> assertThat(error.code()).isEqualTo("EXTRACTION_ARCHIVE_INVALID"));
    }
}
