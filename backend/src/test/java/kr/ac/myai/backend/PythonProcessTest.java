package kr.ac.myai.backend;

import kr.ac.myai.backend.process.PythonProcess;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.Files;
import java.util.List;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;
import java.util.stream.Stream;

import static org.assertj.core.api.Assertions.*;

class PythonProcessTest {
    @TempDir Path root;

    @Test
    void keylessEntryRemovesCredentialsAndUnrelatedInheritedValues() throws Exception {
        assertThat(child("executeKeyless")).isEqualTo("0:True\n");
    }

    @Test
    void existingEntryStillUsesItsCallersEnvironment() throws Exception {
        assertThat(child("execute")).isEqualTo("5:True\n");
    }

    @Test
    void preservesTheExactFailureCodeSeparatelyFromStdout() {
        var result = run("sys.stdout.buffer.write(b'unchanged');sys.stderr.buffer.write(b'ARCHIVE_CONFLICT\\n');sys.exit(3)", 3000);
        assertThat(result.exitCode()).isEqualTo(3);
        assertThat(result.stdout()).isEqualTo("unchanged".getBytes(StandardCharsets.UTF_8));
        assertThat(stderr(result)).isEqualTo("ARCHIVE_CONFLICT\n".getBytes(StandardCharsets.UTF_8));
    }

    @Test
    void drainsBothStreamsAtTheirExactLimitsWithoutDecodingDiagnostics() {
        var result = run("sys.stdout.buffer.write(b'o'*(8*1024*1024));sys.stderr.buffer.write(b'e'*65535+b'\\xff')", 5000);
        assertThat(result.exitCode()).isZero();
        byte[] output = new byte[8 * 1024 * 1024]; Arrays.fill(output, (byte) 'o');
        byte[] errors = new byte[65536]; Arrays.fill(errors, (byte) 'e'); errors[65535] = (byte) 0xff;
        assertThat(Arrays.equals(result.stdout(), output)).isTrue();
        assertThat(Arrays.equals(stderr(result), errors)).isTrue();
    }

    @ParameterizedTest @ValueSource(strings = {"stdout", "stderr"})
    void rejectsAnExtraByteAndReapsTheChild(String stream) throws Exception {
        int limit = stream.equals("stdout") ? 8 * 1024 * 1024 : 65536;
        assertThatThrownBy(() -> run("sys." + stream + ".buffer.write(b'x'*" + (limit + 1) + ")", 5000))
                .isInstanceOfSatisfying(PythonProcess.Failure.class, error -> assertThat(error.retryable()).isFalse());
        assertStartedAndReaped();
    }

    @Test
    void timeoutReapsTheKeylessChild() throws Exception {
        assertThatThrownBy(() -> run("time.sleep(30)", 1000))
                .isInstanceOfSatisfying(PythonProcess.Failure.class, error -> assertThat(error.retryable()).isTrue());
        assertStartedAndReaped();
    }

    @Test
    void interruptionKeepsTheFlagAndReapsTheKeylessChild() throws Exception {
        var failed = new AtomicBoolean(); var interrupted = new AtomicBoolean();
        Thread worker = new Thread(() -> {
            try { run("time.sleep(30)", 5000); }
            catch (PythonProcess.Failure error) {
                failed.set(error.retryable()); interrupted.set(Thread.currentThread().isInterrupted());
            }
        });
        worker.start();
        try {
            PythonProbe.waitForStarts(root, 1);
            worker.interrupt(); worker.join(3000);
            assertThat(worker.isAlive()).isFalse();
            assertThat(failed).isTrue(); assertThat(interrupted).isTrue();
            assertThat(PythonProbe.processes(root)).noneMatch(ProcessHandle::isAlive);
        } finally {
            worker.interrupt(); worker.join(3000); PythonProbe.stopAll(root);
        }
    }

    private PythonProcess.Result run(String code, long timeout) {
        return PythonProcess.executeKeyless(PythonProbe.PYTHON, root.toString(), List.of("-B", "-s", "-c",
                "import os,sys,time\nfrom pathlib import Path\nPath('pid-'+str(os.getpid())).write_text(str(os.getpid()))\n" + code),
                new byte[0], timeout);
    }

    private byte[] stderr(PythonProcess.Result result) {
        try { return (byte[]) result.getClass().getMethod("stderr").invoke(result); }
        catch (ReflectiveOperationException error) { throw new AssertionError("Result does not preserve bounded stderr", error); }
    }

    private void assertStartedAndReaped() throws Exception {
        try (var files = Files.list(root)) {
            assertThat(files.anyMatch(path -> path.getFileName().toString().startsWith("pid-"))).isTrue();
        }
        assertThat(PythonProbe.processes(root)).noneMatch(ProcessHandle::isAlive);
    }

    private String child(String entry) throws Exception {
        String classpath = Stream.of(PythonProcess.class, Child.class)
                .map(type -> {
                    try { return Path.of(type.getProtectionDomain().getCodeSource().getLocation().toURI()).toString(); }
                    catch (Exception ex) { throw new IllegalStateException(ex); }
                }).distinct().collect(Collectors.joining(System.getProperty("path.separator")));
        var builder = new ProcessBuilder(Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                "-cp", classpath, Child.class.getName(), entry, PythonProbe.PYTHON, root.toString());
        var environment = builder.environment();
        environment.clear();
        environment.put("PATH", System.getenv("PATH"));
        for (String name : List.of("OPENAI_API_KEY", "DB_PASSWORD", "MYAI_LOCAL_API_TOKEN", "UNRELATED_SECRET_MARKER")) {
            environment.put(name, "synthetic-only");
        }
        environment.put("PYTHONPATH", root.toString());
        var process = builder.start();
        try {
            assertThat(process.waitFor(10, TimeUnit.SECONDS)).isTrue();
            String stderr = new String(process.getErrorStream().readAllBytes(), StandardCharsets.UTF_8);
            assertThat(process.exitValue()).withFailMessage("child entry failed: %s", stderr).isZero();
            assertThat(stderr).isEmpty();
            return new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8);
        } finally {
            process.descendants().forEach(ProcessHandle::destroyForcibly);
            process.destroyForcibly();
            process.waitFor(1, TimeUnit.SECONDS);
        }
    }

    public static class Child {
        public static void main(String[] arguments) throws Exception {
            String code = "import os; names={'OPENAI_API_KEY','DB_PASSWORD','MYAI_LOCAL_API_TOKEN',"
                    + "'UNRELATED_SECRET_MARKER','PYTHONPATH'}; print(str(len(names.intersection(os.environ)))"
                    + "+':'+str(bool(os.environ.get('PATH'))))";
            var method = PythonProcess.class.getMethod(arguments[0], String.class, String.class,
                    List.class, byte[].class, long.class);
            var result = (PythonProcess.Result) method.invoke(null, arguments[1], arguments[2],
                    List.of("-B", "-s", "-c", code), new byte[0], 3000L);
            System.out.write(result.stdout());
            if (result.exitCode() != 0) System.exit(result.exitCode());
        }
    }
}
