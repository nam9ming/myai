package kr.ac.myai.backend.process;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.*;

public final class PythonProcess {
    private static final int LIMIT = 8 * 1024 * 1024;

    public record Result(int exitCode, byte[] stdout) { }

    public static final class Failure extends RuntimeException {
        private final boolean retryable;
        public Failure(boolean retryable) { super("PYTHON_UNAVAILABLE"); this.retryable = retryable; }
        public boolean retryable() { return retryable; }
    }

    public static Result execute(String executable, String workdir, List<String> arguments, byte[] input, long timeoutMillis) {
        Path directory;
        try { directory = Path.of(workdir); }
        catch (RuntimeException ex) { throw new Failure(false); }
        if (executable == null || executable.isBlank() || !directory.isAbsolute() || !Files.isDirectory(directory)
                || timeoutMillis < 1 || timeoutMillis > 60000 || input.length > LIMIT) throw new Failure(false);
        if (Thread.currentThread().isInterrupted()) throw new Failure(true);
        Process process = null;
        ExecutorService workers = Executors.newVirtualThreadPerTaskExecutor();
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(timeoutMillis);
        try {
            var command = new ArrayList<String>(); command.add(executable); command.addAll(arguments);
            process = new ProcessBuilder(command).directory(directory.toFile()).start();
            Process child = process;
            var output = CompletableFuture.supplyAsync(() -> bounded(child.getInputStream(), LIMIT), workers);
            var errors = CompletableFuture.supplyAsync(() -> bounded(child.getErrorStream(), 65536), workers);
            var write = CompletableFuture.runAsync(() -> {
                try (var stdin = child.getOutputStream()) { stdin.write(input); }
                catch (IOException ex) { throw new UncheckedIOException(ex); }
            }, workers);
            var failed = new CompletableFuture<Void>();
            for (var task : new CompletableFuture<?>[]{output, errors, write}) {
                task.whenComplete((value, error) -> { if (error != null) failed.completeExceptionally(error); });
            }
            CompletableFuture.anyOf(process.onExit(), failed).get(remaining(deadline), TimeUnit.NANOSECONDS);
            int exit = process.exitValue();
            write.get(remaining(deadline), TimeUnit.NANOSECONDS);
            errors.get(remaining(deadline), TimeUnit.NANOSECONDS);
            return new Result(exit, output.get(remaining(deadline), TimeUnit.NANOSECONDS));
        } catch (IOException | ExecutionException ex) {
            throw new Failure(false);
        } catch (TimeoutException ex) {
            throw new Failure(true);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt(); throw new Failure(true);
        } finally {
            boolean interrupted = Thread.interrupted();
            try {
                if (process != null) {
                    process.descendants().forEach(ProcessHandle::destroyForcibly);
                    process.destroyForcibly();
                    try { process.waitFor(200, TimeUnit.MILLISECONDS); }
                    catch (InterruptedException ex) { interrupted = true; }
                    try { process.getOutputStream().close(); } catch (IOException ignored) { }
                    try { process.getInputStream().close(); } catch (IOException ignored) { }
                    try { process.getErrorStream().close(); } catch (IOException ignored) { }
                }
                workers.shutdownNow();
                try { workers.awaitTermination(200, TimeUnit.MILLISECONDS); }
                catch (InterruptedException ex) { interrupted = true; }
            } finally { if (interrupted) Thread.currentThread().interrupt(); }
        }
    }

    private static long remaining(long deadline) throws TimeoutException {
        long remaining = deadline - System.nanoTime();
        if (remaining <= 0) throw new TimeoutException();
        return remaining;
    }

    private static byte[] bounded(InputStream stream, int max) {
        try {
            byte[] bytes = stream.readNBytes(max + 1);
            if (bytes.length > max) throw new IOException("PYTHON_IO_LIMIT");
            return bytes;
        } catch (IOException ex) { throw new UncheckedIOException(ex); }
    }

    private PythonProcess() { }
}
