package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.handoff.HandoffReference;
import kr.ac.myai.backend.handoff.HumanHandoffArchiveReader;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermission;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

class HumanHandoffArchiveReaderTest {
    @TempDir Path root;
    final ReviewedImportReader json = new ReviewedImportReader();

    @Test
    void readsRealHumanReviewHandoffFromChunkedValidatedAndFailedParents() throws Exception {
        var fixtures = new SourceReviewFixtures(root, null, json, null);
        for (String mode : List.of("success", "permanent")) {
            Path work = Files.createDirectories(root.resolve(mode));
            var source = (ObjectNode) new ObjectMapper().readTree(PythonProbe.REPO.resolve("backend/examples/source-import.json").toFile());
            var document = SourceReviewFixtures.document(source); ChunkedArchiveFixtures.enlarge(document, "block_index");
            var input = new ObjectMapper().createObjectNode().put("data_kind", source.path("data_kind").asText());
            for (String key : List.of("document_version_id", "title", "published_date")) input.set(key, document.path(key));
            input.set("blocks", document.path("block_index")); Path inputFile = Files.writeString(work.resolve("input.json"), input.toString());
            String run = java.util.UUID.randomUUID().toString();
            Path archive = ChunkedArchiveFixtures.archive(work, inputFile, run, document.path("preprocessing_version").asText(), mode);
            var handoff = fixtures.handoff(source, run, archive);
            JsonNode receipt = new ObjectMapper().readTree(handoff.image().resolve("receipt.json").toFile());
            String reference = receipt.path("handoff_ref").asText();
            String hash = ReviewedImportReader.sha256(Files.readAllBytes(handoff.image().resolve("receipt.json")));
            var result = reader(PythonProbe.REPO, 10000).read(reference, hash, handoff.directory());
            assertThat(result.projection().path("parent").path("status").asText()).isEqualTo(mode.equals("success") ? "validated" : "failed");
            assertThat(result.review().path("changes")).isNotEmpty();
            assertThat(result.projection().path("events")).hasSize(1);
            assertThat(reader(PythonProbe.REPO, 10000).read(result.reference()).receipt()).isEqualTo(result.receipt());
        }
    }

    @Test
    void readsFrozenHandoffAfterOriginalReviewAndRunPathsAreRemoved() throws Exception {
        Fixture fixture = fixture("api");
        var result = reader(PythonProbe.REPO, 10000).read(fixture.reference(), fixture.hash(), fixture.directory().getParent());
        JsonNode projection = result.projection(), review = result.review();
        assertThat(projection.path("schema_version").asText()).isEqualTo("human-handoff-projection-v1");
        assertThat(projection.path("parent").path("status").asText()).isEqualTo("validated");
        assertThat(review.path("review").path("started_at").asText()).isEqualTo("2020-01-01T04:00:00.999999999Z");
        assertThat(review.path("review").path("finished_at").asText()).isEqualTo("2020-01-01T04:00:01.000000001Z");
        assertThat(result.receipt().path("summary").path("review_duration_ns").asLong()).isEqualTo(2);
        assertThat(result.directory()).isEqualTo(fixture.directory());
        assertThat(result.reference()).isEqualTo(new HandoffReference(fixture.directory().toString(), fixture.reference(), fixture.hash()));
        assertThat(reader(PythonProbe.REPO, 10000).read(result.reference()).projection()).isEqualTo(projection);
    }

    @Test
    void verifiesHandoffWithoutWritingPythonBytecodeIntoWorkdir() throws Exception {
        Fixture fixture = fixture("manual");
        String receipt = Files.readString(fixture.directory().resolve("receipt.json"));
        Path probe = probe("print(" + quote(receipt) + ")");
        Path launcher = Files.writeString(root.resolve("python-launcher"), "#!/bin/sh\n"
                + "unset PYTHONDONTWRITEBYTECODE PYTHONPYCACHEPREFIX\n"
                + "exec '" + PythonProbe.PYTHON.replace("'", "'\\''") + "' \"$@\"\n");
        Files.setPosixFilePermissions(launcher, Set.of(PosixFilePermission.OWNER_READ,
                PosixFilePermission.OWNER_WRITE, PosixFilePermission.OWNER_EXECUTE));
        var reader = new HumanHandoffArchiveReader(json, launcher.toString(), probe.toString(), 10000);
        var result = reader.read(fixture.reference(), fixture.hash(), fixture.directory().getParent());
        assertThat(result.projection().path("parent").path("execution_mode").asText()).isEqualTo("manual_import");
        try (var files = Files.walk(probe)) {
            assertThat(files.map(path -> path.getFileName().toString()).toList()).doesNotContain("__pycache__");
        }
    }

    @Test
    void preservesFailedManualAndEmptyProjectionWithoutInventingWorkflow() throws Exception {
        for (String mode : List.of("failed", "manual", "empty")) {
            Fixture fixture = fixture(mode);
            var result = reader(PythonProbe.REPO, 10000).read(fixture.reference(), fixture.hash(), fixture.directory().getParent());
            assertThat(result.projection().path("parent").path("status").asText()).isEqualTo(mode.equals("failed") ? "failed" : "validated");
            assertThat(result.projection().path("parent").path("execution_mode").asText()).isEqualTo(mode.equals("manual") ? "manual_import" : "api");
            if (mode.equals("empty")) {
                assertThat(result.projection().path("events")).isEmpty();
                assertThat(result.projection().path("evidence")).isNotEmpty();
            } else {
                assertThat(result.projection().path("events").get(0).has("revision")).isFalse();
                assertThat(result.projection().path("events").get(0).path("facts").has("reviewer_id")).isFalse();
            }
        }
    }

    @Test
    void preservesDeclaredNanosecondDurationBeyondLongRange() throws Exception {
        Fixture fixture = fixture("long-duration");
        var result = reader(PythonProbe.REPO, 10000).read(fixture.reference(), fixture.hash(), fixture.directory().getParent());
        assertThat(result.receipt().path("summary").path("review_duration_ns").bigIntegerValue())
                .isEqualTo(new java.math.BigInteger("15147388800000000002"));
    }

    @Test
    void validatesExactNonemptyUniqueReferencesAndOnlyMissingOrNullMeansAbsent() throws Exception {
        var mapper = new ObjectMapper();
        var entry = mapper.createObjectNode().put("directory", root.toRealPath().resolve("a".repeat(64)).toString())
                .put("handoff_ref", "a".repeat(64)).put("receipt_sha256", "b".repeat(64));
        var references = mapper.createArrayNode().add(entry);
        assertThat(HandoffReference.list(references)).containsExactly(new HandoffReference(entry.path("directory").asText(), "a".repeat(64), "b".repeat(64)));
        assertThat(HandoffReference.list(mapper.createObjectNode().path("missing"))).isEmpty();
        assertThat(HandoffReference.list(mapper.nullNode())).isEmpty();
        for (JsonNode invalid : List.of(mapper.createArrayNode(), entry, mapper.createArrayNode().add(entry).add(entry),
                mapper.createArrayNode().add(entry.deepCopy().put("extra", "PRIVATE_VALUE")),
                mapper.createArrayNode().add(entry.deepCopy().put("directory", "relative/PRIVATE_VALUE")),
                mapper.createArrayNode().add(entry.deepCopy().put("handoff_ref", "A".repeat(64))),
                mapper.createArrayNode().add(entry.deepCopy().put("receipt_sha256", true)),
                mapper.createArrayNode().add(entry.deepCopy().put("directory", root.resolve("other").toString())))) {
            assertThatThrownBy(() -> HandoffReference.list(invalid)).isInstanceOf(ExtractionException.class).hasMessageNotContaining("PRIVATE_VALUE");
        }
    }

    @Test
    void refusesWrongHashBadPathsAndSymbolicDirectoryAncestors() throws Exception {
        Fixture fixture = fixture("api");
        var reader = reader(PythonProbe.REPO, 10000);
        assertThatThrownBy(() -> reader.read(fixture.reference(), "0".repeat(64), fixture.directory().getParent())).isInstanceOf(ExtractionException.class);
        assertThatThrownBy(() -> reader.read("../PRIVATE_VALUE", fixture.hash(), fixture.directory().getParent())).isInstanceOf(ExtractionException.class);
        assertThatThrownBy(() -> reader.read(fixture.reference(), fixture.hash(), Path.of("relative/PRIVATE_VALUE"))).isInstanceOf(ExtractionException.class);
        assertThatThrownBy(() -> reader.read(fixture.reference(), fixture.hash(), fixture.directory().getParent().resolve("child/.."))).isInstanceOf(ExtractionException.class);
        Path alias = root.resolve("alias"); Files.createSymbolicLink(alias, fixture.directory().getParent());
        assertThatThrownBy(() -> reader.read(fixture.reference(), fixture.hash(), alias)).isInstanceOf(ExtractionException.class);
        Path wrapper = Files.createDirectory(root.resolve("wrapper"));
        Files.createSymbolicLink(wrapper.resolve(fixture.reference()), fixture.directory());
        assertThatThrownBy(() -> reader.read(fixture.reference(), fixture.hash(), wrapper.toRealPath())).isInstanceOf(ExtractionException.class);
        Path ancestor = root.resolve("ancestor"); Files.createSymbolicLink(ancestor, root.toRealPath());
        assertThatThrownBy(() -> reader.read(fixture.reference(), fixture.hash(), ancestor.resolve(fixture.directory().getParent().getFileName())))
                .isInstanceOf(ExtractionException.class).hasMessageNotContaining("PRIVATE_VALUE");
    }

    @Test
    void rejectsTamperedMissingWritableAndExpandedReadModes() throws Exception {
        Fixture fixture = fixture("api");
        Path projection = fixture.directory().resolve("projection.json");
        byte[] original = Files.readAllBytes(projection);
        for (String mode : List.of("tampered", "writable", "group-readable", "missing", "symlink")) {
            fixture.directory().toFile().setWritable(true, true);
            if (mode.equals("missing") || mode.equals("symlink")) Files.delete(projection);
            else {
                projection.toFile().setWritable(true, true);
                Files.write(projection, mode.equals("tampered") ? "PRIVATE_VALUE".getBytes() : original);
                Files.setPosixFilePermissions(projection, mode.equals("writable") ? Set.of(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_WRITE)
                        : mode.equals("group-readable") ? Set.of(PosixFilePermission.OWNER_READ, PosixFilePermission.GROUP_READ) : Set.of(PosixFilePermission.OWNER_READ));
            }
            if (mode.equals("symlink")) Files.createSymbolicLink(projection, Files.write(root.resolve("outside.json"), original));
            Files.setPosixFilePermissions(fixture.directory(), Set.of(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_EXECUTE));
            assertThatThrownBy(() -> reader(PythonProbe.REPO, 10000).read(fixture.reference(), fixture.hash(), fixture.directory().getParent()))
                    .isInstanceOf(ExtractionException.class).hasMessageNotContaining("PRIVATE_VALUE");
            fixture.directory().toFile().setWritable(true, true);
            if (Files.isSymbolicLink(projection)) Files.delete(projection);
            if (Files.exists(projection)) projection.toFile().setWritable(true, true);
            Files.write(projection, original);
            Files.setPosixFilePermissions(projection, Set.of(PosixFilePermission.OWNER_READ));
            Files.setPosixFilePermissions(fixture.directory(), Set.of(PosixFilePermission.OWNER_READ, PosixFilePermission.OWNER_EXECUTE));
        }
    }

    @Test
    void crossChecksReturnedReceiptAndArtifactsEvenWhenPythonClaimsSuccess() throws Exception {
        Fixture fixture = fixture("api");
        String receipt = Files.readString(fixture.directory().resolve("receipt.json"));
        ObjectNode forged = (ObjectNode) json.parseJson(receipt.getBytes());
        forged.put("handoff_ref", "0".repeat(64));
        assertThatThrownBy(() -> reader(probe("print(" + quote(forged.toString()) + ")"), 3000)
                .read(fixture.reference(), fixture.hash(), fixture.directory().getParent())).isInstanceOf(ExtractionException.class);
        for (String name : List.of("projection.json", "review/" + forged.path("summary").path("review_ref").asText() + "/review.json")) {
            Path file = fixture.directory().resolve(name);
            byte[] original = Files.readAllBytes(file);
            Path probe = probe("p=Path(" + quote(file.toString()) + ");p.chmod(0o600);p.write_bytes(p.read_bytes()+b' ');p.chmod(0o400)\nprint(" + quote(receipt) + ")");
            assertThatThrownBy(() -> reader(probe, 3000).read(fixture.reference(), fixture.hash(), fixture.directory().getParent()))
                    .isInstanceOfSatisfying(ExtractionException.class, ex -> assertThat(ex.code()).isEqualTo("EXTRACTION_ARCHIVE_INVALID"));
            file.toFile().setWritable(true, true); Files.write(file, original); file.toFile().setWritable(false, false);
        }
    }

    @Test
    void bindsProjectionAndReviewedOutputToTheActualParentDocument() throws Exception {
        for (String target : List.of("projection.json", "review.json")) {
            Fixture fixture = fixture("api");
            ObjectNode receipt = (ObjectNode) json.parseJson(Files.readAllBytes(fixture.directory().resolve("receipt.json")));
            String name = target.equals("projection.json") ? target
                    : "review/" + receipt.path("summary").path("review_ref").asText() + "/review.json";
            ObjectNode artifact = (ObjectNode) json.parseJson(Files.readAllBytes(fixture.directory().resolve(name)));
            ObjectNode document = (ObjectNode) (target.equals("projection.json") ? artifact.path("documents").get(0) : artifact.path("output"));
            document.put("document_version_id", "40000000-0000-4000-8000-000000000fff");
            byte[] changed = artifact.toString().getBytes();
            rewrite(fixture.directory().resolve(name), changed);
            ((ObjectNode) receipt.path("artifacts").path(name)).put("size", changed.length).put("sha256", ReviewedImportReader.sha256(changed));
            if (target.equals("projection.json")) ((ObjectNode) receipt.path("summary")).put("projection_sha256", ReviewedImportReader.sha256(changed));
            byte[] returned = receipt.toString().getBytes();
            rewrite(fixture.directory().resolve("receipt.json"), returned);
            Path probe = probe("print(" + quote(receipt.toString()) + ")");
            assertThatThrownBy(() -> reader(probe, 3000).read(fixture.reference(), ReviewedImportReader.sha256(returned), fixture.directory().getParent()))
                    .isInstanceOfSatisfying(ExtractionException.class, ex -> assertThat(ex.code()).isEqualTo("EXTRACTION_ARCHIVE_INVALID"));
        }
    }

    @Test
    void rejectsDirectoryReplacementAfterPythonVerification() throws Exception {
        Fixture fixture = fixture("api");
        String receipt = Files.readString(fixture.directory().resolve("receipt.json"));
        Path probe = probe("import shutil\np=Path(" + quote(fixture.directory().toString()) + ")\n"
                + "old=p.parent/'old';p.rename(old);shutil.copytree(old,p)\nprint(" + quote(receipt) + ")");
        assertThatThrownBy(() -> reader(probe, 3000).read(fixture.reference(), fixture.hash(), fixture.directory().getParent()))
                .isInstanceOfSatisfying(ExtractionException.class, ex -> assertThat(ex.code()).isEqualTo("EXTRACTION_ARCHIVE_INVALID"));
    }

    @Test
    void rejectsStrictJsonAndExcessOutputWithoutLeakingPythonText() throws Exception {
        Fixture fixture = fixture("api");
        for (String body : List.of("print('PRIVATE_VALUE')", "print('{} {}')", "print('{\"format_version\":1,\"format_version\":2}')",
                "sys.stdout.buffer.write(b'\\xff')", "print('['*101 + ']'*101)", "sys.stdout.write('x'*(8*1024*1024+1))",
                "sys.stderr.write('x'*65537);time.sleep(30)")) {
            Path probe = probe(body);
            assertThatThrownBy(() -> reader(probe, 3000).read(fixture.reference(), fixture.hash(), fixture.directory().getParent()))
                    .isInstanceOf(ExtractionException.class).hasMessageNotContaining("PRIVATE_VALUE");
            assertThat(PythonProbe.processes(probe)).noneMatch(ProcessHandle::isAlive);
        }
    }

    @Test
    void mapsPythonFailuresAndCleansUpTimedOutInterruptedProcesses() throws Exception {
        Fixture fixture = fixture("api");
        for (int exit : List.of(1, 2, 3, 5)) {
            String expected = switch (exit) {
                case 2 -> "EXTRACTION_VALIDATION_ERROR";
                case 3 -> "EXTRACTION_ARCHIVE_INVALID";
                case 5 -> "EXTRACTION_IO_ERROR";
                default -> "EXTRACTION_PROTOCOL_ERROR";
            };
            Path probe = probe("sys.stderr.write('PRIVATE_VALUE\\n');sys.exit(" + exit + ")");
            assertThatThrownBy(() -> reader(probe, 3000).read(fixture.reference(), fixture.hash(), fixture.directory().getParent()))
                    .isInstanceOfSatisfying(ExtractionException.class, ex -> {
                        assertThat(ex.code()).isEqualTo(expected);
                        assertThat(ex.getMessage()).doesNotContain("PRIVATE_VALUE", probe.toString());
                    });
        }
        Path slow = probe("time.sleep(30)");
        assertThatThrownBy(() -> reader(slow, 300).read(fixture.reference(), fixture.hash(), fixture.directory().getParent()))
                .isInstanceOfSatisfying(ExtractionException.class, ex -> assertThat(ex.retryable()).isTrue());
        assertThat(PythonProbe.processes(slow)).noneMatch(ProcessHandle::isAlive);
        Thread.currentThread().interrupt();
        try {
            assertThatThrownBy(() -> reader(PythonProbe.REPO, 10000).read(fixture.reference(), fixture.hash(), fixture.directory().getParent()))
                    .isInstanceOfSatisfying(ExtractionException.class, ex -> assertThat(ex.retryable()).isTrue());
            assertThat(Thread.currentThread().isInterrupted()).isTrue();
        } finally { Thread.interrupted(); }
    }

    HumanHandoffArchiveReader reader(Path workdir, long timeout) {
        return new HumanHandoffArchiveReader(json, PythonProbe.PYTHON, workdir.toString(), timeout);
    }

    Path probe(String body) throws Exception {
        Path probe = PythonProbe.create(root, "");
        Path module = Files.createDirectories(probe.resolve("processing/evaluation"));
        Files.writeString(module.resolve("__init__.py"), "");
        Files.writeString(module.resolve("__main__.py"), "import sys,time,os\nfrom pathlib import Path\nPath('pid-'+str(os.getpid())).write_text(str(os.getpid()))\n" + body);
        return probe;
    }

    String quote(String value) throws Exception { return new ObjectMapper().writeValueAsString(value); }

    void rewrite(Path file, byte[] bytes) throws Exception {
        file.toFile().setWritable(true, true); Files.write(file, bytes); file.toFile().setWritable(false, false);
    }

    Fixture fixture(String mode) throws Exception {
        Path target = Files.createTempDirectory(root, "handoffs-").toRealPath();
        String script = """
                import copy, hashlib, json, shutil, sys
                from pathlib import Path
                from datetime import datetime, timezone
                from unittest.mock import patch
                from processing.tests.test_human_handoff import HumanHandoffFixture
                from processing.tests.test_dataset import uid
                from processing.tests.test_extraction_prompt_metadata import metadata
                from processing.extraction.archive import _json, freeze_run, import_run
                from processing.extraction.prompt import render_prompt
                from processing.extraction.validation import parse_input
                from processing.evaluation.handoff_storage import freeze_handoff
                root, mode = Path(sys.argv[1]), sys.argv[2]
                f = HumanHandoffFixture(); f.setUp()
                try:
                    parent = f.selected
                    if mode == 'failed': parent = f.make_run(uid(552), failed=True)
                    if mode == 'manual':
                        info = metadata(); info.update(run_id=uid(553), document_version_id=f.source['document_version_id'])
                        meta, prompt, output = [f.work / n for n in ('manual-meta', 'manual-prompt', 'manual-output')]
                        meta.write_bytes(_json(info)); prompt.write_bytes(render_prompt(parse_input(f.input.read_bytes())))
                        output.write_bytes(_json(f.good_output))
                        class SourceClock(datetime):
                            @classmethod
                            def now(cls, tz=None): return cls(2020, 1, 1, 3, tzinfo=timezone.utc)
                        with patch('processing.extraction.archive.datetime', SourceClock):
                            import_run(f.input, meta, [(prompt, output)], f.run_root)
                        frozen = freeze_run(uid(553), f.run_root)
                        parent = dict(run_id=uid(553), snapshot_ref=frozen['snapshot_ref'],
                            receipt_sha256=hashlib.sha256((f.run_root / frozen['snapshot_ref'] / 'receipt.json').read_bytes()).hexdigest())
                    output = copy.deepcopy(f.good_output)
                    if mode == 'empty': output.update(items=[], warnings=['NO_EVENT_FOUND'])
                    class HandoffClock(datetime):
                        @classmethod
                        def now(cls, tz=None): return datetime.fromisoformat('2500-01-01T05:00:00Z' if mode == 'long-duration' else '2020-01-01T05:00:00Z')
                    finish = '2500-01-01T04:00:01.000000001Z' if mode == 'long-duration' else '2020-01-01T04:00:01.000000001Z'
                    frozen = '2500-01-01T04:20:00Z' if mode == 'long-duration' else '2020-01-01T04:20:00Z'
                    with patch('processing.evaluation.reviews.datetime', HandoffClock):
                        review = f.make_human(uid(991), source=parent, failed=mode == 'failed', output=output,
                            started='2020-01-01T04:00:00.999999999Z', finished=finish, frozen=frozen)
                    f.use_review(review)
                    selected = f.work / 'handoff-selection.json'; selected.write_bytes(_json(f.request))
                    with patch('processing.evaluation.human_handoff.datetime', HandoffClock), patch('processing.extraction.archive.datetime', HandoffClock):
                        receipt = freeze_handoff(selected, root, f.human_root)
                    print(json.dumps(dict(reference=receipt['handoff_ref'],
                        hash=hashlib.sha256((root / receipt['handoff_ref'] / 'receipt.json').read_bytes()).hexdigest())))
                finally: f.doCleanups()
                """;
        Process process = new ProcessBuilder(PythonProbe.PYTHON, "-c", script, target.toString(), mode)
                .directory(PythonProbe.REPO.toFile()).start();
        assertThat(process.waitFor(20, TimeUnit.SECONDS)).isTrue();
        assertThat(process.exitValue()).describedAs(new String(process.getErrorStream().readAllBytes())).isZero();
        JsonNode result = json.parseJson(process.getInputStream().readAllBytes());
        String reference = result.path("reference").asText();
        return new Fixture(target.resolve(reference), reference, result.path("hash").asText());
    }

    record Fixture(Path directory, String reference, String hash) { }

    @AfterEach
    void makeOwnedTempsRemovable() throws Exception { ExtractionArchiveReaderTest.unseal(root); }
}
