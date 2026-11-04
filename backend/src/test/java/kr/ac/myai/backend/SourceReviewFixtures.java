package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.springframework.jdbc.core.JdbcTemplate;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

import static org.assertj.core.api.Assertions.assertThat;

final class SourceReviewFixtures {
    final Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final ExtractionRunMySqlTest extraction = new ExtractionRunMySqlTest();

    SourceReviewFixtures(Path root, JdbcTemplate jdbc, ReviewedImportReader reader, ReviewedImportService importer) {
        this.root = root;
        extraction.root = root; extraction.jdbc = jdbc; extraction.reader = reader; extraction.importer = importer;
    }

    ObjectNode source(boolean pending) throws Exception {
        var source = extraction.source();
        if (pending) pending(document(source));
        return source;
    }

    ObjectNode human(boolean pending) throws Exception {
        Files.copy(Path.of("examples/synthetic-source.txt"), root.resolve("synthetic-source.txt"), java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        var ids = new HashMap<String, String>();
        String json = Pattern.compile("10000000-0000-4000-8000-[0-9]{12}").matcher(Files.readString(Path.of("examples/reviewed-import.json")))
                .replaceAll(match -> ids.computeIfAbsent(match.group(), ignored -> UUID.randomUUID().toString()));
        ObjectNode input = (ObjectNode) mapper.readTree(json);
        if (pending) pending(document(input));
        return input;
    }

    static ObjectNode document(ObjectNode input) { return (ObjectNode) input.path("documents").get(0); }
    static String version(ObjectNode input) { return document(input).path("document_version_id").asText(); }
    static String event(ObjectNode input) { return input.path("events").get(0).path("event_id").asText(); }

    private static void pending(ObjectNode doc) {
        doc.put("use_review", "pending").put("use_note", "합성 미검토").putNull("latest_check_attempt_at")
                .putNull("last_verified_at").put("check_result", "unchecked").putArray("checks");
    }

    void register(ObjectNode source) throws Exception { extraction.registerSource(source); }
    Path archive(ObjectNode source, String run) throws Exception { return extraction.archive(source, run, false); }

    Handoff handoff(ObjectNode source, String run, Path archive) throws Exception {
        return handoff(source, run, archive, output -> { });
    }

    Handoff handoff(ObjectNode source, String run, Path archive, java.util.function.Consumer<ObjectNode> edit) throws Exception {
        Path work = Files.createTempDirectory(root, "source-review-handoff-").toRealPath();
        Path sourceFile = Files.writeString(work.resolve("source.json"), source.toString());
        var output = (ObjectNode) mapper.readTree(PythonProbe.REPO.resolve("contracts/examples/ai-extraction.json").toFile());
        var doc = document(source); output.put("document_version_id", version(source));
        var block = doc.path("block_index").get(0); String text = block.path("text").asText();
        ((ObjectNode) output.path("evidence").get(0)).put("block_id", block.path("block_id").asText()).put("quote", text)
                .put("start_char", 0).put("end_char", text.codePointCount(0, text.length()))
                .put("text_sha256", ReviewedImportReader.sha256(text.getBytes(StandardCharsets.UTF_8)));
        edit.accept(output);
        Path outputFile = Files.writeString(work.resolve("output.json"), output.toString());
        Path handoffRoot = work.resolve("handoffs");
        String script = """
                import hashlib, json, sys, uuid
                from datetime import datetime, timezone
                from pathlib import Path
                from processing.extraction.archive import freeze_run, _json
                from processing.evaluation.reviews import freeze_review
                from processing.evaluation.handoff_storage import freeze_handoff
                source_path, output_path, run_root, run, work_path, handoff_root = sys.argv[1:]
                work, run_root = Path(work_path), Path(run_root)
                frozen = freeze_run(run, run_root)
                parent = run_root / frozen['snapshot_ref']
                receipt = frozen['receipt']
                output = json.loads(Path(output_path).read_bytes())
                before = json.loads((parent / f"attempt-{len(receipt['attempts'])}.output").read_bytes()) if receipt['status'] == 'validated' else None
                at = datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
                review = dict(schema_version='human-review-v1', review_id=str(uuid.uuid4()),
                    source=dict(run_id=run, snapshot_ref=frozen['snapshot_ref'], receipt_sha256=hashlib.sha256((parent / 'receipt.json').read_bytes()).hexdigest()),
                    review=dict(reviewed_by='synthetic-source-reviewer', started_at=at, finished_at=at, basis='source_only', note='합성 시험; 실제 사람 검토 선언 아님'),
                    output=output, changes=[])
                if before != output:
                    review['changes'].append(dict(field_path='output', before=before, after=output, reason='합성 원문 대조 수정',
                        evidence_ids=[e['evidence_id'] for e in output['evidence']], reviewer=review['review']['reviewed_by'], time=at))
                review_path = work / 'review.json'; review_path.write_bytes(_json(review))
                review_root = work / 'reviews'; selected = freeze_review(review_path, review_root, run_root)
                request = dict(schema_version='human-handoff-v1', handoff_id=str(uuid.uuid4()), review_ref=selected['review_ref'],
                    review_receipt_sha256=hashlib.sha256((review_root / selected['review_ref'] / 'receipt.json').read_bytes()).hexdigest(),
                    source=json.loads(Path(source_path).read_bytes()), area_id='10000000-0000-4000-8000-000000000005',
                    split_group_id='10000000-0000-4000-8000-000000000006', dictionary_version='synthetic-dictionary-v1')
                request_path = work / 'handoff.json'; request_path.write_bytes(_json(request))
                result = freeze_handoff(request_path, Path(handoff_root), review_root)
                print(json.dumps(result, ensure_ascii=False))
                """;
        var process = new ProcessBuilder(PythonProbe.PYTHON, "-c", script, sourceFile.toString(), outputFile.toString(), archive.toString(), run,
                work.toString(), handoffRoot.toString()).directory(PythonProbe.REPO.toFile()).start();
        assertThat(process.waitFor(15, TimeUnit.SECONDS)).isTrue();
        assertThat(process.exitValue()).as(new String(process.getErrorStream().readAllBytes(), StandardCharsets.UTF_8)).isZero();
        JsonNode receipt = mapper.readTree(process.getInputStream().readAllBytes());
        Path image = handoffRoot.resolve(receipt.path("handoff_ref").asText());
        var request = mapper.createObjectNode().put("schema_version", "human-handoff-import-v1")
                .put("handoff_ref", receipt.path("handoff_ref").asText())
                .put("receipt_sha256", ReviewedImportReader.sha256(Files.readAllBytes(image.resolve("receipt.json"))))
                .put("reason", "합성 원문 검토 이력 보존 시험");
        var revisions = request.putArray("revisions");
        for (var event : mapper.readTree(image.resolve("projection.json").toFile()).path("events"))
            revisions.addObject().put("event_id", event.path("event_id").asText()).put("revision_id", UUID.randomUUID().toString()).put("expected_revision_no", 0);
        Path file = Files.writeString(work.resolve("import.json"), request.toString());
        return new Handoff(handoffRoot, image, file);
    }

    record Handoff(Path directory, Path image, Path file) { }
}
