package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.local.SourceUploadStore;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.charset.StandardCharsets;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.mockStatic;

class SourceUploadStoreTest {
    private static final String VERSION = "55555555-5555-4555-8555-555555555555";
    private static final byte[] META = ("{\"schema_version\":\"source-upload-v1\",\"format\":\"txt\","
            + "\"document_version_id\":\"" + VERSION + "\"}").getBytes(StandardCharsets.UTF_8);
    private static final byte[] RAW = "SYNTHETIC NOTICE".getBytes(StandardCharsets.UTF_8);
    private static final byte[] SOURCE = "{\"schema_version\":\"source-import-v1\"}".getBytes(StandardCharsets.UTF_8);
    private static final byte[] INPUT = "{\"blocks\":[]}".getBytes(StandardCharsets.UTF_8);
    private static final ObjectMapper JSON = new ObjectMapper();
    @TempDir Path temporary;
    private Path sources, requests;
    private SourceUploadStore store;

    @BeforeEach void setup() throws Exception {
        sources = Files.createDirectory(temporary.resolve("sources"), PosixFilePermissions.asFileAttribute(
                PosixFilePermissions.fromString("rwx------"))).toRealPath();
        requests = Files.createDirectory(temporary.resolve("requests"), PosixFilePermissions.asFileAttribute(
                PosixFilePermissions.fromString("rwx------"))).toRealPath();
        store = new SourceUploadStore(sources.toString(), requests.toString());
    }

    @Test void retainsOriginalBytesWithPrivatePermissionsAndReusesExactContent() throws Exception {
        Path raw = store.retainRaw(RAW, "txt");
        assertThat(raw).isEqualTo(sources.resolve("uploads/" + sha(RAW) + ".txt"));
        assertThat(Files.readAllBytes(raw)).isEqualTo(RAW);
        assertThat(Files.getPosixFilePermissions(raw)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
        assertThat(Files.getPosixFilePermissions(raw.getParent())).isEqualTo(PosixFilePermissions.fromString("rwx------"));
        var modified = Files.getLastModifiedTime(raw);
        assertThat(store.retainRaw(RAW, "txt")).isEqualTo(raw);
        assertThat(Files.getLastModifiedTime(raw)).isEqualTo(modified);
    }

    @Test void acceptsTwentyMiBRawButRejectsLargerAndUnsupportedFormats() throws Exception {
        byte[] large = new byte[20 * 1024 * 1024]; java.util.Arrays.fill(large, (byte) 'x');
        assertThat(Files.size(store.retainRaw(large, "txt"))).isEqualTo(20L * 1024 * 1024);
        rejected(() -> store.retainRaw(new byte[20 * 1024 * 1024 + 1], "txt"), 413);
        rejected(() -> store.retainRaw(RAW, "../txt"), 422);
        rejected(() -> store.retainRaw(new byte[0], "txt"), 422);
    }

    @Test void refusesExistingDifferentBytesLinksAndUnsafePermissionsWithoutOverwriting() throws Exception {
        Path raw = store.retainRaw(RAW, "txt");
        Files.writeString(raw, "different original");
        rejected(() -> store.retainRaw(RAW, "txt"), 409);
        assertThat(Files.readString(raw)).isEqualTo("different original");
        Files.delete(raw);
        Path outside = Files.writeString(temporary.resolve("outside"), "outside stays");
        Files.createSymbolicLink(raw, outside);
        rejected(() -> store.retainRaw(RAW, "txt"), 409);
        assertThat(Files.readString(outside)).isEqualTo("outside stays");
        Files.delete(raw); Files.write(raw, RAW);
        Files.setPosixFilePermissions(raw, PosixFilePermissions.fromString("rw-r--r--"));
        rejected(() -> store.retainRaw(RAW, "txt"), 409);
        assertThat(Files.readAllBytes(raw)).isEqualTo(RAW);
    }

    @Test void publishesOneCompleteReceiptAndReplaysTheOriginalPreparedBytes() throws Exception {
        store.retainRaw(RAW, "txt");
        assertThat(store.find(VERSION, META, RAW)).isNull();
        var first = store.commit(VERSION, META, SOURCE, INPUT, receipt(SOURCE, INPUT));
        var replay = store.find(VERSION, META, RAW);
        assertThat(first.sourceImport()).isEqualTo(SOURCE);
        assertThat(replay.sourceImport()).isEqualTo(SOURCE);
        assertThat(replay.aiInput()).isEqualTo(INPUT);
        assertThat(replay.receipt().path("preprocessing_version").asText()).isEqualTo("synthetic-policy-v1");
        byte[] changed = "{\"new_policy\":true}".getBytes(StandardCharsets.UTF_8);
        var original = store.commit(VERSION, META, changed, INPUT, receipt(changed, INPUT));
        assertThat(original.sourceImport()).isEqualTo(SOURCE);
        rejected(() -> store.find(VERSION, (new String(META, StandardCharsets.UTF_8) + " ").getBytes(StandardCharsets.UTF_8), RAW), 409);
        rejected(() -> store.find(VERSION, META, "other raw".getBytes(StandardCharsets.UTF_8)), 409);
        assertThat(store.find(VERSION, META, RAW).sourceImport()).isEqualTo(SOURCE);
    }

    @Test void concurrentSameVersionRequestsUseOneCompleteOriginalBundle() throws Exception {
        store.retainRaw(RAW, "txt");
        try (var workers = Executors.newVirtualThreadPerTaskExecutor()) {
            Callable<byte[]> commit = () -> store.commit(VERSION, META, SOURCE, INPUT, receipt(SOURCE, INPUT)).sourceImport();
            var results = workers.invokeAll(List.of(commit, commit, commit, commit));
            for (var result : results) assertThat(result.get()).isEqualTo(SOURCE);
        }
        assertThat(store.find(VERSION, META, RAW).aiInput()).isEqualTo(INPUT);
        try (var files = Files.walk(requests)) {
            for (Path file : files.filter(Files::isRegularFile).toList()) {
                assertThat(Files.getPosixFilePermissions(file)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
            }
        }
    }

    @Test void detectsTamperedPreparedBytesAndSourceWithoutRepairingThem() throws Exception {
        Path raw = store.retainRaw(RAW, "txt");
        store.commit(VERSION, META, SOURCE, INPUT, receipt(SOURCE, INPUT));
        Path prepared;
        try (var files = Files.walk(requests)) {
            prepared = files.filter(p -> p.getFileName().toString().equals("source-import.json")).findFirst().orElseThrow();
        }
        Files.writeString(prepared, "tampered");
        rejected(() -> store.find(VERSION, META, RAW), 409);
        assertThat(Files.readString(prepared)).isEqualTo("tampered");
        Files.write(prepared, SOURCE); Files.writeString(raw, "changed raw");
        rejected(() -> store.find(VERSION, META, RAW), 409);
        assertThat(Files.readString(raw)).isEqualTo("changed raw");
    }

    @Test void rejectsLinksAtTheReceiptAndConfiguredRoot() throws Exception {
        store.retainRaw(RAW, "txt");
        store.commit(VERSION, META, SOURCE, INPUT, receipt(SOURCE, INPUT));
        Path index = requests.resolve("uploads/" + VERSION + ".json");
        Files.delete(index);
        Path outside = Files.writeString(temporary.resolve("outside-index"), "outside");
        Files.createSymbolicLink(index, outside);
        rejected(() -> store.find(VERSION, META, RAW), 409);
        Path link = temporary.resolve("source-link"); Files.createSymbolicLink(link, sources);
        rejected(() -> new SourceUploadStore(link.toString(), requests.toString()).retainRaw(RAW, "txt"), 500);
        assertThat(Files.readString(outside)).isEqualTo("outside");
    }

    @Test void rejectsInvalidPreparedHashesBeforePublishingAReadyReceipt() throws Exception {
        store.retainRaw(RAW, "txt");
        var bad = (com.fasterxml.jackson.databind.node.ObjectNode) receipt(SOURCE, INPUT);
        bad.put("source_import_sha256", "0".repeat(64));
        rejected(() -> store.commit(VERSION, META, SOURCE, INPUT, bad), 422);
        assertThat(store.find(VERSION, META, RAW)).isNull();
        assertThat(Files.readAllBytes(sources.resolve("uploads/" + sha(RAW) + ".txt"))).isEqualTo(RAW);
    }

    @Test void partialBundleWriteFailureKeepsExistingOriginalAndAllowsAnExactRetry() throws Exception {
        Path raw = store.retainRaw(RAW, "txt");
        store.commit(VERSION, META, SOURCE, INPUT, receipt(SOURCE, INPUT));
        Path firstIndex = requests.resolve("uploads/" + VERSION + ".json");
        byte[] indexBytes = Files.readAllBytes(firstIndex);
        Path firstBundle = requests.resolve("uploads/bundles/" + JSON.readTree(indexBytes).path("bundle_id").asText());
        var firstFiles = new java.util.TreeMap<String, String>();
        for (String name : List.of("metadata.json", "source-import.json", "input.json", "receipt.json")) {
            firstFiles.put(name, sha(Files.readAllBytes(firstBundle.resolve(name))));
        }
        String nextVersion = "66666666-6666-4666-8666-666666666666";
        byte[] metadata = new String(META, StandardCharsets.UTF_8).replace(VERSION, nextVersion).getBytes(StandardCharsets.UTF_8);
        var nextReceipt = (com.fasterxml.jackson.databind.node.ObjectNode) receipt(SOURCE, INPUT);
        nextReceipt.put("document_version_id", nextVersion).put("metadata_sha256", sha(metadata));
        var writes = new AtomicInteger();
        try (var ignored = mockStatic(Files.class, call -> {
            if (call.getMethod().getName().equals("newByteChannel") && call.getArguments().length == 3
                    && call.getArgument(0) instanceof Path file && call.getArgument(1) instanceof Set<?> options
                    && options.contains(StandardOpenOption.CREATE_NEW)
                    && Set.of("metadata.json", "source-import.json", "input.json", "receipt.json").contains(file.getFileName().toString())
                    && writes.incrementAndGet() == 3) {
                assertThat(Files.readAllBytes(file.getParent().resolve("metadata.json"))).isEqualTo(metadata);
                assertThat(Files.readAllBytes(file.getParent().resolve("source-import.json"))).isEqualTo(SOURCE);
                throw new IOException("SYNTHETIC_PARTIAL_WRITE_FAILURE");
            }
            return call.callRealMethod();
        })) {
            assertThatThrownBy(() -> store.commit(nextVersion, metadata, SOURCE, INPUT, nextReceipt))
                    .isInstanceOfSatisfying(ApiException.class, error -> {
                        assertThat(error.status().value()).isEqualTo(500);
                        assertThat(error.code()).isEqualTo("SOURCE_UPLOAD_IO_ERROR");
                        assertThat(error.getMessage()).doesNotContain("SYNTHETIC_PARTIAL_WRITE_FAILURE", temporary.toString());
                    });
        }
        assertThat(writes.get()).isEqualTo(3);
        assertThat(requests.resolve("uploads/" + nextVersion + ".json")).doesNotExist();
        try (var bundles = Files.list(requests.resolve("uploads/bundles"))) { assertThat(bundles.toList()).containsExactly(firstBundle); }
        assertThat(Files.readAllBytes(raw)).isEqualTo(RAW);
        assertThat(Files.readAllBytes(firstIndex)).isEqualTo(indexBytes);
        for (var entry : firstFiles.entrySet()) assertThat(sha(Files.readAllBytes(firstBundle.resolve(entry.getKey())))).isEqualTo(entry.getValue());
        assertThat(store.find(VERSION, META, RAW).sourceImport()).isEqualTo(SOURCE);
        assertThat(store.find(nextVersion, metadata, RAW)).isNull();
        assertThat(store.commit(nextVersion, metadata, SOURCE, INPUT, nextReceipt).aiInput()).isEqualTo(INPUT);
        assertThat(Files.readAllBytes(firstIndex)).isEqualTo(indexBytes);
        for (var entry : firstFiles.entrySet()) assertThat(sha(Files.readAllBytes(firstBundle.resolve(entry.getKey())))).isEqualTo(entry.getValue());
    }

    private JsonNode receipt(byte[] source, byte[] input) throws Exception {
        return JSON.createObjectNode().put("schema_version", "source-upload-receipt-v1")
                .put("document_version_id", VERSION).put("metadata_sha256", sha(META)).put("raw_sha256", sha(RAW))
                .put("format", "txt").put("source_import_sha256", sha(source)).put("ai_input_sha256", sha(input))
                .put("preprocessing_version", "synthetic-policy-v1").put("text_scope", "provided_text")
                .put("text_review_required", false);
    }

    private String sha(byte[] bytes) throws Exception { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
    private void rejected(org.assertj.core.api.ThrowableAssert.ThrowingCallable action, int status) {
        assertThatThrownBy(action).isInstanceOfSatisfying(ApiException.class,
                ex -> assertThat(ex.status().value()).isEqualTo(status));
    }
}
