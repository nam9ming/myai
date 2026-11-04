package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.node.ObjectNode;
import jakarta.validation.Validation;
import jakarta.validation.ValidatorFactory;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.extraction.VerifiedExtraction;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.local.ExtractionUploadService;
import kr.ac.myai.backend.local.ExtractionUploadStore;
import kr.ac.myai.backend.local.LocalManagementService;
import kr.ac.myai.backend.local.LocalRequestStore;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.service.*;
import org.assertj.core.api.ThrowableAssert.ThrowingCallable;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.mock.env.MockEnvironment;

import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class ExtractionUploadServiceTest {
    private static final String RUN = "71fb66f0-e610-4f9c-8f26-4bb77655ee8c";
    private static final String OTHER_RUN = "66666666-6666-4666-8666-666666666666";
    private static final String ACTOR = "synthetic-extraction-upload-manager";
    private final ObjectMapper mapper = new ObjectMapper().findAndRegisterModules().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    private final ReviewedImportReader json = new ReviewedImportReader();
    private final ValidatorFactory validators = Validation.buildDefaultValidatorFactory();
    private final ExtractionImportService database = mock(ExtractionImportService.class);
    private final AtomicBoolean databaseUnavailable = new AtomicBoolean();
    private final Map<String, VerifiedExtraction> registered = new HashMap<>();
    @TempDir Path temporary;
    Path requests, extractionRoot, sources;
    ExtractionUploadStore store;
    ExtractionArchiveReader archives;
    LocalManagementService management;
    ExtractionUploadService service;

    @BeforeEach void setup() throws Exception {
        temporary = temporary.toRealPath();
        requests = directory(temporary.resolve("requests")); extractionRoot = directory(temporary.resolve("extractions"));
        sources = directory(temporary.resolve("sources"));
        store = new ExtractionUploadStore(requests.toString(), json);
        archives = new ExtractionArchiveReader(json, python(), PythonProbe.REPO.toString(), 10_000);
        when(database.importRun(anyString(), any(Path.class), anyString(), anyString())).thenAnswer(call -> {
            String run = call.getArgument(0), actor = call.getArgument(2), expected = call.getArgument(3);
            Path root = call.getArgument(1);
            if (!actor.equals(ACTOR)) throw new AssertionError("Explicit actor must reach the DB boundary");
            var verified = archives.read(run, root);
            if (!verified.inputSha256().equals(expected)) throw new ExtractionException("EXTRACTION_VALIDATION_ERROR", "expected_input_hash", false);
            if (databaseUnavailable.get()) throw new ExtractionException("EXTRACTION_DATABASE_UNAVAILABLE", null, true);
            var previous = registered.putIfAbsent(run, verified);
            if (previous != null && !previous.receiptSha256().equals(verified.receiptSha256()))
                throw new ExtractionException("EXTRACTION_CONFLICT", null, false);
            return new ExtractionImportService.Result(run, verified.documentVersionId(), verified.status(), verified.attempts(),
                    verified.dataKind(), verified.metadataSha256(), verified.receiptSha256(), previous != null, true);
        });
        service = create(extractionRoot);
    }

    @AfterEach void cleanup() throws Exception { validators.close(); ExtractionArchiveReaderTest.unseal(temporary); }

    @Test void stagesExactInitialAndSlotBytesWithSafePublicDescriptors() throws Exception {
        var fixture = fixture(validOutput());
        var initial = service.initialize(fixture.control(), fixture.metadata(), fixture.input());
        var expected = new TreeMap<>(initial(fixture)); result(initial, expected);
        assertThat(registered).isEmpty(); assertThat(extractionRoot.resolve(RUN)).doesNotExist();
        expected.put("attempt-1.prompt", fixture.prompts().getFirst());
        result(service.put(RUN, 1, "prompt", fixture.prompts().getFirst()), expected);
        expected.put("attempt-1.output", fixture.outputs().getFirst());
        result(service.put(RUN, 1, "output", fixture.outputs().getFirst()), expected);
        assertThat(store.ready(RUN, sha(fixture.input())).control()).isEqualTo(fixture.control());
        assertThat(registered).isEmpty(); assertThat(extractionRoot.resolve(RUN)).doesNotExist();
    }

    @Test void sharesTheExactThreeKeyControlReaderWithTheExistingManagementGateway() throws Exception {
        var fixture = fixture(validOutput());
        var parsed = management.readExtractionRequest(fixture.control());
        assertThat(parsed.runId()).isEqualTo(RUN); assertThat(parsed.expectedInputHash()).isEqualTo(sha(fixture.input()));
        for (byte[] invalid : List.of(bytes("{}"), bytes("{"), bytes(mapper.readTree(fixture.control()).deepCopy().toString() + "{}"),
                bytes(new String(fixture.control(), StandardCharsets.UTF_8).replace("\"run_id\":", "\"run_id\":\"" + RUN + "\",\"run_id\":")),
                bytes(((ObjectNode) mapper.readTree(fixture.control())).put("extra", true).toString()))) {
            rejected(() -> management.readExtractionRequest(invalid), 422);
            rejected(() -> service.initialize(invalid, fixture.metadata(), fixture.input()), 422);
        }
        assertThat(store.find(RUN)).isEmpty(); assertThat(registered).isEmpty();
    }

    @Test void rejectsMetadataRunModeAttemptAndInputHashMismatchesBeforeStaging() throws Exception {
        var fixture = fixture(validOutput());
        for (String change : List.of("run", "mode", "zero", "four", "fraction", "missing")) {
            var metadata = (ObjectNode) mapper.readTree(fixture.metadata());
            switch (change) {
                case "run" -> metadata.put("run_id", OTHER_RUN);
                case "mode" -> metadata.put("execution_mode", "api");
                case "zero" -> metadata.put("attempts", 0);
                case "four" -> metadata.put("attempts", 4);
                case "fraction" -> metadata.put("attempts", 1.5);
                case "missing" -> metadata.remove("run_id");
            }
            rejected(() -> service.initialize(fixture.control(), bytes(metadata.toString()), fixture.input()), 422);
        }
        var wrongHash = ((ObjectNode) mapper.readTree(fixture.control())).put("expected_input_hash", "0".repeat(64));
        rejected(() -> service.initialize(bytes(wrongHash.toString()), fixture.metadata(), fixture.input()), 422);
        assertThat(store.find(RUN)).isEmpty(); assertThat(registered).isEmpty();
    }

    @Test void keepsNewControlAndMetadataLimitsSeparateFromTheExistingInputAndSlotLimits() throws Exception {
        var fixture = fixture(validOutput());
        rejected(() -> service.initialize(padded(fixture.control(), 64 * 1024 + 1), fixture.metadata(), fixture.input()), 413);
        rejected(() -> service.initialize(fixture.control(), padded(fixture.metadata(), 64 * 1024 + 1), fixture.input()), 413);
        byte[] largeInput = padded(fixture.input(), 8 * 1024 * 1024 + 1);
        rejected(() -> service.initialize(control(RUN, largeInput), fixture.metadata(), largeInput), 413);
        byte[] input = padded(fixture.input(), 8 * 1024 * 1024);
        result(service.initialize(padded(control(RUN, input), 64 * 1024), padded(fixture.metadata(), 64 * 1024), input),
                Map.of("control.json", padded(control(RUN, input), 64 * 1024), "metadata.json", padded(fixture.metadata(), 64 * 1024), "input.json", input));
        var before = tree(requests);
        rejected(() -> service.put(RUN, 1, "output", new byte[5 * 1024 * 1024 + 1]), 413);
        rejected(() -> service.put(RUN, 1, "prompt", new byte[20 * 1024 * 1024 + 1]), 413);
        rejected(() -> service.finalizeUpload(RUN, padded(control(RUN, input), 64 * 1024 + 1)), 413);
        assertThat(tree(requests)).isEqualTo(before); assertThat(registered).isEmpty();
    }

    @ParameterizedTest @ValueSource(ints = {1, 3})
    void finalizesActualPythonAttemptsAndForwardsTheOriginalFinalControlToManagement(int attempts) throws Exception {
        byte[][] outputs = attempts == 1 ? new byte[][] {validOutput()}
                : new byte[][] {bytes("not-json"), new byte[] {(byte) 0xff}, validOutput()};
        var fixture = fixture(outputs); stage(fixture);
        byte[] finalControl = bytes("\n" + mapper.readTree(fixture.control()).toPrettyString() + "\n ");
        var staging = tree(requests.resolve("extraction-uploads"));
        var result = service.finalizeUpload(RUN, finalControl);
        finalResult(result, finalControl, "validated", attempts, false);
        var verified = archives.read(RUN, extractionRoot);
        originals(fixture, verified); assertThat(verified.directory()).isNotEqualTo(extractionRoot.resolve(RUN));
        assertThat(tree(requests.resolve("extraction-uploads"))).isEqualTo(staging);
        assertThat(Files.readAllBytes(requests.resolve(sha(finalControl) + ".json"))).isEqualTo(finalControl);
        if (attempts == 3) assertThat(verified.receipt().path("attempts").get(0).path("status").asText()).isEqualTo("failed");
    }

    @Test void allFailedEmptyAndInvalidUtf8OutputsBecomeARealFailedArchiveAndKeepEveryOriginal() throws Exception {
        var fixture = fixture(bytes("{broken"), new byte[0], new byte[] {(byte) 0xff, 0}); stage(fixture);
        finalResult(service.finalizeUpload(RUN, fixture.control()), fixture.control(), "failed", 3, false);
        var verified = archives.read(RUN, extractionRoot); originals(fixture, verified);
        assertThat(verified.receipt().path("attempts")).hasSize(3).allSatisfy(attempt ->
                assertThat(attempt.path("status").asText()).isEqualTo("failed"));
    }

    @Test void leavesFullMetadataSemanticsToTheActualPythonValidatorAtFinalize() throws Exception {
        var good = fixture(validOutput()); var metadata = (ObjectNode) mapper.readTree(good.metadata()); metadata.put("usage_in", -1);
        var invalid = new Fixture(good.control(), bytes(metadata.toString()), good.input(), good.prompts(), good.outputs());
        stage(invalid); var before = tree(requests.resolve("extraction-uploads"));
        rejected(() -> service.finalizeUpload(RUN, invalid.control()), 422);
        assertThat(tree(requests.resolve("extraction-uploads"))).isEqualTo(before);
        assertThat(extractionRoot.resolve(RUN).resolve("receipt.json")).doesNotExist(); assertThat(registered).isEmpty();
    }

    @Test void completedCanonicalAcceptsOnlyExactInitialAndSlotRetransmissionsWithoutReplacingFiles() throws Exception {
        var fixture = fixture(validOutput()); manual(fixture, null);
        archives.read(RUN, extractionRoot); var before = tree(extractionRoot);
        result(service.initialize(fixture.control(), fixture.metadata(), fixture.input()), initial(fixture));
        service.put(RUN, 1, "prompt", fixture.prompts().getFirst()); service.put(RUN, 1, "output", fixture.outputs().getFirst());
        finalResult(service.finalizeUpload(RUN, fixture.control()), fixture.control(), "validated", 1, false);
        finalResult(service.finalizeUpload(RUN, fixture.control()), fixture.control(), "validated", 1, true);
        var changedMetadata = append(fixture.metadata(), " ");
        rejected(() -> service.initialize(fixture.control(), changedMetadata, fixture.input()), 409);
        byte[] input = append(fixture.input(), " ");
        rejected(() -> service.initialize(control(RUN, input), fixture.metadata(), input), 409);
        rejected(() -> service.put(RUN, 1, "prompt", bytes("DIFFERENT PROMPT")), 409);
        rejected(() -> service.put(RUN, 1, "output", bytes("DIFFERENT OUTPUT")), 409);
        rejected(() -> service.put(RUN, 2, "prompt", bytes("ADDED ATTEMPT")), 409);
        assertThat(tree(extractionRoot)).isEqualTo(before); originals(fixture, archives.read(RUN, extractionRoot));
    }

    @ParameterizedTest @ValueSource(strings = {"api-v1", "api-v2"})
    void cannotConvertAnExistingApiOrChunkedRunIntoAManualUpload(String kind) throws Exception {
        Path work = directory(temporary.resolve("api-fixture"));
        Path inputFile = kind.equals("api-v2") ? ChunkedArchiveFixtures.input(work)
                : file(work.resolve("input.json"), Files.readAllBytes(PythonProbe.REPO.resolve("contracts/examples/ai-input.json")));
        Path apiRoot = kind.equals("api-v2") ? ChunkedArchiveFixtures.archive(work, inputFile, RUN, "fixture-nfc-v1", "success")
                : ExtractionArchiveReaderTest.apiArchive(work, inputFile, RUN, "fixture-nfc-v1");
        var canonical = archives.read(RUN, apiRoot); var before = tree(apiRoot); var manual = fixture(validOutput());
        byte[] input = Files.readAllBytes(inputFile); var target = create(apiRoot);
        rejected(() -> target.initialize(control(RUN, input), manual.metadata(), input), 409);
        assertThat(tree(apiRoot)).isEqualTo(before); assertThat(registered).isEmpty();
        assertThat(canonical.receipt().path("execution_mode").asText()).isEqualTo("api");
    }

    @Test void corruptCanonicalIsNotTreatedAsAbsentOrSilentlyRepaired() throws Exception {
        var fixture = fixture(validOutput()); manual(fixture, null);
        Path receipt = extractionRoot.resolve(RUN).resolve("receipt.json"); Files.writeString(receipt, "SYNTHETIC CORRUPT RECEIPT");
        var before = tree(extractionRoot);
        rejected(() -> service.initialize(fixture.control(), fixture.metadata(), fixture.input()), 422);
        assertThat(tree(extractionRoot)).isEqualTo(before); assertThat(registered).isEmpty();
    }

    @Test void theSameCompleteHttpStageResumesAnInterruptedCanonicalWithTheOriginalIdentity() throws Exception {
        var fixture = fixture(bytes("not-json"), validOutput(), validOutput()); stage(fixture);
        var staged = store.ready(RUN, sha(fixture.input())); JsonNode first = manual(fixture, staged.directory());
        Path canonical = extractionRoot.resolve(RUN); byte[] identity = Files.readAllBytes(canonical.resolve("identity.json"));
        Files.delete(canonical.resolve("receipt.json")); Files.delete(canonical.resolve("attempt-3.output"));
        var before = tree(requests.resolve("extraction-uploads"));
        finalResult(service.finalizeUpload(RUN, fixture.control()), fixture.control(), "validated", 3, false);
        assertThat(Files.readAllBytes(canonical.resolve("identity.json"))).isEqualTo(identity);
        assertThat(json.readJson(canonical.resolve("receipt.json"))).isEqualTo(first);
        assertThat(tree(requests.resolve("extraction-uploads"))).isEqualTo(before);
        originals(fixture, archives.read(RUN, extractionRoot));
    }

    @Test void ownedStageDoesNotRecreateAnIdentityWhenCanonicalPayloadsRemainWithoutIdentityAndReceipt() throws Exception {
        var fixture = fixture(validOutput()); stage(fixture);
        var staged = store.ready(RUN, sha(fixture.input())); manual(fixture, staged.directory());
        Path canonical = extractionRoot.resolve(RUN);
        Files.delete(canonical.resolve("identity.json")); Files.delete(canonical.resolve("receipt.json"));
        assertThat(Files.readAllBytes(canonical.resolve("input.json"))).isEqualTo(fixture.input());
        var before = tree(extractionRoot); var staging = tree(requests.resolve("extraction-uploads"));
        rejected(() -> service.finalizeUpload(RUN, fixture.control()), 422);
        assertThat(tree(extractionRoot)).isEqualTo(before); assertThat(tree(requests.resolve("extraction-uploads"))).isEqualTo(staging);
        assertThat(canonical.resolve("identity.json")).doesNotExist(); assertThat(registered).isEmpty();
    }

    @Test void ownedCompleteStageResumesAnEmptyCanonicalDirectoryBeforeTheFirstIdentityInstall() throws Exception {
        var fixture = fixture(validOutput()); stage(fixture);
        Path canonical = directory(extractionRoot.resolve(RUN));
        try (var files = Files.list(canonical)) { assertThat(files.toList()).isEmpty(); }
        var staging = tree(requests.resolve("extraction-uploads"));
        finalResult(service.finalizeUpload(RUN, fixture.control()), fixture.control(), "validated", 1, false);
        assertThat(canonical.resolve("identity.json")).isRegularFile(); assertThat(canonical.resolve("receipt.json")).isRegularFile();
        assertThat(tree(requests.resolve("extraction-uploads"))).isEqualTo(staging);
        originals(fixture, archives.read(RUN, extractionRoot));
    }

    @Test void anIncompleteExternalCliRunWithoutTheHttpStageIsRejectedAndPreserved() throws Exception {
        var fixture = fixture(validOutput()); manual(fixture, null);
        Path canonical = extractionRoot.resolve(RUN); Files.delete(canonical.resolve("receipt.json"));
        Files.delete(canonical.resolve("attempt-1.output")); var before = tree(extractionRoot);
        assertThat(store.find(RUN)).isEmpty();
        rejected(() -> service.initialize(fixture.control(), fixture.metadata(), fixture.input()), 422);
        rejected(() -> service.finalizeUpload(RUN, fixture.control()), 422);
        assertThat(store.find(RUN)).isEmpty(); assertThat(tree(extractionRoot)).isEqualTo(before); assertThat(registered).isEmpty();
        Path emptyRoot = directory(temporary.resolve("external-empty-root")); directory(emptyRoot.resolve(RUN));
        var emptyService = create(emptyRoot); var emptyBefore = tree(emptyRoot);
        rejected(() -> emptyService.initialize(fixture.control(), fixture.metadata(), fixture.input()), 422);
        rejected(() -> emptyService.finalizeUpload(RUN, fixture.control()), 422);
        assertThat(tree(emptyRoot)).isEqualTo(emptyBefore); assertThat(store.find(RUN)).isEmpty(); assertThat(registered).isEmpty();
    }

    @Test void ownedCompleteStageResumesAfterPythonStopsBeforeLinkingTheFirstIdentity() throws Exception {
        var fixture = fixture(validOutput()); stage(fixture);
        Path canonical = directory(extractionRoot.resolve(RUN));
        byte[] interrupted = bytes("SYNTHETIC PARTIAL IDENTITY");
        Path unfinished = file(canonical.resolve(".abcdefgh.tmp"), interrupted);
        finalResult(service.finalizeUpload(RUN, fixture.control()), fixture.control(), "validated", 1, false);
        assertThat(Files.readAllBytes(unfinished)).isEqualTo(interrupted);
        originals(fixture, archives.read(RUN, extractionRoot));
    }

    @Test void arbitraryPublicOrLinkedLeftoversCannotBeMistakenForAnUninstalledIdentity() throws Exception {
        var fixture = fixture(validOutput()); stage(fixture);
        for (String kind : List.of("payload", "public", "link")) {
            Path root = directory(temporary.resolve("invalid-leftover-" + kind));
            Path canonical = directory(root.resolve(RUN));
            Path leftover = canonical.resolve(kind.equals("payload") ? "input.json" : ".abcdefgh.tmp");
            if (kind.equals("link")) Files.createSymbolicLink(leftover, file(root.resolve("outside.txt"), bytes("OUTSIDE CANARY")));
            else {
                file(leftover, bytes("SYNTHETIC LEFTOVER"));
                if (kind.equals("public")) Files.setPosixFilePermissions(leftover, PosixFilePermissions.fromString("rw-r--r--"));
            }
            var before = tree(root);
            rejected(() -> create(root).finalizeUpload(RUN, fixture.control()), 422);
            assertThat(tree(root)).isEqualTo(before);
            assertThat(canonical.resolve("identity.json")).doesNotExist();
        }
        assertThat(registered).isEmpty();
    }

    @Test void finalizeRejectsIncompletePairsUrlControlAndExpectedHashMismatches() throws Exception {
        var fixture = fixture(validOutput()); service.initialize(fixture.control(), fixture.metadata(), fixture.input());
        service.put(RUN, 1, "prompt", fixture.prompts().getFirst());
        rejected(() -> service.finalizeUpload(RUN, fixture.control()), 422);
        rejected(() -> service.finalizeUpload(OTHER_RUN, fixture.control()), 422);
        service.put(RUN, 1, "output", fixture.outputs().getFirst());
        var before = tree(requests.resolve("extraction-uploads"));
        byte[] wrongHash = bytes(((ObjectNode) mapper.readTree(fixture.control())).put("expected_input_hash", "0".repeat(64)).toString());
        rejected(() -> service.finalizeUpload(RUN, wrongHash), 409);
        rejected(() -> service.finalizeUpload(RUN, bytes("{}")), 422);
        assertThat(tree(requests.resolve("extraction-uploads"))).isEqualTo(before);
        assertThat(extractionRoot.resolve(RUN)).doesNotExist(); assertThat(registered).isEmpty();
    }

    @Test void databaseFailureKeepsTheSameArchiveAndStageForAnExactFinalizeRetry() throws Exception {
        var fixture = fixture(validOutput()); stage(fixture);
        Path publicCanary = file(sources.resolve("existing-public-canary.txt"), bytes("EXISTING SYNTHETIC PUBLIC CONTENT"));
        var sourceBefore = tree(sources); var stageBefore = tree(requests.resolve("extraction-uploads"));
        databaseUnavailable.set(true);
        var error = rejected(() -> service.finalizeUpload(RUN, fixture.control()), 503); assertThat(error.retryable()).isTrue();
        assertThat(registered).isEmpty(); originals(fixture, archives.read(RUN, extractionRoot));
        var archiveBefore = tree(extractionRoot); databaseUnavailable.set(false);
        finalResult(service.finalizeUpload(RUN, fixture.control()), fixture.control(), "validated", 1, false);
        finalResult(service.finalizeUpload(RUN, fixture.control()), fixture.control(), "validated", 1, true);
        assertThat(tree(extractionRoot)).isEqualTo(archiveBefore); assertThat(tree(requests.resolve("extraction-uploads"))).isEqualTo(stageBefore);
        assertThat(tree(sources)).isEqualTo(sourceBefore); assertThat(Files.readString(publicCanary)).isEqualTo("EXISTING SYNTHETIC PUBLIC CONTENT");
    }

    private ExtractionUploadService create(Path root) {
        var environment = new MockEnvironment().withProperty("myai.local-api.actor", ACTOR)
                .withProperty("myai.local-api.source-root", sources.toString()).withProperty("myai.local-api.extraction-root", root.toString())
                .withProperty("myai.local-api.handoff-root", sources.toString());
        management = new LocalManagementService(json, new PublicationCommandReader(json, validators.getValidator()),
                mock(ReviewedImportService.class), database, mock(HumanHandoffImportService.class), mock(PublicationService.class),
                new LocalRequestStore(requests.toString()), environment);
        return new ExtractionUploadService(management, archives, store, json, root.toString());
    }

    private Fixture fixture(byte[]... outputs) throws Exception {
        byte[] input = Files.readAllBytes(PythonProbe.REPO.resolve("contracts/examples/ai-input.json"));
        var metadata = (ObjectNode) mapper.readTree(PythonProbe.REPO.resolve("processing/examples/extraction-metadata.json").toFile());
        metadata.put("attempts", outputs.length);
        byte[] rawMetadata = bytes(" \n" + metadata.toPrettyString() + "\n ");
        var prompts = new ArrayList<byte[]>();
        for (int index = 0; index < outputs.length; index++) prompts.add(bytes("합성 수동 입력 " + (index + 1) + " 😀\r\n"));
        return new Fixture(control(RUN, input), rawMetadata, input, List.copyOf(prompts), List.of(outputs));
    }

    private void stage(Fixture fixture) {
        service.initialize(fixture.control(), fixture.metadata(), fixture.input());
        for (int index = 0; index < fixture.outputs().size(); index++) {
            service.put(RUN, index + 1, "output", fixture.outputs().get(index));
            service.put(RUN, index + 1, "prompt", fixture.prompts().get(index));
        }
    }

    private JsonNode manual(Fixture fixture, Path staged) throws Exception {
        Path directory = staged == null ? directory(temporary.resolve("cli-input-" + UUID.randomUUID())) : staged;
        if (staged == null) {
            file(directory.resolve("input.json"), fixture.input()); file(directory.resolve("metadata.json"), fixture.metadata());
            for (int index = 0; index < fixture.outputs().size(); index++) {
                file(directory.resolve("attempt-" + (index + 1) + ".prompt"), fixture.prompts().get(index));
                file(directory.resolve("attempt-" + (index + 1) + ".output"), fixture.outputs().get(index));
            }
        }
        var pairs = new ArrayList<ExtractionArchiveReader.AttemptFiles>();
        for (int index = 1; index <= fixture.outputs().size(); index++) pairs.add(new ExtractionArchiveReader.AttemptFiles(
                directory.resolve("attempt-" + index + ".prompt"), directory.resolve("attempt-" + index + ".output")));
        return archives.importManual(RUN, extractionRoot, directory.resolve("input.json"), directory.resolve("metadata.json"), pairs);
    }

    private Map<String, byte[]> initial(Fixture fixture) { return Map.of("control.json", fixture.control(), "metadata.json", fixture.metadata(), "input.json", fixture.input()); }
    private void result(ExtractionUploadService.Result value, Map<String, byte[]> expected) throws Exception {
        var result = mapper.valueToTree(value);
        assertThat(result.path("schema_version").asText()).isEqualTo("extraction-upload-result-v1");
        assertThat(result.path("run_id").asText()).isEqualTo(RUN); assertThat(result.path("state").asText()).isEqualTo("staged");
        assertThat(result.path("expected_input_hash")).isEqualTo(mapper.readTree(expected.get("control.json")).path("expected_input_hash"));
        assertThat(result.path("review_required").asBoolean()).isTrue();
        var fields = new HashSet<String>(); result.fieldNames().forEachRemaining(fields::add);
        assertThat(fields).containsExactlyInAnyOrder("schema_version", "run_id", "expected_input_hash", "state", "received_files", "review_required");
        var artifacts = new TreeMap<String, JsonNode>();
        result.path("received_files").forEach(artifact -> assertThat(artifacts.put(artifact.path("name").asText(), artifact)).isNull());
        assertThat(artifacts.keySet()).containsExactlyInAnyOrderElementsOf(expected.keySet());
        for (var entry : expected.entrySet()) {
            assertThat(artifacts.get(entry.getKey()).path("size_bytes").asLong()).isEqualTo(entry.getValue().length);
            assertThat(artifacts.get(entry.getKey()).path("sha256").asText()).isEqualTo(sha(entry.getValue()));
        }
        assertThat(result.toString()).doesNotContain(temporary.toString(), "합성 수동 입력", "EXISTING SYNTHETIC PUBLIC CONTENT");
    }

    private void finalResult(LocalManagementService.Result value, byte[] control, String status, int attempts, boolean replay) throws Exception {
        JsonNode result = mapper.valueToTree(value);
        assertThat(result.path("schema_version").asText()).isEqualTo("local-management-result-v1");
        assertThat(result.path("request_sha256").asText()).isEqualTo(sha(control));
        assertThat(result.path("data").path("run_id").asText()).isEqualTo(RUN);
        assertThat(result.path("data").path("status").asText()).isEqualTo(status);
        assertThat(result.path("data").path("attempts").asInt()).isEqualTo(attempts);
        assertThat(result.path("data").path("already_registered").asBoolean()).isEqualTo(replay);
        assertThat(result.path("data").path("review_required").asBoolean()).isTrue();
    }

    private void originals(Fixture fixture, VerifiedExtraction verified) throws Exception {
        var expected = new TreeMap<String, byte[]>(); expected.put("input.json", fixture.input()); expected.put("metadata.json", fixture.metadata());
        for (int index = 0; index < fixture.outputs().size(); index++) {
            expected.put("attempt-" + (index + 1) + ".prompt", fixture.prompts().get(index));
            expected.put("attempt-" + (index + 1) + ".output", fixture.outputs().get(index));
        }
        assertThat(ExtractionArchiveReader.artifactNames(verified.receipt())).containsExactlyInAnyOrderElementsOf(expected.keySet());
        for (var entry : expected.entrySet()) {
            assertThat(Files.readAllBytes(verified.directory().resolve(entry.getKey()))).isEqualTo(entry.getValue());
            var artifact = verified.receipt().path("artifacts").path(entry.getKey());
            assertThat(artifact.path("size").asLong()).isEqualTo(entry.getValue().length);
            assertThat(artifact.path("sha256").asText()).isEqualTo(sha(entry.getValue()));
        }
    }

    private ApiException rejected(ThrowingCallable action, int status) {
        var thrown = catchThrowable(action); assertThat(thrown).isInstanceOf(ApiException.class);
        var error = (ApiException) thrown; assertThat(error.status().value()).isEqualTo(status);
        assertThat(error.getMessage()).doesNotContain(temporary.toString(), "SYNTHETIC CORRUPT RECEIPT", "합성 수동 입력", "EXISTING SYNTHETIC PUBLIC CONTENT");
        return error;
    }
    private byte[] control(String run, byte[] input) throws Exception { return bytes(" \n" + mapper.createObjectNode().put("schema_version", "extraction-import-request-v1").put("run_id", run).put("expected_input_hash", sha(input)) + "\n "); }
    private static byte[] bytes(String value) { return value.getBytes(StandardCharsets.UTF_8); }
    private byte[] append(byte[] value, String suffix) { return bytes(new String(value, StandardCharsets.UTF_8) + suffix); }
    private byte[] padded(byte[] value, int size) { byte[] result = Arrays.copyOf(value, size); Arrays.fill(result, value.length, size, (byte) ' '); return result; }
    private byte[] validOutput() throws Exception { return Files.readAllBytes(PythonProbe.REPO.resolve("contracts/examples/ai-extraction.json")); }
    private String sha(byte[] value) throws Exception { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value)); }
    private Path directory(Path path) throws Exception { return Files.createDirectory(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))).toRealPath(); }
    private Path file(Path path, byte[] value) throws Exception { Files.createFile(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------"))); return Files.write(path, value); }
    private Map<String, String> tree(Path root) throws Exception { var out = new TreeMap<String, String>(); try (var paths = Files.walk(root)) { for (Path path : paths.toList()) out.put(root.relativize(path).toString(), PosixFilePermissions.toString(Files.getPosixFilePermissions(path)) + ":" + (Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) ? sha(Files.readAllBytes(path)) : "directory")); } return out; }
    private String python() { Path configured = Path.of(PythonProbe.PYTHON); if (configured.isAbsolute()) return configured.toString(); for (String entry : System.getenv().getOrDefault("PATH", "").split(java.io.File.pathSeparator)) { Path candidate = Path.of(entry).resolve(configured); if (Files.isExecutable(candidate)) return candidate.toAbsolutePath().normalize().toString(); } throw new AssertionError("Set an available MYAI_PYTHON_EXECUTABLE"); }
    private record Fixture(byte[] control, byte[] metadata, byte[] input, List<byte[]> prompts, List<byte[]> outputs) { }
}
