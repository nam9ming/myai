package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.handoff.HumanHandoffArchiveReader;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.process.PythonProcess;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.nio.charset.StandardCharsets;
import java.net.URLClassLoader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

class CitizenHumanHandoffArchiveTest {
    @TempDir Path root;
    final ReviewedImportReader json = new ReviewedImportReader();
    final ObjectMapper mapper = new ObjectMapper();

    @AfterEach void unsealOwnedFiles() throws Exception {
        PythonProbe.stopAll(root); ExtractionArchiveReaderTest.unseal(root);
    }

    @Test
    void readsActualFrozenCitizenHandoffWithoutLegacyContext() throws Exception {
        var fixture = fixture("review_success");
        var image = reader(PythonProbe.REPO, 20_000).read(fixture.ref(), fixture.hash(), fixture.handoffRoot());
        assertThat(image.projection().path("schema_version").asText()).isEqualTo("citizen-human-handoff-projection-v1");
        assertThat(keys(image.projection().path("context"))).containsExactly("split_group_id");
        assertThat(image.projection().path("events")).isNotEmpty();
        assertThat(image.projection().path("documents")).hasSize(1);
        assertThat(image.projection().path("parent").path("execution_mode").asText()).isEqualTo("manual_import");
        assertThat(image.review().path("output").path("schema_version").asText()).isEqualTo("extract-citizen-v1");
        assertThat(image.receipt().path("summary").path("backend_import_supported").asBoolean()).isFalse();
        var before = CitizenExtractionArchiveTest.tree(image.directory());
        assertThat(reader(PythonProbe.REPO, 20_000).read(image.reference()).projection()).isEqualTo(image.projection());
        assertThat(CitizenExtractionArchiveTest.tree(image.directory())).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"review_success", "review_failed", "empty"})
    void citizenImageRetainsFactsAndFailedParentAfterOriginalRunAndReviewAreRemoved(String testCase) throws Exception {
        var fixture = fixture(testCase);
        for (Path directory : List.of(fixture.runRoot(), fixture.reviewRoot())) {
            assertThat(directory.toAbsolutePath().normalize()).startsWith(root.toRealPath());
            ExtractionArchiveReaderTest.unseal(directory);
            try (var files = Files.walk(directory)) { for (Path file : files.sorted(Comparator.reverseOrder()).toList()) Files.delete(file); }
        }
        var before = CitizenExtractionArchiveTest.tree(fixture.directory());
        var image = reader(PythonProbe.REPO, 20_000).read(fixture.ref(), fixture.hash(), fixture.handoffRoot());
        assertThat(image.projection()).isEqualTo(mapper.readTree(fixture.directory().resolve("projection.json").toFile()));
        assertThat(image.projection().path("parent").path("status").asText()).isEqualTo(testCase.equals("review_failed") ? "failed" : "validated");
        if (testCase.equals("empty")) assertThat(image.projection().path("events")).isEmpty();
        else {
            assertThat(image.projection().path("events")).hasSize(5);
            var facts = image.projection().path("events").get(0).path("facts");
            assertThat(facts.path("application_period")).isNotEqualTo(facts.path("occurrences"));
            assertThat(facts.has("rules_version")).isFalse(); assertThat(facts.has("dictionary_version")).isFalse();
        }
        assertThat(CitizenExtractionArchiveTest.tree(fixture.directory())).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"directory_555", "file_444", "nested_file_444", "extra_file", "extra_directory", "extra_symlink"})
    void rejectsNoncanonicalModesAndUnlistedEntriesWithoutRepairWhenHelperClaimsSuccess(String defect) throws Exception {
        var fixture = fixture("review_success"); Path directory = fixture.directory();
        var receipt = mapper.readTree(directory.resolve("receipt.json").toFile());
        if (defect.equals("directory_555")) Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("r-xr-xr-x"));
        else if (defect.equals("file_444")) Files.setPosixFilePermissions(directory.resolve("projection.json"), PosixFilePermissions.fromString("r--r--r--"));
        else if (defect.equals("nested_file_444")) {
            var projection = mapper.readTree(directory.resolve("projection.json").toFile());
            String prefix = "review/" + projection.path("review").path("review_ref").asText() + "/source/";
            var review = mapper.readTree(directory.resolve("review/" + projection.path("review").path("review_ref").asText() + "/review.json").toFile());
            Files.setPosixFilePermissions(directory.resolve(prefix + review.path("source").path("snapshot_ref").asText() + "/metadata.json"), PosixFilePermissions.fromString("r--r--r--"));
        } else {
            Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("rwx------"));
            Path extra = directory.resolve("unlisted");
            if (defect.equals("extra_file")) Files.writeString(extra, "합성 미등록 인계 파일");
            else if (defect.equals("extra_directory")) Files.createDirectory(extra);
            else Files.createSymbolicLink(extra, fixture.sourceFile());
            Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("r-x------"));
        }
        var before = CitizenExtractionArchiveTest.tree(directory);
        try { invalid(() -> reader(probe("print(" + mapper.writeValueAsString(receipt.toString()) + ")"), 10_000).read(fixture.ref(), fixture.hash(), fixture.handoffRoot())); }
        finally { assertThat(CitizenExtractionArchiveTest.tree(directory)).isEqualTo(before); }
    }

    @ParameterizedTest
    @ValueSource(strings = {"legacy_projection", "selection_family", "review_output_family", "parent_metadata_family", "parent_input_document"})
    void rejectsCrossFamilyAndEmbeddedSourceMismatchEvenWhenOuterArtifactHashesMatch(String defect) throws Exception {
        var fixture = fixture("review_success"); Path directory = fixture.directory();
        var projection = (ObjectNode) mapper.readTree(directory.resolve("projection.json").toFile());
        String reviewPrefix = "review/" + projection.path("review").path("review_ref").asText() + "/";
        var review = (ObjectNode) mapper.readTree(directory.resolve(reviewPrefix + "review.json").toFile());
        String parentPrefix = reviewPrefix + "source/" + review.path("source").path("snapshot_ref").asText() + "/";
        if (defect.equals("legacy_projection")) {
            projection.put("schema_version", "human-handoff-projection-v1");
            ((ObjectNode) projection.path("context")).put("area_id", "10000000-0000-4000-8000-000000000005").put("dictionary_version", "synthetic-dictionary-v1");
            rewrite(directory.resolve("projection.json"), projection);
        } else if (defect.equals("selection_family")) {
            var selection = (ObjectNode) mapper.readTree(directory.resolve("selection.json").toFile()); selection.put("schema_version", "human-handoff-v1");
            rewrite(directory.resolve("selection.json"), selection);
        } else if (defect.equals("review_output_family")) {
            ((ObjectNode) review.path("output")).put("schema_version", "extract-schema-v1"); rewrite(directory.resolve(reviewPrefix + "review.json"), review);
        } else {
            Path path = directory.resolve(parentPrefix + (defect.equals("parent_metadata_family") ? "metadata.json" : "input.json"));
            var value = (ObjectNode) mapper.readTree(path.toFile());
            if (defect.equals("parent_metadata_family")) value.put("schema_version", "extract-schema-v1");
            else value.put("document_version_id", "10000000-0000-4000-8000-000000000005");
            rewrite(path, value);
        }
        var receipt = (ObjectNode) mapper.readTree(directory.resolve("receipt.json").toFile());
        var artifacts = (ObjectNode) receipt.path("artifacts");
        for (var fields = artifacts.fieldNames(); fields.hasNext();) {
            String name = fields.next(); byte[] bytes = Files.readAllBytes(directory.resolve(name));
            artifacts.putObject(name).put("size", bytes.length).put("sha256", ReviewedImportReader.sha256(bytes));
        }
        ((ObjectNode) receipt.path("summary")).put("projection_sha256", artifacts.path("projection.json").path("sha256").asText());
        var identity = (ObjectNode) mapper.readTree(directory.resolve("identity.json").toFile()); identity.set("artifacts", artifacts.deepCopy());
        rewrite(directory.resolve("identity.json"), identity); rewrite(directory.resolve("receipt.json"), receipt);
        String hash = ReviewedImportReader.sha256(Files.readAllBytes(directory.resolve("receipt.json")));
        var before = CitizenExtractionArchiveTest.tree(directory);
        try { invalid(() -> reader(probe("print(" + mapper.writeValueAsString(receipt.toString()) + ")"), 10_000).read(fixture.ref(), hash, fixture.handoffRoot())); }
        finally { assertThat(CitizenExtractionArchiveTest.tree(directory)).isEqualTo(before); }
    }

    @Test
    void citizenVerificationTimeoutAndInterruptPreserveImageAndReapSubprocess() throws Exception {
        var fixture = fixture("review_success"); var before = CitizenExtractionArchiveTest.tree(fixture.directory());
        Path slow = probe("time.sleep(30)");
        assertThatThrownBy(() -> reader(slow, 200).read(fixture.ref(), fixture.hash(), fixture.handoffRoot()))
                .isInstanceOfSatisfying(ExtractionException.class, error -> {
                    assertThat(error.code()).isEqualTo("EXTRACTION_RUNTIME_UNAVAILABLE"); assertThat(error.retryable()).isTrue();
                });
        assertThat(PythonProbe.processes(slow)).noneMatch(ProcessHandle::isAlive);
        Thread.currentThread().interrupt();
        try {
            assertThatThrownBy(() -> reader(PythonProbe.REPO, 10_000).read(fixture.ref(), fixture.hash(), fixture.handoffRoot()))
                    .isInstanceOfSatisfying(ExtractionException.class, error -> assertThat(error.retryable()).isTrue());
            assertThat(Thread.currentThread().isInterrupted()).isTrue();
        } finally { Thread.interrupted(); }
        assertThat(CitizenExtractionArchiveTest.tree(fixture.directory())).isEqualTo(before);
    }

    @Test
    void freshJvmVerifiesCitizenImageWithoutPassingCredentialsOrUserSiteToPython() throws Exception {
        var fixture = fixture("review_success");
        var before = CitizenExtractionArchiveTest.tree(fixture.directory());
        String receipt = Files.readString(fixture.directory().resolve("receipt.json"));
        Path report = root.resolve("environment-report.json");
        Path probe = probe("""
                import json
                allowed={'PATH','LANG','LANGUAGE'}
                if sys.platform=='darwin': allowed.add('__CF_USER_TEXT_ENCODING')
                bad=sorted(name for name in os.environ if name not in allowed and not name.startswith('LC_'))
                Path(%s).write_text(json.dumps(dict(unexpected_names=bad,no_user_site=bool(sys.flags.no_user_site),no_bytecode=bool(sys.dont_write_bytecode))))
                if bad or not sys.flags.no_user_site or not sys.dont_write_bytecode: sys.exit(97)
                print(%s)
                """.formatted(mapper.writeValueAsString(report.toString()), mapper.writeValueAsString(receipt)));
        Path stdout = root.resolve("environment.stdout"), stderr = root.resolve("environment.stderr");
        var builder = new ProcessBuilder(Path.of(System.getProperty("java.home"), "bin", "java").toString(), "-Xmx256m",
                "-cp", javaClasspath(), EnvironmentChild.class.getName(), PythonProbe.PYTHON, probe.toString(),
                fixture.ref(), fixture.hash(), fixture.handoffRoot().toString());
        builder.environment().clear();
        builder.environment().put("PATH", System.getenv().getOrDefault("PATH", "/usr/bin:/bin"));
        builder.environment().put("LANG", "C.UTF-8");
        for (String key : List.of("OPENAI_API_KEY", "OPENAI_MODEL", "DB_PASSWORD", "DB_URL", "MYAI_LOCAL_API_TOKEN", "PYTHONPATH", "SYNTHETIC_OTHER_MARKER")) {
            builder.environment().put(key, "SYNTHETIC_ONLY_MARKER");
        }
        var process = builder.redirectOutput(stdout.toFile()).redirectError(stderr.toFile()).start();
        try {
            assertThat(process.waitFor(30, TimeUnit.SECONDS)).isTrue();
            assertThat(process.exitValue()).withFailMessage("keyless child failed: %s", Files.readString(stderr)).isZero();
            assertThat(Files.readString(stdout).trim()).isEqualTo("KEYLESS_HANDOFF_OK");
            var flags = mapper.readTree(report.toFile());
            assertThat(flags.path("unexpected_names")).isEmpty();
            assertThat(flags.path("no_user_site").asBoolean()).isTrue();
            assertThat(flags.path("no_bytecode").asBoolean()).isTrue();
        } finally { process.destroyForcibly(); assertThat(process.waitFor(3, TimeUnit.SECONDS)).isTrue(); }
        assertThat(CitizenExtractionArchiveTest.tree(fixture.directory())).isEqualTo(before);
    }

    public static final class EnvironmentChild {
        public static void main(String[] args) {
            new HumanHandoffArchiveReader(new ReviewedImportReader(), args[0], args[1], 10_000)
                    .read(args[2], args[3], Path.of(args[4]));
            System.out.println("KEYLESS_HANDOFF_OK");
        }
    }

    private static String javaClasspath() throws Exception {
        var entries = new LinkedHashSet<String>(); entries.add(System.getProperty("java.class.path"));
        for (ClassLoader loader = CitizenHumanHandoffArchiveTest.class.getClassLoader(); loader != null; loader = loader.getParent()) {
            if (loader instanceof URLClassLoader urls) for (var url : urls.getURLs()) entries.add(Path.of(url.toURI()).toString());
        }
        for (Class<?> type : List.of(CitizenHumanHandoffArchiveTest.class, HumanHandoffArchiveReader.class)) {
            var source = type.getProtectionDomain().getCodeSource();
            if (source != null) entries.add(Path.of(source.getLocation().toURI()).toString());
        }
        return String.join(java.io.File.pathSeparator, entries);
    }

    Path probe(String body) throws Exception { var helper = new HumanHandoffArchiveReaderTest(); helper.root = root; return helper.probe(body); }
    void rewrite(Path file, JsonNode value) throws Exception {
        Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("rw-------")); Files.writeString(file, value.toString());
        Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("r--------"));
    }
    void invalid(org.assertj.core.api.ThrowableAssert.ThrowingCallable action) {
        assertThatThrownBy(action).isInstanceOfSatisfying(ExtractionException.class, error -> assertThat(error.code()).isEqualTo("EXTRACTION_ARCHIVE_INVALID"));
    }

    Fixture fixture(String testCase) throws Exception {
        Path work = Files.createTempDirectory(root.toRealPath(), "citizen-handoff-");
        String script = """
                import json, sys
                from pathlib import Path
                from processing.tests.test_citizen_handoff import create_citizen_handoff_fixture
                print(json.dumps(create_citizen_handoff_fixture(Path(sys.argv[1]), case=sys.argv[2]), default=str))
                """;
        var process = PythonProcess.executeKeyless(PythonProbe.PYTHON, PythonProbe.REPO.toString(),
                List.of("-B", "-s", "-c", script, work.toString(), testCase), new byte[0], 30_000);
        assertThat(process.exitCode()).as(new String(process.stderr(), java.nio.charset.StandardCharsets.UTF_8)).isZero();
        JsonNode value = mapper.readTree(process.stdout());
        return new Fixture(Path.of(value.path("handoff_root").asText()), value.path("handoff_ref").asText(), value.path("receipt_sha256").asText(),
                Path.of(value.path("source_root").asText()), Path.of(value.path("source_file").asText()),
                Path.of(value.path("run_root").asText()), Path.of(value.path("review_root").asText()));
    }

    HumanHandoffArchiveReader reader(Path workdir, long timeout) {
        return new HumanHandoffArchiveReader(json, PythonProbe.PYTHON, workdir.toString(), timeout);
    }
    Set<String> keys(JsonNode node) { var keys = new HashSet<String>(); node.fieldNames().forEachRemaining(keys::add); return keys; }
    record Fixture(Path handoffRoot, String ref, String hash, Path sourceRoot, Path sourceFile, Path runRoot, Path reviewRoot) {
        Path directory() { return handoffRoot.resolve(ref); }
    }
}
