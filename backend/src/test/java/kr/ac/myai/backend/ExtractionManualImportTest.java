package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.net.URLClassLoader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

class ExtractionManualImportTest {
    private static final String ID = "71fb66f0-e610-4f9c-8f26-4bb77655ee8c";
    private static final String OTHER_ID = "10000000-0000-4000-8000-000000000001";
    private static final ObjectMapper JSON = new ObjectMapper();
    @TempDir Path root;
    private final ReviewedImportReader json = new ReviewedImportReader();

    @BeforeEach
    void normalizeOwnedTemporaryRoot() throws Exception { root = root.toRealPath(); }

    @AfterEach
    void cleanupOwnedProcessesAndFiles() throws Exception {
        PythonProbe.stopAll(root);
        ExtractionArchiveReaderTest.unseal(root);
    }

    @Test
    void importsAnActualSingleAttemptAndPreservesNullableDecimalMetadataBytes() throws Exception {
        var fixture = fixture(root.resolve("single"), validOutput());
        var receipt = manual(reader(PythonProbe.REPO, 10_000), ID, fixture);
        assertThat(receipt.path("run_id").asText()).isEqualTo(ID);
        assertThat(receipt.path("status").asText()).isEqualTo("validated");
        assertThat(receipt.path("review_required").asBoolean()).isTrue();
        assertThat(receipt.path("attempts")).hasSize(1);
        assertOriginals(fixture, receipt);
        var metadata = json.parseJson(Files.readAllBytes(fixture.root().resolve(ID).resolve("metadata.json")));
        assertThat(metadata.path("model_label").isNull()).isTrue();
        assertThat(metadata.path("model_version").isNull()).isTrue();
        assertThat(metadata.path("started_at").isNull()).isTrue();
        assertThat(metadata.path("cost").decimalValue()).isEqualByComparingTo("0.1234567890123456789");
        var frozen = reader(PythonProbe.REPO, 10_000).read(ID, fixture.root());
        assertThat(frozen.receipt()).isEqualTo(receipt);
        assertThat(frozen.metadataJson()).isEqualTo(Files.readString(fixture.metadata()));
    }

    @Test
    void keepsThreeActualAttemptsInOrderWithEarlierFailuresAndFinalSuccess() throws Exception {
        var fixture = fixture(root.resolve("three"), bytes("not json"), new byte[]{(byte) 0xff}, validOutput());
        var receipt = manual(reader(PythonProbe.REPO, 10_000), ID, fixture);
        assertThat(receipt.path("attempts")).hasSize(3);
        assertThat(receipt.path("attempts").get(0).path("status").asText()).isEqualTo("failed");
        assertThat(receipt.path("attempts").get(1).path("status").asText()).isEqualTo("failed");
        assertThat(receipt.path("attempts").get(2).path("status").asText()).isEqualTo("validated");
        assertThat(receipt.path("status").asText()).isEqualTo("validated");
        assertOriginals(fixture, receipt);
    }

    @Test
    void preservesAllFailedAttemptsIncludingEmptyAndInvalidUtf8Output() throws Exception {
        var fixture = fixture(root.resolve("failed"), bytes("{broken"), new byte[0], new byte[]{(byte) 0xff, 0});
        var receipt = manual(reader(PythonProbe.REPO, 10_000), ID, fixture);
        assertThat(receipt.path("status").asText()).isEqualTo("failed");
        assertThat(receipt.path("attempts")).hasSize(3).allSatisfy(attempt ->
                assertThat(attempt.path("status").asText()).isEqualTo("failed"));
        assertThat(receipt.path("review_required").asBoolean()).isTrue();
        assertOriginals(fixture, receipt);
        assertThat(reader(PythonProbe.REPO, 10_000).read(ID, fixture.root()).status()).isEqualTo("failed");
    }

    @Test
    void reusesTheExactRunAndRejectsChangedInputMetadataPromptAndOutputWithoutOverwriting() throws Exception {
        var fixture = fixture(root.resolve("replay"), validOutput());
        var reader = reader(PythonProbe.REPO, 10_000);
        var first = manual(reader, ID, fixture);
        var before = tree(fixture.root());
        assertThat(manual(reader, ID, fixture)).isEqualTo(first);
        assertThat(tree(fixture.root())).isEqualTo(before);
        for (Path path : List.of(fixture.input(), fixture.metadata(), fixture.attempts().getFirst().prompt(), fixture.attempts().getFirst().output())) {
            byte[] original = Files.readAllBytes(path);
            try {
                byte[] changed = java.util.Arrays.copyOf(original, original.length + 1);
                changed[changed.length - 1] = ' ';
                Files.write(path, changed);
                failure(() -> manual(reader, ID, fixture), "EXTRACTION_CONFLICT");
                assertThat(tree(fixture.root())).isEqualTo(before);
            } finally { Files.write(path, original); }
        }
    }

    @Test
    void refusesAddingAttemptsToAnAlreadyCompletedRunUuid() throws Exception {
        var fixture = fixture(root.resolve("append"), validOutput());
        var reader = reader(PythonProbe.REPO, 10_000);
        manual(reader, ID, fixture);
        var before = tree(fixture.root());
        Files.writeString(fixture.metadata(), Files.readString(fixture.metadata()).replace("\"attempts\": 1", "\"attempts\": 3"));
        var pairs = new ArrayList<>(fixture.attempts());
        for (int index = 2; index <= 3; index++) pairs.add(new Pair(
                file(fixture.metadata().getParent().resolve("prompt-" + index), bytes("synthetic later prompt " + index)),
                file(fixture.metadata().getParent().resolve("output-" + index), validOutput())));
        var expanded = new Fixture(fixture.root(), fixture.input(), fixture.metadata(), List.copyOf(pairs));
        failure(() -> manual(reader, ID, expanded), "EXTRACTION_CONFLICT");
        assertThat(tree(fixture.root())).isEqualTo(before);
    }

    @Test
    void resumesAnInterruptedIdentityWithTheSameOriginalFilesAndRecordedTime() throws Exception {
        var fixture = fixture(root.resolve("resume"), bytes("not json"), validOutput(), validOutput());
        var reader = reader(PythonProbe.REPO, 10_000);
        var original = manual(reader, ID, fixture);
        Path canonical = fixture.root().resolve(ID);
        byte[] identity = Files.readAllBytes(canonical.resolve("identity.json"));
        Files.delete(canonical.resolve("receipt.json"));
        Files.delete(canonical.resolve("attempt-3.output"));
        assertThat(manual(reader, ID, fixture)).isEqualTo(original);
        assertThat(Files.readAllBytes(canonical.resolve("identity.json"))).isEqualTo(identity);
        assertOriginals(fixture, original);
    }

    @Test
    void rejectsRunIdAndApiModeMismatchesWithoutChangingCallerFiles() throws Exception {
        var fixture = fixture(root.resolve("mismatch"), validOutput());
        var reader = reader(PythonProbe.REPO, 10_000);
        byte[] input = Files.readAllBytes(fixture.input()), metadata = Files.readAllBytes(fixture.metadata());
        var mismatch = catchThrowable(() -> manual(reader, OTHER_ID, fixture));
        assertThat(mismatch).isInstanceOf(ExtractionException.class);
        assertThat(((ExtractionException) mismatch).code()).isIn("EXTRACTION_VALIDATION_ERROR", "EXTRACTION_ARCHIVE_INVALID");
        assertThat(Files.readAllBytes(fixture.input())).isEqualTo(input);
        assertThat(Files.readAllBytes(fixture.metadata())).isEqualTo(metadata);
        assertThat(fixture.root().resolve(ID)).doesNotExist();
        assertThat(fixture.root().resolve(OTHER_ID)).doesNotExist();
        var api = fixture(root.resolve("api-mode"), validOutput());
        Files.writeString(api.metadata(), Files.readString(api.metadata())
                .replace("\"manual_import\"", "\"api\"")
                .replace("\"synthetic-fixture\"", "\"openai\"")
                .replace("\"model_label\": null", "\"model_label\": \"synthetic-model\"")
                .replace("\"model_label\": \"실제 모델 호출 없음\",", ""));
        failure(() -> manual(reader, ID, api), "EXTRACTION_VALIDATION_ERROR");
        assertThat(api.root().resolve(ID)).doesNotExist();
    }

    @Test
    void refusesFabricatedRunStatusHashesReceiptOrExitCode() throws Exception {
        var fixture = fixture(root.resolve("forged"), validOutput());
        JsonNode good = manual(reader(PythonProbe.REPO, 10_000), ID, fixture);
        var changedStatus = good.deepCopy(); ((ObjectNode) changedStatus).put("status", "failed");
        var changedRun = good.deepCopy(); ((ObjectNode) changedRun).put("run_id", OTHER_ID);
        var changedInput = good.deepCopy(); ((ObjectNode) changedInput).put("input_sha256", "0".repeat(64));
        var changedMetadata = good.deepCopy(); ((ObjectNode) changedMetadata).put("metadata_sha256", "0".repeat(64));
        var extra = good.deepCopy(); ((ObjectNode) extra).put("private_path", "SYNTHETIC_PRIVATE_VALUE");
        for (String body : List.of("print('SYNTHETIC_PRIVATE_VALUE')", print(changedStatus), print(changedRun),
                print(changedInput), print(changedMetadata), print(extra), print(good) + "\nsys.exit(4)")) {
            var probe = probe(body);
            failure(() -> manual(reader(probe, 3_000), ID, fixture), "EXTRACTION_ARCHIVE_INVALID");
        }
        var swapped = fixture(root.resolve("swapped"), validOutput());
        String response = print(good);
        failure(() -> manual(reader(probe(response), 3_000), ID, swapped), "EXTRACTION_ARCHIVE_INVALID");
    }

    @Test
    void acceptsOnlyTheExactConflictCodeOnExitThreeAndDoesNotExposeDiagnostics() throws Exception {
        var fixture = fixture(root.resolve("codes"), validOutput());
        failure(() -> manual(reader(probe("sys.stderr.write('ARCHIVE_CONFLICT\\n');sys.exit(3)"), 3_000), ID, fixture), "EXTRACTION_CONFLICT");
        for (String diagnostic : List.of("ARCHIVE_CONFLICT", "PREFIX_ARCHIVE_CONFLICT\n", "ARCHIVE_CONFLICT\n\n",
                "ARCHIVE_CONFLICT\nSYNTHETIC_PRIVATE_VALUE\n", "SYNTHETIC_PRIVATE_VALUE\n")) {
            Path probe = probe("sys.stderr.write(" + JSON.writeValueAsString(diagnostic) + ");sys.exit(3)");
            failure(() -> manual(reader(probe, 3_000), ID, fixture), "EXTRACTION_ARCHIVE_INVALID");
        }
        failure(() -> manual(reader(probe("sys.stderr.write('ARCHIVE_CONFLICT\\n');sys.exit(2)"), 3_000), ID, fixture), "EXTRACTION_VALIDATION_ERROR");
        failure(() -> manual(reader(probe("sys.stderr.write('SYNTHETIC_PRIVATE_VALUE\\n');sys.exit(5)"), 3_000), ID, fixture), "EXTRACTION_IO_ERROR");
    }

    @Test
    void boundsRuntimeAndReapsTheTimedOutImportProcess() throws Exception {
        var fixture = fixture(root.resolve("timeout"), validOutput());
        Path probe = probe("time.sleep(30)");
        long started = System.nanoTime();
        var error = failure(() -> manual(reader(probe, 300), ID, fixture), "EXTRACTION_RUNTIME_UNAVAILABLE");
        assertThat(error.retryable()).isTrue();
        assertThat(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - started)).isLessThan(4_000);
        assertThat(PythonProbe.processes(probe)).noneMatch(ProcessHandle::isAlive);
    }

    @Test
    void rejectsUnsafeSuppliedPathsBeforeStartingTheInterpreter() throws Exception {
        var fixture = fixture(root.resolve("invalid-paths"), validOutput());
        Path probe = probe("Path('unexpected').write_text('started')");
        var reader = reader(probe, 3000);
        for (String run : new String[]{null, "../escape", "invalid"}) {
            failure(() -> manual(reader, run, fixture), "EXTRACTION_VALIDATION_ERROR");
        }
        Path linkedRoot = Files.createSymbolicLink(root.resolve("linked-root"), fixture.root());
        Path linkedInput = Files.createSymbolicLink(root.resolve("linked-input"), fixture.input());
        Path linkedMetadata = Files.createSymbolicLink(root.resolve("linked-metadata"), fixture.metadata());
        Path linkedPrompt = Files.createSymbolicLink(root.resolve("linked-prompt"), fixture.attempts().getFirst().prompt());
        Path linkedOutput = Files.createSymbolicLink(root.resolve("linked-output"), fixture.attempts().getFirst().output());
        for (var invalid : List.of(
                new Fixture(Path.of("relative"), fixture.input(), fixture.metadata(), fixture.attempts()),
                new Fixture(linkedRoot, fixture.input(), fixture.metadata(), fixture.attempts()),
                new Fixture(fixture.root(), Path.of("relative"), fixture.metadata(), fixture.attempts()),
                new Fixture(fixture.root(), linkedInput, fixture.metadata(), fixture.attempts()),
                new Fixture(fixture.root(), fixture.input(), linkedMetadata, fixture.attempts()),
                new Fixture(fixture.root(), fixture.input(), fixture.metadata(), List.of(new Pair(linkedPrompt, fixture.attempts().getFirst().output()))),
                new Fixture(fixture.root(), fixture.input(), fixture.metadata(), List.of(new Pair(fixture.attempts().getFirst().prompt(), linkedOutput))),
                new Fixture(fixture.root(), fixture.input(), fixture.metadata(), List.of()),
                new Fixture(fixture.root(), fixture.input(), fixture.metadata(), java.util.Collections.nCopies(4, fixture.attempts().getFirst())))) {
            failure(() -> manual(reader, ID, invalid), "EXTRACTION_VALIDATION_ERROR");
        }
        assertThat(probe.resolve("unexpected")).doesNotExist();
        assertThat(fixture.root().resolve(ID)).doesNotExist();
    }

    @Test
    void actualFreshJvmKeepsImportFreezeSealedVerificationAndDraftCheckKeyless() throws Exception {
        Path childRoot = directory(root.resolve("environment-child"));
        Path stdout = root.resolve("environment.stdout"), stderr = root.resolve("environment.stderr");
        var builder = new ProcessBuilder(Path.of(System.getProperty("java.home"), "bin", "java").toString(), "-Xmx256m",
                "-cp", javaClasspath(), EnvironmentChild.class.getName(), childRoot.toString(), python());
        builder.environment().clear();
        builder.environment().put("PATH", System.getenv().getOrDefault("PATH", "/usr/bin:/bin"));
        builder.environment().put("LANG", "C.UTF-8");
        for (String name : List.of("OPENAI_API_KEY", "OPENAI_MODEL", "DB_PASSWORD", "DB_URL", "MYAI_LOCAL_API_TOKEN",
                "MYAI_SYNTHETIC_MARKER", "PYTHONPATH", "SYNTHETIC_OTHER_MARKER")) builder.environment().put(name, "SYNTHETIC_ONLY_MARKER");
        var process = builder.redirectOutput(stdout.toFile()).redirectError(stderr.toFile()).start();
        try {
            assertThat(process.waitFor(30, TimeUnit.SECONDS)).isTrue();
            Path commands = childRoot.resolve("environment-command-flags.jsonl");
            String report = Files.exists(commands) ? Files.readString(commands) : "no command report";
            assertThat(process.exitValue()).withFailMessage("environment fixture failed: %s; commands: %s", Files.readString(stderr), report).isZero();
            assertThat(Files.readString(stdout).trim()).isEqualTo("KEYLESS_READER_OK");
            assertThat(Files.readString(stderr)).isEmpty();
        } finally { process.destroyForcibly(); assertThat(process.waitFor(3, TimeUnit.SECONDS)).isTrue(); }
    }

    public static final class EnvironmentChild {
        public static void main(String[] args) throws Exception {
            var test = new ExtractionManualImportTest();
            test.root = Path.of(args[0]);
            var fixture = test.fixture(test.root.resolve("actual"), validOutput());
            Path reports = test.root.resolve("environment-command-flags.jsonl");
            Path probe = test.forwardingProbe(reports);
            var reader = new ExtractionArchiveReader(new ReviewedImportReader(), args[1], probe.toString(), 10_000);
            var imported = manual(reader, ID, fixture);
            if (!imported.path("status").asText().equals("validated")) throw new AssertionError("Expected validated synthetic import");
            var frozen = reader.read(ID, fixture.root());
            reader.readSealed(ID, frozen.directory().getParent());
            Path draft = test.makeDraft(args[1], fixture);
            reader.checkDraft(ID, fixture.root(), Files.readString(draft));
            var commands = new LinkedHashSet<String>();
            for (String line : Files.readAllLines(reports)) {
                var report = JSON.readTree(line);
                if (!report.path("unexpected_names").isEmpty() || !report.path("no_user_site").asBoolean()
                        || !report.path("no_bytecode").asBoolean()) throw new AssertionError("Python environment or interpreter flags were not isolated");
                commands.add(report.path("command").asText());
            }
            if (!commands.containsAll(Set.of("import", "freeze", "verify-sealed", "check-draft"))) throw new AssertionError("Missing real Python archive command coverage");
            System.out.println("KEYLESS_READER_OK");
        }
    }

    private Fixture fixture(Path base, byte[]... outputs) throws Exception {
        directory(base);
        Path archive = directory(base.resolve("archive"));
        Path input = file(base.resolve("input.json"), Files.readAllBytes(PythonProbe.REPO.resolve("contracts/examples/ai-input.json")));
        String metadata = "\n" + Files.readString(PythonProbe.REPO.resolve("processing/examples/extraction-metadata.json"))
                .replace("\"attempts\": 1", "\"attempts\": " + outputs.length)
                .replace("\"cost\": null", "\"cost\": 0.1234567890123456789") + "\n";
        Path meta = file(base.resolve("metadata.json"), bytes(metadata));
        var attempts = new ArrayList<Pair>();
        for (int index = 0; index < outputs.length; index++) attempts.add(new Pair(
                file(base.resolve("prompt-" + (index + 1)), bytes("합성 수동 입력 " + (index + 1) + " 😀\r\n")),
                file(base.resolve("output-" + (index + 1)), outputs[index])));
        return new Fixture(archive, input, meta, List.copyOf(attempts));
    }

    private void assertOriginals(Fixture fixture, JsonNode receipt) throws Exception {
        Path canonical = fixture.root().resolve(ID);
        assertThat(json.parseJson(Files.readAllBytes(canonical.resolve("receipt.json")))).isEqualTo(receipt);
        var originals = new TreeMap<String, Path>();
        originals.put("input.json", fixture.input()); originals.put("metadata.json", fixture.metadata());
        for (int index = 0; index < fixture.attempts().size(); index++) {
            originals.put("attempt-" + (index + 1) + ".prompt", fixture.attempts().get(index).prompt());
            originals.put("attempt-" + (index + 1) + ".output", fixture.attempts().get(index).output());
        }
        assertThat(ExtractionArchiveReader.artifactNames(receipt)).containsExactlyInAnyOrderElementsOf(originals.keySet());
        for (var entry : originals.entrySet()) {
            byte[] raw = Files.readAllBytes(entry.getValue());
            assertThat(Files.readAllBytes(canonical.resolve(entry.getKey()))).isEqualTo(raw);
            assertThat(receipt.path("artifacts").path(entry.getKey()).path("size").asLong()).isEqualTo(raw.length);
            assertThat(receipt.path("artifacts").path(entry.getKey()).path("sha256").asText()).isEqualTo(ReviewedImportReader.sha256(raw));
        }
        assertThat(receipt.path("input_sha256").asText()).isEqualTo(ReviewedImportReader.sha256(Files.readAllBytes(fixture.input())));
        assertThat(receipt.path("metadata_sha256").asText()).isEqualTo(ReviewedImportReader.sha256(Files.readAllBytes(fixture.metadata())));
    }

    private Path forwardingProbe(Path report) throws Exception {
        Path probe = probe("");
        String body = """
                import json,runpy
                import processing,processing.extraction
                allowed={'PATH','LANG','LANGUAGE'}
                if sys.platform=='darwin':
                    allowed.add('__CF_USER_TEXT_ENCODING')
                bad=sorted(name for name in os.environ if name not in allowed and not name.startswith('LC_'))
                with Path(%s).open('a',encoding='utf-8') as target:
                    target.write(json.dumps(dict(command=sys.argv[1],unexpected_names=bad,
                        no_user_site=bool(sys.flags.no_user_site),no_bytecode=bool(sys.dont_write_bytecode)))+'\\n')
                if bad or not sys.flags.no_user_site or not sys.dont_write_bytecode:
                    sys.exit(97)
                processing.__path__.append(%s)
                processing.extraction.__path__=[%s]
                runpy.run_module('processing.extraction',run_name='__main__')
                """.formatted(JSON.writeValueAsString(report.toString()), JSON.writeValueAsString(PythonProbe.REPO.resolve("processing").toString()),
                        JSON.writeValueAsString(PythonProbe.REPO.resolve("processing/extraction").toString()));
        Path module = probe.resolve("processing/extraction/__main__.py");
        Files.writeString(module, "import sys,time,os\nfrom pathlib import Path\nPath('pid-'+str(os.getpid())).write_text(str(os.getpid()))\n" + body);
        return probe;
    }

    private Path makeDraft(String executable, Fixture fixture) throws Exception {
        var input = (ObjectNode) json.parseJson(Files.readAllBytes(fixture.input()));
        var source = (ObjectNode) JSON.readTree(PythonProbe.REPO.resolve("backend/examples/source-import.json").toFile());
        var document = (ObjectNode) source.path("documents").get(0);
        for (String field : List.of("document_version_id", "title", "published_date")) document.set(field, input.path(field));
        document.set("block_index", input.path("blocks"));
        var lines = new ArrayList<String>(); for (var block : input.path("blocks")) lines.add(block.path("text").asText());
        String cleaned = String.join("\n", lines);
        document.put("cleaned_text", cleaned).put("text_sha256", ReviewedImportReader.sha256(bytes(cleaned))).put("preprocessing_version", "fixture-nfc-v1");
        Path sourcePath = file(root.resolve("draft-source.json"), bytes(source.toString()));
        Path draft = root.resolve("draft.json");
        String script = "from processing.extraction.draft import draft_run; import sys; draft_run(sys.argv[1],sys.argv[2],sys.argv[3],"
                + "'00000000-0000-0000-0000-000000000000','00000000-0000-0000-0000-000000000000','synthetic-environment',sys.argv[4])";
        var builder = new ProcessBuilder(executable, "-B", "-s", "-c", script, ID, sourcePath.toString(), draft.toString(), fixture.root().toString())
                .directory(PythonProbe.REPO.toFile());
        builder.environment().clear(); builder.environment().put("PATH", System.getenv().getOrDefault("PATH", "/usr/bin:/bin"));
        var process = builder.start();
        try {
            assertThat(process.waitFor(10, TimeUnit.SECONDS)).isTrue();
            assertThat(process.exitValue()).isZero();
            assertThat(process.getInputStream().readAllBytes()).isEmpty();
            assertThat(process.getErrorStream().readAllBytes()).isEmpty();
        } finally { process.destroyForcibly(); assertThat(process.waitFor(3, TimeUnit.SECONDS)).isTrue(); }
        return draft;
    }

    private Path probe(String body) throws Exception {
        var fixture = new ExtractionArchiveReaderTest(); fixture.root = root;
        return fixture.probe(body);
    }

    private ExtractionArchiveReader reader(Path workdir, long timeout) {
        return new ExtractionArchiveReader(json, python(), workdir.toString(), timeout);
    }

    private static JsonNode manual(ExtractionArchiveReader reader, String runId, Fixture fixture) throws Exception {
        var attempts = fixture.attempts().stream()
                .map(pair -> new ExtractionArchiveReader.AttemptFiles(pair.prompt(), pair.output())).toList();
        return reader.importManual(runId, fixture.root(), fixture.input(), fixture.metadata(), attempts);
    }

    private ExtractionException failure(org.assertj.core.api.ThrowableAssert.ThrowingCallable call, String code) {
        var caught = catchThrowable(call);
        assertThat(caught).isInstanceOf(ExtractionException.class);
        var error = (ExtractionException) caught;
        assertThat(error.code()).isEqualTo(code);
        assertThat(error.getMessage()).doesNotContain("SYNTHETIC_PRIVATE_VALUE", root.toString(), "ARCHIVE_CONFLICT");
        return error;
    }

    private Map<String, String> tree(Path directory) throws Exception {
        var result = new TreeMap<String, String>();
        try (var paths = Files.walk(directory)) {
            for (Path path : paths.toList()) result.put(directory.relativize(path).toString(),
                    PosixFilePermissions.toString(Files.getPosixFilePermissions(path)) + ":"
                            + (Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) ? ReviewedImportReader.sha256(Files.readAllBytes(path)) : "directory"));
        }
        return result;
    }

    private static String javaClasspath() throws Exception {
        var entries = new LinkedHashSet<String>();
        entries.add(System.getProperty("java.class.path"));
        for (ClassLoader loader = ExtractionManualImportTest.class.getClassLoader(); loader != null; loader = loader.getParent()) {
            if (loader instanceof URLClassLoader urls) for (var url : urls.getURLs()) entries.add(Path.of(url.toURI()).toString());
        }
        for (Class<?> type : List.of(ExtractionManualImportTest.class, ExtractionArchiveReader.class)) {
            var source = type.getProtectionDomain().getCodeSource();
            if (source != null) entries.add(Path.of(source.getLocation().toURI()).toString());
        }
        return String.join(java.io.File.pathSeparator, entries);
    }

    private record Pair(Path prompt, Path output) { }
    private record Fixture(Path root, Path input, Path metadata, List<Pair> attempts) { }
    private static byte[] validOutput() throws Exception { return Files.readAllBytes(PythonProbe.REPO.resolve("contracts/examples/ai-extraction.json")); }
    private static byte[] bytes(String text) { return text.getBytes(StandardCharsets.UTF_8); }
    private static String print(JsonNode value) throws Exception { return "print(" + JSON.writeValueAsString(value.toString()) + ")"; }
    private static Path file(Path path, byte[] bytes) throws Exception {
        Files.createFile(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        return Files.write(path, bytes);
    }
    private static Path directory(Path path) throws Exception {
        return Files.createDirectory(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
    }
    private static String python() {
        Path configured = Path.of(PythonProbe.PYTHON);
        if (configured.isAbsolute()) return configured.toString();
        for (String entry : System.getenv().getOrDefault("PATH", "").split(java.io.File.pathSeparator)) {
            Path candidate = Path.of(entry).resolve(configured);
            if (Files.isExecutable(candidate)) return candidate.toAbsolutePath().normalize().toString();
        }
        throw new AssertionError("Set an available MYAI_PYTHON_EXECUTABLE");
    }
}

