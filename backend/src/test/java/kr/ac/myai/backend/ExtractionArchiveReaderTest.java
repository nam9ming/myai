package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.LinkOption;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

class ExtractionArchiveReaderTest {
    @TempDir Path root;
    final ReviewedImportReader json = new ReviewedImportReader();
    final String id = "71fb66f0-e610-4f9c-8f26-4bb77655ee8c";

    @Test
    void readsActualChunkedCyclesAndSealedReuseWithFinalWholeOutputHash() throws Exception {
        Path input = ChunkedArchiveFixtures.input(root);
        Path archive = ChunkedArchiveFixtures.archive(root, input, id, "fixture-nfc-v1", "retry");
        var result = reader(PythonProbe.REPO, 10000).read(id, archive);
        assertThat(result.attempts()).isEqualTo(2);
        assertThat(result.receipt().path("format_version").asText()).isEqualTo("extraction-archive-v2");
        assertThat(result.metadata().path("prompt_version").asText()).isEqualTo("prompt-v3");
        assertThat(result.status()).isEqualTo("validated");
        assertThat(result.outputSha256()).isEqualTo(ReviewedImportReader.sha256(Files.readAllBytes(result.directory().resolve("attempt-2.output"))));
        assertThat(Files.readAllBytes(result.directory().resolve("attempt-1.output"))).isEmpty();
        var before = tree();
        assertThat(reader(PythonProbe.REPO, 10000).readSealed(id, archive).receipt()).isEqualTo(result.receipt());
        assertThat(tree()).isEqualTo(before);
    }

    @Test
    void readsChunkedPermanentFailureAndRejectsChangedSubrequest() throws Exception {
        Path input = ChunkedArchiveFixtures.input(root);
        Path archive = ChunkedArchiveFixtures.archive(root, input, id, "fixture-nfc-v1", "permanent");
        var result = reader(PythonProbe.REPO, 10000).readSealed(id, archive);
        assertThat(result.status()).isEqualTo("failed");
        assertThat(result.attempts()).isEqualTo(1);
        assertThat(result.receipt().path("total_calls").asInt()).isEqualTo(1);
        assertThat(result.receipt().path("attempts").get(0).path("chunks").get(1).path("attempted").asBoolean(true)).isFalse();
        assertThat(Files.readAllBytes(result.directory().resolve("attempt-1.output"))).isEmpty();
        Path output = result.directory().resolve("attempt-1-chunk-000001.response");
        output.toFile().setWritable(true, true); Files.writeString(output, "changed"); output.toFile().setWritable(false, false);
        var before = tree();
        assertThatThrownBy(() -> reader(PythonProbe.REPO, 10000).readSealed(id, archive)).isInstanceOf(ExtractionException.class);
        assertThat(tree()).isEqualTo(before);
    }

    @Test
    void keepsThreeFailedDocumentCyclesSeparateFromActualHttpCalls() throws Exception {
        Path input = ChunkedArchiveFixtures.input(root);
        Path archive = ChunkedArchiveFixtures.archive(root, input, id, "fixture-nfc-v1", "all-failed");
        var result = reader(PythonProbe.REPO, 10000).readSealed(id, archive);
        assertThat(result.status()).isEqualTo("failed");
        assertThat(result.attempts()).isEqualTo(3);
        assertThat(result.metadata().path("attempts").asInt()).isEqualTo(3);
        assertThat(result.receipt().path("total_calls").asInt()).isEqualTo(6);
        assertThat(Files.readAllBytes(result.directory().resolve("attempt-3.output"))).isEmpty();
        assertThat(result.receipt().path("artifacts").has("attempt-3-chunk-000002.response")).isTrue();
    }

    @Test
    void rejectsFinalOutputChangedAfterPythonVerification() throws Exception {
        Path archive = archive(false);
        String receipt = Files.readString(archive.resolve(id).resolve("receipt.json"));
        String target = new ObjectMapper().writeValueAsString(archive.resolve(id).resolve("attempt-1.output").toString());
        Path probe = probe("p=Path(" + target + ");p.chmod(0o600);p.write_bytes(p.read_bytes()+b' ');p.chmod(0o400)\nprint(" + quotedPacket(receipt) + ")");
        assertThatThrownBy(() -> reader(probe, 3000).read(id, archive)).isInstanceOfSatisfying(ExtractionException.class,
                ex -> assertThat(ex.code()).isEqualTo("EXTRACTION_ARCHIVE_INVALID"));
    }

    @Test
    void preservesOversizedFailedManualOutputWithoutChangingArchive() throws Exception {
        byte[] raw = new byte[8 * 1024 * 1024 + 17]; java.util.Arrays.fill(raw, (byte) 'x');
        raw[raw.length - 1] = (byte) 0xff;
        Path archive = archive(true, 1, raw);
        var before = tree();
        var result = reader(PythonProbe.REPO, 10000).read(id, archive);
        assertThat(result.status()).isEqualTo("failed");
        assertThat(result.receipt().path("format_version").asText()).isEqualTo("extraction-archive-v1");
        assertThat(result.receipt().path("attempts").get(0).path("error_code").asText()).isEqualTo("JSON_LIMIT");
        assertThat(result.receipt().path("artifacts").path("attempt-1.output").path("size").asLong()).isEqualTo(raw.length);
        assertThat(result.outputSha256()).isEqualTo(ReviewedImportReader.sha256(raw));
        assertThat(reader(PythonProbe.REPO, 10000).readSealed(id, archive).receipt()).isEqualTo(result.receipt());
        assertThat(tree()).isEqualTo(before);
    }

    @Test
    void rejectsSameSizeChangeBeyondOutputLimitAfterPythonVerification() throws Exception {
        byte[] raw = new byte[8 * 1024 * 1024 + 17]; java.util.Arrays.fill(raw, (byte) 'x');
        raw[raw.length - 1] = (byte) 0xff;
        Path archive = archive(true, 1, raw);
        String receipt = Files.readString(archive.resolve(id).resolve("receipt.json"));
        String target = new ObjectMapper().writeValueAsString(archive.resolve(id).resolve("attempt-1.output").toString());
        Path probe = probe("p=Path(" + target + ");p.chmod(0o600)\n"
                + "with p.open('r+b') as stream:\n stream.seek(-1,2);stream.write(b'x')\n"
                + "p.chmod(0o400)\nprint(" + quotedPacket(receipt) + ");sys.exit(4)");
        assertThatThrownBy(() -> reader(probe, 3000).readSealed(id, archive)).isInstanceOfSatisfying(ExtractionException.class,
                ex -> assertThat(ex.code()).isEqualTo("EXTRACTION_ARCHIVE_INVALID"));
    }

    @Test
    void acceptsApiArchiveWithResponseArtifactsAndMeasuredUsage() throws Exception {
        Path archive = apiArchive(root, PythonProbe.REPO.resolve("contracts/examples/ai-input.json"), id, "fixture-nfc-v1");
        var result = reader(PythonProbe.REPO, 10000).read(id, archive);
        assertThat(result.metadata().path("execution_mode").asText()).isEqualTo("api");
        assertThat(result.metadata().path("usage_in").asInt()).isEqualTo(17);
        assertThat(result.metadata().path("usage_out").asInt()).isEqualTo(31);
        assertThat(result.receipt().path("artifacts").size()).isEqualTo(6);
        assertThat(result.receipt().path("artifacts").has("attempt-1.response")).isTrue();
        assertThat(result.status()).isEqualTo("validated");
    }

    static Path apiArchive(Path work, Path input, String runId, String preprocessing) throws Exception {
        Files.createDirectories(work);
        Path archive = work.resolve("api-archive");
        String script = """
                import json, sys, hashlib
                from pathlib import Path
                from unittest.mock import patch
                from processing.extraction.api import run_api
                source, root, run_id, preprocessing = sys.argv[1:]
                document = json.loads(Path(source).read_bytes())
                output = json.loads(Path('contracts/examples/ai-extraction.json').read_bytes())
                output['document_version_id'] = document['document_version_id']
                block = document['blocks'][0]
                output['evidence'][0].update(block_id=block['block_id'], quote=block['text'], start_char=0,
                    end_char=len(block['text']), text_sha256=hashlib.sha256(block['text'].encode()).hexdigest())
                response = dict(object='response', status='completed', error=None, model='gpt-6.1-sol',
                    output=[dict(type='message', role='assistant', status='completed',
                        content=[dict(type='output_text', text=json.dumps(output, ensure_ascii=False))])],
                    usage=dict(input_tokens=17, output_tokens=31))
                with patch('processing.extraction.api._exchange', return_value=(200, json.dumps(response).encode(), None, True)):
                    result = run_api(source, preprocessing, root, run_id)
                assert result['status'] == 'validated'
                """;
        var builder = new ProcessBuilder(PythonProbe.PYTHON, "-c", script, input.toString(), archive.toString(), runId, preprocessing)
                .directory(PythonProbe.REPO.toFile());
        builder.environment().put("OPENAI_API_KEY", "TEST_ONLY_OPENAI_KEY");
        builder.environment().put("OPENAI_MODEL", "gpt-6.1-sol");
        var process = builder.start();
        assertThat(process.waitFor(10, TimeUnit.SECONDS)).isTrue();
        assertThat(process.exitValue()).isZero();
        return archive;
    }

    @Test
    void readsActualPythonValidatedArchiveAndPreservesOriginalMetadata() throws Exception {
        Path archive = archive(false);
        var result = reader(PythonProbe.REPO, 10000).read(id, archive);
        assertThat(result.metadata().path("cost").decimalValue()).isEqualByComparingTo("0.1234567890123456789");
        assertThat(result.metadataJson()).isEqualTo(Files.readString(archive.resolve(id).resolve("metadata.json")));
        assertThat(result.receipt().path("status").asText()).isEqualTo("validated");
        assertThat(result.receipt().path("review_required").asBoolean()).isTrue();
        assertThat(result.receipt().path("run_id").asText()).isEqualTo(id);
        assertThat(result.input().path("data_kind").asText()).isEqualTo("synthetic");
    }

    @Test
    void bindsReturnedReceiptTagToTheActualInput() throws Exception {
        Path archive = archive(false);
        Path receiptPath = archive.resolve(id).resolve("receipt.json");
        String changed = Files.readString(receiptPath).replace("\"data_kind\":\"synthetic\"", "\"data_kind\":\"real\"");
        receiptPath.toFile().setWritable(true, true);
        Files.writeString(receiptPath, changed);
        receiptPath.toFile().setWritable(false, false);
        Path probe = probe("print(" + quotedPacket(changed) + ")");
        assertThatThrownBy(() -> reader(probe, 3000).read(id, archive)).isInstanceOf(ExtractionException.class);
    }

    @Test
    void preservesMultipleAttemptResultsAndLastStatus() throws Exception {
        var result = reader(PythonProbe.REPO, 10000).read(id, archive(false, 2));
        assertThat(result.attempts()).isEqualTo(2);
        assertThat(result.receipt().path("attempts").get(0).path("status").asText()).isEqualTo("failed");
        assertThat(result.receipt().path("attempts").get(1).path("status").asText()).isEqualTo("validated");
        assertThat(result.status()).isEqualTo("validated");
    }

    @Test
    void readsSealedMultipleAttemptArchiveWithoutChangingFilesOrModes() throws Exception {
        Path archive = archive(false, 2);
        var before = tree();
        var result = reader(PythonProbe.REPO, 10000).readSealed(id, archive);
        assertThat(result.directory()).isEqualTo(archive.resolve(id).toRealPath());
        assertThat(result.attempts()).isEqualTo(2);
        assertThat(result.receipt().path("attempts").get(0).path("status").asText()).isEqualTo("failed");
        assertThat(result.status()).isEqualTo("validated");
        assertThat(tree()).isEqualTo(before);
    }

    @Test
    void readsSealedFailedNonUtf8ArchiveWithoutDiscardingRawOutput() throws Exception {
        Path archive = archive(true);
        var before = tree();
        var result = reader(PythonProbe.REPO, 10000).readSealed(id, archive);
        assertThat(result.status()).isEqualTo("failed");
        assertThat(Files.readAllBytes(result.directory().resolve("attempt-1.output"))).containsExactly((byte) 0xff);
        assertThat(tree()).isEqualTo(before);
    }

    @Test
    void refusesMutableArchiveWithoutCreatingFrozenCopiesOrRepairingModes() throws Exception {
        Path archive = archive(false);
        unseal(archive.resolve(id));
        var before = tree();
        assertThatThrownBy(() -> reader(PythonProbe.REPO, 10000).readSealed(id, archive))
                .isInstanceOfSatisfying(ExtractionException.class,
                        ex -> assertThat(ex.code()).isEqualTo("EXTRACTION_ARCHIVE_INVALID"));
        assertThat(tree()).isEqualTo(before);
    }

    @Test
    void refusesMissingSealedArtifactsWithoutRepair() throws Exception {
        Path archive = archive(false);
        Path directory = archive.resolve(id);
        directory.toFile().setWritable(true, true);
        Files.delete(directory.resolve("attempt-1.output"));
        directory.toFile().setWritable(false, false);
        var before = tree();
        assertThatThrownBy(() -> reader(PythonProbe.REPO, 10000).readSealed(id, archive))
                .isInstanceOfSatisfying(ExtractionException.class,
                        ex -> assertThat(ex.code()).isEqualTo("EXTRACTION_ARCHIVE_INVALID"));
        assertThat(tree()).isEqualTo(before);
    }

    private Map<String, String> tree() throws Exception {
        var result = new TreeMap<String, String>();
        try (var paths = Files.walk(root)) {
            for (Path path : paths.toList()) {
                String content = Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)
                        ? ReviewedImportReader.sha256(Files.readAllBytes(path)) : "directory";
                result.put(root.relativize(path).toString(), Files.getPosixFilePermissions(path).toString() + ":" + content);
            }
        }
        return result;
    }

    @Test
    void rejectsMetadataChangedAfterPythonVerification() throws Exception {
        Path archive = archive(false);
        String receipt = Files.readString(archive.resolve(id).resolve("receipt.json"));
        String target = new ObjectMapper().writeValueAsString(archive.resolve(id).resolve("metadata.json").toString());
        Path probe = probe("p=Path(" + target + ");p.chmod(0o600);p.write_bytes(p.read_bytes()+b' ');p.chmod(0o400)\nprint(" + quotedPacket(receipt) + ")");
        assertThatThrownBy(() -> reader(probe, 3000).read(id, archive)).isInstanceOfSatisfying(ExtractionException.class,
                ex -> assertThat(ex.code()).isEqualTo("EXTRACTION_ARCHIVE_INVALID"));
    }

    @Test
    void acceptsPreservedFailedRunButRejectsTamperIncompleteSymlinkAndBadPaths() throws Exception {
        Path archive = archive(true);
        var result = reader(PythonProbe.REPO, 10000).read(id, archive);
        assertThat(result.receipt().path("status").asText()).isEqualTo("failed");
        assertThat(result.receipt().path("attempts").get(0).path("failure_kind").asText()).isEqualTo("schema");
        unseal(archive.resolve(id));
        Files.writeString(archive.resolve(id).resolve("attempt-1.output"), "PRIVATE_VALUE changed");
        assertThatThrownBy(() -> reader(PythonProbe.REPO, 10000).read(id, archive)).isInstanceOf(ExtractionException.class).hasMessageNotContaining("PRIVATE_VALUE");
        assertThatThrownBy(() -> reader(PythonProbe.REPO, 10000).read("../PRIVATE_VALUE", archive)).isInstanceOf(ExtractionException.class);
        assertThatThrownBy(() -> reader(PythonProbe.REPO, 10000).read(id, Path.of("relative/PRIVATE_VALUE"))).isInstanceOf(ExtractionException.class);
        Path link = root.resolve("alias"); Files.createSymbolicLink(link, archive);
        assertThatThrownBy(() -> reader(PythonProbe.REPO, 10000).read(id, link)).isInstanceOf(ExtractionException.class);
        Files.delete(archive.resolve(id).resolve("receipt.json"));
        assertThatThrownBy(() -> reader(PythonProbe.REPO, 10000).read(id, archive)).isInstanceOf(ExtractionException.class);
    }

    @Test
    void refusesFabricatedStatusExitOrRunAndKillsTimedOutProcess() throws Exception {
        Path archive = archive(false);
        String good = Files.readString(archive.resolve(id).resolve("receipt.json"));
        for (String body : List.of("print('PRIVATE_VALUE')", "print(" + quotedPacket(good.replace("validated", "failed")) + ")",
                "print(" + quotedPacket(good) + ");sys.exit(4)", "print(" + quotedPacket(good.replace(id, "10000000-0000-4000-8000-000000000001")) + ")")) {
            var probe = probe(body);
            assertThatThrownBy(() -> reader(probe, 3000).read(id, archive)).isInstanceOf(ExtractionException.class).hasMessageNotContaining("PRIVATE_VALUE");
        }
        Path slow = probe("time.sleep(30)");
        assertThatThrownBy(() -> reader(slow, 300).read(id, archive)).isInstanceOf(ExtractionException.class);
        assertThat(PythonProbe.processes(slow)).noneMatch(ProcessHandle::isAlive);
    }

    Path archive(boolean failed) throws Exception {
        return archive(failed, 1);
    }

    Path archive(boolean failed, int attempts) throws Exception {
        return archive(failed, attempts, null);
    }

    private Path archive(boolean failed, int attempts, byte[] rawOutput) throws Exception {
        Path archive = root.resolve("archive");
        Path metadata = root.resolve("metadata.json");
        String meta = Files.readString(PythonProbe.REPO.resolve("processing/examples/extraction-metadata.json"))
                .replace("\"cost\": null", "\"cost\": 0.1234567890123456789")
                .replace("\"attempts\": 1", "\"attempts\": " + attempts);
        Files.writeString(metadata, meta);
        Path prompt = Files.writeString(root.resolve("prompt.txt"), "합성 수동 도구 입력 전문; 실제 모델 호출 없음");
        Path output = root.resolve("output.json");
        Files.write(output, rawOutput != null ? rawOutput : failed ? new byte[]{(byte) 0xff} : Files.readAllBytes(PythonProbe.REPO.resolve("contracts/examples/ai-extraction.json")));
        var command = new java.util.ArrayList<>(List.of(PythonProbe.PYTHON, "-m", "processing.extraction", "import", "--input",
                PythonProbe.REPO.resolve("contracts/examples/ai-input.json").toString(), "--metadata", metadata.toString(),
                "--root", archive.toString()));
        for (int i = 0; i < attempts; i++) {
            Path selected = i == 0 && attempts > 1 ? Files.writeString(root.resolve("first-failed-output"), "not json") : output;
            command.addAll(List.of("--attempt", prompt.toString(), selected.toString()));
        }
        var process = new ProcessBuilder(command).directory(PythonProbe.REPO.toFile()).start();
        assertThat(process.waitFor(10, TimeUnit.SECONDS)).isTrue();
        assertThat(process.exitValue()).isEqualTo(failed ? 4 : 0);
        var freeze = new ProcessBuilder(PythonProbe.PYTHON, "-m", "processing.extraction", "freeze", id, "--root", archive.toString())
                .directory(PythonProbe.REPO.toFile()).start();
        assertThat(freeze.waitFor(10, TimeUnit.SECONDS)).isTrue(); assertThat(freeze.exitValue()).isEqualTo(failed ? 4 : 0);
        var packet = new ObjectMapper().readTree(freeze.getInputStream().readAllBytes());
        return archive.resolve(packet.path("snapshot_ref").asText()).getParent();
    }

    Path probe(String body) throws Exception {
        Path probe = PythonProbe.create(root, "");
        Path module = Files.createDirectories(probe.resolve("processing/extraction"));
        Files.writeString(module.resolve("__init__.py"), "");
        Files.writeString(module.resolve("__main__.py"), "import sys,time,os\nfrom pathlib import Path\nPath('pid-'+str(os.getpid())).write_text(str(os.getpid()))\n" + body);
        return probe;
    }

    ExtractionArchiveReader reader(Path workdir, long timeout) {
        return new ExtractionArchiveReader(json, PythonProbe.PYTHON, workdir.toString(), timeout);
    }

    String quotedPacket(String receipt) throws Exception {
        var mapper = new ObjectMapper();
        var packet = mapper.createObjectNode().put("protocol_version", "extraction-registration-v1").put("snapshot_ref", id);
        packet.set("receipt", mapper.readTree(receipt));
        return mapper.writeValueAsString(packet.toString());
    }

    @AfterEach
    void makeOwnedTempsRemovable() throws Exception { unseal(root); }

    static void unseal(Path directory) throws Exception {
        try (var paths = Files.walk(directory)) {
            for (Path path : paths.toList()) if (!Files.isSymbolicLink(path)) path.toFile().setWritable(true, true);
        }
    }
}
