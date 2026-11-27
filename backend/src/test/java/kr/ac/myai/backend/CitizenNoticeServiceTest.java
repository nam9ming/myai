package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.CitizenPublicationContent;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.repository.PublicationRepository;
import kr.ac.myai.backend.repository.PublicSnapshotRepository;
import kr.ac.myai.backend.service.CitizenNoticeService;
import kr.ac.myai.backend.source.SourceView;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.HttpStatus;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class CitizenNoticeServiceTest {
    private static final String CURRENT = "30000000-0000-4000-8000-000000000001";
    private static final String PAST = "30000000-0000-4000-8000-000000000002";
    private static final String EMPTY = "30000000-0000-4000-8000-000000000003";
    private static final String OTHER_KIND = "30000000-0000-4000-8000-000000000004";
    private static final String EVENT = "20000000-0000-4000-8000-000000000004";
    private static final String REVISION = "20000000-0000-4000-8000-000000000007";
    private static final String CHANGED_REVISION = "30000000-0000-4000-8000-000000000010";
    private static final Instant CREATED = Instant.parse("2026-11-18T00:00:00Z");
    private static final int LIMIT = 8 * 1024 * 1024;
    private final ObjectMapper mapper = new ObjectMapper();
    private final ReviewedImportReader reader = new ReviewedImportReader();
    private final PublicationContent shared = new PublicationContent(reader, mapper);
    private final CitizenPublicationContent canonical = new CitizenPublicationContent(shared, mapper);
    private final PublicSnapshotRepository repository = mock(PublicSnapshotRepository.class);
    private final CitizenNoticeService service = new CitizenNoticeService(repository, canonical, shared, mapper);
    private final Map<String, PublicSnapshotRepository.Published> records = new HashMap<>();
    private List<PublicSnapshotRepository.CitizenHistoric> audits;
    private final Map<Integer, String> auditSnapshots = new HashMap<>();
    private ObjectNode payload;
    private PublicationRepository.Document document;
    private String head;

    @BeforeEach
    void publicFixtures() throws Exception {
        var batch = reader.read(Path.of("examples/citizen-reviewed-import.json"), Path.of("examples"));
        payload = (ObjectNode) mapper.readTree(batch.events().getFirst().payloadJson());
        revision(payload).put("review_status", "approved").put("publication_intent", "public");
        revision(payload).putArray("categories").add("education").add("support").add("culture").add("construction_traffic").add("living");
        var source = batch.documents().getFirst();
        document = new PublicationRepository.Document(source.id(), source.versionId(), source.versionNo(), source.textSha256(), source.metadataJson(), source.privateContentRef());
        records.put(CURRENT, published(CURRENT, "synthetic", payload));
        audits = List.of(audit(CURRENT, REVISION, 1, "publish"));
        head = CURRENT;
        when(repository.head(CitizenPublicationContent.CHANNEL)).thenAnswer(call -> Optional.ofNullable(head));
        when(repository.citizenPublished(anyString())).thenAnswer(call -> Optional.ofNullable(records.get(call.getArgument(0))));
        when(repository.citizenHistory(anyString(), anyString(), nullable(Long.class), anyInt())).thenAnswer(call -> {
            long headVersion = audits.stream().mapToLong(PublicSnapshotRepository.CitizenHistoric::version).max().orElse(0);
            Long before = call.getArgument(2); int limit = call.getArgument(3);
            long end = before == null ? headVersion : before - 1, start = Math.max(0, end - limit + 1);
            var page = audits.stream().filter(item -> item.version() >= Math.max(0, start - 1) && item.version() <= end).limit(limit + 2L).toList();
            return new PublicSnapshotRepository.CitizenHistory(headVersion, start, end, page);
        });
    }

    @Test
    void listsTheVerifiedFixedCitizenFactsWithoutLegacyOrPrivateFields() throws Exception {
        Instant before = Instant.now();
        JsonNode result = service.list(null);
        assertThat(fields(result)).containsExactlyInAnyOrder("schema_version", "snapshot_id", "generated_at", "data");
        assertThat(result.path("schema_version").asText()).isEqualTo("citizen-api-v1");
        assertThat(result.path("snapshot_id").asText()).isEqualTo(CURRENT);
        assertThat(Instant.parse(result.path("generated_at").asText())).isBetween(before, Instant.now());
        var data = result.path("data");
        assertThat(fields(data)).containsExactlyInAnyOrder("created_at", "data_kind", "mode", "timezone", "notice_count", "notices", "sources");
        assertThat(data.path("created_at").asText()).isEqualTo("2026-11-18T00:00:00Z");
        assertThat(data.path("data_kind").asText()).isEqualTo("synthetic");
        assertThat(data.path("mode").asText()).isEqualTo("current");
        assertThat(data.path("timezone").asText()).isEqualTo("Asia/Seoul");
        assertThat(data.path("notice_count").intValue()).isEqualTo(1);
        var notice = data.path("notices").get(0);
        assertThat(notice.path("categories")).hasSize(5);
        assertThat(notice.path("application_period").path("value").asText()).isEqualTo("2026-11-20~2026-11-25");
        assertThat(notice.path("occurrences").path("value").asText()).isEqualTo("2026-12-01~2026-12-02");
        assertThat(notice.path("cost").path("value").isNull()).isTrue();
        assertThat(notice.path("cost").path("knowledge").asText()).isEqualTo("not_stated");
        assertThat(data.path("sources").get(0).path("last_verified_at").asText()).isEqualTo("2026-11-02T02:00:00Z");
        assertThat(result.toString()).doesNotContain("reviewer", "raw_asset_path", "cleaned_text", "human_overrides", "originating_run_ids", "rules_version", "dictionary_version", "point_id", "eligibleness", "is_free");
        assertThat(service.list(UUID.fromString(CURRENT)).path("data")).isEqualTo(data);
    }

    @Test
    void detailIncludesOnlyTheChosenNoticeSourcesAndUnknownPrehistory() throws Exception {
        var extra = payload.deepCopy();
        String otherEvent = "30000000-0000-4000-8000-000000000020";
        String otherRevision = "30000000-0000-4000-8000-000000000021";
        ((ObjectNode) extra.path("event")).put("event_id", otherEvent);
        revision(extra).put("event_id", otherEvent).put("revision_id", otherRevision).put("title", "다른 공개 공지");
        String otherDoc = "30000000-0000-4000-8000-000000000030";
        String otherVersion = "30000000-0000-4000-8000-000000000031";
        revision(extra).putArray("source_version_ids").add(otherVersion);
        ((ObjectNode) extra.path("event").path("document_links").get(0)).put("document_id", otherDoc);
        for (var quote : extra.path("evidence")) ((ObjectNode) quote).put("document_version_id", otherVersion);
        var metadata = (ObjectNode) mapper.readTree(document.metadata());
        ((ObjectNode) metadata.path("document")).put("document_id", otherDoc).put("document_version_id", otherVersion).put("title", "다른 문서");
        var second = new PublicationRepository.Document(otherDoc, otherVersion, 1, document.textHash(), metadata.toString(), document.privateRef());
        records.put(CURRENT, published(CURRENT, "synthetic", Map.of(document.versionId(), new SourceView(document), otherVersion, new SourceView(second)), payload, extra));
        var result = service.notice(UUID.fromString(EVENT), UUID.fromString(CURRENT), null, kr.ac.myai.backend.repository.PublicSnapshotRepository.MAX_CITIZEN_HISTORY);
        var data = result.path("data");
        assertThat(fields(data)).containsExactlyInAnyOrder("created_at", "data_kind", "mode", "timezone", "notice", "sources", "history");
        assertThat(data.path("notice").path("event_id").asText()).isEqualTo(EVENT);
        assertThat(data.path("sources")).hasSize(1);
        assertThat(data.path("sources").get(0).path("document_version_id").asText()).isEqualTo("20000000-0000-4000-8000-000000000002");
        assertThat(result.toString()).doesNotContain("다른 문서", "다른 공개 공지");
        var history = data.path("history");
        assertThat(fields(history)).containsExactlyInAnyOrder("scope", "completeness", "status", "window", "entries", "error");
        assertThat(history.path("scope").asText()).isEqualTo("same_data_kind_published_snapshots");
        assertThat(history.path("completeness").asText()).isEqualTo("unknown");
        assertThat(history.path("entries")).hasSize(1);
        var first = history.path("entries").get(0);
        assertThat(fields(first)).containsExactlyInAnyOrder("kind", "snapshot_id", "published_at", "action", "before", "after");
        assertThat(first.path("kind").asText()).isEqualTo("first_observed");
        assertThat(first.path("before").isNull()).isTrue();
        assertThat(fields(first.path("after"))).containsExactlyInAnyOrder("notice", "sources");
        assertThat(first.path("after").path("notice").path("title").asText()).isEqualTo("합성 시민 공지 😀");
    }

    @Test
    void preservesAllRawFieldValuesIncludingArraysAndExplicitCostWithoutDerivingEligibility() throws Exception {
        var preparation = (ObjectNode) revision(payload).path("preparation");
        preparation.put("knowledge", "known").putNull("reason").putArray("evidence_ids").add("body-quote");
        preparation.putArray("value").add("신분증").add("신청서");
        var cost = (ObjectNode) revision(payload).path("cost");
        cost.put("value", "무료(교재비 별도)").put("knowledge", "known").putNull("reason").putArray("evidence_ids").add("body-quote");
        records.put(CURRENT, published(CURRENT, "synthetic", payload));
        var notice = detail().path("notice");
        assertThat(fields(notice)).containsExactlyInAnyOrder("event_id", "revision_id", "title", "categories", "application_period", "occurrences",
                "regions", "locations", "residency_requirement", "target", "eligibility", "application_method", "preparation", "cost", "recruitment", "lifecycle",
                "source_version_ids", "document_links", "relations", "evidence");
        assertThat(notice.path("preparation").path("value").get(0).asText()).isEqualTo("신분증");
        assertThat(notice.path("preparation").path("value").get(1).asText()).isEqualTo("신청서");
        assertThat(notice.path("cost").path("value").asText()).isEqualTo("무료(교재비 별도)");
        assertThat(notice.path("eligibility").path("knowledge").asText()).isEqualTo("not_stated");
        assertThat(notice.path("eligibility").path("value").isNull()).isTrue();
    }

    @Test
    void emptyPublicationRemainsAValidListAndHasNoInventedNotice() throws Exception {
        records.put(CURRENT, published(CURRENT, "synthetic"));
        var data = service.list(null).path("data");
        assertThat(data.path("notice_count").intValue()).isZero();
        assertThat(data.path("notices")).isEmpty();
        assertThat(data.path("sources")).isEmpty();
        error(() -> service.notice(UUID.fromString(EVENT), UUID.fromString(CURRENT), null, kr.ac.myai.backend.repository.PublicSnapshotRepository.MAX_CITIZEN_HISTORY), HttpStatus.NOT_FOUND, "NOTICE_NOT_FOUND");
    }

    @Test
    void omittedHeadAbsenceIsUnavailableAndBrokenHeadIsInvalid() {
        head = null;
        error(() -> service.list(null), HttpStatus.SERVICE_UNAVAILABLE, "PUBLIC_DATA_NOT_READY");
        head = PAST;
        error(() -> service.list(null), HttpStatus.INTERNAL_SERVER_ERROR, "SNAPSHOT_INVALID");
    }

    @Test
    void unknownExplicitOrOtherFamilyIdIsNotFoundEvenWithoutAHead() {
        head = null;
        error(() -> service.list(UUID.fromString(PAST)), HttpStatus.NOT_FOUND, "SNAPSHOT_NOT_FOUND");
    }

    @Test
    void retiredExplicitSnapshotReturnsTheCurrentIdAndNullHeadStillConflicts() throws Exception {
        records.put(PAST, published(PAST, "synthetic", payload));
        assertThatThrownBy(() -> service.list(UUID.fromString(PAST))).isInstanceOfSatisfying(ApiException.class, failure -> {
            assertThat(failure.status()).isEqualTo(HttpStatus.CONFLICT);
            assertThat(failure.code()).isEqualTo("SNAPSHOT_RETIRED");
            assertThat(failure.currentSnapshotId()).isEqualTo(CURRENT);
        });
        var row = records.get(PAST);
        records.put(PAST, new PublicSnapshotRepository.Published(row.snapshot(), row.schemaVersion(), row.createdAt(), null));
        assertThatThrownBy(() -> service.list(UUID.fromString(PAST))).isInstanceOfSatisfying(ApiException.class, failure -> {
            assertThat(failure.code()).isEqualTo("SNAPSHOT_RETIRED");
            assertThat(failure.currentSnapshotId()).isNull();
        });
    }

    @ParameterizedTest
    @ValueSource(strings = {"checksum", "db_schema", "db_created", "db_rules", "db_dictionary", "root_schema", "root_channel", "private", "source_ref", "source_hash"})
    void refusesCorruptedPublicationMetadataOrPublicContent(String corruption) throws Exception {
        var row = records.get(CURRENT);
        var snapshot = row.snapshot();
        switch (corruption) {
            case "checksum" -> snapshot = new PublicationRepository.Snapshot(CURRENT, "current", null, snapshot.canonical(), "f".repeat(64), "synthetic", null, null);
            case "db_schema" -> row = new PublicSnapshotRepository.Published(snapshot, "snapshot-v1", CREATED, CURRENT);
            case "db_created" -> row = new PublicSnapshotRepository.Published(snapshot, row.schemaVersion(), CREATED.plusSeconds(1), CURRENT);
            case "db_rules" -> snapshot = new PublicationRepository.Snapshot(CURRENT, "current", null, snapshot.canonical(), snapshot.checksum(), "synthetic", "private-rules", null);
            case "db_dictionary" -> snapshot = new PublicationRepository.Snapshot(CURRENT, "current", null, snapshot.canonical(), snapshot.checksum(), "synthetic", null, "private-dictionary");
            default -> {
                String change = corruption;
                snapshot = altered(snapshot, json -> {
                    switch (change) {
                        case "root_schema" -> json.put("schema_version", "snapshot-v1");
                        case "root_channel" -> json.put("channel_key", "current");
                        case "private" -> ((ObjectNode) json.path("notices").get(0)).put("reviewer_id", "private-reviewer");
                        case "source_ref" -> ((ObjectNode) json.path("notices").get(0)).putArray("source_version_ids").add(PAST);
                        case "source_hash" -> ((ObjectNode) json.path("notices").get(0).path("evidence").get(0)).put("text_sha256", "f".repeat(64));
                    }
                });
            }
        }
        records.put(CURRENT, new PublicSnapshotRepository.Published(snapshot, row.schemaVersion(), row.createdAt(), CURRENT));
        error(() -> service.list(null), HttpStatus.INTERNAL_SERVER_ERROR, "SNAPSHOT_INVALID");
    }

    @Test
    void historyPreservesChangedWithdrawnAndRollbackRestoredStates() throws Exception {
        var changed = payload.deepCopy();
        revision(changed).put("revision_id", CHANGED_REVISION).put("title", "변경된 합성 시민 공지");
        records.put(PAST, published(PAST, "synthetic", changed));
        records.put(EMPTY, published(EMPTY, "synthetic"));
        audits = List.of(audit(CURRENT, REVISION, 1, "publish"), audit(PAST, CHANGED_REVISION, 2, "publish"),
                audit(EMPTY, null, 3, "publish"), audit(CURRENT, REVISION, 4, "rollback"));
        var entries = detail().path("history").path("entries");
        assertThat(entries).hasSize(4);
        assertThat(entries.get(0).path("kind").asText()).isEqualTo("first_observed");
        assertThat(entries.get(1).path("kind").asText()).isEqualTo("changed");
        assertThat(entries.get(1).path("before").path("notice").path("title").asText()).isEqualTo("합성 시민 공지 😀");
        assertThat(entries.get(1).path("after").path("notice").path("title").asText()).isEqualTo("변경된 합성 시민 공지");
        assertThat(entries.get(2).path("kind").asText()).isEqualTo("withdrawn");
        assertThat(entries.get(2).path("after").isNull()).isTrue();
        assertThat(entries.get(3).path("kind").asText()).isEqualTo("restored");
        assertThat(entries.get(3).path("before").isNull()).isTrue();
        assertThat(entries.get(3).path("after").path("notice").path("revision_id").asText()).isEqualTo(REVISION);
        assertThat(entries.get(3).path("action").asText()).isEqualTo("rollback");
        assertThat(entries.get(3).path("published_at").asText()).isEqualTo("2026-11-18T04:00:00Z");
        for (var entry : entries) assertThat(fields(entry)).containsExactlyInAnyOrder("kind", "snapshot_id", "published_at", "action", "before", "after");
        assertThat(entries.get(0).path("after").path("notice").path("cost").path("reason").asText()).isEqualTo("합성 원문에 해당 정보가 명시되지 않음");
    }

    @Test
    void omitsUnchangedRepublicationAndComparesOnlyTheSelectedDataKind() throws Exception {
        records.put(PAST, published(PAST, "synthetic", payload));
        var real = payload.deepCopy();
        revision(real).put("title", "별도 종류의 공지");
        records.put(OTHER_KIND, published(OTHER_KIND, "real", real));
        audits = List.of(audit(PAST, REVISION, 1, "publish"), audit(OTHER_KIND, REVISION, 2, "publish"), audit(CURRENT, REVISION, 3, "publish"));
        var entries = detail().path("history").path("entries");
        assertThat(entries).hasSize(1);
        assertThat(entries.get(0).path("snapshot_id").asText()).isEqualTo(PAST);
        assertThat(entries.toString()).doesNotContain("별도 종류의 공지", OTHER_KIND);
    }

    @Test
    void recordsChangedFrozenSourceChecksEvenWhenTheNoticeRevisionIsUnchanged() throws Exception {
        records.put(PAST, published(PAST, "synthetic", payload));
        var metadata = (ObjectNode) mapper.readTree(document.metadata());
        var source = (ObjectNode) metadata.path("document");
        source.put("last_verified_at", "2026-11-02T03:00:00Z").put("latest_check_attempt_at", "2026-11-02T03:00:00Z");
        source.withArray("checks").addObject().put("check_id", "30000000-0000-4000-8000-000000000040")
                .put("checked_at", "2026-11-02T03:00:00Z").put("result", "verified").put("text_sha256", document.textHash())
                .put("reviewer_id", "private-reviewer").put("note", "합성 후속 확인");
        records.put(CURRENT, published(CURRENT, "synthetic", Map.of(document.versionId(), new SourceView(document, metadata.toString(), 1, "a".repeat(64), Map.of())), payload));
        audits = List.of(audit(PAST, REVISION, 1, "publish"), audit(CURRENT, REVISION, 2, "publish"));
        var entries = detail().path("history").path("entries");
        assertThat(entries).hasSize(2);
        assertThat(entries.get(1).path("kind").asText()).isEqualTo("changed");
        assertThat(entries.get(1).path("before").path("notice")).isEqualTo(entries.get(1).path("after").path("notice"));
        assertThat(entries.get(1).path("before").path("sources").get(0).path("last_verified_at").asText()).isEqualTo("2026-11-02T02:00:00Z");
        assertThat(entries.get(1).path("after").path("sources").get(0).path("last_verified_at").asText()).isEqualTo("2026-11-02T03:00:00Z");
    }

    @ParameterizedTest
    @ValueSource(strings = {"wrong_revision", "present_without_membership", "absent_with_membership", "missing_past", "no_history", "missing_current", "invalid_action"})
    void refusesMissingHistoryOrMembershipThatDisagreesWithCanonicalFacts(String corruption) throws Exception {
        records.put(PAST, published(PAST, "synthetic", payload));
        records.put(EMPTY, published(EMPTY, "synthetic"));
        audits = switch (corruption) {
            case "wrong_revision" -> List.of(audit(CURRENT, CHANGED_REVISION, 1, "publish"));
            case "present_without_membership" -> List.of(audit(CURRENT, null, 1, "publish"));
            case "absent_with_membership" -> List.of(audit(EMPTY, REVISION, 1, "publish"), audit(CURRENT, REVISION, 2, "rollback"));
            case "missing_past" -> List.of(audit(OTHER_KIND, REVISION, 1, "publish"), audit(CURRENT, REVISION, 2, "rollback"));
            case "no_history" -> List.of();
            case "missing_current" -> List.of(audit(PAST, REVISION, 1, "publish"));
            default -> List.of(audit(CURRENT, REVISION, 1, "approve"));
        };
        error(this::detail, HttpStatus.INTERNAL_SERVER_ERROR, "SNAPSHOT_INVALID");
    }

    @Test
    void duplicateAuditVersionsCannotMasqueradeAsAValidPage() {
        audits = Collections.nCopies(1001, audit(CURRENT, REVISION, 1, "publish"));
        error(this::detail, HttpStatus.INTERNAL_SERVER_ERROR, "SNAPSHOT_INVALID");
    }

    @Test
    void oneThousandRepeatedImmutableRowsUsesOnlyOneCanonicalRead() throws Exception {
        records.put(CURRENT, padded(records.get(CURRENT), 5 * 1024 * 1024));
        audits = java.util.stream.IntStream.rangeClosed(1, 1000).mapToObj(hour -> audit(CURRENT, REVISION, hour, hour == 1 ? "publish" : "rollback")).toList();
        assertThat(detail().path("history").path("entries")).hasSize(1);
        verify(repository, times(1)).citizenPublished(CURRENT);
    }

    @Test
    void cumulativeUtf8BudgetIncludesCurrentAndFailsOnlyAboveEightMiB() throws Exception {
        records.put(CURRENT, padded(records.get(CURRENT), LIMIT / 2));
        records.put(PAST, padded(published(PAST, "synthetic", payload), LIMIT / 2));
        audits = List.of(audit(PAST, REVISION, 1, "publish"), audit(CURRENT, REVISION, 2, "publish"));
        assertThat(detail().path("history").path("entries")).hasSize(1);
        records.put(PAST, padded(published(PAST, "synthetic", payload), LIMIT / 2 + 1));
        tooLarge();
    }

    @Test
    void skippedOtherDataKindStillConsumesTheRawReadBudget() throws Exception {
        records.put(CURRENT, padded(records.get(CURRENT), LIMIT / 2));
        records.put(OTHER_KIND, padded(published(OTHER_KIND, "real", payload), LIMIT / 2 + 1));
        audits = List.of(audit(OTHER_KIND, REVISION, 1, "publish"), audit(CURRENT, REVISION, 2, "publish"));
        tooLarge();
    }

    @Test
    void verifiedSnapshotsAreCachedOnlyWithinOneRequest() throws Exception {
        assertThat(detail().path("notice").path("title").asText()).isEqualTo("합성 시민 공지 😀");
        var row = records.get(CURRENT);
        records.put(CURRENT, new PublicSnapshotRepository.Published(altered(row.snapshot(), json -> json.put("channel_key", "current")), row.schemaVersion(), CREATED, CURRENT));
        error(this::detail, HttpStatus.INTERNAL_SERVER_ERROR, "SNAPSHOT_INVALID");
    }

    @Test
    void alternatingLargeFrozenStatesRejectsResponseAmplification() throws Exception {
        var current = records.get(CURRENT);
        records.put(CURRENT, new PublicSnapshotRepository.Published(altered(current.snapshot(), value ->
                ((ObjectNode) value.path("notices").get(0)).put("title", "A".repeat(2 * 1024 * 1024))), current.schemaVersion(), CREATED, CURRENT));
        var past = published(PAST, "synthetic", payload);
        records.put(PAST, new PublicSnapshotRepository.Published(altered(past.snapshot(), value ->
                ((ObjectNode) value.path("notices").get(0)).put("title", "B".repeat(2 * 1024 * 1024))), past.schemaVersion(), CREATED, CURRENT));
        audits = List.of(audit(PAST, REVISION, 1, "publish"), audit(CURRENT, REVISION, 2, "publish"),
                audit(PAST, REVISION, 3, "rollback"), audit(CURRENT, REVISION, 4, "rollback"));
        tooLarge();
    }

    @Test
    void pagesBeforeTheSelectedHeadAndUsesOnlyTheVerifiedBoundaryState() throws Exception {
        var first = payload.deepCopy(); revision(first).put("title", "first");
        var second = payload.deepCopy(); revision(second).put("title", "second");
        records.put(PAST, published(PAST, "synthetic", first));
        records.put(EMPTY, published(EMPTY, "synthetic", second));
        audits = List.of(audit(PAST, REVISION, 1, "publish"), audit(EMPTY, REVISION, 2, "publish"), audit(CURRENT, REVISION, 3, "publish"));
        var data = service.notice(UUID.fromString(EVENT), UUID.fromString(CURRENT), null, 1).path("data");
        assertThat(data.path("notice").path("title").asText()).isEqualTo("합성 시민 공지 😀");
        var window = data.path("history").path("window");
        assertThat(window.path("from_version").asLong()).isEqualTo(2);
        assertThat(window.path("to_version").asLong()).isEqualTo(2);
        assertThat(window.path("next_before_version").asLong()).isEqualTo(2);
        assertThat(window.path("has_more").asBoolean()).isTrue();
        var entry = data.path("history").path("entries").get(0);
        assertThat(entry.path("kind").asText()).isEqualTo("changed");
        assertThat(entry.path("before").path("notice").path("title").asText()).isEqualTo("second");
        var older = service.notice(UUID.fromString(EVENT), UUID.fromString(CURRENT), 1L, 1).path("data");
        assertThat(older.path("notice")).isEqualTo(data.path("notice"));
        assertThat(older.path("history").path("window").path("has_more").asBoolean()).isFalse();
        assertThat(older.path("history").path("entries").get(0).path("kind").asText()).isEqualTo("first_observed");
        assertThat(older.path("history").path("entries").get(0).path("snapshot_id").asText()).isEqualTo(PAST);
    }

    @Test
    void aPageRecordsConfirmedAbsenceWithoutInventingARestorationAcrossDataKinds() throws Exception {
        records.put(PAST, published(PAST, "synthetic", payload));
        records.put(OTHER_KIND, published(OTHER_KIND, "real", payload));
        records.put(EMPTY, published(EMPTY, "synthetic"));
        audits = List.of(audit(PAST, REVISION, 1, "publish"), audit(OTHER_KIND, REVISION, 2, "publish"),
                audit(EMPTY, null, 3, "publish"), audit(CURRENT, REVISION, 4, "publish"));
        var data = service.notice(UUID.fromString(EVENT), UUID.fromString(CURRENT), null, 2).path("data");
        var entries = data.path("history").path("entries");
        assertThat(entries).hasSize(2);
        assertThat(entries.get(0).path("kind").asText()).isEqualTo("observed");
        assertThat(entries.get(0).path("snapshot_id").asText()).isEqualTo(EMPTY);
        assertThat(entries.get(0).path("before").isNull()).isTrue();
        assertThat(entries.get(0).path("after").isNull()).isTrue();
        assertThat(entries.get(1).path("kind").asText()).isEqualTo("observed");
        assertThat(entries.get(1).path("after").path("notice").path("event_id").asText()).isEqualTo(EVENT);
    }

    @Test
    void aCurrentSnapshotAtEightMiBStillServesFactsAndOnlyAdditionalHistoryDegrades() throws Exception {
        records.put(CURRENT, padded(records.get(CURRENT), LIMIT));
        assertThat(service.list(null).path("data").path("notice_count").asInt()).isEqualTo(1);
        assertThat(detail().path("notice").path("event_id").asText()).isEqualTo(EVENT);
        assertThat(detail().path("history").path("status").asText()).isEqualTo("available");
        records.put(PAST, published(PAST, "synthetic", payload));
        audits = List.of(audit(PAST, REVISION, 1, "publish"), audit(CURRENT, REVISION, 2, "publish"));
        tooLarge();
        assertThat(service.list(UUID.fromString(CURRENT)).path("data").path("notice_count").asInt()).isEqualTo(1);
    }

    @Test
    void aCanonicalAboveEightMiBIsInvalidRatherThanAHistoryCapacityFailure() {
        var current = records.get(CURRENT); var row = current.snapshot();
        String raw = row.canonical() + " ".repeat(LIMIT + 1 - row.canonical().getBytes(StandardCharsets.UTF_8).length);
        var oversized = new PublicationRepository.Snapshot(CURRENT, row.mode(), row.caseId(), raw,
                ReviewedImportReader.sha256(raw.getBytes(StandardCharsets.UTF_8)), row.kind(), row.rulesVersion(), row.dictionaryVersion());
        records.put(CURRENT, new PublicSnapshotRepository.Published(oversized, current.schemaVersion(), current.createdAt(), CURRENT));
        error(() -> service.list(null), HttpStatus.INTERNAL_SERVER_ERROR, "SNAPSHOT_INVALID");
        error(this::detail, HttpStatus.INTERNAL_SERVER_ERROR, "SNAPSHOT_INVALID");
    }

    @Test
    void replacementValidationHasAnIndependentBudgetForTwoValidLargeSnapshots() throws Exception {
        records.put(CURRENT, padded(records.get(CURRENT), 5 * 1024 * 1024));
        records.put(PAST, padded(published(PAST, "synthetic", payload), 5 * 1024 * 1024));
        assertThatThrownBy(() -> service.list(UUID.fromString(PAST))).isInstanceOfSatisfying(ApiException.class, failure -> {
            assertThat(failure.status()).isEqualTo(HttpStatus.CONFLICT);
            assertThat(failure.code()).isEqualTo("SNAPSHOT_RETIRED");
            assertThat(failure.currentSnapshotId()).isEqualTo(CURRENT);
        });
    }

    @Test
    void maximumValidCurrentFactsStillFitAnUnavailableHistoryEnvelope() throws Exception {
        var original = records.get(CURRENT);
        int originalTitle = mapper.readTree(original.snapshot().canonical()).path("notices").get(0).path("title").asText().getBytes(StandardCharsets.UTF_8).length;
        int titleBytes = LIMIT - original.snapshot().canonical().getBytes(StandardCharsets.UTF_8).length + originalTitle;
        revision(payload).put("title", "x".repeat(titleBytes));
        var maximum = published(CURRENT, "synthetic", payload);
        assertThat(maximum.snapshot().canonical().getBytes(StandardCharsets.UTF_8).length).isEqualTo(LIMIT);
        records.put(CURRENT, maximum);
        var result = org.junit.jupiter.api.Assertions.assertDoesNotThrow(() -> service.notice(UUID.fromString(EVENT), UUID.fromString(CURRENT), null, kr.ac.myai.backend.repository.PublicSnapshotRepository.MAX_CITIZEN_HISTORY));
        assertThat(result.path("data").path("notice").path("title").asText()).hasSize(titleBytes);
        assertThat(result.path("data").path("history").path("status").asText()).isEqualTo("unavailable");
        assertThat(result.path("data").path("history").path("entries").isNull()).isTrue();
        assertThat(mapper.writeValueAsBytes(result).length).isLessThanOrEqualTo(LIMIT + 1024);
    }

    private JsonNode detail() { return service.notice(UUID.fromString(EVENT), UUID.fromString(CURRENT), null, kr.ac.myai.backend.repository.PublicSnapshotRepository.MAX_CITIZEN_HISTORY).path("data"); }
    private void tooLarge() {
        var data = detail();
        assertThat(data.path("notice").path("event_id").asText()).isEqualTo(EVENT);
        assertThat(data.path("sources")).isNotEmpty();
        var history = data.path("history");
        assertThat(history.path("status").asText()).isEqualTo("unavailable");
        assertThat(history.path("window").isNull()).isTrue();
        assertThat(history.path("entries").isNull()).isTrue();
        assertThat(history.path("error").path("code").asText()).isEqualTo("CITIZEN_HISTORY_TOO_LARGE");
        assertThat(history.path("error").path("retryable").asBoolean()).isFalse();
    }
    private void error(org.assertj.core.api.ThrowableAssert.ThrowingCallable call, HttpStatus status, String code) {
        assertThatThrownBy(call).isInstanceOfSatisfying(ApiException.class, failure -> {
            assertThat(failure.status()).isEqualTo(status);
            assertThat(failure.code()).isEqualTo(code);
        });
    }
    private PublicSnapshotRepository.CitizenHistoric audit(String id, String revisionId, int hour, String action) {
        auditSnapshots.put(hour - 1, id);
        return new PublicSnapshotRepository.CitizenHistoric(id, revisionId, CREATED.plusSeconds(hour * 3600L), action, hour - 1, hour == 1 ? null : auditSnapshots.get(hour - 2));
    }
    private PublicSnapshotRepository.Published published(String id, String kind, ObjectNode... events) throws Exception {
        var metadata = (ObjectNode) mapper.readTree(document.metadata());
        metadata.put("data_kind", kind);
        var view = new SourceView(document, metadata.toString(), 0, null, Map.of());
        return published(id, kind, Map.of(document.versionId(), view), events);
    }
    private PublicSnapshotRepository.Published published(String id, String kind, Map<String, SourceView> sources, ObjectNode... events) {
        var rows = new ArrayList<PublicationRepository.Revision>();
        for (var original : events) {
            var value = original.deepCopy().put("data_kind", kind);
            var revision = value.path("revision");
            String json = value.toString();
            rows.add(new PublicationRepository.Revision(revision.path("revision_id").asText(), revision.path("event_id").asText(), 1, "approved", "public", json,
                    ReviewedImportReader.sha256(json.getBytes(StandardCharsets.UTF_8)), revision.path("revision_id").asText(), 1));
        }
        var command = new PublicationCommand.CitizenPublish("citizen-publication-command-v1", "publish", "합성 시민 조회 시험", kind,
                rows.stream().map(row -> UUID.fromString(row.id())).toList(), null);
        var snapshot = canonical.snapshot(command, rows, sources, id, CREATED);
        return new PublicSnapshotRepository.Published(snapshot, CitizenPublicationContent.SCHEMA_VERSION, CREATED, CURRENT);
    }
    private PublicSnapshotRepository.Published padded(PublicSnapshotRepository.Published original, int bytes) {
        var row = original.snapshot();
        String value = row.canonical() + " ".repeat(bytes - row.canonical().getBytes(StandardCharsets.UTF_8).length);
        var padded = new PublicationRepository.Snapshot(row.id(), row.mode(), row.caseId(), value, ReviewedImportReader.sha256(value.getBytes(StandardCharsets.UTF_8)), row.kind(), null, null);
        canonical.verifySnapshot(padded, CitizenPublicationContent.SCHEMA_VERSION, CREATED);
        return new PublicSnapshotRepository.Published(padded, original.schemaVersion(), original.createdAt(), original.currentId());
    }
    private PublicationRepository.Snapshot altered(PublicationRepository.Snapshot original, Consumer<ObjectNode> change) throws Exception {
        var json = (ObjectNode) mapper.readTree(original.canonical());
        change.accept(json);
        String value = json.toString();
        return new PublicationRepository.Snapshot(original.id(), original.mode(), original.caseId(), value,
                ReviewedImportReader.sha256(value.getBytes(StandardCharsets.UTF_8)), original.kind(), original.rulesVersion(), original.dictionaryVersion());
    }
    private ObjectNode revision(ObjectNode value) { return (ObjectNode) value.path("revision"); }
    private java.util.Set<String> fields(JsonNode node) { var names = new HashSet<String>(); node.fieldNames().forEachRemaining(names::add); return names; }
}
