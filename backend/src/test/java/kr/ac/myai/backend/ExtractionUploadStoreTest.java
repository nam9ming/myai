package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.local.ExtractionUploadStore;
import org.assertj.core.api.ThrowableAssert.ThrowingCallable;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.Callable;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.mockStatic;

class ExtractionUploadStoreTest {
    private static final String RUN = "71fb66f0-e610-4f9c-8f26-4bb77655ee8c";
    private static final String OTHER_RUN = "66666666-6666-4666-8666-666666666666";
    private static final Set<String> INITIAL_NAMES = Set.of("control.json", "metadata.json", "input.json");
    private static final ObjectMapper JSON = new ObjectMapper();
    @TempDir Path temporary;
    Path root;
    byte[] input;
    Fixture fixture;
    ExtractionUploadStore store;

    @BeforeEach void setup() throws Exception {
        temporary = temporary.toRealPath();
        root = Files.createDirectory(temporary.resolve("requests"), PosixFilePermissions.asFileAttribute(
                PosixFilePermissions.fromString("rwx------")));
        input = Files.readAllBytes(Path.of("../contracts/examples/ai-input.json"));
        fixture = packet(RUN, 3, input);
        store = instance(root);
    }

    @Test void initializesExactOriginalsWithPublicDescriptorsAndPrivateModes() throws Exception {
        assertThat(store.find(RUN)).isEmpty();
        var staged = initialize(store, fixture);
        assertThat(staged.runId()).isEqualTo(RUN);
        assertThat(staged.expectedInputHash()).isEqualTo(sha(input));
        assertThat(staged.attempts()).isEqualTo(3);
        assertThat(staged.control()).isEqualTo(fixture.control());
        assertThat(staged.directory()).isAbsolute().startsWith(root.resolve("extraction-uploads"));
        originals(staged, initial(fixture));
        privateModes();
    }

    @Test void exactInitializationReusesTheFirstBundleAcrossInstancesWithoutChangingOriginals() throws Exception {
        var first = initialize(store, fixture); var before = tree(root);
        var repeated = initialize(instance(root), fixture);
        assertThat(repeated.directory()).isEqualTo(first.directory());
        assertThat(repeated.control()).isEqualTo(fixture.control());
        assertThat(instance(root).find(RUN)).isPresent();
        originals(repeated, initial(fixture));
        assertThat(tree(root)).isEqualTo(before);
    }

    @Test void differentInitialBytesOrDeclaredAttemptsConflictWithoutChangingTheFirstBundle() throws Exception {
        var first = initialize(store, fixture); var before = tree(root);
        rejected(() -> store.initialize(RUN, fixture.hash(), 3, append(fixture.control(), " "), fixture.metadata(), input), 409);
        rejected(() -> store.initialize(RUN, fixture.hash(), 3, fixture.control(), append(fixture.metadata(), " "), input), 409);
        var changedInput = packet(RUN, 3, append(input, " "));
        rejected(() -> initialize(store, changedInput), 409);
        rejected(() -> initialize(store, packet(RUN, 2, input)), 409);
        originals(store.find(RUN).orElseThrow(), initial(fixture));
        assertThat(store.find(RUN).orElseThrow().directory()).isEqualTo(first.directory());
        assertThat(tree(root)).isEqualTo(before);
    }

    @Test void initialLimitsAcceptTheirBoundariesAndRejectEmptyOrLargerInputsBeforePublishing() throws Exception {
        var large = packet(RUN, 1, padded(input, 8 * 1024 * 1024));
        var control = padded(large.control(), 64 * 1024); var metadata = padded(large.metadata(), 64 * 1024);
        var staged = store.initialize(RUN, large.hash(), 1, control, metadata, large.input());
        originals(staged, Map.of("control.json", control, "metadata.json", metadata, "input.json", large.input()));
        var next = packet(OTHER_RUN, 1, input); var before = tree(root);
        for (byte[] empty : new byte[][] {null, new byte[0]}) {
            rejected(() -> store.initialize(OTHER_RUN, next.hash(), 1, empty, next.metadata(), input), 422);
            rejected(() -> store.initialize(OTHER_RUN, next.hash(), 1, next.control(), empty, input), 422);
            rejected(() -> store.initialize(OTHER_RUN, next.hash(), 1, next.control(), next.metadata(), empty), 422);
        }
        rejected(() -> store.initialize(OTHER_RUN, next.hash(), 1, padded(next.control(), 64 * 1024 + 1), next.metadata(), input), 413);
        rejected(() -> store.initialize(OTHER_RUN, next.hash(), 1, next.control(), padded(next.metadata(), 64 * 1024 + 1), input), 413);
        var oversized = packet(OTHER_RUN, 1, padded(input, 8 * 1024 * 1024 + 1));
        rejected(() -> initialize(store, oversized), 413);
        assertThat(store.find(OTHER_RUN)).isEmpty(); assertThat(tree(root)).isEqualTo(before);
    }

    @Test void invalidIdsHashesAndAttemptCountsCannotCreateStaging() throws Exception {
        for (String run : new String[] {null, "../escape", "not-a-uuid"})
            rejected(() -> store.initialize(run, fixture.hash(), 3, fixture.control(), fixture.metadata(), input), 422);
        for (String hash : new String[] {null, "../escape", "f".repeat(63), "F".repeat(64)})
            rejected(() -> store.initialize(RUN, hash, 3, fixture.control(), fixture.metadata(), input), 422);
        for (int attempts : new int[] {0, 4})
            rejected(() -> store.initialize(RUN, fixture.hash(), attempts, fixture.control(), fixture.metadata(), input), 422);
        var mismatched = packet(RUN, 1, append(input, " "));
        rejected(() -> store.initialize(RUN, mismatched.hash(), 1, mismatched.control(), mismatched.metadata(), input), 422);
        assertThat(store.find(RUN)).isEmpty();
    }

    @Test void emptyAndInvalidUtf8SlotsRemainOpaqueAndAllThreePairsKeepExactBytes() throws Exception {
        initialize(store, fixture);
        byte[] invalid = {(byte) 0xff, 0, (byte) 0x80};
        var expected = new TreeMap<>(initial(fixture));
        put(1, "prompt", new byte[0], expected); put(1, "output", invalid, expected);
        put(2, "prompt", invalid, expected); put(2, "output", new byte[0], expected);
        byte[] maximumPrompt = new byte[20 * 1024 * 1024]; Arrays.fill(maximumPrompt, (byte) 'p');
        byte[] maximumOutput = new byte[5 * 1024 * 1024]; Arrays.fill(maximumOutput, (byte) 0xff);
        put(3, "output", maximumOutput, expected); put(3, "prompt", maximumPrompt, expected);
        var ready = store.ready(RUN, fixture.hash()); originals(ready, expected);
        var before = tree(root);
        rejected(() -> store.put(RUN, 3, "prompt", new byte[20 * 1024 * 1024 + 1]), 413);
        rejected(() -> store.put(RUN, 3, "output", new byte[5 * 1024 * 1024 + 1]), 413);
        assertThat(tree(root)).isEqualTo(before); privateModes();
    }

    @Test void slotsAreExclusiveAndLimitedToTheDeclaredFixedNamesAndAttempts() throws Exception {
        var one = packet(RUN, 1, input); initialize(store, one);
        byte[] prompt = bytes("SYNTHETIC PRIVATE PROMPT");
        store.put(RUN, 1, "prompt", prompt); var before = tree(root);
        store.put(RUN, 1, "prompt", prompt);
        rejected(() -> store.put(RUN, 1, "prompt", bytes("DIFFERENT PROMPT")), 409);
        for (int attempt : new int[] {0, 2, 4}) rejected(() -> store.put(RUN, attempt, "output", new byte[0]), 422);
        for (String name : new String[] {null, "../output", "input.json", "receipt", "OUTPUT"})
            rejected(() -> store.put(RUN, 1, name, new byte[0]), 422);
        rejected(() -> store.put(RUN, 1, "output", null), 422);
        assertThat(tree(root)).isEqualTo(before);
        assertThat(Files.readAllBytes(store.find(RUN).orElseThrow().directory().resolve("attempt-1.prompt"))).isEqualTo(prompt);
    }

    @Test void readyRequiresEveryDeclaredPairAndTheOriginalInputHashWithoutWriting() throws Exception {
        rejected(() -> store.ready(RUN, fixture.hash()), 404);
        rejected(() -> store.put(RUN, 1, "output", new byte[0]), 404);
        initialize(store, fixture);
        var expected = new TreeMap<>(initial(fixture));
        for (int attempt = 3; attempt >= 1; attempt--) {
            var before = tree(root); rejected(() -> store.ready(RUN, fixture.hash()), 422);
            assertThat(tree(root)).isEqualTo(before);
            put(attempt, "output", bytes("not valid result JSON: " + attempt), expected);
            rejected(() -> store.ready(RUN, fixture.hash()), 422);
            put(attempt, "prompt", bytes("manual prompt " + attempt), expected);
        }
        var before = tree(root);
        rejected(() -> store.ready(RUN, "0".repeat(64)), 409);
        originals(store.ready(RUN, fixture.hash()), expected);
        assertThat(tree(root)).isEqualTo(before);
    }

    @Test void twoInstancesInstallOneInitialBundleAndConflictingInitialBytesHaveOneWinner() throws Exception {
        var left = instance(root); var right = instance(root);
        var results = race(() -> initialize(left, fixture), () -> initialize(right, fixture));
        var first = (ExtractionUploadStore.Staged) results.get(0); var second = (ExtractionUploadStore.Staged) results.get(1);
        assertThat(second.directory()).isEqualTo(first.directory()); originals(first, initial(fixture));
        try (var paths = Files.walk(root)) {
            assertThat(paths.filter(path -> path.getFileName().toString().equals("control.json")).count()).isEqualTo(1);
        }
        var other = packet(OTHER_RUN, 1, input);
        var conflicting = new Fixture(other.run(), other.hash(), 1, append(other.control(), " "), other.metadata(), input);
        var conflict = race(() -> initialize(left, other), () -> initialize(right, conflicting));
        assertThat(conflict.stream().filter(value -> value instanceof ExtractionUploadStore.Staged).count()).isEqualTo(1);
        assertThat(conflict.stream().filter(value -> value instanceof ApiException ex && ex.status().value() == 409).count()).isEqualTo(1);
        var winner = (ExtractionUploadStore.Staged) conflict.stream().filter(value -> value instanceof ExtractionUploadStore.Staged).findFirst().orElseThrow();
        assertThat(instance(root).find(OTHER_RUN).orElseThrow().control()).isEqualTo(winner.control());
        originals(instance(root).find(RUN).orElseThrow(), initial(fixture));
    }

    @Test void twoInstancesReuseIdenticalSlotsAndPreserveOneWinnerForDifferentBytes() throws Exception {
        var one = packet(RUN, 1, input); initialize(store, one);
        var left = instance(root); var right = instance(root); byte[] prompt = bytes("SYNTHETIC PROMPT");
        for (var result : race(() -> left.put(RUN, 1, "prompt", prompt), () -> right.put(RUN, 1, "prompt", prompt)))
            assertThat(result).isInstanceOf(ExtractionUploadStore.Staged.class);
        byte[] a = {(byte) 0xff}, b = bytes("not-json");
        var results = race(() -> left.put(RUN, 1, "output", a), () -> right.put(RUN, 1, "output", b));
        assertThat(results.stream().filter(value -> value instanceof ExtractionUploadStore.Staged).count()).isEqualTo(1);
        assertThat(results.stream().filter(value -> value instanceof ApiException ex && ex.status().value() == 409).count()).isEqualTo(1);
        byte[] winner = results.get(0) instanceof ExtractionUploadStore.Staged ? a : b;
        var expected = new TreeMap<>(initial(one)); expected.put("attempt-1.prompt", prompt); expected.put("attempt-1.output", winner);
        originals(instance(root).ready(RUN, one.hash()), expected); privateModes();
    }

    @Test void aSlotPublishedDuringFindDoesNotTurnAValidRunIntoAConflict() throws Exception {
        var one = packet(RUN, 1, input); var staged = initialize(store, one);
        byte[] prompt = bytes("PROMPT"), output = bytes("OUTPUT");
        store.put(RUN, 1, "prompt", prompt);
        Path target = staged.directory().resolve("attempt-1.output");
        var published = new AtomicBoolean(); var writer = instance(root);
        try (var workers = Executors.newVirtualThreadPerTaskExecutor();
             var ignored = mockStatic(Files.class, call -> {
                 Object result = call.callRealMethod();
                 if (call.getMethod().getName().equals("exists") && target.equals(call.getArgument(0))
                         && Boolean.FALSE.equals(result) && published.compareAndSet(false, true))
                     workers.submit(() -> writer.put(RUN, 1, "output", output)).get(10, TimeUnit.SECONDS);
                 return result;
             })) {
            assertThat(store.find(RUN)).isPresent();
        }
        assertThat(published).isTrue();
        var expected = new TreeMap<>(initial(one)); expected.put("attempt-1.prompt", prompt); expected.put("attempt-1.output", output);
        originals(store.ready(RUN, one.hash()), expected);
    }

    @Test void slotIntegrityWriteFailurePreservesInstalledBytesForAnExactRetry() throws Exception {
        var one = packet(RUN, 1, input); var staged = initialize(store, one);
        byte[] prompt = bytes("PROMPT"), output = {(byte) 0xff, 0};
        store.put(RUN, 1, "prompt", prompt);
        Path target = staged.directory().resolve("attempt-1.output"); var injected = new AtomicBoolean();
        try (var ignored = mockStatic(Files.class, call -> {
            if (call.getMethod().getName().equals("createLink") && call.getArgument(0) instanceof Path record
                    && record.getParent().equals(staged.directory()) && !record.equals(target)
                    && Files.isRegularFile(target, LinkOption.NOFOLLOW_LINKS) && injected.compareAndSet(false, true)) {
                assertThat(Files.readAllBytes(target)).isEqualTo(output);
                throw new IOException("SYNTHETIC_SLOT_RECORD_IO_FAILURE");
            }
            return call.callRealMethod();
        })) {
            rejected(() -> store.put(RUN, 1, "output", output), 500);
        }
        assertThat(injected).isTrue(); assertThat(Files.readAllBytes(target)).isEqualTo(output);
        rejected(() -> store.ready(RUN, one.hash()), 422);
        rejected(() -> store.put(RUN, 1, "output", bytes("DIFFERENT OUTPUT")), 409);
        store.put(RUN, 1, "output", output);
        var expected = new TreeMap<>(initial(one)); expected.put("attempt-1.prompt", prompt); expected.put("attempt-1.output", output);
        originals(store.ready(RUN, one.hash()), expected);
    }

    @Test void storedPayloadTamperingIsRejectedWithoutRepairOrLossOfTheRemainingOriginals() throws Exception {
        var one = packet(RUN, 1, input); initialize(store, one);
        var expected = new TreeMap<>(initial(one)); put(1, "prompt", bytes("PROMPT"), expected); put(1, "output", bytes("OUTPUT"), expected);
        Path directory = store.ready(RUN, one.hash()).directory();
        for (var entry : expected.entrySet()) {
            Path file = directory.resolve(entry.getKey()); byte[] changed = bytes("SYNTHETIC TAMPER");
            Files.write(file, changed); var before = tree(root);
            rejected(() -> store.ready(RUN, one.hash()), 409);
            assertThat(tree(root)).isEqualTo(before); assertThat(Files.readAllBytes(file)).isEqualTo(changed);
            Files.write(file, entry.getValue());
            originals(store.ready(RUN, one.hash()), expected);
        }
        Path extra = Files.writeString(directory.resolve("attempt-2.output"), "UNDECLARED OUTPUT");
        Files.setPosixFilePermissions(extra, PosixFilePermissions.fromString("rw-------"));
        var before = tree(root); rejected(() -> store.ready(RUN, one.hash()), 409);
        assertThat(tree(root)).isEqualTo(before);
    }

    @Test void persistedFileLinksAndUnsafePermissionsIncludingGeneratedFilesAreRejectedWithoutRepair() throws Exception {
        var one = packet(RUN, 1, input); initialize(store, one);
        store.put(RUN, 1, "prompt", bytes("PROMPT")); store.put(RUN, 1, "output", bytes("OUTPUT"));
        Path outside = Files.writeString(temporary.resolve("outside"), "OUTSIDE STAYS");
        List<Path> files;
        try (var paths = Files.walk(root)) { files = paths.filter(path -> Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)).toList(); }
        for (Path file : files) {
            byte[] original = Files.readAllBytes(file);
            Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("rw-r--r--"));
            rejected(() -> store.ready(RUN, one.hash()), 409);
            assertThat(Files.getPosixFilePermissions(file)).isEqualTo(PosixFilePermissions.fromString("rw-r--r--"));
            Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("rw-------"));
            Files.delete(file); Files.createSymbolicLink(file, outside);
            rejected(() -> store.ready(RUN, one.hash()), 409);
            assertThat(Files.isSymbolicLink(file)).isTrue(); assertThat(Files.readString(outside)).isEqualTo("OUTSIDE STAYS");
            Files.delete(file); Files.write(file, original, StandardOpenOption.CREATE_NEW);
            Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("rw-------"));
            assertThat(store.ready(RUN, one.hash()).runId()).isEqualTo(RUN);
        }
        Path directory = store.ready(RUN, one.hash()).directory();
        Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("rwxr-xr-x"));
        rejected(() -> store.ready(RUN, one.hash()), 409);
        assertThat(Files.getPosixFilePermissions(directory)).isEqualTo(PosixFilePermissions.fromString("rwxr-xr-x"));
        Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("rwx------"));
        Path moved = Files.move(directory, temporary.resolve("moved-bundle")); var preserved = tree(moved);
        Files.createSymbolicLink(directory, moved);
        rejected(() -> store.ready(RUN, one.hash()), 409);
        assertThat(Files.isSymbolicLink(directory)).isTrue(); assertThat(tree(moved)).isEqualTo(preserved);
    }

    @Test void invalidRootsIntermediateLinksAndRootReplacementCannotReadOrWriteThroughThem() throws Exception {
        Path outside = Files.writeString(temporary.resolve("not-directory"), "OUTSIDE STAYS");
        Path direct = Files.createSymbolicLink(temporary.resolve("source-link"), root);
        Path intermediate = Files.createSymbolicLink(temporary.resolve("parent-link"), temporary);
        for (String configured : new String[] {null, "", "relative", temporary.resolve("missing").toString(), outside.toString(),
                direct.toString(), intermediate.resolve("requests").toString()})
            rejected(() -> initialize(new ExtractionUploadStore(configured, new ReviewedImportReader()), fixture), 500);
        Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwxr-xr-x"));
        try { rejected(() -> initialize(store, fixture), 500); }
        finally { Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwx------")); }
        initialize(store, fixture); var before = tree(root);
        Path original = Files.move(root, temporary.resolve("original-requests")); Files.createSymbolicLink(root, original);
        rejected(() -> store.find(RUN), 500);
        assertThat(tree(original)).isEqualTo(before); assertThat(Files.isSymbolicLink(root)).isTrue();
        assertThat(Files.readString(outside)).isEqualTo("OUTSIDE STAYS");
    }

    @Test void failureAfterTwoCompleteInitialFilesPublishesNothingAndKeepsExistingOriginalsForRetry() throws Exception {
        var existing = initialize(store, fixture); var before = tree(root);
        var next = packet(OTHER_RUN, 1, input); var wanted = initial(next);
        var injected = new AtomicBoolean(); var completed = new AtomicInteger();
        Set<String> writes = Set.of("newByteChannel", "newOutputStream", "write", "writeString", "createFile", "createLink", "copy", "move");
        try (var ignored = mockStatic(Files.class, call -> {
            if (!injected.get() && writes.contains(call.getMethod().getName())
                    && (!call.getMethod().getName().equals("newByteChannel")
                    || Arrays.stream(call.getRawArguments()).anyMatch(argument ->
                    argument instanceof Set<?> options && options.contains(StandardOpenOption.WRITE)
                    || argument instanceof OpenOption[] optionArray && Arrays.asList(optionArray).contains(StandardOpenOption.WRITE)))) {
                for (Object argument : call.getArguments()) if (argument instanceof Path file
                        && file.startsWith(root) && INITIAL_NAMES.contains(file.getFileName().toString())) {
                    int done = 0;
                    for (var entry : wanted.entrySet()) {
                        Path sibling = file.getParent().resolve(entry.getKey());
                        if (Files.isRegularFile(sibling, LinkOption.NOFOLLOW_LINKS)
                                && Arrays.equals(Files.readAllBytes(sibling), entry.getValue())) done++;
                    }
                    if (done == 2) {
                        completed.set(done); injected.set(true);
                        throw new IOException("SYNTHETIC_TWO_FILES_IO_FAILURE");
                    }
                }
            }
            return call.callRealMethod();
        })) {
            rejected(() -> initialize(store, next), 500);
        }
        assertThat(injected).isTrue(); assertThat(completed).hasValue(2);
        assertThat(store.find(OTHER_RUN)).isEmpty(); assertThat(tree(root)).isEqualTo(before);
        assertThat(store.find(RUN).orElseThrow().directory()).isEqualTo(existing.directory());
        originals(store.find(RUN).orElseThrow(), initial(fixture));
        originals(initialize(store, next), initial(next));
        originals(store.find(RUN).orElseThrow(), initial(fixture));
    }

    private ExtractionUploadStore instance(Path path) { return new ExtractionUploadStore(path.toString(), new ReviewedImportReader()); }
    private ExtractionUploadStore.Staged initialize(ExtractionUploadStore selected, Fixture data) { return selected.initialize(data.run(), data.hash(), data.attempts(), data.control(), data.metadata(), data.input()); }
    private void put(int attempt, String artifact, byte[] content, Map<String, byte[]> expected) { store.put(RUN, attempt, artifact, content); expected.put("attempt-" + attempt + "." + artifact, content); }
    private Map<String, byte[]> initial(Fixture data) { return Map.of("control.json", data.control(), "metadata.json", data.metadata(), "input.json", data.input()); }

    private Fixture packet(String run, int attempts, byte[] content) throws Exception {
        var metadata = (ObjectNode) JSON.readTree(Path.of("../processing/examples/extraction-metadata.json").toFile());
        metadata.put("run_id", run).put("attempts", attempts);
        String hash = sha(content);
        byte[] control = bytes(" \n" + JSON.createObjectNode().put("schema_version", "extraction-import-request-v1")
                .put("run_id", run).put("expected_input_hash", hash) + "\n");
        return new Fixture(run, hash, attempts, control, bytes(metadata.toString()), content);
    }

    private void originals(ExtractionUploadStore.Staged staged, Map<String, byte[]> expected) throws Exception {
        var artifacts = new TreeMap<String, ExtractionUploadStore.Artifact>();
        for (var artifact : staged.artifacts()) assertThat(artifacts.put(artifact.name(), artifact)).isNull();
        assertThat(artifacts.keySet()).containsExactlyInAnyOrderElementsOf(expected.keySet());
        for (var entry : expected.entrySet()) {
            assertThat(Files.readAllBytes(staged.directory().resolve(entry.getKey()))).isEqualTo(entry.getValue());
            assertThat(artifacts.get(entry.getKey()).sizeBytes()).isEqualTo(entry.getValue().length);
            assertThat(artifacts.get(entry.getKey()).sha256()).isEqualTo(sha(entry.getValue()));
        }
    }

    private List<Object> race(Callable<ExtractionUploadStore.Staged> a, Callable<ExtractionUploadStore.Staged> b) throws Exception {
        var barrier = new CyclicBarrier(2);
        try (var workers = Executors.newVirtualThreadPerTaskExecutor()) {
            var results = new ArrayList<java.util.concurrent.Future<Object>>();
            for (var operation : List.of(a, b)) results.add(workers.submit(() -> {
                barrier.await(5, TimeUnit.SECONDS);
                try { return operation.call(); } catch (ApiException error) { return error; }
            }));
            return List.of(results.get(0).get(15, TimeUnit.SECONDS), results.get(1).get(15, TimeUnit.SECONDS));
        }
    }

    private Map<String, String> tree(Path selected) throws Exception {
        var result = new TreeMap<String, String>();
        try (var paths = Files.walk(selected)) { for (Path path : paths.toList()) {
            String mode = PosixFilePermissions.toString(Files.getPosixFilePermissions(path, LinkOption.NOFOLLOW_LINKS));
            String key = String.valueOf(Files.readAttributes(path, java.nio.file.attribute.BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS).fileKey());
            result.put(selected.relativize(path).toString(), mode + "|" + key + (Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) ? "|" + sha(Files.readAllBytes(path)) : ""));
        } }
        return result;
    }

    private void privateModes() throws Exception { try (var paths = Files.walk(root)) { for (Path path : paths.toList()) assertThat(PosixFilePermissions.toString(Files.getPosixFilePermissions(path))).isEqualTo(Files.isDirectory(path) ? "rwx------" : "rw-------"); } }
    private void rejected(ThrowingCallable action, int status) { assertThatThrownBy(action).isInstanceOfSatisfying(ApiException.class, error -> { assertThat(error.status().value()).isEqualTo(status); assertThat(error.getMessage()).doesNotContain(temporary.toString(), "SYNTHETIC_TWO_FILES_IO_FAILURE", "SYNTHETIC PRIVATE PROMPT"); }); }
    private static byte[] bytes(String value) { return value.getBytes(StandardCharsets.UTF_8); }
    private byte[] append(byte[] value, String suffix) { return bytes(new String(value, StandardCharsets.UTF_8) + suffix); }
    private byte[] padded(byte[] value, int size) { byte[] result = Arrays.copyOf(value, size); Arrays.fill(result, value.length, size, (byte) ' '); return result; }
    private String sha(byte[] value) throws Exception { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value)); }
    private record Fixture(String run, String hash, int attempts, byte[] control, byte[] metadata, byte[] input) { }
}
