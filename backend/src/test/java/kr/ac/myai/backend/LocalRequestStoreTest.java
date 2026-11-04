package kr.ac.myai.backend;

import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.local.LocalRequestStore;
import org.assertj.core.api.ThrowableAssert.ThrowingCallable;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.http.HttpStatus;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

class LocalRequestStoreTest {
    private static final byte[] CONTENT = " \n{\"schema_version\":\"store-synthetic\",\"note\":\"SYNTHETIC_PRIVATE_BODY 합성 🧪\"}\n".getBytes(StandardCharsets.UTF_8);
    @TempDir Path base;
    Path root;
    LocalRequestStore store;

    @BeforeEach
    void fixture() throws Exception {
        base = base.toRealPath();
        root = Files.createDirectory(base.resolve("requests"), PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        store = new LocalRequestStore(root.toString());
    }

    @Test
    void retainsOriginalBytesWithShaNameAndPrivateMode() throws Exception {
        Path file = store.retain(CONTENT);
        assertThat(file).isEqualTo(target(CONTENT));
        assertThat(Files.readAllBytes(file)).isEqualTo(CONTENT);
        assertThat(Files.getPosixFilePermissions(file)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
        assertThat(Files.getPosixFilePermissions(root)).isEqualTo(PosixFilePermissions.fromString("rwx------"));
        assertOnly(file);
    }

    @Test
    void whitespaceChangesProduceSeparateOriginalFiles() throws Exception {
        byte[] compact = "{\"value\":1}".getBytes(StandardCharsets.UTF_8);
        byte[] padded = " \n{\"value\":1}\n".getBytes(StandardCharsets.UTF_8);
        Path first = store.retain(compact), second = store.retain(padded);
        assertThat(first).isEqualTo(target(compact)).isNotEqualTo(second);
        assertThat(second).isEqualTo(target(padded));
        assertThat(Files.readAllBytes(first)).isEqualTo(compact);
        assertThat(Files.readAllBytes(second)).isEqualTo(padded);
        assertOnly(first, second);
    }

    @Test
    void identicalBytesReuseExistingFileWithoutFileOrDirectoryWrites() throws Exception {
        Path file = store.retain(CONTENT);
        FileTime stamp = FileTime.from(Instant.parse("2026-01-01T00:00:00Z"));
        Files.setLastModifiedTime(file, stamp);
        Files.setLastModifiedTime(root, stamp);
        assertThat(store.retain(CONTENT)).isEqualTo(file);
        assertThat(Files.getLastModifiedTime(file)).isEqualTo(stamp);
        assertThat(Files.getLastModifiedTime(root)).isEqualTo(stamp);
        assertThat(Files.readAllBytes(file)).isEqualTo(CONTENT);
        assertOnly(file);
    }

    @Test
    void storesOpaqueBytesWithoutRepeatingJsonValidation() throws Exception {
        byte[] opaque = {(byte) 0xff, 0, 1};
        Path file = store.retain(opaque);
        assertThat(file).isEqualTo(target(opaque));
        assertThat(Files.readAllBytes(file)).isEqualTo(opaque);
        assertOnly(file);
    }

    @Test
    void rejectsNullEmptyAndOversizeWithoutCreatingFiles() throws Exception {
        for (byte[] invalid : new byte[][] {null, new byte[0], new byte[8 * 1024 * 1024 + 1]}) {
            assertError(() -> store.retain(invalid), HttpStatus.UNPROCESSABLE_ENTITY, "LOCAL_API_VALIDATION_ERROR");
            assertOnly();
        }
    }

    @Test
    void acceptsExactlyEightMiBWithoutLeavingTemporaryFiles() throws Exception {
        byte[] content = new byte[8 * 1024 * 1024];
        Path file = store.retain(content);
        assertThat(file).isEqualTo(target(content));
        assertThat(Files.readAllBytes(file)).isEqualTo(content);
        assertThat(Files.getPosixFilePermissions(file)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
        assertOnly(file);
    }

    @Test
    void preservesConflictingExistingContentAndTimestamp() throws Exception {
        Path file = target(CONTENT);
        Files.writeString(file, "SYNTHETIC_EXISTING_CONTENT");
        Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("rw-------"));
        FileTime stamp = FileTime.from(Instant.parse("2026-01-01T00:00:00Z"));
        Files.setLastModifiedTime(file, stamp);
        assertError(() -> store.retain(CONTENT), HttpStatus.CONFLICT, "LOCAL_API_REQUEST_CONFLICT");
        assertThat(Files.readString(file)).isEqualTo("SYNTHETIC_EXISTING_CONTENT");
        assertThat(Files.getLastModifiedTime(file)).isEqualTo(stamp);
        assertThat(Files.getPosixFilePermissions(file)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
        assertOnly(file);
    }

    @Test
    void preservesDirectoryAtExpectedFileName() throws Exception {
        Path file = Files.createDirectory(target(CONTENT));
        Path nested = Files.writeString(file.resolve("canary"), "SYNTHETIC_UNRELATED");
        assertError(() -> store.retain(CONTENT), HttpStatus.CONFLICT, "LOCAL_API_REQUEST_CONFLICT");
        assertThat(Files.readString(nested)).isEqualTo("SYNTHETIC_UNRELATED");
        assertOnly(file);
    }

    @Test
    void rejectsExistingAndDanglingTargetSymlinksWithoutTouchingDestinations() throws Exception {
        Path unrelated = Files.writeString(base.resolve("unrelated"), "SYNTHETIC_UNRELATED");
        Path missing = base.resolve("missing");
        Path file = target(CONTENT);
        for (Path destination : List.of(unrelated, missing)) {
            Files.createSymbolicLink(file, destination);
            assertError(() -> store.retain(CONTENT), HttpStatus.CONFLICT, "LOCAL_API_REQUEST_CONFLICT");
            assertThat(Files.isSymbolicLink(file)).isTrue();
            assertThat(Files.readSymbolicLink(file)).isEqualTo(destination);
            assertThat(Files.readString(unrelated)).isEqualTo("SYNTHETIC_UNRELATED");
            assertThat(Files.exists(missing)).isFalse();
            assertOnly(file);
            Files.delete(file);
        }
    }

    @Test
    void rejectsExistingFileWithAnyModeOtherThan0600WithoutChangingIt() throws Exception {
        Path file = store.retain(CONTENT);
        for (String mode : List.of("rw-r--r--", "r--------", "rwx------")) {
            var permissions = PosixFilePermissions.fromString(mode);
            Files.setPosixFilePermissions(file, permissions);
            assertError(() -> store.retain(CONTENT), HttpStatus.CONFLICT, "LOCAL_API_REQUEST_CONFLICT");
            assertThat(Files.getPosixFilePermissions(file)).isEqualTo(permissions);
            assertThat(Files.readAllBytes(file)).isEqualTo(CONTENT);
            assertOnly(file);
        }
    }

    @Test
    void rejectsUnconfiguredRelativeMissingAndNonDirectoryRoots() throws Exception {
        Path file = Files.writeString(base.resolve("not-directory"), "SYNTHETIC_UNRELATED");
        for (String configured : new String[] {null, "", "requests", base.resolve("missing").toString(), file.toString()}) {
            assertError(() -> new LocalRequestStore(configured).retain(CONTENT), HttpStatus.INTERNAL_SERVER_ERROR, "LOCAL_API_IO_ERROR");
        }
        assertThat(Files.readString(file)).isEqualTo("SYNTHETIC_UNRELATED");
        assertThat(Files.exists(base.resolve("missing"))).isFalse();
        assertOnly();
    }

    @Test
    void rejectsRootWithAnyModeOtherThan0700WithoutChangingIt() throws Exception {
        try {
            for (String mode : List.of("rwxr-xr-x", "rwx--x---", "r-x------")) {
                var permissions = PosixFilePermissions.fromString(mode);
                Files.setPosixFilePermissions(root, permissions);
                assertError(() -> store.retain(CONTENT), HttpStatus.INTERNAL_SERVER_ERROR, "LOCAL_API_IO_ERROR");
                assertThat(Files.getPosixFilePermissions(root)).isEqualTo(permissions);
                assertOnly();
            }
        } finally { Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwx------")); }
    }

    @Test
    void rejectsRootSymlinkAndIntermediateSymlinkWithoutWriting() throws Exception {
        Path direct = Files.createSymbolicLink(base.resolve("direct"), root);
        Path intermediate = Files.createSymbolicLink(base.resolve("intermediate"), base);
        for (Path configured : List.of(direct, intermediate.resolve("requests"))) {
            assertError(() -> new LocalRequestStore(configured.toString()).retain(CONTENT), HttpStatus.INTERNAL_SERVER_ERROR, "LOCAL_API_IO_ERROR");
        }
        assertThat(Files.isSymbolicLink(direct)).isTrue();
        assertThat(Files.isSymbolicLink(intermediate)).isTrue();
        assertOnly();
    }

    @Test
    void checksRootAgainAfterConstructionAndPreservesItsReplacement() throws Exception {
        Path original = Files.move(root, base.resolve("original"));
        Files.createSymbolicLink(root, original);
        assertError(() -> store.retain(CONTENT), HttpStatus.INTERNAL_SERVER_ERROR, "LOCAL_API_IO_ERROR");
        assertThat(Files.isSymbolicLink(root)).isTrue();
        assertThat(Files.readSymbolicLink(root)).isEqualTo(original);
        try (var files = Files.list(original)) { assertThat(files.count()).isZero(); }
    }

    @Test
    void concurrentIdenticalBodiesInstallOneCompleteFileAndRemoveEveryTemporaryFile() throws Exception {
        var executor = Executors.newFixedThreadPool(4);
        var ready = new CountDownLatch(4);
        var start = new CountDownLatch(1);
        var futures = new ArrayList<Future<Path>>();
        try {
            for (int index = 0; index < 4; index++) futures.add(executor.submit(() -> {
                ready.countDown();
                start.await();
                Path file = store.retain(CONTENT);
                assertThat(Files.readAllBytes(file)).isEqualTo(CONTENT);
                return file;
            }));
            assertThat(ready.await(5, TimeUnit.SECONDS)).isTrue();
            start.countDown();
            for (var future : futures) assertThat(future.get(10, TimeUnit.SECONDS)).isEqualTo(target(CONTENT));
        } finally {
            start.countDown();
            executor.shutdownNow();
        }
        Path file = target(CONTENT);
        assertThat(Files.getPosixFilePermissions(file)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
        assertOnly(file);
    }

    private Path target(byte[] content) throws Exception {
        return root.resolve(HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(content)) + ".json");
    }

    private void assertOnly(Path... expected) throws Exception {
        try (var files = Files.list(root)) { assertThat(files.toList()).containsExactlyInAnyOrder(expected); }
    }

    private void assertError(ThrowingCallable action, HttpStatus status, String code) {
        assertThatThrownBy(action).isInstanceOfSatisfying(ApiException.class, error -> {
            assertThat(error.status()).isEqualTo(status);
            assertThat(error.code()).isEqualTo(code);
            assertThat(error.getMessage()).isNotBlank().containsPattern("[가-힣]")
                    .doesNotContain(base.toString(), "SYNTHETIC_PRIVATE_BODY", "SYNTHETIC_EXISTING_CONTENT", "SYNTHETIC_UNRELATED");
        });
    }
}
