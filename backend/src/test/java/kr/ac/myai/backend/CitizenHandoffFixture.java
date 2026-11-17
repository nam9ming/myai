package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.process.PythonProcess;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.assertThat;

final class CitizenHandoffFixture {
    private static final ObjectMapper JSON = new ObjectMapper();
    private CitizenHandoffFixture() { }

    static ObjectNode source(Path root, CitizenExtractionArchiveTest.Fixture extraction) throws Exception {
        var input = JSON.readTree(extraction.input().toFile());
        var source = (ObjectNode) JSON.readTree(Path.of("examples/source-import.json").toFile());
        var document = (ObjectNode) source.path("documents").get(0);
        document.put("document_id", UUID.randomUUID().toString());
        for (String field : List.of("document_version_id", "title", "published_date")) document.set(field, input.path(field));
        document.set("block_index", input.path("blocks"));
        var blocks = new ArrayList<String>(); input.path("blocks").forEach(block -> blocks.add(block.path("text").asText()));
        byte[] raw = String.join("\n", blocks).getBytes(StandardCharsets.UTF_8);
        String filename = UUID.randomUUID() + ".txt";
        Files.write(root.resolve(filename), raw);
        document.put("raw_asset_path", filename).put("raw_sha256", ReviewedImportReader.sha256(raw))
                .put("cleaned_text", new String(raw, StandardCharsets.UTF_8)).put("text_sha256", ReviewedImportReader.sha256(raw))
                .put("preprocessing_version", "fixture-nfc-v1").put("use_review", "pending").put("check_result", "unchecked")
                .putNull("latest_check_attempt_at").putNull("last_verified_at").putArray("checks");
        return source;
    }

    static Handoff freeze(Path root, ObjectNode source, CitizenExtractionArchiveTest.Fixture extraction,
                          Consumer<ObjectNode> edit) throws Exception {
        Path work = Files.createTempDirectory(root, "citizen-handoff-").toRealPath();
        var output = (ObjectNode) JSON.readTree(PythonProbe.REPO.resolve("contracts/examples/citizen-ai-extraction.json").toFile());
        output.put("document_version_id", source.path("documents").get(0).path("document_version_id").asText());
        edit.accept(output);
        Path sourceFile = Files.writeString(work.resolve("source.json"), source.toString());
        Path outputFile = Files.writeString(work.resolve("review-output.json"), output.toString());
        Path handoffRoot = work.resolve("handoffs");
        String script = """
                import hashlib, json, sys, uuid
                from datetime import datetime, timezone
                from pathlib import Path
                from processing.extraction.archive import freeze_run, _json
                from processing.evaluation.reviews import freeze_review
                from processing.evaluation.handoff_storage import freeze_handoff
                source_file, output_file, archive, run, work, handoffs = sys.argv[1:]
                work, archive = Path(work), Path(archive)
                frozen = freeze_run(run, archive)
                parent = archive / frozen['snapshot_ref']
                receipt = frozen['receipt']
                output = json.loads(Path(output_file).read_bytes())
                before = json.loads((parent / f"attempt-{len(receipt['attempts'])}.output").read_bytes()) if receipt['status'] == 'validated' else None
                at = datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
                review = dict(schema_version='human-review-v1', review_id=str(uuid.uuid4()),
                    source=dict(run_id=run, snapshot_ref=frozen['snapshot_ref'], receipt_sha256=hashlib.sha256((parent / 'receipt.json').read_bytes()).hexdigest()),
                    review=dict(reviewed_by='PRIVATE_CITIZEN_REVIEW_DECLARATION', started_at=at, finished_at=at,
                        basis='source_only', note='합성 시험; 실제 사람 판독/승인 아님'), output=output, changes=[])
                if before != output:
                    review['changes'].append(dict(field_path='output', before=before, after=output, reason='합성 원문 대조 수정',
                        evidence_ids=[e['evidence_id'] for e in output['evidence']], reviewer=review['review']['reviewed_by'], time=at))
                review_file = work / 'review.json'; review_file.write_bytes(_json(review))
                reviews = work / 'reviews'; selected = freeze_review(review_file, reviews, archive)
                request = dict(schema_version='citizen-human-handoff-v1', handoff_id=str(uuid.uuid4()), review_ref=selected['review_ref'],
                    review_receipt_sha256=hashlib.sha256((reviews / selected['review_ref'] / 'receipt.json').read_bytes()).hexdigest(),
                    source=json.loads(Path(source_file).read_bytes()), split_group_id=str(uuid.uuid5(uuid.UUID(run), 'synthetic-d06-group')))
                selection = work / 'selection.json'; selection.write_bytes(_json(request))
                print(json.dumps(freeze_handoff(selection, Path(handoffs), reviews), ensure_ascii=False))
                """;
        var process = PythonProcess.executeKeyless(PythonProbe.PYTHON, PythonProbe.REPO.toString(),
                List.of("-B", "-s", "-c", script, sourceFile.toString(), outputFile.toString(), extraction.archive().toString(),
                        extraction.run(), work.toString(), handoffRoot.toString()), new byte[0], 20_000);
        assertThat(process.exitCode()).as(new String(process.stderr(), StandardCharsets.UTF_8)).isZero();
        var receipt = JSON.readTree(process.stdout());
        Path image = handoffRoot.resolve(receipt.path("handoff_ref").asText());
        var projection = JSON.readTree(image.resolve("projection.json").toFile());
        var request = JSON.createObjectNode().put("schema_version", "citizen-human-handoff-import-v1")
                .put("handoff_ref", receipt.path("handoff_ref").asText())
                .put("receipt_sha256", ReviewedImportReader.sha256(Files.readAllBytes(image.resolve("receipt.json"))))
                .put("reason", "합성 시민 사람 수정 인계");
        var revisions = request.putArray("revisions");
        for (var event : projection.path("events")) revisions.addObject().put("event_id", event.path("event_id").asText())
                .put("revision_id", UUID.randomUUID().toString()).put("expected_revision_no", 0);
        return new Handoff(source, extraction, handoffRoot, image, request, projection);
    }

    record Handoff(ObjectNode source, CitizenExtractionArchiveTest.Fixture extraction, Path handoffRoot, Path image,
                   ObjectNode request, JsonNode projection) {
        String run() { return extraction.run(); }
        String eventId() { return projection.path("events").get(0).path("event_id").asText(); }
    }
}
