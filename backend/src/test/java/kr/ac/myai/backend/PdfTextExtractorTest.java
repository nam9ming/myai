package kr.ac.myai.backend;

import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.local.PdfTextExtractor;
import kr.ac.myai.backend.local.SourceTextPreprocessor;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.*;

class PdfTextExtractorTest {
    @TempDir Path root;
    private int sequence;

    @AfterEach
    void cleanup() throws Exception {
        for (var process : processes()) {
            process.descendants().forEach(ProcessHandle::destroyForcibly);
            if (process.isAlive()) process.destroyForcibly();
        }
    }

    @Test
    void extractsActualSyntheticPdfFromBytesWithPagesAndActualToolVersion() {
        var extractor = new PdfTextExtractor(actualTool());
        byte[] raw = pdf(false, "First synthetic page", "Second synthetic page");
        var text = extractor.extract(raw);
        assertThat(text.pages()).hasSize(2);
        assertThat(text.pages().get(0)).contains("First synthetic page");
        assertThat(text.pages().get(1)).contains("Second synthetic page");
        assertThat(text.toolVersion()).matches(".*\\d+\\.\\d+(?:\\.\\d+)?.*");
        var prepared = new SourceTextPreprocessor(extractor).prepare("pdf", raw);
        assertThat(prepared.blocks()).extracting(SourceTextPreprocessor.Block::page).containsExactly(1, 2);
        assertThat(prepared.blocks()).extracting(SourceTextPreprocessor.Block::blockId).doesNotHaveDuplicates();
        assertThat(prepared.textScope()).isEqualTo("embedded_text_only");
        assertThat(prepared.textReviewRequired()).isTrue();
        assertThat(prepared.preprocessingVersion()).contains(text.toolVersion());
    }

    @Test
    void rejectsActualPdfWithAnyBlankPageAndDoesNotCountTheFinalFormFeedAsAnotherPage() {
        var extractor = new PdfTextExtractor(actualTool());
        assertThat(extractor.extract(pdf(false, "one page")).pages()).hasSize(1);
        for (byte[] raw : List.of(pdf(false, "first", "", "third"), pdf(false, "first", ""), pdf(false, ""))) {
            failure(extractor, raw, 422, "PDF_PAGE_REVIEW_REQUIRED");
        }
    }

    @Test
    void rejectsBrokenAndPasswordEncryptedPdfWithoutReturningToolDiagnostics() {
        var extractor = new PdfTextExtractor(actualTool());
        failure(extractor, "%PDF-1.4\nPRIVATE_BROKEN_PDF".getBytes(StandardCharsets.UTF_8), 422, "PDF_EXTRACTION_FAILED");
        failure(extractor, pdf(true, "encrypted synthetic text"), 422, "PDF_EXTRACTION_FAILED");
    }

    @Test
    void validatesOptionalAbsoluteExecutableOnlyWhenPdfIsRequested() {
        for (String executable : List.of("", "pdftotext", root.resolve("private-missing").toString(), root.toString())) {
            var extractor = new PdfTextExtractor(executable);
            assertThat(new SourceTextPreprocessor(extractor).prepare("txt", "본문".getBytes(StandardCharsets.UTF_8)).cleanedText())
                    .isEqualTo("본문");
            failure(extractor, new byte[]{1}, 503, "PDF_TOOL_NOT_READY");
        }
    }

    @Test
    void passesOnlyFixedArgumentsAndRawStdinWithoutAShellOrSourceFile() throws Exception {
        Path stdin = root.resolve("received-input");
        Path probe = probe("""
                [ "$#" -eq 7 ] && [ "$1" = '-enc' ] && [ "$2" = 'UTF-8' ] && [ "$3" = '-eol' ] &&
                [ "$4" = 'unix' ] && [ "$5" = '-layout' ] && [ "$6" = '-' ] && [ "$7" = '-' ] || exit 32
                /bin/cat > %s
                printf 'first\n\fsecond\n\f'
                """.formatted(quote(stdin)));
        byte[] raw = {0, 1, 2, (byte) 0xff, 10, 13};
        assertThat(new PdfTextExtractor(probe.toString()).extract(raw).pages()).containsExactly("first\n", "second\n");
        assertThat(Files.readAllBytes(stdin)).isEqualTo(raw);
        assertStopped();
    }

    @Test
    void rejectsActualBlankMiddleAndLastPagesButIgnoresOnlyOneTrailingSentinel() throws Exception {
        for (String output : List.of("first\\f\\fthird\\f", "first\\f\\f", "\\f", "   \\f")) {
            var probe = probe("/bin/cat > /dev/null\nprintf '" + output + "'");
            failure(new PdfTextExtractor(probe.toString()), new byte[]{1}, 422, "PDF_PAGE_REVIEW_REQUIRED");
        }
        var probe = probe("/bin/cat > /dev/null\nprintf 'first\\fsecond'");
        assertThat(new PdfTextExtractor(probe.toString()).extract(new byte[]{1}).pages()).containsExactly("first", "second");
        assertStopped();
    }

    @Test
    void drainsBothOutputPipesWhileWritingLargeStdin() throws Exception {
        Path probe = probe("""
                /bin/dd if=/dev/zero bs=60000 count=1 >&2 2>/dev/null
                printf 'synthetic body\f'
                /bin/cat > /dev/null
                """);
        assertThat(new PdfTextExtractor(probe.toString()).extract(new byte[20 * 1024 * 1024]).pages())
                .containsExactly("synthetic body");
        assertStopped();
    }

    @Test
    void boundsStdoutAndStderrAndKillsTheWriterOnOverflow() throws Exception {
        for (String body : List.of(
                "/bin/dd if=/dev/zero bs=4194305 count=1 2>/dev/null\n/bin/sleep 20",
                "/bin/dd if=/dev/zero bs=65537 count=1 >&2 2>/dev/null\n/bin/sleep 20")) {
            Path probe = probe(body);
            long started = System.nanoTime();
            failure(new PdfTextExtractor(probe.toString()), new byte[]{1}, 422, "PDF_EXTRACTION_FAILED");
            assertThat(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started)).isLessThan(5_000);
            assertStopped();
        }
    }

    @Test
    void versionProbeAndBlockedStdinShareOneTenSecondDeadlineAndReapChildren() throws Exception {
        Path child = root.resolve("child-pid");
        Path probe = probe("/bin/sleep 20 &\nprintf '%s' \"$!\" > " + quote(child) + "\nwait", "/bin/sleep 4");
        long started = System.nanoTime();
        failure(new PdfTextExtractor(probe.toString()), new byte[20 * 1024 * 1024], 422, "PDF_EXTRACTION_FAILED");
        long elapsed = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started);
        assertThat(elapsed).isBetween(9_000L, 12_500L);
        assertStopped();
    }

    @Test
    void omitsInheritedEnvironmentAndDoesNotExposeStderrOrExecutablePaths() throws Exception {
        Path environment = root.resolve("environment-names");
        var probe = probe("""
                /usr/bin/env | /usr/bin/cut -d= -f1 > %s
                /bin/cat > /dev/null
                printf 'PRIVATE_TOOL_STDERR' >&2
                exit 4
                """.formatted(quote(environment)));
        failure(new PdfTextExtractor(probe.toString()), new byte[]{1}, 422, "PDF_EXTRACTION_FAILED");
        assertThat(Files.readAllLines(environment)).allSatisfy(name ->
                assertThat(name).isIn("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "SYSTEMROOT", "PWD", "SHLVL", "_"));
        assertStopped();
    }

    @Test
    void rejectsMalformedUtf8OrUnrecognizedVersionWithoutLeakingOutput() throws Exception {
        var malformed = probe("/bin/cat > /dev/null\nprintf '\\377'");
        failure(new PdfTextExtractor(malformed.toString()), new byte[]{1}, 422, "PDF_EXTRACTION_FAILED");
        Path unavailable = root.resolve("unrecognized-version");
        Files.writeString(unavailable, "#!/bin/sh\nprintf 'PRIVATE_UNKNOWN_TOOL' >&2\nexit 0\n");
        Files.setPosixFilePermissions(unavailable, PosixFilePermissions.fromString("rwx------"));
        failure(new PdfTextExtractor(unavailable.toString()), new byte[]{1}, 503, "PDF_TOOL_NOT_READY");
        assertStopped();
    }

    @Test
    void preservesInterruptAndStopsTheRunningProcess() throws Exception {
        Path probe = probe("/bin/sleep 20");
        var error = new AtomicReference<Throwable>();
        var interrupted = new AtomicBoolean();
        Thread worker = Thread.ofPlatform().start(() -> {
            try { new PdfTextExtractor(probe.toString()).extract(new byte[1024 * 1024]); }
            catch (Throwable ex) { error.set(ex); }
            finally { interrupted.set(Thread.currentThread().isInterrupted()); }
        });
        try {
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
            while (!Files.exists(probe.resolveSibling(probe.getFileName() + ".pid")) && System.nanoTime() < deadline) Thread.sleep(10);
            worker.interrupt(); worker.join(3_000);
            assertThat(worker.isAlive()).isFalse();
            assertThat(error.get()).isInstanceOf(ApiException.class);
            assertThat(interrupted.get()).isTrue();
            assertStopped();
        } finally { worker.interrupt(); worker.join(3_000); }
    }

    private Path probe(String body) throws Exception { return probe(body, ""); }

    private Path probe(String body, String versionBody) throws Exception {
        Path executable = root.resolve("pdf probe ; $ " + sequence++);
        Files.writeString(executable, "#!/bin/sh\nif [ \"$#\" -eq 1 ] && [ \"$1\" = '-v' ]; then\n"
                + versionBody + "\nprintf 'pdftotext version 25.04.0\\n' >&2\nexit 0\nfi\n"
                + "printf '%s' \"$$\" > " + quote(executable.resolveSibling(executable.getFileName() + ".pid")) + "\n" + body + "\n");
        Files.setPosixFilePermissions(executable, PosixFilePermissions.fromString("rwx------"));
        return executable;
    }

    private ApiException failure(PdfTextExtractor extractor, byte[] raw, int status, String code) {
        var caught = catchThrowable(() -> extractor.extract(raw));
        assertThat(caught).isInstanceOf(ApiException.class);
        var error = (ApiException) caught;
        assertThat(error.status().value()).isEqualTo(status);
        assertThat(error.code()).isEqualTo(code);
        assertThat(error.getMessage()).doesNotContain(root.toString(), "PRIVATE_", "encrypted synthetic text");
        return error;
    }

    private List<ProcessHandle> processes() throws Exception {
        var result = new ArrayList<ProcessHandle>();
        try (var files = Files.list(root)) {
            for (Path file : files.filter(path -> path.getFileName().toString().endsWith(".pid") || path.getFileName().toString().equals("child-pid")).toList()) {
                ProcessHandle.of(Long.parseLong(Files.readString(file))).ifPresent(result::add);
            }
        }
        return result;
    }

    private void assertStopped() throws Exception {
        for (var process : processes()) {
            process.onExit().get(3, TimeUnit.SECONDS);
            assertThat(process.isAlive()).isFalse();
        }
    }

    private static String actualTool() {
        String configured = System.getenv("MYAI_LOCAL_API_PDFTOTEXT");
        if (configured != null && !configured.isBlank()) return configured;
        for (String path : List.of("/opt/homebrew/bin/pdftotext", "/usr/local/bin/pdftotext", "/usr/bin/pdftotext")) {
            if (Files.isExecutable(Path.of(path))) return path;
        }
        throw new AssertionError("Set MYAI_LOCAL_API_PDFTOTEXT to the absolute Poppler executable");
    }

    private static String quote(Path path) { return "'" + path.toString().replace("'", "'\\''") + "'"; }

    private static byte[] pdf(boolean encrypted, String... pages) {
        try {
            var objects = new ArrayList<String>();
            objects.add("<< /Type /Catalog /Pages 2 0 R >>");
            var kids = new ArrayList<String>();
            for (int i = 0; i < pages.length; i++) kids.add((4 + i) + " 0 R");
            objects.add("<< /Type /Pages /Kids [" + String.join(" ", kids) + "] /Count " + pages.length + " >>");
            objects.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
            for (int i = 0; i < pages.length; i++) objects.add("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    + "/Resources << /Font << /F1 3 0 R >> >> /Contents " + (4 + pages.length + i) + " 0 R >>");
            for (String page : pages) {
                String stream = page.isEmpty() ? "" : "BT /F1 12 Tf 50 700 Td (" + page + ") Tj ET\n";
                objects.add("<< /Length " + stream.length() + " >>\nstream\n" + stream + "endstream");
            }
            if (encrypted) objects.add("<< /Filter /Standard /V 1 /R 2 /O <" + "00".repeat(32) + "> /U <" + "00".repeat(32) + "> /P -4 >>");
            var output = new ByteArrayOutputStream();
            output.write("%PDF-1.4\n".getBytes(StandardCharsets.US_ASCII));
            var offsets = new ArrayList<Integer>();
            for (int i = 0; i < objects.size(); i++) {
                offsets.add(output.size());
                output.write(((i + 1) + " 0 obj\n" + objects.get(i) + "\nendobj\n").getBytes(StandardCharsets.US_ASCII));
            }
            int xref = output.size();
            output.write(("xref\n0 " + (objects.size() + 1) + "\n0000000000 65535 f \n").getBytes(StandardCharsets.US_ASCII));
            for (int offset : offsets) output.write(String.format(java.util.Locale.ROOT, "%010d 00000 n \n", offset).getBytes(StandardCharsets.US_ASCII));
            String encryption = encrypted ? " /Encrypt " + objects.size() + " 0 R /ID [<" + "00".repeat(16) + "><" + "00".repeat(16) + ">]" : "";
            output.write(("trailer\n<< /Size " + (objects.size() + 1) + " /Root 1 0 R" + encryption + " >>\nstartxref\n" + xref + "\n%%EOF\n").getBytes(StandardCharsets.US_ASCII));
            return output.toByteArray();
        } catch (Exception ex) { throw new AssertionError(ex); }
    }
}
