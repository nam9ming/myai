package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.calculation.PythonCalculator;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.*;

class PythonCalculatorTest {
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();

    @AfterEach
    void cleanup() throws Exception { PythonProbe.stopAll(root); }

    @Test
    void runsActualPythonWithUtf8FactsAndInputHash() throws Exception {
        var data = calculator(PythonProbe.REPO, 5000).calculate(input());
        assertThat(data.path("counts").path("candidate").asInt()).isEqualTo(1);
        assertThat(data.path("items").get(0).path("title").asText()).isEqualTo("합성 공지 😀");
        assertThat(data.path("items").get(0).path("distance_m").asDouble()).isZero();
        assertThat(data.path("items").get(0).path("time_overlap_minutes").asDouble()).isEqualTo(120);
        assertThat(data.has("diagnostics")).isFalse();
    }

    @Test
    void supportsAValidEmptyCalculation() throws Exception {
        var input = input(); input.putArray("events"); input.putArray("source_versions");
        var data = calculator(PythonProbe.REPO, 5000).calculate(input);
        assertThat(data.path("items").isEmpty()).isTrue();
        assertThat(data.path("counts").path("candidate").asInt()).isZero();
    }

    @Test
    void drainsBothPipesWhileLargeStdinIsPending() throws Exception {
        Path probe = PythonProbe.create(root, """
                sys.stdout.write(' ' * 100000)
                sys.stdout.flush()
                sys.stderr.buffer.write(b'x' * 60000)
                sys.stderr.flush()
                """ + PythonProbe.ECHO + "response['data']={'marker':'정상 😀'}\nprint(json.dumps(response,ensure_ascii=False))");
        var input = input(); ((ObjectNode) input.path("source_versions").get(0)).put("title", "x".repeat(2 * 1024 * 1024));
        assertThat(calculator(probe, 5000).calculate(input).path("marker").asText()).isEqualTo("정상 😀");
        assertStopped(probe);
    }

    @Test
    void rejectsUnavailableConfigurationWithoutLeakingPaths() throws Exception {
        for (var calculator : List.of(
                calculator(root.resolve("missing-private-path"), 5000),
                new PythonCalculator(mapper, new ReviewedImportReader(), "private-missing-executable", root.toString(), 5000),
                calculator(root, 0))) {
            var error = failure(calculator, input(), "CALCULATION_UNAVAILABLE", false);
            assertThat(error.getMessage()).doesNotContain(root.toString(), "private-");
        }
    }

    @Test
    void rejectsOversizeInputBeforeStartingProcess() throws Exception {
        Path probe = PythonProbe.create(root, "time.sleep(20)");
        var input = input(); ((ObjectNode) input.path("source_versions").get(0)).put("title", "x".repeat(8 * 1024 * 1024));
        failure(calculator(probe, 5000), input, "CALCULATION_UNAVAILABLE", false);
        assertThat(PythonProbe.processes(root)).isEmpty();
    }

    @Test
    void timeoutsAlsoBoundBlockedStdinWritesAndKillProcess() throws Exception {
        Path probe = PythonProbe.create(root, "time.sleep(20)");
        var input = input(); ((ObjectNode) input.path("source_versions").get(0)).put("title", "x".repeat(2 * 1024 * 1024));
        long start = System.nanoTime();
        failure(calculator(probe, 500), input, "CALCULATION_UNAVAILABLE", true);
        assertThat((System.nanoTime() - start) / 1_000_000).isLessThan(4000);
        assertStopped(probe);
    }

    @Test
    void boundsStdoutAndStderrWhileBothPipesAreDrained() throws Exception {
        for (String stream : List.of("stdout", "stderr")) {
            int size = stream.equals("stdout") ? 8 * 1024 * 1024 + 1 : 65537;
            Path probe = PythonProbe.create(root, "sys." + stream + ".buffer.write(b'x' * " + size + ")\nsys." + stream + ".flush()\ntime.sleep(20)");
            failure(calculator(probe, 5000), input(), "CALCULATION_UNAVAILABLE", false);
            assertStopped(probe);
        }
    }

    @Test
    void nonzeroExitIsNotAnEmptySuccessOrRawStderr() throws Exception {
        Path probe = PythonProbe.create(root, "print('PRIVATE_CONDITION', file=sys.stderr)\nsys.exit(4)");
        var error = failure(calculator(probe, 5000), input(), "CALCULATION_UNAVAILABLE", false);
        assertThat(error.getMessage()).doesNotContain("PRIVATE_CONDITION", root.toString());
        assertStopped(probe);
    }

    @Test
    void rejectsMalformedOutputAndEveryEchoMismatch() throws Exception {
        var mutations = List.of(
                "response['protocol_version']='calc-v2'", "response['request_id']='wrong'",
                "response['snapshot_id']='wrong'", "response['input_sha256']='0'*64",
                "response['rules_version']='wrong'", "response['data']=[]",
                "response['diagnostics']={}", "response['private_path']='PRIVATE_PATH'", "del response['data']");
        for (String mutation : mutations) {
            Path probe = PythonProbe.create(root, PythonProbe.ECHO + mutation + "\nprint(json.dumps(response))");
            failure(calculator(probe, 5000), input(), "CALCULATION_PROTOCOL_ERROR", false);
            assertStopped(probe);
        }
        for (String body : List.of("sys.stdout.buffer.write(b'\\xff')", "print('{} {}')", "print('{\\\"a\\\":1,\\\"a\\\":2}')")) {
            Path probe = PythonProbe.create(root, "sys.stdin.buffer.read()\n" + body);
            failure(calculator(probe, 5000), input(), "CALCULATION_PROTOCOL_ERROR", false);
            assertStopped(probe);
        }
    }

    @Test
    void interruptPreservesFlagAndReleasesProcessAndPermit() throws Exception {
        Path probe = PythonProbe.create(root, "time.sleep(20)");
        var calculator = calculator(probe, 5000);
        var error = new AtomicReference<Throwable>(); var flag = new AtomicBoolean();
        var request = input();
        Thread worker = Thread.ofPlatform().start(() -> {
            try { calculator.calculate(request); } catch (Throwable ex) { error.set(ex); }
            finally { flag.set(Thread.currentThread().isInterrupted()); }
        });
        try {
            PythonProbe.waitForStarts(probe, 1);
            worker.interrupt(); worker.join(3000);
            assertThat(worker.isAlive()).isFalse();
            assertThat(error.get()).isInstanceOf(ApiException.class);
            assertThat(((ApiException) error.get()).retryable()).isTrue();
            assertThat(flag.get()).isTrue();
            assertStopped(probe);
            assertCapacity(calculator, probe);
        } finally { worker.interrupt(); worker.join(3000); }
    }

    @Test
    void overloadFailsWithoutStartingAnExtraChild() throws Exception {
        Path probe = PythonProbe.create(root, "time.sleep(20)");
        var calculator = calculator(probe, 5000);
        assertCapacity(calculator, probe);
    }

    private void assertCapacity(PythonCalculator calculator, Path probe) throws Exception {
        var executor = Executors.newFixedThreadPool(4);
        var futures = new ArrayList<java.util.concurrent.Future<?>>();
        var request = input();
        try {
            for (int i = 0; i < 4; i++) futures.add(executor.submit(() -> calculator.calculate(request)));
            PythonProbe.waitForStarts(probe, 4);
            failure(calculator, input(), "CALCULATION_UNAVAILABLE", true);
            assertThat(PythonProbe.processes(probe)).filteredOn(ProcessHandle::isAlive).hasSize(4);
        } finally {
            futures.forEach(f -> f.cancel(true)); executor.shutdownNow();
            assertThat(executor.awaitTermination(3, java.util.concurrent.TimeUnit.SECONDS)).isTrue();
        }
        assertStopped(probe);
    }

    private PythonCalculator calculator(Path workdir, long timeout) {
        return new PythonCalculator(mapper, new ReviewedImportReader(), PythonProbe.PYTHON, workdir.toString(), timeout);
    }

    private ObjectNode input() throws Exception {
        return (ObjectNode) mapper.readTree(PythonProbe.REPO.resolve("processing/examples/match-input.json").toFile());
    }

    private ApiException failure(PythonCalculator calculator, ObjectNode input, String code, boolean retryable) {
        var caught = catchThrowable(() -> calculator.calculate(input));
        assertThat(caught).isInstanceOf(ApiException.class);
        var error = (ApiException) caught;
        assertThat(error.code()).isEqualTo(code);
        assertThat(error.retryable()).isEqualTo(retryable);
        assertThat(error.status().value()).isEqualTo(code.equals("CALCULATION_PROTOCOL_ERROR") ? 500 : 503);
        return error;
    }

    private void assertStopped(Path probe) throws Exception {
        try (var files = java.nio.file.Files.list(probe)) {
            assertThat(files.anyMatch(p -> p.getFileName().toString().startsWith("pid-"))).isTrue();
        }
        for (var process : PythonProbe.processes(probe)) {
            process.onExit().get(3, java.util.concurrent.TimeUnit.SECONDS);
            assertThat(process.isAlive()).isFalse();
        }
    }
}
