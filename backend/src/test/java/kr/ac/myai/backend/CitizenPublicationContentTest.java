package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.CitizenPublicationContent;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.repository.PublicationRepository;
import kr.ac.myai.backend.source.SourceView;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.*;

class CitizenPublicationContentTest {
    private static final String ID = "20000000-0000-4000-8000-000000000090";
    private static final Instant AT = Instant.parse("2026-11-18T00:00:00Z");
    private static final String FACTS = "application_period occurrences regions locations residency_requirement target eligibility application_method preparation cost recruitment lifecycle";
    @TempDir Path root;
    private final ObjectMapper mapper = new ObjectMapper();
    private final ReviewedImportReader reader = new ReviewedImportReader();
    private final CitizenPublicationContent content = new CitizenPublicationContent(new PublicationContent(reader, mapper), mapper);
    private ObjectNode payload;
    private Map<String, SourceView> sources;

    @BeforeEach
    void prepareApprovedCitizenRevision() throws Exception {
        Files.copy(Path.of("examples/citizen-source.txt"), root.resolve("citizen-source.txt"));
        var batch = reader.read(Path.of("examples/citizen-reviewed-import.json"), root);
        payload = (ObjectNode) mapper.readTree(batch.events().getFirst().payloadJson());
        revision().put("review_status", "approved").put("publication_intent", "public");
        var document = batch.documents().getFirst();
        var row = new PublicationRepository.Document(document.id(), document.versionId(), document.versionNo(),
                document.textSha256(), document.metadataJson(), document.privateContentRef());
        sources = new LinkedHashMap<>(Map.of(row.versionId(), new SourceView(row)));
    }

    @Test
    void publishesOnlyCitizenFactsAndFixedPublicSourceMetadata() throws Exception {
        revision().putArray("categories").add("education").add("support").add("culture").add("construction_traffic").add("living");
        ((ObjectNode) revision().path("preparation")).put("knowledge", "known").putNull("reason").putArray("evidence_ids").add("body-quote");
        ((ObjectNode) revision().path("preparation")).putArray("value").add("신분증").add("신청서");
        revision().putArray("human_overrides").addObject().put("reviewer", "private-reviewer");
        payload.putArray("human_handoffs").addObject().put("directory", root.toString());
        var snapshot = snapshot();
        var json = mapper.readTree(snapshot.canonical());
        assertThat(fields(json)).containsExactlyInAnyOrder("schema_version", "snapshot_id", "created_at", "data_kind", "mode", "case_id", "channel_key", "timezone", "revision_ids", "notices", "sources", "notice_count");
        assertThat(json.path("channel_key").asText()).isEqualTo("citizen:current");
        assertThat(json.path("notice_count").intValue()).isEqualTo(1);
        assertThat(snapshot.rulesVersion()).isNull();
        assertThat(snapshot.dictionaryVersion()).isNull();
        var notice = json.path("notices").get(0);
        var expected = new HashSet<>(List.of("event_id", "revision_id", "title", "categories", "source_version_ids", "document_links", "relations", "evidence"));
        expected.addAll(List.of(FACTS.split(" ")));
        assertThat(fields(notice)).isEqualTo(expected);
        for (String fact : FACTS.split(" ")) assertThat(notice.path(fact)).isEqualTo(revision().path(fact));
        assertThat(notice.path("application_period").path("value").asText()).isEqualTo("2026-11-20~2026-11-25");
        assertThat(notice.path("occurrences").path("value").asText()).isEqualTo("2026-12-01~2026-12-02");
        assertThat(notice.path("cost").path("value").isNull()).isTrue();
        assertThat(notice.path("preparation").path("value").get(1).asText()).isEqualTo("신청서");
        assertThat(fields(json.path("sources").get(0))).containsExactlyInAnyOrder("document_id", "document_version_id", "publisher", "official_url", "title", "official_number", "published_date", "collected_at", "text_sha256", "last_verified_at", "latest_check_attempt_at", "check_result", "checks");
        assertThat(fields(json.path("sources").get(0).path("checks").get(0))).containsExactlyInAnyOrder("checked_at", "result", "text_sha256");
        assertThat(snapshot.canonical()).doesNotContain("human_overrides", "reviewer", "originating_run_ids", "human_handoffs", "raw_asset_path", "cleaned_text", "block_index", "check_id", "use_note", root.toString());
        content.verifySnapshot(snapshot, "citizen-snapshot-v1", AT);
    }

    @Test
    void keepsManyToManySourcesAndSortsNoticesAndUsedSourceVersions() throws Exception {
        var first = row(payload);
        var other = payload.deepCopy();
        ((ObjectNode) other.path("event")).put("event_id", "20000000-0000-4000-8000-000000000005");
        ((ObjectNode) other.path("revision")).put("event_id", "20000000-0000-4000-8000-000000000005").put("revision_id", "20000000-0000-4000-8000-000000000008");
        var second = row(other);
        var snapshot = content.snapshot(command(List.of(second, first)), List.of(second, first), sources, ID, AT);
        var json = mapper.readTree(snapshot.canonical());
        assertThat(json.path("notices").get(0).path("event_id").asText()).isEqualTo(first.eventId());
        assertThat(json.path("revision_ids").get(0).asText()).isEqualTo(first.id());
        assertThat(json.path("notices").get(1).path("source_version_ids")).isEqualTo(json.path("notices").get(0).path("source_version_ids"));
        assertThat(json.path("sources")).hasSize(1);
        content.verifySnapshot(snapshot, "citizen-snapshot-v1", AT);
    }

    @Test
    void newlyPublishedSnapshotExcludesUnlinkedEvidenceInAnOlderStoredRevision() throws Exception {
        var expected = payload.path("evidence").deepCopy();
        var unrelated = ((ObjectNode) payload.path("evidence").get(1)).deepCopy().put("evidence_id", "unrelated-quote");
        payload.withArray("evidence").add(unrelated);
        var published = mapper.readTree(snapshot().canonical());
        assertThat(published.path("notices").get(0).path("evidence")).isEqualTo(expected);
        assertThat(payload.path("evidence")).hasSize(3);
    }

    @Test
    void preservesMultipleDocumentsAndRelationsWithoutReviewerIdentity() throws Exception {
        var original = sources.values().iterator().next().original();
        var metadata = (ObjectNode) mapper.readTree(original.metadata());
        var document = (ObjectNode) metadata.path("document");
        String secondDocument = "20000000-0000-4000-8000-000000000011";
        String secondVersion = "20000000-0000-4000-8000-000000000012";
        document.put("document_id", secondDocument).put("document_version_id", secondVersion);
        var second = new PublicationRepository.Document(secondDocument, secondVersion, 1, original.textHash(), metadata.toString(), original.privateRef());
        sources.put(secondVersion, new SourceView(second));
        revision().withArray("source_version_ids").insert(0, secondVersion);
        var quote = ((ObjectNode) payload.path("evidence").get(0)).deepCopy().put("evidence_id", "second-heading").put("document_version_id", secondVersion);
        payload.withArray("evidence").add(quote);
        var event = (ObjectNode) payload.path("event");
        event.withArray("document_links").addObject().put("document_id", secondDocument).put("role", "correction").putArray("evidence_ids").add("second-heading");
        event.withArray("relations").addObject().put("from_document_id", secondDocument).put("to_document_id", original.id())
                .put("type", "corrects").put("reason", "합성 정정 근거").put("created_at", "2026-11-02T02:00:00Z").put("reviewed_by", "private-reviewer");
        var snapshot = snapshot();
        var json = mapper.readTree(snapshot.canonical());
        assertThat(json.path("sources")).hasSize(2);
        assertThat(json.path("sources").get(0).path("document_version_id").asText()).isEqualTo(original.versionId());
        assertThat(json.path("sources").get(1).path("document_version_id").asText()).isEqualTo(secondVersion);
        assertThat(json.path("notices").get(0).path("relations").get(0).path("reason").asText()).isEqualTo("합성 정정 근거");
        assertThat(snapshot.canonical()).doesNotContain("reviewed_by", "private-reviewer");
        content.verifySnapshot(snapshot, "citizen-snapshot-v1", AT);
    }

    @Test
    void publishesAnEmptyCitizenSnapshotWithoutFakeLegacyVersions() throws Exception {
        var snapshot = content.snapshot(command(List.of()), List.of(), Map.of(), ID, AT);
        var json = mapper.readTree(snapshot.canonical());
        assertThat(json.path("notice_count").intValue()).isZero();
        assertThat(json.path("notices")).isEmpty();
        assertThat(json.path("sources")).isEmpty();
        content.verifySnapshot(snapshot, "citizen-snapshot-v1", AT);
    }

    @Test
    void validatesOriginalWhitespaceBytesAgainstTheirOwnChecksum() throws Exception {
        var original = snapshot();
        String bytes = " \n" + mapper.readTree(original.canonical()).toPrettyString() + "\n ";
        var preserved = new PublicationRepository.Snapshot(original.id(), original.mode(), original.caseId(), bytes,
                ReviewedImportReader.sha256(bytes.getBytes(StandardCharsets.UTF_8)), original.kind(), null, null);
        assertThatCode(() -> content.verifySnapshot(preserved, "citizen-snapshot-v1", AT)).doesNotThrowAnyException();
    }

    @ParameterizedTest
    @ValueSource(strings = {"changed", "unreachable", "uncertain"})
    void preservesPreviousVerificationAndDifferentHashOnLaterFailedChecks(String result) throws Exception {
        var original = sources.values().iterator().next().original();
        var metadata = (ObjectNode) mapper.readTree(original.metadata());
        var document = (ObjectNode) metadata.path("document");
        document.put("latest_check_attempt_at", "2026-11-02T03:00:00Z").put("check_result", result);
        document.withArray("checks").addObject().put("check_id", "20000000-0000-4000-8000-000000000013")
                .put("checked_at", "2026-11-02T03:00:00Z").put("result", result).put("reviewer_id", "private-reviewer")
                .put("text_sha256", "f".repeat(64)).put("note", "후속 확인 실패");
        sources.put(original.versionId(), new SourceView(original, metadata.toString(), 1, "a".repeat(64), Map.of()));
        var snapshot = snapshot();
        var json = mapper.readTree(snapshot.canonical());
        assertThat(json.path("sources").get(0).path("last_verified_at").asText()).isEqualTo("2026-11-02T02:00:00Z");
        assertThat(json.path("sources").get(0).path("check_result").asText()).isEqualTo(result);
        assertThat(json.path("sources").get(0).path("checks").get(1).path("text_sha256").asText()).isEqualTo("f".repeat(64));
        content.verifySnapshot(snapshot, "citizen-snapshot-v1", AT);
    }

    @ParameterizedTest
    @ValueSource(strings = {"root", "notice", "field", "source", "check", "link", "evidence"})
    void rejectsPrivateOrUnrecognizedFieldsAtEveryPublicObject(String place) throws Exception {
        reject(json -> {
            ObjectNode node = switch (place) {
                case "root" -> json;
                case "notice" -> notice(json);
                case "field" -> (ObjectNode) notice(json).path("cost");
                case "source" -> source(json);
                case "check" -> (ObjectNode) source(json).path("checks").get(0);
                case "link" -> (ObjectNode) notice(json).path("document_links").get(0);
                default -> (ObjectNode) notice(json).path("evidence").get(0);
            };
            node.put("private_internal", "must never export");
        });
    }

    @ParameterizedTest
    @ValueSource(strings = {"overflow", "fraction", "text", "negative", "mismatch"})
    void rejectsInvalidOrOverflowedNoticeCounts(String change) throws Exception {
        reject(json -> {
            switch (change) {
                case "overflow" -> json.put("notice_count", new BigInteger("18446744073709551617"));
                case "fraction" -> json.put("notice_count", 1.0);
                case "text" -> json.put("notice_count", "1");
                case "negative" -> json.put("notice_count", -1);
                default -> json.put("notice_count", 0);
            }
        });
    }

    @ParameterizedTest
    @ValueSource(strings = {"source_ref", "duplicate_source_ref", "evidence_ref", "evidence_hash", "quote_length", "quote_end_overflow", "duplicate_evidence", "duplicate_source", "duplicate_revision", "duplicate_notice", "unlinked_document", "missing_fact", "object_value", "known_null", "unknown_value", "unknown_reason", "unsupported_category", "duplicate_category", "source_check_hash", "source_check_summary", "source_url", "relative_source_url", "unused_source", "relation_self"})
    void rejectsBrokenPublicFactsSourcesEvidenceAndIdentity(String change) throws Exception {
        reject(json -> {
            var notice = notice(json);
            var quote = (ObjectNode) notice.path("evidence").get(0);
            var cost = (ObjectNode) notice.path("cost");
            switch (change) {
                case "source_ref" -> notice.putArray("source_version_ids").add(ID);
                case "duplicate_source_ref" -> notice.withArray("source_version_ids").add(notice.path("source_version_ids").get(0));
                case "evidence_ref" -> ((ObjectNode) notice.path("application_period")).putArray("evidence_ids").add("absent");
                case "evidence_hash" -> quote.put("text_sha256", "f".repeat(64));
                case "quote_length" -> quote.put("end_char", 11);
                case "quote_end_overflow" -> quote.put("end_char", new BigInteger("18446744073709551626"));
                case "duplicate_evidence" -> notice.withArray("evidence").add(quote.deepCopy());
                case "duplicate_source" -> json.withArray("sources").add(source(json).deepCopy());
                case "duplicate_revision" -> json.withArray("revision_ids").add(revision().path("revision_id"));
                case "duplicate_notice" -> { json.withArray("notices").add(notice.deepCopy()); json.put("notice_count", 2); }
                case "unlinked_document" -> ((ObjectNode) notice.path("document_links").get(0)).put("document_id", ID);
                case "missing_fact" -> notice.remove("cost");
                case "object_value" -> cost.put("knowledge", "known").putObject("value").put("amount", 0);
                case "known_null" -> cost.put("knowledge", "known").putArray("evidence_ids").add("body-quote");
                case "unknown_value" -> cost.put("value", "무료");
                case "unknown_reason" -> cost.putNull("reason");
                case "unsupported_category" -> notice.putArray("categories").add("traffic");
                case "duplicate_category" -> notice.putArray("categories").add("education").add("education");
                case "source_check_hash" -> ((ObjectNode) source(json).path("checks").get(0)).put("text_sha256", "f".repeat(64));
                case "source_check_summary" -> source(json).put("check_result", "changed");
                case "source_url" -> source(json).put("official_url", "file:///private/source.txt");
                case "relative_source_url" -> source(json).put("official_url", "private/source.txt");
                case "unused_source" -> json.withArray("sources").add(source(json).deepCopy().put("document_version_id", ID));
                case "relation_self" -> notice.withArray("relations").addObject().put("from_document_id", source(json).path("document_id").asText())
                        .put("to_document_id", source(json).path("document_id").asText()).put("type", "corrects")
                        .put("reason", "합성 관계").put("created_at", "2026-11-02T02:00:00Z");
            }
        });
    }

    @ParameterizedTest
    @ValueSource(strings = {"schema_version", "channel_key", "mode", "timezone", "data_kind", "snapshot_id", "created_at", "case_id"})
    void rejectsWrongSnapshotEnvelopeMetadata(String field) throws Exception {
        reject(json -> json.put(field, "wrong"));
    }

    @Test
    void bindsChecksumDatabaseSchemaCreationTimeAndNullLegacyVersions() throws Exception {
        var snapshot = snapshot();
        assertRejected(() -> content.verifySnapshot(snapshot, "snapshot-v1", AT));
        assertRejected(() -> content.verifySnapshot(snapshot, "citizen-snapshot-v1", AT.plusSeconds(1)));
        assertRejected(() -> content.verifySnapshot(snapshot, "citizen-snapshot-v1", null));
        assertRejected(() -> content.verifySnapshot(new PublicationRepository.Snapshot(snapshot.id(), snapshot.mode(), snapshot.caseId(), snapshot.canonical(), "0".repeat(64), snapshot.kind(), null, null), "citizen-snapshot-v1", AT));
        assertRejected(() -> content.verifySnapshot(new PublicationRepository.Snapshot(snapshot.id(), snapshot.mode(), snapshot.caseId(), snapshot.canonical(), snapshot.checksum(), snapshot.kind(), "fake-rules", null), "citizen-snapshot-v1", AT));
        assertRejected(() -> content.verifySnapshot(new PublicationRepository.Snapshot(snapshot.id(), snapshot.mode(), snapshot.caseId(), snapshot.canonical(), snapshot.checksum(), snapshot.kind(), null, "fake-dictionary"), "citizen-snapshot-v1", AT));
    }

    @Test
    void rejectsWrongProducerFamilyMissingSourcesAndDuplicateEvents() throws Exception {
        var saved = row(payload);
        assertRejected(() -> content.snapshot(command(List.of(saved)), List.of(saved), Map.of(), ID, AT));
        assertRejected(() -> content.snapshot(command(List.of(saved)), List.of(saved, saved), sources, ID, AT));
        payload.remove("schema_version");
        var legacy = row(payload);
        assertRejected(() -> content.snapshot(command(List.of(legacy)), List.of(legacy), sources, ID, AT));
    }

    @Test
    void enforcesEightMiBAtProductionAndVerificationBoundaries() throws Exception {
        revision().put("title", "한".repeat(3 * 1024 * 1024));
        assertRejected(this::snapshot);
        var empty = content.snapshot(command(List.of()), List.of(), Map.of(), ID, AT);
        String oversized = empty.canonical() + " ".repeat(8 * 1024 * 1024);
        var row = new PublicationRepository.Snapshot(empty.id(), empty.mode(), empty.caseId(), oversized,
                ReviewedImportReader.sha256(oversized.getBytes(StandardCharsets.UTF_8)), empty.kind(), null, null);
        assertRejected(() -> content.verifySnapshot(row, "citizen-snapshot-v1", AT));
    }

    private PublicationRepository.Snapshot snapshot() { var row = row(payload); return content.snapshot(command(List.of(row)), List.of(row), sources, ID, AT); }
    private PublicationCommand.CitizenPublish command(List<PublicationRepository.Revision> rows) {
        return new PublicationCommand.CitizenPublish("citizen-publication-command-v1", "publish", "합성 시민 공개", "synthetic", rows.stream().map(row -> UUID.fromString(row.id())).toList(), null);
    }
    private PublicationRepository.Revision row(ObjectNode value) {
        var revision = value.path("revision");
        String json = value.toString();
        return new PublicationRepository.Revision(revision.path("revision_id").asText(), revision.path("event_id").asText(), revision.path("revision_no").asLong(), "approved", "public", json,
                ReviewedImportReader.sha256(json.getBytes(StandardCharsets.UTF_8)), revision.path("revision_id").asText(), 1);
    }
    private void reject(Consumer<ObjectNode> mutate) throws Exception {
        var original = snapshot();
        var json = (ObjectNode) mapper.readTree(original.canonical());
        mutate.accept(json);
        String canonical = json.toString();
        var corrupted = new PublicationRepository.Snapshot(original.id(), original.mode(), original.caseId(), canonical,
                ReviewedImportReader.sha256(canonical.getBytes(StandardCharsets.UTF_8)), original.kind(), null, null);
        assertRejected(() -> content.verifySnapshot(corrupted, "citizen-snapshot-v1", AT));
    }
    private void assertRejected(org.assertj.core.api.ThrowableAssert.ThrowingCallable action) {
        assertThatThrownBy(action).isInstanceOf(PublicationException.class);
    }
    private ObjectNode revision() { return (ObjectNode) payload.path("revision"); }
    private ObjectNode notice(ObjectNode value) { return (ObjectNode) value.path("notices").get(0); }
    private ObjectNode source(ObjectNode value) { return (ObjectNode) value.path("sources").get(0); }
    private Set<String> fields(JsonNode value) { var fields = new HashSet<String>(); value.fieldNames().forEachRemaining(fields::add); return fields; }
}
