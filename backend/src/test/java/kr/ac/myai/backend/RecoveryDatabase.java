package kr.ac.myai.backend;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

final class RecoveryDatabase implements AutoCloseable {
    private static final String OWNER_LABEL = "myai.recovery.owner";
    private static final String SCHEMA = "myai_recovery";
    private static final String USERNAME = "myai_recovery";
    private static final String INSPECT = "{{.Id}} {{.Name}} {{index .Config.Labels \"myai.recovery.owner\"}}";
    private final Path root;
    private final String owner = UUID.randomUUID().toString();
    private final String name = "myai-recovery-" + owner;
    private final String password = UUID.randomUUID().toString();
    private final Path credentials;
    private String id;
    private String url;
    private JdbcTemplate jdbc;
    private boolean closed;

    private RecoveryDatabase(Path root) throws IOException {
        this.root = root.toRealPath();
        credentials = privateFile(this.root, name + "-", ".env");
        try {
            Files.writeString(credentials, "MYSQL_DATABASE=" + SCHEMA + "\nMYSQL_USER=" + USERNAME
                    + "\nMYSQL_PASSWORD=" + password + "\nMYSQL_ROOT_PASSWORD=" + UUID.randomUUID() + "\n");
        } catch (IOException error) {
            try { Files.delete(credentials); }
            catch (IOException cleanup) { error.addSuppressed(cleanup); }
            throw error;
        }
    }

    static RecoveryDatabase start(Path privateRoot) {
        privateDirectory(privateRoot);
        RecoveryDatabase database = null;
        try {
            database = new RecoveryDatabase(privateRoot);
            database.launch();
            return database;
        } catch (IOException | RuntimeException error) {
            if (database != null) {
                try { database.cleanupAfterFailedStart(); }
                catch (IOException | RuntimeException cleanup) { error.addSuppressed(cleanup); }
            }
            throw new IllegalStateException("Recovery database start failed", error);
        }
    }

    JdbcTemplate jdbc() { return jdbc; }
    String url() { return url; }
    String username() { return USERNAME; }
    String password() { return password; }
    String id() { return id; }

    private void launch() throws IOException {
        var result = command(List.of("docker", "run", "--detach", "--name", name, "--label", OWNER_LABEL + "=" + owner,
                "--label", "myai.recovery.stage=database-recovery", "--env-file", credentials.toString(),
                "--publish", "127.0.0.1::3306", "mysql:8.4.13"), null, null, Duration.ofMinutes(2));
        String created = Files.readString(result).trim();
        if (!created.matches("[a-f0-9]{64}")) throw new IllegalStateException("Recovery container ID missing");
        id = created;
        verifyOwner();
        String address = Files.readString(command(List.of("docker", "port", id, "3306/tcp"), null, null, Duration.ofSeconds(15))).trim();
        if (!address.matches("127\\.0\\.0\\.1:[0-9]+")) throw new IllegalStateException("Recovery localhost port missing");
        url = "jdbc:mysql://" + address + "/" + SCHEMA
                + "?useSSL=false&allowPublicKeyRetrieval=true&connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true"
                + "&characterEncoding=UTF-8&connectTimeout=2000&socketTimeout=10000";
        jdbc = new JdbcTemplate(new DriverManagerDataSource(url, USERNAME, password));
        long deadline = System.nanoTime() + Duration.ofMinutes(2).toNanos();
        while (System.nanoTime() < deadline) {
            try {
                if (Integer.valueOf(1).equals(jdbc.queryForObject("SELECT 1", Integer.class))) return;
            } catch (org.springframework.dao.DataAccessException notReady) {
                // 새 서버 초기화가 끝날 때까지 전용 계정의 실제 접속을 기다린다.
            }
            try { Thread.sleep(200); }
            catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("Recovery database start interrupted");
            }
        }
        throw new IllegalStateException("Recovery database readiness timed out");
    }

    void dump(Path newFile) { dump(newFile, false); }
    void dumpData(Path newFile) { dump(newFile, true); }

    private void dump(Path newFile, boolean dataOnly) {
        verifyOwner();
        Path target = newFile.toAbsolutePath().normalize();
        privateDirectory(target.getParent());
        if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) throw new IllegalArgumentException("Recovery dump requires a new file");
        try {
            Path partial = privateFile(target.getParent(), ".recovery-dump-", ".partial");
            command(List.of("docker", "exec", id, "sh", "-c", "MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\" exec mysqldump --user=root"
                    + " --single-transaction --no-tablespaces --set-gtid-purged=OFF --hex-blob --default-character-set=utf8mb4"
                    + " --skip-comments --skip-dump-date --order-by-primary" + (dataOnly ? " --no-create-info --skip-triggers " : " ") + SCHEMA), null, partial, Duration.ofMinutes(2));
            // 같은 디렉터리 hard link는 기존 파일을 덮지 않고 완성본 이름을 원자적으로 만든다.
            Files.createLink(target, partial);
            Files.delete(partial);
        } catch (IOException error) {
            throw new IllegalStateException("Recovery database dump failed", error);
        }
    }

    void restore(Path existingDump) {
        verifyOwner();
        if (!Files.isRegularFile(existingDump, LinkOption.NOFOLLOW_LINKS) || Files.isSymbolicLink(existingDump))
            throw new IllegalArgumentException("Recovery restore requires a regular dump");
        Long tables = jdbc.queryForObject("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()", Long.class);
        if (tables == null || tables != 0) throw new IllegalStateException("Recovery restore requires an empty schema");
        try {
            command(List.of("docker", "exec", "--interactive", id, "sh", "-c",
                    "MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\" exec mysql --user=root --default-character-set=utf8mb4 " + SCHEMA),
                    existingDump, null, Duration.ofMinutes(2));
        } catch (IOException error) {
            throw new IllegalStateException("Recovery database restore failed", error);
        }
    }

    private void verifyOwner() {
        if (closed || id == null) throw new IllegalStateException("Recovery database is closed or unowned");
        try {
            String actual = Files.readString(command(List.of("docker", "inspect", "--format", INSPECT, id), null, null, Duration.ofSeconds(15))).trim();
            if (!actual.equals(id + " /" + name + " " + owner)) throw new IllegalStateException("Recovery container ownership mismatch");
        } catch (IOException error) {
            throw new IllegalStateException("Recovery container ownership check failed", error);
        }
    }

    @Override public void close() {
        if (closed) return;
        boolean interrupted = Thread.interrupted();
        try {
            verifyOwner();
            command(List.of("docker", "rm", "--force", "--volumes", id), null, null, Duration.ofSeconds(30));
            Files.delete(credentials);
            closed = true;
        } catch (IOException error) {
            throw new IllegalStateException("Recovery database cleanup failed", error);
        } finally {
            if (interrupted) Thread.currentThread().interrupt();
        }
    }

    private void cleanupAfterFailedStart() throws IOException {
        boolean interrupted = Thread.interrupted();
        try {
            if (id == null) {
                String found = Files.readString(command(List.of("docker", "container", "ls", "--all", "--no-trunc", "--filter", "name=^/" + name + "$",
                        "--filter", "label=" + OWNER_LABEL + "=" + owner, "--format", "{{.ID}}"), null, null, Duration.ofSeconds(15))).trim();
                if (!found.isEmpty()) {
                    if (!found.matches("[a-f0-9]{64}")) throw new IllegalStateException("Recovery failed-start container ambiguous");
                    id = found;
                }
            }
            if (id != null) {
                verifyOwner();
                command(List.of("docker", "rm", "--force", "--volumes", id), null, null, Duration.ofSeconds(30));
            }
            Files.delete(credentials);
            closed = true;
        } finally {
            if (interrupted) Thread.currentThread().interrupt();
        }
    }

    private Path command(List<String> arguments, Path input, Path output, Duration timeout) throws IOException {
        Path stdout = output == null ? privateFile(root, name + "-stdout-", ".log") : output;
        Path stderr = privateFile(root, name + "-stderr-", ".log");
        Process process = new ProcessBuilder(arguments).redirectInput(input == null ? Path.of("/dev/null").toFile() : input.toFile())
                .redirectOutput(stdout.toFile()).redirectError(stderr.toFile()).start();
        try {
            if (!process.waitFor(timeout.toMillis(), TimeUnit.MILLISECONDS)) {
                stop(process);
                throw new IllegalStateException("Recovery Docker command timed out; private diagnostics: " + stderr.getFileName());
            }
            if (process.exitValue() != 0)
                throw new IllegalStateException("Recovery Docker command failed (exit " + process.exitValue() + "); private diagnostics: " + stderr.getFileName());
            return stdout;
        } catch (InterruptedException interrupted) {
            stop(process);
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Recovery Docker command interrupted");
        }
    }

    private static void stop(Process process) {
        var children = process.descendants().toList();
        children.forEach(ProcessHandle::destroyForcibly);
        process.destroyForcibly();
        try {
            if (!process.waitFor(5, TimeUnit.SECONDS)) throw new IllegalStateException("Recovery Docker process cleanup timed out");
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("Recovery Docker process cleanup interrupted");
        }
    }

    private static Path privateFile(Path directory, String prefix, String suffix) throws IOException {
        return Files.createTempFile(directory, prefix, suffix, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
    }

    private static void privateDirectory(Path directory) {
        try {
            if (directory == null || !Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS) || Files.isSymbolicLink(directory)
                    || !Files.getPosixFilePermissions(directory).equals(PosixFilePermissions.fromString("rwx------")))
                throw new IllegalArgumentException("Recovery directory must be a private 0700 directory");
        } catch (IOException error) {
            throw new IllegalArgumentException("Recovery directory is unavailable", error);
        }
    }
}
