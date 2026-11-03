package kr.ac.myai.backend;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.Map;

import static org.assertj.core.api.Assertions.*;

@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class RecoveryDatabaseTest {
    @TempDir Path root;

    @Test
    void shouldRestoreUnicodeAndNullIntoFreshDatabaseAndRejectOccupiedTarget() throws Exception {
        Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwx------"));
        Path dump = root.resolve("synthetic.sql");
        var ids = new ArrayList<String>();
        try (var source = RecoveryDatabase.start(root); var target = RecoveryDatabase.start(root)) {
            ids.addAll(List.of(source.id(), target.id()));
            assertThat(source.id()).isNotEqualTo(target.id());
            assertThat(source.url()).startsWith("jdbc:mysql://127.0.0.1:").contains("/myai_recovery?");
            assertThat(source.jdbc().queryForObject("SELECT DATABASE()", String.class)).isEqualTo("myai_recovery");
            source.jdbc().execute("CREATE TABLE recovery_probe (id INT PRIMARY KEY, content LONGTEXT, unknown_value VARCHAR(40)) CHARACTER SET utf8mb4");
            source.jdbc().update("INSERT INTO recovery_probe VALUES (?, ?, ?)", 1, "합성 원문 😀\n줄바꿈", null);
            source.jdbc().update("INSERT INTO recovery_probe VALUES (?, ?, ?)", 2, "null 아님", "보존");
            List<Map<String, Object>> before = source.jdbc().queryForList("SELECT * FROM recovery_probe ORDER BY id");
            try (var files = Files.list(root)) {
                var credentials = files.filter(p -> p.getFileName().toString().endsWith(".env")).toList();
                assertThat(credentials).hasSize(2);
                for (var file : credentials)
                    assertThat(Files.getPosixFilePermissions(file)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
            }
            Path dataBefore = root.resolve("data-before.sql");
            source.dumpData(dataBefore);
            byte[] data = Files.readAllBytes(dataBefore);
            assertThat(Files.readString(dataBefore)).contains("INSERT INTO `recovery_probe`").doesNotContain("CREATE TABLE", source.password(), target.password());
            assertThat(Files.getPosixFilePermissions(dataBefore)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
            assertThatThrownBy(() -> source.dumpData(dataBefore)).isInstanceOf(IllegalArgumentException.class);
            assertThat(Files.readAllBytes(dataBefore)).isEqualTo(data);
            source.dump(dump);
            assertThat(Files.getPosixFilePermissions(dump)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
            assertThat(Files.readString(dump)).doesNotContain(source.password(), target.password());
            byte[] original = Files.readAllBytes(dump);
            assertThatThrownBy(() -> source.dump(dump)).isInstanceOf(IllegalArgumentException.class);
            assertThat(Files.readAllBytes(dump)).isEqualTo(original);
            target.restore(dump);
            Path dataAfter = root.resolve("data-after.sql");
            target.dumpData(dataAfter);
            assertThat(Files.readAllBytes(dataAfter)).isEqualTo(data);
            assertThat(Files.getPosixFilePermissions(dataAfter)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
            assertThatThrownBy(() -> target.dumpData(dataAfter)).isInstanceOf(IllegalArgumentException.class);
            assertThat(Files.readAllBytes(dataAfter)).isEqualTo(data);
            System.out.println("recovery data-before SHA-256=" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(data)));
            System.out.println("recovery data-after SHA-256=" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(dataAfter))));
            assertThat(target.jdbc().queryForList("SELECT * FROM recovery_probe ORDER BY id")).isEqualTo(before);
            assertThatThrownBy(() -> target.restore(dump)).isInstanceOf(IllegalStateException.class).hasMessageContaining("empty");
            assertThat(target.jdbc().queryForList("SELECT * FROM recovery_probe ORDER BY id")).isEqualTo(before);
        }
        for (String id : ids) assertThat(docker("container", "ls", "--all", "--no-trunc", "--filter", "id=" + id, "--format", "{{.ID}}")).isEmpty();
        try (var files = Files.list(root)) {
            assertThat(files.filter(p -> p.getFileName().toString().endsWith(".env"))).isEmpty();
        }
    }

    @Test
    void shouldReportSqlFailureAfterPartialDdlAndDiscardTargetOnClose() throws Exception {
        Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwx------"));
        Path invalid = root.resolve("invalid.sql");
        Files.writeString(invalid, "CREATE TABLE partial_probe (id INT PRIMARY KEY);\nINSERT INTO partial_probe VALUES (7);\nTHIS IS INVALID SQL;\n");
        Files.setPosixFilePermissions(invalid, PosixFilePermissions.fromString("rw-------"));
        String id;
        try (var target = RecoveryDatabase.start(root)) {
            id = target.id();
            assertThatThrownBy(() -> target.restore(invalid)).isInstanceOf(IllegalStateException.class).hasMessageContaining("failed");
            // MySQL DDL은 부분 적용될 수 있어 실패 대상은 재사용하지 않고 close로 폐기한다.
            assertThat(target.jdbc().queryForObject("SELECT id FROM partial_probe", Integer.class)).isEqualTo(7);
            assertThatThrownBy(() -> target.restore(invalid)).isInstanceOf(IllegalStateException.class).hasMessageContaining("empty");
        }
        assertThat(docker("container", "ls", "--all", "--no-trunc", "--filter", "id=" + id, "--format", "{{.ID}}")).isEmpty();
    }

    @Test
    void shouldRefuseOperationsWhenOwnedContainerNameChanges() throws Exception {
        Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwx------"));
        Path dump = root.resolve("empty.sql");
        Files.writeString(dump, "SELECT 1;\n");
        try (var target = RecoveryDatabase.start(root)) {
            String original = docker("inspect", "--format", "{{.Name}}", target.id()).substring(1);
            docker("rename", target.id(), "myai-recovery-renamed-" + UUID.randomUUID());
            try {
                assertThatThrownBy(() -> target.dump(root.resolve("refused.sql"))).isInstanceOf(IllegalStateException.class).hasMessageContaining("ownership");
                assertThatThrownBy(() -> target.dumpData(root.resolve("refused-data.sql"))).isInstanceOf(IllegalStateException.class).hasMessageContaining("ownership");
                assertThatThrownBy(() -> target.restore(dump)).isInstanceOf(IllegalStateException.class).hasMessageContaining("ownership");
                assertThatThrownBy(target::close).isInstanceOf(IllegalStateException.class).hasMessageContaining("ownership");
                assertThat(docker("container", "ls", "--all", "--no-trunc", "--filter", "id=" + target.id(), "--format", "{{.ID}}")).isEqualTo(target.id());
                assertThat(root.resolve("refused.sql")).doesNotExist();
                assertThat(root.resolve("refused-data.sql")).doesNotExist();
            } finally {
                docker("rename", target.id(), original);
            }
        }
    }

    @Test
    void shouldRejectSharedOrSymbolicCredentialRootBeforeCreatingContainer() throws Exception {
        Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwxr-xr-x"));
        assertThatThrownBy(() -> RecoveryDatabase.start(root)).isInstanceOf(IllegalArgumentException.class);
        Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwx------"));
        Path link = root.resolve("link");
        Files.createSymbolicLink(link, root);
        assertThatThrownBy(() -> RecoveryDatabase.start(link)).isInstanceOf(IllegalArgumentException.class);
    }
    @Test
    void shouldCloseOwnedDatabaseWhilePreservingCallerInterrupt() throws Exception {
        Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwx------"));
        var database = RecoveryDatabase.start(root);
        String id = database.id();
        try {
            Thread.currentThread().interrupt();
            assertThatCode(database::close).doesNotThrowAnyException();
            assertThat(Thread.currentThread().isInterrupted()).isTrue();
        } finally {
            Thread.interrupted();
            database.close();
        }
        assertThat(docker("container", "ls", "--all", "--no-trunc", "--filter", "id=" + id, "--format", "{{.ID}}")).isEmpty();
        try (var files = Files.list(root)) {
            assertThat(files.filter(p -> p.getFileName().toString().endsWith(".env"))).isEmpty();
        }
    }

    private String docker(String... arguments) throws Exception {
        Path stdout = Files.createTempFile(root, "probe-", ".stdout", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        Path stderr = Files.createTempFile(root, "probe-", ".stderr", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        var command = new ArrayList<>(List.of("docker"));
        command.addAll(List.of(arguments));
        Process process = new ProcessBuilder(command).redirectInput(Path.of("/dev/null").toFile())
                .redirectOutput(stdout.toFile()).redirectError(stderr.toFile()).start();
        try {
            assertThat(process.waitFor(15, TimeUnit.SECONDS)).as("Docker boundary probe timeout").isTrue();
            assertThat(process.exitValue()).as("Docker boundary probe exit").isZero();
            return Files.readString(stdout).trim();
        } finally {
            if (process.isAlive()) {
                process.descendants().forEach(ProcessHandle::destroyForcibly);
                process.destroyForcibly();
                assertThat(process.waitFor(5, TimeUnit.SECONDS)).isTrue();
            }
        }
    }
}
