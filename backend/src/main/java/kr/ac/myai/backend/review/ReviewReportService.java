package kr.ac.myai.backend.review;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.extraction.VerifiedExtraction;
import kr.ac.myai.backend.handoff.HandoffReference;
import kr.ac.myai.backend.handoff.HumanHandoffArchiveReader;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.repository.PublicationRepository;
import kr.ac.myai.backend.repository.ExtractionRunRepository;
import kr.ac.myai.backend.repository.ReviewReportRepository;
import kr.ac.myai.backend.repository.SourceReviewRepository;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ExtractionImportService;
import kr.ac.myai.backend.source.SourceReviewException;
import org.springframework.context.annotation.Profile;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.TransactionException;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.time.Instant;
import java.util.*;
import java.util.function.Supplier;

/** 저장 원문·수정본·검사 결과를 비공개 보고서용으로만 조합한다. */
@Service
@Profile("!fixture")
public class ReviewReportService {
    private static final int ARTIFACT_LIMIT = 8 * 1024 * 1024;
    private static final int REPORT_LIMIT = 64 * 1024 * 1024;
    private final ReviewReportRepository repository;
    private final ObjectMapper mapper;
    private final ReviewedImportReader json;
    private final PublicationContent content;
    private final SourceReviewRepository sources;
    private final ExtractionArchiveReader archives;
    private final HumanHandoffArchiveReader handoffs;
    private final PublicationCommandReader commands;
    private final PublicationService publication;
    private final ExtractionImportService extractions;
    private final ExtractionRunRepository extractionRuns;

    public ReviewReportService(ReviewReportRepository repository, ObjectMapper mapper, ReviewedImportReader json,
                               PublicationContent content, SourceReviewRepository sources, ExtractionArchiveReader archives,
                               HumanHandoffArchiveReader handoffs, PublicationCommandReader commands, PublicationService publication,
                               ExtractionImportService extractions, ExtractionRunRepository extractionRuns) {
        this.repository = repository; this.mapper = mapper; this.json = json; this.content = content;
        this.sources = sources; this.archives = archives; this.handoffs = handoffs; this.commands = commands; this.publication = publication;
        this.extractions = extractions;
        this.extractionRuns = extractionRuns;
    }

    public ObjectNode build(UUID documentVersionId, Path sourceRoot, Path optionalPreviewRequest) {
        if (documentVersionId == null || sourceRoot == null) throw error("REPORT_VALIDATION_ERROR", "document_version_id/source_root");
        ObjectNode saved;
        try { saved = repository.capture(documentVersionId); }
        catch (DataAccessException | TransactionException ex) { throw error("REPORT_DATABASE_UNAVAILABLE", null); }
        var report = mapper.createObjectNode().put("format_version", "local-review-report-v1").put("document_version_id", documentVersionId.toString());
        report.set("capture", saved.path("capture"));
        var budget = new Budget();
        budget.add(saved.path("review_audits")); budget.add(saved.path("publication"));
        var originals = new LinkedHashMap<String, JsonNode>();
        var documents = report.putArray("documents");
        for (var row : saved.path("documents")) {
            var document = mapper.createObjectNode(); document.set("database", row);
            String id = row.path("document_version_id").asText();
            document.set("source_checks", filtered(saved.path("source_checks"), "document_version_id", id));
            document.set("source_reviews", filtered(saved.path("source_reviews"), "document_version_id", id));
            document.set("validation", inspect(() -> {
                var metadata = parse(row.path("metadata_json")); var original = metadata.path("document");
                document.set("original", original); originals.put(id, metadata);
                var envelope = mapper.createObjectNode().put("schema_version", "source-import-v1").put("data_kind", metadata.path("data_kind").asText());
                envelope.putArray("documents").add(original); envelope.putArray("evidence"); envelope.putArray("events");
                var parsed = json.validateStored(envelope, sourceRoot).documents().getFirst();
                check(parsed.id().equals(row.path("document_id").asText()) && parsed.versionId().equals(id)
                        && parsed.versionNo() == row.path("version_no").asLong()
                        && parsed.textSha256().equals(row.path("text_sha256").asText())
                        && Objects.equals(parsed.privateContentRef(), row.path("private_content_ref").textValue()), "documents");
                return null;
            }));
            var raw = document.putObject("raw_asset");
            raw.set("validation", inspect(() -> {
                JsonNode original = document.path("original");
                Path root = canonicalDirectory(sourceRoot);
                String name = original.path("raw_asset_path").textValue();
                check(name != null, "raw_asset_path"); Path relative = Path.of(name);
                check(!relative.isAbsolute() && relative.normalize().equals(relative) && !relative.startsWith(".."), "raw_asset_path");
                byte[] bytes = read(root.resolve(relative), root);
                check(ReviewedImportReader.sha256(bytes).equals(original.path("raw_sha256").asText()), "raw_sha256");
                raw.setAll(encoded(bytes)); return null;
            }));
            var operational = document.putObject("operational");
            operational.put("same_snapshot_as_capture", false);
            operational.set("validation", inspect(() -> {
                var view = sources.view(document(row));
                operational.set("effective_metadata", parseText(view.effectiveMetadata()));
                operational.put("source_review_no", view.reviewNo()).put("source_review_sha256", view.reviewSha256());
                return null;
            }));
            var imports = document.putArray("imports");
            for (var rowImport : filtered(saved.path("imports"), "report_document_version_id", id)) imports.add(importedHandoff(rowImport, id, budget));
            budget.addRemainder(document, imports); documents.add(document);
        }
        var extractions = report.putArray("extractions");
        for (var row : saved.path("extractions")) {
            var extraction = mapper.createObjectNode(); extraction.set("database", row);
            var artifacts = extraction.putObject("artifacts");
            extraction.set("validation", inspect(() -> {
                if (row.path("receipt_json").isTextual()) {
                    var receipt = parse(row.path("receipt_json"));
                    for (var artifact : receipt.path("artifacts")) if (artifact.path("size").isIntegralNumber()
                            && artifact.path("size").asLong() > ARTIFACT_LIMIT) throw error("REPORT_TOO_LARGE", "artifact");
                }
                String ref = row.path("raw_ref").textValue(); check(ref != null, "raw_ref"); Path path = Path.of(ref);
                check(path.isAbsolute() && path.getFileName() != null && path.getFileName().toString().equals(row.path("run_id").asText()), "raw_ref");
                var run = archives.readSealed(row.path("run_id").asText(), path.getParent());
                check(run.directory().equals(path), "raw_ref"); compareRun(row, run, originals);
                extraction.set("receipt", run.receipt()); extraction.set("metadata", run.metadata());
                for (var artifact : run.receipt().path("artifacts").properties()) {
                    String name = artifact.getKey();
                    check(Set.of("input.json", "metadata.json").contains(name)
                            || name.matches("attempt-[1-3]\\.(?:prompt|output|response|exchange)"), "artifacts");
                    var item = mapper.createObjectNode(); artifacts.set(name, item);
                    item.set("validation", inspect(() -> {
                        byte[] bytes = read(path.resolve(name), path);
                        check(artifact.getValue().path("size").isIntegralNumber() && bytes.length == artifact.getValue().path("size").asLong()
                                && ReviewedImportReader.sha256(bytes).equals(artifact.getValue().path("sha256").asText()), "artifacts");
                        item.setAll(encoded(bytes)); budget.add(item); return null;
                    }));
                }
                for (var item : artifacts) if (item.path("validation").path("status").asText().equals("invalid")) throw error("REPORT_ARTIFACT_INVALID", "artifacts");
                return null;
            }));
            budget.addRemainder(extraction, artifacts); extractions.add(extraction);
        }
        var events = report.putArray("events"); var grouped = new LinkedHashMap<String, ObjectNode>();
        for (var row : saved.path("revisions")) {
            String eventId = row.path("event_id").asText();
            var event = grouped.computeIfAbsent(eventId, id -> {
                var value = mapper.createObjectNode().put("event_id", id).put("current_revision_id", row.path("current_review_revision_id").textValue());
                value.putArray("revisions"); events.add(value); return value;
            });
            var revision = mapper.createObjectNode(); revision.set("database", row);
            revision.put("is_current", row.path("revision_id").equals(row.path("current_review_revision_id")));
            revision.set("validation", inspect(() -> {
                JsonNode payload = content.payload(revision(row)); revision.set("payload", payload);
                var envelope = envelope(payload, originals);
                var checked = json.validateStored(envelope, sourceRoot);
                this.extractions.verifyReadOnlyReferences(checked.events()); return null;
            }));
            var proofs = revision.putArray("handoffs");
            var payload = revision.path("payload");
            revision.set("handoff_validation", inspect(() -> {
                check(payload.isObject(), "payload");
                for (var reference : HandoffReference.list(payload.path("human_handoffs"))) {
                    var proof = mapper.createObjectNode(); proof.set("reference", mapper.valueToTree(reference));
                    proof.set("validation", inspect(() -> {
                        var image = handoffs.read(reference); proof.set("projection", image.projection()); proof.set("review", image.review());
                        proof.set("receipt", image.receipt()); return null;
                    }));
                    budget.add(proof); proofs.add(proof);
                }
                return null;
            }));
            budget.addRemainder(revision, proofs); ((ArrayNode) event.path("revisions")).add(revision);
        }
        report.set("review_audits", saved.path("review_audits"));
        report.set("publication", saved.path("publication"));
        for (var row : report.path("publication").path("snapshots")) {
            var snapshot = (ObjectNode) row;
            snapshot.set("validation", inspect(() -> {
                var value = new PublicationRepository.Snapshot(row.path("snapshot_id").asText(), row.path("mode").asText(), row.path("case_id").textValue(),
                        row.path("canonical_json").asText(), row.path("checksum").asText(), row.path("data_kind").asText(), row.path("rules_version").asText(), row.path("dictionary_version").asText());
                content.verifySnapshot(value, value.mode().equals("current") ? "current" : "replay:" + value.caseId()); return null;
            }));
        }
        var preview = report.putObject("preview");
        if (optionalPreviewRequest == null) preview.put("status", "not_requested").putNull("code").putNull("field");
        else {
            var result = inspect(() -> {
                var command = commands.read(optionalPreviewRequest);
                if (!(command instanceof PublicationCommand.Publish request) || !request.action().equals("preview")) throw error("REPORT_PREVIEW_INVALID", "action");
                var related = new HashSet<String>(); saved.path("revisions").forEach(row -> related.add(row.path("revision_id").asText()));
                if (request.revisionIds().stream().noneMatch(id -> related.contains(id.toString()))) throw error("REPORT_PREVIEW_INVALID", "revision_ids");
                var value = publication.execute(request, sourceRoot, "local-review-report");
                preview.set("result", mapper.valueToTree(value)); preview.put("is_publication", false);
                preview.set("summary", previewSummary(request, value.preview())); return null;
            });
            preview.setAll(result); preview.put("same_snapshot_as_capture", false);
        }
        if (report.toString().getBytes(StandardCharsets.UTF_8).length > REPORT_LIMIT) throw error("REPORT_TOO_LARGE", "report");
        return report;
    }

    private ObjectNode previewSummary(PublicationCommand.Publish request, JsonNode proposed) {
        var summary = mapper.createObjectNode().put("status", "unknown")
                .put("change_basis", "event_id별 revision_id 변경 수이며 사실 필드의 차이나 향후 공개 결과를 확정하지 않습니다.");
        for (String key : List.of("new_events", "revision_changed", "removed_events", "unchanged_events", "cancelled_events")) summary.putNull(key);
        var baseline = summary.putObject("baseline");
        baseline.put("status", "unknown").put("same_snapshot_as_capture", false);
        String channel = request.mode().equals("current") ? "current" : "replay:" + request.caseId();
        baseline.put("channel_key", channel);
        baseline.set("validation", inspect(() -> {
            var read = repository.previewBaseline(channel); baseline.set("database", read);
            baseline.set("read_at", read.path("read_at"));
            Map<String, String> previous = Map.of();
            if (read.path("status").asText().equals("none")) {
                baseline.put("status", "none").putNull("snapshot_id").putNull("checksum").putNull("head_version");
            } else {
                JsonNode row = read.path("snapshot");
                baseline.put("snapshot_id", row.path("snapshot_id").asText()).put("checksum", row.path("checksum").asText());
                baseline.set("head_version", read.path("head").path("lock_version"));
                var snapshot = new PublicationRepository.Snapshot(row.path("snapshot_id").asText(), row.path("mode").asText(), row.path("case_id").textValue(),
                        row.path("canonical_json").asText(), row.path("checksum").asText(), row.path("data_kind").asText(), row.path("rules_version").asText(), row.path("dictionary_version").asText());
                content.verifySnapshot(snapshot, channel);
                check(row.path("schema_version").asText().equals("snapshot-v1"), "schema_version");
                previous = eventRevisions(content.parse(snapshot.canonical()));
                baseline.put("status", "present");
            }
            var current = eventRevisions(proposed);
            int added = 0, changed = 0, unchanged = 0;
            for (var event : current.entrySet()) {
                if (!previous.containsKey(event.getKey())) added++;
                else if (previous.get(event.getKey()).equals(event.getValue())) unchanged++;
                else changed++;
            }
            int removed = 0, cancelled = 0;
            for (String event : previous.keySet()) if (!current.containsKey(event)) removed++;
            for (var event : proposed.path("event_public_payloads")) if (event.path("lifecycle").asText().equals("cancelled")) cancelled++;
            summary.put("status", "available").put("new_events", added).put("revision_changed", changed)
                    .put("removed_events", removed).put("unchanged_events", unchanged).put("cancelled_events", cancelled);
            return null;
        }));
        if (baseline.path("validation").path("status").asText().equals("invalid")) baseline.put("status", "unknown");
        return summary;
    }

    private ObjectNode importedHandoff(JsonNode row, String documentVersionId, Budget budget) {
        var imported = mapper.createObjectNode(); imported.set("database", row);
        var proofs = imported.putArray("handoffs");
        imported.set("validation", inspect(() -> {
            check(row.path("status").asText().equals("succeeded") && row.path("schema_version").asText().equals("human-handoff-import-v1"), "import_batches");
            var refs = parse(row.path("result_refs_json")); imported.set("result_refs", refs);
            var references = HandoffReference.list(refs.path("human_handoffs"));
            check(!references.isEmpty(), "human_handoffs");
            String runId = refs.path("originating_run_id").textValue();
            for (var reference : references) {
                var proof = mapper.createObjectNode(); proof.set("reference", mapper.valueToTree(reference));
                proof.set("validation", inspect(() -> {
                    var image = handoffs.read(reference);
                    proof.set("projection", image.projection()); proof.set("review", image.review()); proof.set("receipt", image.receipt());
                    boolean related = false;
                    for (var document : image.projection().path("documents")) related |= document.path("document_version_id").asText().equals(documentVersionId);
                    check(related && Objects.equals(runId, image.projection().path("parent").path("run_id").textValue()), "originating_run_id");
                    Path directory = Path.of(extractionRuns.handoffParentDirectory(runId, image));
                    var run = archives.readSealed(runId, directory.getParent());
                    extractionRuns.checkDocument(run); extractionRuns.verifiedHandoffParent(run, image);
                    return null;
                }));
                budget.add(proof); proofs.add(proof);
            }
            for (var proof : proofs) check(proof.path("validation").path("status").asText().equals("valid"), "human_handoffs");
            return null;
        }));
        budget.addRemainder(imported, proofs);
        return imported;
    }

    private Map<String, String> eventRevisions(JsonNode snapshot) {
        check(snapshot.path("event_public_payloads").isArray(), "event_public_payloads");
        var result = new LinkedHashMap<String, String>();
        for (var event : snapshot.path("event_public_payloads")) {
            String id = event.path("event_id").textValue(), revision = event.path("revision_id").textValue();
            check(id != null && id.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
                    && revision != null && revision.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
                    && result.putIfAbsent(id, revision) == null, "event_public_payloads");
        }
        check(snapshot.path("event_count").isIntegralNumber() && snapshot.path("event_count").canConvertToInt()
                && snapshot.path("event_count").intValue() == result.size(), "event_count");
        return result;
    }

    private ObjectNode envelope(JsonNode payload, Map<String, JsonNode> documents) {
        JsonNode revision = payload.path("revision"); boolean draft = revision.path("origin").asText().equals("ai_draft");
        var envelope = mapper.createObjectNode().put("schema_version", draft ? "ai-draft-import-v1" : "reviewed-import-v1").put("data_kind", payload.path("data_kind").asText());
        if (draft) envelope.set("originating_run_id", revision.path("originating_run_ids").path(0));
        if (payload.has("human_handoffs")) envelope.set("human_handoffs", payload.path("human_handoffs"));
        var sources = envelope.putArray("documents");
        check(revision.path("source_version_ids").isArray(), "source_version_ids");
        for (var ref : revision.path("source_version_ids")) { var metadata = documents.get(ref.asText()); check(metadata != null, "source_version_ids"); sources.add(metadata.path("document")); }
        envelope.set("evidence", payload.path("evidence")); var event = (ObjectNode) payload.path("event").deepCopy();
        event.set("revision", revision); event.put("expected_revision_no", revision.path("revision_no").asLong() - 1); envelope.putArray("events").add(event); return envelope;
    }

    private void compareRun(JsonNode row, VerifiedExtraction run, Map<String, JsonNode> documents) {
        Map<String, String> expected = new LinkedHashMap<>();
        expected.put("document_version_id", run.documentVersionId()); expected.put("input_sha256", run.inputSha256()); expected.put("output_sha256", run.outputSha256());
        expected.put("status", run.status()); expected.put("raw_ref", run.directory().toString()); expected.put("data_kind", run.dataKind());
        expected.put("metadata_json", run.metadataJson()); expected.put("metadata_sha256", run.metadataSha256()); expected.put("receipt_json", run.receiptJson()); expected.put("receipt_sha256", run.receiptSha256());
        for (String key : List.of("provider", "prompt_version", "model_version", "schema_version", "preprocessing_version", "execution_mode")) expected.put(key, run.nullable(key));
        expected.put("model", run.nullable("model_label")); expected.forEach((key, value) -> check(Objects.equals(row.path(key).textValue(), value), key));
        check(row.path("attempts").isIntegralNumber() && row.path("attempts").asInt() == run.attempts(), "attempts");
        var source = documents.get(run.documentVersionId()); check(source != null, "document_version_id");
        var original = source.path("document"); var input = mapper.createObjectNode(); input.set("data_kind", source.path("data_kind"));
        for (String key : List.of("document_version_id", "title", "published_date")) input.set(key, original.path(key));
        input.set("blocks", original.path("block_index")); check(input.equals(run.input()) && original.path("preprocessing_version").equals(run.metadata().path("preprocessing_version")), "input");
    }

    private ObjectNode inspect(Supplier<JsonNode> action) {
        var result = mapper.createObjectNode().put("started_at", Instant.now().toString())
                .put("scope", "형식·해시·참조의 기계 검사입니다. 의미 정확성·실제 사람 판독·수정 감사의 진실성을 인증하지 않습니다.");
        try { action.get(); result.put("status", "valid").putNull("code").putNull("field"); }
        catch (PublicationException ex) { if (ex.code().equals("REPORT_TOO_LARGE")) throw ex; invalid(result, ex.code(), ex.field()); }
        catch (ImportException ex) { invalid(result, ex.code(), ex.field()); }
        catch (ExtractionException ex) { invalid(result, ex.code(), ex.field()); }
        catch (SourceReviewException ex) { invalid(result, ex.code(), ex.field()); }
        catch (DataAccessException | TransactionException ex) { invalid(result, "REPORT_DATABASE_UNAVAILABLE", null); }
        catch (RuntimeException ex) { invalid(result, "REPORT_VALIDATION_ERROR", null); }
        result.put("checked_at", Instant.now().toString()); return result;
    }

    private void invalid(ObjectNode result, String code, String field) { result.put("status", "invalid").put("code", code).put("field", field).put("message", "저장 원문·참조·검증 환경을 확인해 주세요. 원래 값은 변경하지 않았습니다."); }
    private JsonNode parse(JsonNode value) { check(value.isTextual(), "json"); return parseText(value.asText()); }
    private JsonNode parseText(String value) { return json.parseJson(value.getBytes(StandardCharsets.UTF_8)); }
    private ArrayNode filtered(JsonNode rows, String field, String id) { var result = mapper.createArrayNode(); for (var row : rows) if (row.path(field).asText().equals(id)) result.add(row); return result; }
    private PublicationRepository.Document document(JsonNode row) { return new PublicationRepository.Document(row.path("document_id").asText(), row.path("document_version_id").asText(), row.path("version_no").asLong(), row.path("text_sha256").asText(), row.path("metadata_json").asText(), row.path("private_content_ref").textValue()); }
    private PublicationRepository.Revision revision(JsonNode row) { return new PublicationRepository.Revision(row.path("revision_id").asText(), row.path("event_id").asText(), row.path("revision_no").asLong(), row.path("review_status").asText(), row.path("publication_intent").asText(), row.path("payload_json").asText(), row.path("payload_sha256").asText(), row.path("current_review_revision_id").asText(), row.path("lock_version").asLong()); }

    private ObjectNode encoded(byte[] bytes) {
        var result = mapper.createObjectNode().put("size", bytes.length).put("sha256", ReviewedImportReader.sha256(bytes));
        try { result.put("encoding", "utf-8").put("text", StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString()); }
        catch (CharacterCodingException ex) { result.put("encoding", "base64").put("base64", Base64.getEncoder().encodeToString(bytes)); }
        return result;
    }

    private Path canonicalDirectory(Path path) {
        try {
            check(path.isAbsolute() && path.normalize().equals(path), "source_root");
            Path root = path.toRealPath(); check(Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS), "source_root"); return root;
        }
        catch (IOException ex) { throw error("REPORT_FILE_UNAVAILABLE", "source_root"); }
    }

    private byte[] read(Path file, Path root) {
        try {
            check(file.isAbsolute() && file.normalize().equals(file) && file.startsWith(root) && root.toRealPath().equals(root), "artifact_path");
            Path current = root;
            for (Path part : root.relativize(file)) { current = current.resolve(part); check(!Files.isSymbolicLink(current), "artifact_path"); }
            var before = Files.readAttributes(file, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS); check(before.isRegularFile(), "artifact_path");
            try (var stream = Files.newInputStream(file, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                byte[] bytes = stream.readNBytes(ARTIFACT_LIMIT + 1);
                if (bytes.length > ARTIFACT_LIMIT) throw error("REPORT_TOO_LARGE", "artifact");
                var after = Files.readAttributes(file, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
                check(after.isRegularFile() && Objects.equals(before.fileKey(), after.fileKey()) && before.size() == after.size() && before.lastModifiedTime().equals(after.lastModifiedTime()), "artifact_path");
                return bytes;
            }
        } catch (IOException | SecurityException ex) { throw error("REPORT_FILE_UNAVAILABLE", "artifact_path"); }
    }

    private static void check(boolean valid, String field) { if (!valid) throw error("REPORT_VALIDATION_ERROR", field); }
    private static PublicationException error(String code, String field) { return new PublicationException(code, "검토 보고서의 입력·원본·크기 또는 연결 상태를 확인해 주세요.", field); }
    private static final class Budget {
        long bytes;
        void add(JsonNode value) { bytes += value.toString().getBytes(StandardCharsets.UTF_8).length; if (bytes > REPORT_LIMIT) throw error("REPORT_TOO_LARGE", "report"); }
        void addRemainder(JsonNode value, JsonNode alreadyCounted) { bytes -= alreadyCounted.toString().getBytes(StandardCharsets.UTF_8).length; add(value); }
    }
}
