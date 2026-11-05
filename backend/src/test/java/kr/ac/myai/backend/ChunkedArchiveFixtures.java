package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

final class ChunkedArchiveFixtures {
    static void enlarge(ObjectNode document, String blocksKey) {
        var blocks = document.withArray(blocksKey);
        for (int index = 1; index <= 3; index++) blocks.addObject().put("block_id", "chunk-fixture-" + index)
                .put("text", "x".repeat(48000)).putNull("page");
        if (blocksKey.equals("block_index")) {
            var text = new StringBuilder();
            for (var block : blocks) { if (!text.isEmpty()) text.append('\n'); text.append(block.path("text").asText()); }
            document.put("cleaned_text", text.toString()).put("text_sha256", ReviewedImportReader.sha256(text.toString().getBytes(StandardCharsets.UTF_8)));
            for (var check : document.path("checks")) if (check.path("result").asText().equals("verified"))
                ((ObjectNode) check).set("text_sha256", document.path("text_sha256"));
        }
    }

    static Path input(Path work) throws Exception {
        Files.createDirectories(work);
        var document = (ObjectNode) new ObjectMapper().readTree(PythonProbe.REPO.resolve("contracts/examples/ai-input.json").toFile());
        enlarge(document, "blocks");
        return Files.writeString(work.resolve("chunk-input.json"), document.toString());
    }

    static Path archive(Path work, Path input, String run, String preprocessing, String mode) throws Exception {
        Files.createDirectories(work);
        Path archive = work.resolve("chunk-archive");
        String script = """
                import json, sys
                from pathlib import Path
                from unittest.mock import patch
                from processing.extraction.api import run_api
                from processing.extraction.archive import freeze_run
                source, root, run, preprocessing, mode = sys.argv[1:]
                document = json.loads(Path(source).read_bytes())
                output = dict(schema_version='extract-schema-v1', document_version_id=document['document_version_id'],
                    items=[], evidence=[], warnings=['CHUNK_CONTEXT_PARTIAL', 'NO_EVENT_FOUND'])
                response = dict(object='response', status='completed', error=None, model='gpt-6.1-sol',
                    output=[dict(type='message', role='assistant', status='completed',
                        content=[dict(type='output_text', text=json.dumps(output))])],
                    usage=dict(input_tokens=17, output_tokens=31))
                calls = 0
                def exchange(*args, **kwargs):
                    global calls
                    calls += 1
                    if mode == 'permanent': return 400, b'{}', None, True
                    if mode == 'all-failed' or mode == 'retry' and calls == 1: return 500, b'{}', None, True
                    return 200, json.dumps(response).encode(), None, True
                with patch('processing.extraction.api._exchange', side_effect=exchange), patch('processing.extraction.api.time.sleep'):
                    result = run_api(source, preprocessing, root, run, model='gpt-6.1-sol')
                expected = 'failed' if mode in ('permanent', 'all-failed') else 'validated'
                assert result['status'] == expected, result
                frozen = freeze_run(run, root)
                assert frozen['receipt']['format_version'] == 'extraction-archive-v2'
                assert frozen['receipt']['total_calls'] == calls
                print(json.dumps(dict(root=str((Path(root) / frozen['snapshot_ref']).parent))))
                """;
        var builder = new ProcessBuilder(PythonProbe.PYTHON, "-c", script, input.toString(), archive.toString(), run, preprocessing, mode)
                .directory(PythonProbe.REPO.toFile());
        builder.environment().put("OPENAI_API_KEY", "TEST_ONLY_OPENAI_KEY");
        builder.environment().put("OPENAI_MODEL", "gpt-6.1-sol");
        var process = builder.start();
        assertThat(process.waitFor(30, TimeUnit.SECONDS)).isTrue();
        assertThat(process.exitValue()).as(new String(process.getErrorStream().readAllBytes(), StandardCharsets.UTF_8)).isZero();
        return Path.of(new ObjectMapper().readTree(process.getInputStream().readAllBytes()).path("root").asText());
    }

    private ChunkedArchiveFixtures() { }
}
