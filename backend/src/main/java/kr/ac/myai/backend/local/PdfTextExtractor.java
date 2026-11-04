package kr.ac.myai.backend.local;

import kr.ac.myai.backend.exception.ApiException;
import org.springframework.http.HttpStatus;

import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.regex.Pattern;

public final class PdfTextExtractor {
    private static final int STDOUT_LIMIT = 4 * 1024 * 1024;
    private static final int STDERR_LIMIT = 64 * 1024;
    private static final Pattern VERSION = Pattern.compile("(?m)^pdftotext version ([0-9]+(?:\\.[0-9]+){1,3})(?:\\s|$)");

    public record PdfText(List<String> pages, String toolVersion) { }
    private record Output(int exitCode, byte[] stdout, byte[] stderr) { }
    private final String executable;

    public PdfTextExtractor(String executable) { this.executable = executable; }

    public PdfText extract(byte[] raw) {
        try {
            if (executable == null || executable.isBlank()) throw failure(true);
            Path tool = Path.of(executable);
            if (!tool.isAbsolute() || !Files.isRegularFile(tool) || !Files.isExecutable(tool)) throw failure(true);
        } catch (java.nio.file.InvalidPathException ex) { throw failure(true); }
        if (raw == null || raw.length == 0) throw failure(false);
        if (raw.length > 20 * 1024 * 1024) throw new ApiException(HttpStatus.PAYLOAD_TOO_LARGE,
                "SOURCE_TEXT_TOO_LARGE", "파일은20MiB 이하여야 합니다. 분할하거나 별도로 검토해 주세요.", "file");

        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(10);
        var versionOutput = execute(List.of("-v"), new byte[0], deadline, true);
        var version = VERSION.matcher(decode(versionOutput.stdout(), true) + decode(versionOutput.stderr(), true));
        if (versionOutput.exitCode() != 0 || !version.find()) throw failure(true);
        var output = execute(List.of("-enc", "UTF-8", "-eol", "unix", "-layout", "-", "-"), raw, deadline, false);
        if (output.exitCode() != 0) throw failure(false);
        String text = decode(output.stdout(), false);
        if (text.codePoints().anyMatch(value -> Character.isISOControl(value)
                && value != '\n' && value != '\r' && value != '\t' && value != '\f')) throw failure(false);
        var pages = new ArrayList<>(Arrays.asList(text.split("\f", -1)));
        if (pages.size() > 1 && pages.getLast().isEmpty()) pages.removeLast();
        if (pages.stream().anyMatch(page -> page.codePoints().allMatch(value -> Character.isWhitespace(value) || Character.isSpaceChar(value)))) {
            throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "PDF_PAGE_REVIEW_REQUIRED",
                    "텍스트 없는 PDF 페이지가 있습니다. 전체 원문을 별도로 검토해 주세요.", "file");
        }
        return new PdfText(List.copyOf(pages), version.group(1));
    }

    private Output execute(List<String> arguments, byte[] input, long deadline, boolean versionProbe) {
        if (Thread.currentThread().isInterrupted()) throw failure(versionProbe);
        Process process = null;
        var workers = Executors.newVirtualThreadPerTaskExecutor();
        try {
            remaining(deadline);
            var command = new ArrayList<String>();
            command.add(executable); command.addAll(arguments);
            var builder = new ProcessBuilder(command);
            builder.environment().clear();
            builder.environment().put("LANG", "C");
            builder.environment().put("LC_ALL", "C");
            process = builder.start();
            Process child = process;
            var stdout = CompletableFuture.supplyAsync(() -> bounded(child.getInputStream(), STDOUT_LIMIT), workers);
            var stderr = CompletableFuture.supplyAsync(() -> bounded(child.getErrorStream(), STDERR_LIMIT), workers);
            var write = CompletableFuture.runAsync(() -> {
                try (var stdin = child.getOutputStream()) { stdin.write(input); }
                catch (IOException ex) { throw new UncheckedIOException(ex); }
            }, workers);
            var failed = new CompletableFuture<Void>();
            for (var task : new CompletableFuture<?>[]{stdout, stderr, write}) {
                task.whenComplete((value, error) -> { if (error != null) failed.completeExceptionally(error); });
            }
            CompletableFuture.anyOf(process.onExit(), failed).get(remaining(deadline), TimeUnit.NANOSECONDS);
            int exit = process.exitValue();
            write.get(remaining(deadline), TimeUnit.NANOSECONDS);
            byte[] errors = stderr.get(remaining(deadline), TimeUnit.NANOSECONDS);
            return new Output(exit, stdout.get(remaining(deadline), TimeUnit.NANOSECONDS), errors);
        } catch (IOException | ExecutionException | TimeoutException ex) {
            throw failure(versionProbe);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw failure(versionProbe);
        } finally {
            boolean interrupted = Thread.interrupted();
            try {
                if (process != null) {
                    var descendants = process.descendants().toList();
                    descendants.forEach(ProcessHandle::destroyForcibly);
                    // 부모가 살아 있는 동안 종료한 자식을 회수할 기회를 준다.
                    long reapDeadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(200);
                    for (var descendant : descendants) {
                        try { descendant.onExit().get(Math.max(1, reapDeadline - System.nanoTime()), TimeUnit.NANOSECONDS); }
                        catch (ExecutionException | TimeoutException ignored) { }
                        catch (InterruptedException ex) { interrupted = true; }
                    }
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

    private static byte[] bounded(InputStream input, int limit) {
        try {
            byte[] bytes = input.readNBytes(limit + 1);
            if (bytes.length > limit) throw new IOException();
            return bytes;
        } catch (IOException ex) { throw new UncheckedIOException(ex); }
    }

    private static String decode(byte[] bytes, boolean versionProbe) {
        try {
            return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();
        } catch (CharacterCodingException ex) { throw failure(versionProbe); }
    }

    private static ApiException failure(boolean versionProbe) {
        return new ApiException(versionProbe ? HttpStatus.SERVICE_UNAVAILABLE : HttpStatus.UNPROCESSABLE_ENTITY,
                versionProbe ? "PDF_TOOL_NOT_READY" : "PDF_EXTRACTION_FAILED",
                versionProbe ? "PDF 변환 도구의 설치·서버 설정을 확인해 주세요." : "PDF를 텍스트로 변환하지 못했습니다. 별도로 검토해 주세요.", "file");
    }
}
