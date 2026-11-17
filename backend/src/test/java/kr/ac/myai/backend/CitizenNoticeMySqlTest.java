package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Timestamp;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = "app.calculation.workdir=")
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class CitizenNoticeMySqlTest {
    @Autowired JdbcTemplate jdbc;
    @Autowired ReviewedImportReader imports;
    @Autowired ReviewedImportService importer;
    @Autowired PublicationCommandReader commands;
    @Autowired PublicationService publication;
    @LocalServerPort int port;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
    final Set<String> ownedSnapshots = new HashSet<>();
    boolean testDatabaseVerified;
    CitizenNoticeFixtures fixtures;

    @DynamicPropertySource
    static void testDatabase(DynamicPropertyRegistry registry) {
        String url = System.getenv("DB_URL");
        if (url == null || !url.startsWith("jdbc:mysql://")
                || !Set.of("/myai_test", "/myai_citizen_test").contains(URI.create(url.substring(5)).getRawPath())) {
            throw new IllegalStateException("시민 조회 시험은 전용 myai_test 또는 myai_citizen_test DB_URL이 필요합니다.");
        }
        registry.add("spring.datasource.url", () -> url);
    }

    @BeforeEach
    void verifyDatabaseAndUnusedCitizenChannel() {
        assertThat(jdbc.queryForObject("SELECT DATABASE()", String.class)).isIn("myai_test", "myai_citizen_test");
        testDatabaseVerified = true;
        assertThat(jdbc.queryForList("SELECT snapshot_id FROM publication_heads WHERE channel_key = 'citizen:current'"))
                .as("기존 시민 head는 시험이 덮어쓰거나 초기화하지 않는다").isEmpty();
        fixtures = new CitizenNoticeFixtures(root, jdbc, imports, importer, commands, publication, ownedSnapshots);
    }

    @AfterEach
    void removeOnlyOwnedSnapshots() {
        if (!testDatabaseVerified) return;
        for (String id : ownedSnapshots) jdbc.update("DELETE FROM publication_audits WHERE after_snapshot_id = ?", id);
        for (String id : ownedSnapshots) jdbc.update("DELETE FROM publication_heads WHERE snapshot_id = ?", id);
        for (String id : ownedSnapshots) jdbc.update("DELETE FROM snapshot_revisions WHERE snapshot_id = ?", id);
        for (String id : ownedSnapshots) jdbc.update("DELETE FROM snapshots WHERE snapshot_id = ?", id);
        ownedSnapshots.clear();
        http.close();
    }

    @Test
    void noCitizenHeadIsUnavailableRatherThanEmpty() throws Exception {
        var before = jdbc.queryForList("SELECT * FROM publication_heads");
        var response = http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/api/v1/citizen/notices"))
                .timeout(Duration.ofSeconds(10)).GET().build(), HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).isEqualTo(503);
        var body = mapper.readTree(response.body());
        assertThat(body.path("error").path("code").asText()).isEqualTo("PUBLIC_DATA_NOT_READY");
        assertThat(body.path("request_id").asText()).matches("[0-9a-f-]{36}");
        assertThat(body.path("error").path("field_errors").isArray()).isTrue();
        assertThat(response.body()).doesNotContain("SELECT ", "jdbc:mysql", "password", "private_content_ref");
        assertThat(jdbc.queryForList("SELECT * FROM publication_heads")).isEqualTo(before);
    }

    @ParameterizedTest
    @ValueSource(strings = {"education", "support", "culture", "construction_traffic", "living"})
    void listsAndReadsSameFrozenCitizenFactsInEveryCategory(String category) throws Exception {
        var input = fixtures.citizen(category, category.equals("support"));
        String approved = fixtures.approve(input, true);
        var published = fixtures.publish(List.of(approved), null);
        JsonNode canonical = fixtures.canonical(published.snapshotId());
        var listed = ok("/api/v1/citizen/notices");
        assertThat(keys(listed)).containsExactlyInAnyOrder("schema_version", "snapshot_id", "generated_at", "data");
        assertThat(listed.path("schema_version").asText()).isEqualTo("citizen-api-v1");
        assertThat(listed.path("snapshot_id").asText()).isEqualTo(published.snapshotId());
        assertThat(Instant.parse(listed.path("generated_at").asText())).isNotNull();
        var data = listed.path("data");
        assertThat(keys(data)).containsExactlyInAnyOrder("created_at", "data_kind", "mode", "timezone", "notice_count", "notices", "sources");
        assertThat(data.path("created_at")).isEqualTo(canonical.path("created_at"));
        assertThat(data.path("notices")).isEqualTo(canonical.path("notices"));
        assertThat(data.path("sources")).isEqualTo(canonical.path("sources"));
        var detail = ok(detail(CitizenNoticeFixtures.event(input), published.snapshotId()));
        assertThat(detail.path("snapshot_id")).isEqualTo(listed.path("snapshot_id"));
        assertThat(keys(detail.path("data"))).containsExactlyInAnyOrder("created_at", "data_kind", "mode", "timezone", "notice", "sources", "history");
        assertThat(detail.path("data").path("notice")).isEqualTo(data.path("notices").get(0));
        assertThat(detail.path("data").path("sources")).isEqualTo(data.path("sources"));
        var notice = detail.path("data").path("notice");
        assertThat(notice.path("categories").get(0).asText()).isEqualTo(category);
        for (String field : "application_period occurrences regions locations residency_requirement target eligibility application_method preparation cost recruitment lifecycle".split(" "))
            assertThat(notice.path(field)).isEqualTo(CitizenNoticeFixtures.revision(input).path(field));
        assertThat(notice.path("application_period")).isNotEqualTo(notice.path("occurrences"));
        if (category.equals("support")) assertThat(notice.path("cost").path("value").asText()).isEqualTo("5,000원");
        else assertThat(notice.path("cost").path("value").isNull()).isTrue();
        assertThat(detail.toString()).doesNotContain("raw_asset_path", "cleaned_text", "human_overrides", "reviewer_id", "private_content_ref", "synthetic-reviewer");
        assertThat(ok("/api/v1/citizen/notices?snapshot_id=" + published.snapshotId()).path("data")).isEqualTo(data);
    }

    @Test
    void explicitEmptyPublicationIsAvailableAndOldSelectionReturnsCurrentId() throws Exception {
        var input = fixtures.citizen("living", false); String revision = fixtures.approve(input, true);
        var first = fixtures.publish(List.of(revision), null); var empty = fixtures.publish(List.of(), 0L);
        var list = ok("/api/v1/citizen/notices?snapshot_id=" + empty.snapshotId());
        assertThat(list.path("data").path("notice_count").asInt(-1)).isZero();
        assertThat(list.path("data").path("notices")).isEmpty(); assertThat(list.path("data").path("sources")).isEmpty();
        for (String path : List.of("/api/v1/citizen/notices?snapshot_id=" + first.snapshotId(), detail(CitizenNoticeFixtures.event(input), first.snapshotId()))) {
            var error = error(path, 409, "SNAPSHOT_RETIRED");
            assertThat(error.path("current_snapshot_id").asText()).isEqualTo(empty.snapshotId());
        }
        error(detail(CitizenNoticeFixtures.event(input), empty.snapshotId()), 404, "NOTICE_NOT_FOUND");
        error("/api/v1/citizen/notices?snapshot_id=" + UUID.randomUUID(), 404, "SNAPSHOT_NOT_FOUND");
        fixtures.rollback(first.snapshotId(), 1);
        assertThat(ok(detail(CitizenNoticeFixtures.event(input), first.snapshotId())).path("data").path("notice").path("revision_id").asText()).isEqualTo(revision);
    }

    @Test
    void publishesMultipleCategoriesAndManyToManySourcesWithoutLeakingReviewers() throws Exception {
        var input = fixtures.citizen("education", false); var second = fixtures.citizen("support", false);
        var revision = CitizenNoticeFixtures.revision(input); revision.withArray("categories").add("culture");
        input.withArray("documents").add(second.path("documents").get(0));
        for (var evidence : second.path("evidence")) {
            var copied = (ObjectNode) evidence.deepCopy(); copied.put("evidence_id", "second-" + copied.path("evidence_id").asText());
            input.withArray("evidence").add(copied);
        }
        revision.withArray("source_version_ids").add(second.path("documents").get(0).path("document_version_id").asText());
        var event = (ObjectNode) input.path("events").get(0);
        event.withArray("document_links").addObject().put("document_id", second.path("documents").get(0).path("document_id").asText())
                .put("role", "original").putArray("evidence_ids").add("second-heading-quote").add("second-body-quote");
        var relation = event.withArray("relations").addObject().put("from_document_id", second.path("documents").get(0).path("document_id").asText())
                .put("to_document_id", input.path("documents").get(0).path("document_id").asText()).put("type", "reposts")
                .put("reviewed_by", "PRIVATE_SYNTHETIC_REVIEWER").put("reason", "합성 재게시 연결").put("created_at", "2026-11-02T02:00:00Z");
        String approved = fixtures.approve(input, true); var published = fixtures.publish(List.of(approved), null);
        var detail = ok(detail(CitizenNoticeFixtures.event(input), published.snapshotId()));
        assertThat(detail.path("data").path("notice").path("categories")).hasSize(2);
        assertThat(detail.path("data").path("sources")).hasSize(2);
        assertThat(detail.path("data").path("notice").path("evidence")).hasSize(4);
        assertThat(detail.path("data").path("notice").path("relations")).hasSize(1);
        assertThat(detail.toString()).doesNotContain("PRIVATE_SYNTHETIC_REVIEWER", "reviewed_by");
        assertThat(relation.path("reviewed_by").asText()).isEqualTo("PRIVATE_SYNTHETIC_REVIEWER");
    }

    @Test
    void citizenAndLegacySelectionsRejectEachOtherAndPreserveLegacyConfig() throws Exception {
        assertThat(jdbc.queryForList("SELECT snapshot_id FROM publication_heads WHERE channel_key='current'")).isEmpty();
        var oldInput = fixtures.legacy(); String oldRevision = fixtures.approve(oldInput, false);
        var legacy = fixtures.publishLegacy(oldInput, oldRevision);
        var before = ok("/api/v1/config");
        var input = fixtures.citizen("culture", false); String citizenRevision = fixtures.approve(input, true);
        var citizen = fixtures.publish(List.of(citizenRevision), null);
        error("/api/v1/citizen/notices?snapshot_id=" + legacy.snapshotId(), 404, "SNAPSHOT_NOT_FOUND");
        error(detail(CitizenNoticeFixtures.event(input), legacy.snapshotId()), 404, "SNAPSHOT_NOT_FOUND");
        error("/api/v1/events/" + CitizenNoticeFixtures.event(oldInput) + "?snapshot_id=" + citizen.snapshotId(), 404, "SNAPSHOT_NOT_FOUND");
        error(detail(CitizenNoticeFixtures.event(oldInput), citizen.snapshotId()), 404, "NOTICE_NOT_FOUND");
        var request = (ObjectNode) mapper.readTree(Path.of("../contracts/examples/matches-request.json").toFile());
        request.put("snapshot_id", citizen.snapshotId()).put("point_id", before.path("data").path("points").get(0).path("point_id").asText());
        var database = CitizenNoticeFixtures.rows(jdbc);
        var response = http.send(HttpRequest.newBuilder(uri("/api/v1/matches")).timeout(Duration.ofSeconds(10)).header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(request.toString())).build(), HttpResponse.BodyHandlers.ofString());
        assertThat(response.statusCode()).isEqualTo(404);
        assertThat(mapper.readTree(response.body()).path("error").path("code").asText()).isEqualTo("SNAPSHOT_NOT_FOUND");
        assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(database);
        var after = ok("/api/v1/config");
        assertThat(after.path("snapshot_id")).isEqualTo(before.path("snapshot_id"));
        assertThat(after.path("data").path("points")).isEqualTo(before.path("data").path("points"));
        assertThat(after.path("data").path("created_at")).isEqualTo(before.path("data").path("created_at"));
    }

    @Test
    void actualPublicationHistoryDistinguishesFirstChangedWithdrawnAndRestoredWithoutRawSources() throws Exception {
        var input = fixtures.citizen("education", false); String originalRevision = fixtures.approve(input, true);
        var first = fixtures.publish(List.of(originalRevision), null);
        var original = ok(detail(CitizenNoticeFixtures.event(input), first.snapshotId())).path("data");
        fixtures.publish(List.of(originalRevision), 0L);
        String edited = fixtures.editTitleAndApprove(input, "원문을 재검토한 합성 공지");
        var changed = fixtures.publish(List.of(edited), 1L);
        var changedFacts = ok(detail(CitizenNoticeFixtures.event(input), changed.snapshotId())).path("data");
        var withdrawn = fixtures.publish(List.of(), 2L);
        String canonical = fixtures.canonicalText(first.snapshotId());
        try (var files = Files.list(root)) { for (Path file : files.toList()) Files.delete(file); }
        fixtures.rollback(first.snapshotId(), 3);
        var detail = ok(detail(CitizenNoticeFixtures.event(input), first.snapshotId()));
        var history = detail.path("data").path("history");
        assertThat(keys(history)).containsExactlyInAnyOrder("scope", "completeness", "entries");
        assertThat(history.path("scope").asText()).isEqualTo("same_data_kind_published_snapshots");
        assertThat(history.path("completeness").asText()).isEqualTo("unknown");
        var entries = history.path("entries"); assertThat(entries).hasSize(4);
        assertThat(entries.findValuesAsText("kind")).containsExactly("first_observed", "changed", "withdrawn", "restored");
        assertThat(entries.get(0).path("before").isNull()).isTrue();
        assertThat(entries.get(0).path("after").path("notice")).isEqualTo(original.path("notice"));
        assertThat(entries.get(1).path("before").path("notice")).isEqualTo(original.path("notice"));
        assertThat(entries.get(1).path("after").path("notice")).isEqualTo(changedFacts.path("notice"));
        assertThat(entries.get(2).path("snapshot_id").asText()).isEqualTo(withdrawn.snapshotId());
        assertThat(entries.get(2).path("before").path("notice")).isEqualTo(changedFacts.path("notice"));
        assertThat(entries.get(2).path("after").isNull()).isTrue();
        assertThat(entries.get(3).path("before").isNull()).isTrue();
        assertThat(entries.get(3).path("after").path("notice")).isEqualTo(original.path("notice"));
        assertThat(entries.get(3).path("action").asText()).isEqualTo("rollback");
        for (var entry : entries) {
            assertThat(keys(entry)).containsExactlyInAnyOrder("kind", "snapshot_id", "published_at", "action", "before", "after");
            for (String side : List.of("before", "after")) if (!entry.path(side).isNull()) {
                assertThat(keys(entry.path(side))).containsExactlyInAnyOrder("notice", "sources");
                assertThat(entry.path(side).path("sources")).isEqualTo(original.path("sources"));
            }
        }
        assertThat(detail.path("data").path("sources")).isEqualTo(original.path("sources"));
        assertThat(fixtures.canonicalText(first.snapshotId())).isEqualTo(canonical);
    }

    @ParameterizedTest
    @ValueSource(strings = {"checksum", "private_notice", "private_source", "current_membership", "past_membership", "past_private"})
    void corruptedCurrentOrHistoricalPublicContentCannotLeakOrReturnPartialFacts(String defect) throws Exception {
        var input = fixtures.citizen("living", false); String approved = fixtures.approve(input, true);
        var first = fixtures.publish(List.of(approved), null);
        var selected = fixtures.publish(List.of(approved), 0L);
        String corrupted = defect.startsWith("past_") ? first.snapshotId() : selected.snapshotId();
        if (defect.equals("checksum")) jdbc.update("UPDATE snapshots SET checksum=? WHERE snapshot_id=?", "0".repeat(64), corrupted);
        else if (defect.endsWith("membership")) jdbc.update("DELETE FROM snapshot_revisions WHERE snapshot_id=?", corrupted);
        else {
            var canonical = (ObjectNode) fixtures.canonical(corrupted);
            if (defect.equals("private_source")) ((ObjectNode) canonical.path("sources").get(0)).put("raw_asset_path", "PRIVATE_CITIZEN_PATH");
            else ((ObjectNode) canonical.path("notices").get(0)).put("reviewer_id", "PRIVATE_CITIZEN_REVIEWER");
            fixtures.replaceCanonical(corrupted, canonical);
        }
        var error = error(detail(CitizenNoticeFixtures.event(input), selected.snapshotId()), 500, "SNAPSHOT_INVALID");
        assertThat(error.toString()).doesNotContain("PRIVATE_CITIZEN", "raw_asset_path", "reviewer_id", "notices");
    }

    @Test
    void thousandAndOneActualAuditRowsFailExplicitlyInsteadOfTruncatingHistory() throws Exception {
        var input = fixtures.citizen("education", false); String approved = fixtures.approve(input, true);
        var published = fixtures.publish(List.of(approved), null);
        var rows = new ArrayList<Object[]>();
        for (int version = 1; version <= 1000; version++) rows.add(new Object[] {UUID.randomUUID().toString(), published.snapshotId(),
                published.snapshotId(), version, Timestamp.from(Instant.now())});
        jdbc.batchUpdate("INSERT INTO publication_audits(audit_id, channel_key, action, before_snapshot_id, after_snapshot_id, head_version, reason, actor, happened_at) "
                + "VALUES (?, 'citizen:current', 'rollback', ?, ?, ?, '합성 이력 한도 시험', 'synthetic-history', ?)", rows);
        assertThat(jdbc.update("UPDATE publication_heads SET lock_version=1000 WHERE channel_key='citizen:current' AND snapshot_id=? AND lock_version=0", published.snapshotId())).isEqualTo(1);
        var error = error(detail(CitizenNoticeFixtures.event(input), published.snapshotId()), 503, "CITIZEN_HISTORY_TOO_LARGE");
        assertThat(error.path("error").path("retryable").asBoolean()).isFalse();
        assertThat(error.has("data")).isFalse();
    }

    @Test
    void firstSelectedKindOccurrenceDoesNotInventWithdrawalOrRestoration() throws Exception {
        var input = fixtures.citizen("education", false); String approved = fixtures.approve(input, true);
        var other = fixtures.publish(List.of(approved), null);
        var otherCanonical = (ObjectNode) fixtures.canonical(other.snapshotId()); otherCanonical.put("data_kind", "real");
        fixtures.replaceCanonical(other.snapshotId(), otherCanonical);
        jdbc.update("UPDATE snapshots SET data_kind='real' WHERE snapshot_id=?", other.snapshotId());
        fixtures.publish(List.of(), 0L);
        var first = fixtures.publish(List.of(approved), 1L);
        var entries = ok(detail(CitizenNoticeFixtures.event(input), first.snapshotId())).path("data").path("history").path("entries");
        assertThat(entries).hasSize(1);
        assertThat(entries.get(0).path("kind").asText()).isEqualTo("first_observed");
        assertThat(entries.get(0).path("snapshot_id").asText()).isEqualTo(first.snapshotId());
        assertThat(entries.get(0).path("before").isNull()).isTrue();
        assertThat(entries.get(0).path("after").isObject()).isTrue();
    }

    @ParameterizedTest
    @ValueSource(strings = {"gap", "before_link", "duplicate_version", "missing_terminal", "head_version"})
    void incompleteOrDisconnectedAuditChainCannotLookUnchanged(String defect) throws Exception {
        var input = fixtures.citizen("living", false); String approved = fixtures.approve(input, true);
        var first = fixtures.publish(List.of(approved), null);
        fixtures.publish(List.of(), 0L); fixtures.rollback(first.snapshotId(), 1L);
        switch (defect) {
            case "gap" -> jdbc.update("DELETE FROM publication_audits WHERE channel_key='citizen:current' AND head_version=1");
            case "before_link" -> jdbc.update("UPDATE publication_audits SET before_snapshot_id=NULL WHERE channel_key='citizen:current' AND head_version=1");
            case "duplicate_version" -> jdbc.update("UPDATE publication_audits SET head_version=0 WHERE channel_key='citizen:current' AND head_version=1");
            case "missing_terminal" -> jdbc.update("DELETE FROM publication_audits WHERE channel_key='citizen:current' AND head_version=2");
            default -> jdbc.update("UPDATE publication_heads SET lock_version=3 WHERE channel_key='citizen:current'");
        }
        error(detail(CitizenNoticeFixtures.event(input), first.snapshotId()), 500, "SNAPSHOT_INVALID");
    }

    @ParameterizedTest
    @ValueSource(strings = {"legacy", "unpublished", "corrupt"})
    void retiredSelectionDoesNotDiscloseAnUnverifiedReplacementId(String defect) throws Exception {
        var input = fixtures.citizen("support", false); String approved = fixtures.approve(input, true);
        var past = fixtures.publish(List.of(approved), null); var replacement = fixtures.publish(List.of(approved), 0L);
        if (defect.equals("legacy")) jdbc.update("UPDATE snapshots SET schema_version='snapshot-v1',rules_version='rules-v1',dictionary_version='synthetic-dictionary' WHERE snapshot_id=?", replacement.snapshotId());
        else if (defect.equals("unpublished")) jdbc.update("DELETE FROM publication_audits WHERE after_snapshot_id=?", replacement.snapshotId());
        else jdbc.update("UPDATE snapshots SET checksum=? WHERE snapshot_id=?", "0".repeat(64), replacement.snapshotId());
        var failure = error("/api/v1/citizen/notices?snapshot_id=" + past.snapshotId(), 500, "SNAPSHOT_INVALID");
        assertThat(failure.has("current_snapshot_id")).isFalse();
        assertThat(failure.toString()).doesNotContain(replacement.snapshotId());
    }

    @Test
    void recentNoticeDoesNotTriggerAnUnboundedSearchThroughEarlierPublications() throws Exception {
        var empty = fixtures.publish(List.of(), null);
        var rows = new ArrayList<Object[]>();
        for (int version = 1; version <= 1000; version++) rows.add(new Object[] {UUID.randomUUID().toString(), empty.snapshotId(),
                empty.snapshotId(), version, Timestamp.from(Instant.now())});
        jdbc.batchUpdate("INSERT INTO publication_audits(audit_id, channel_key, action, before_snapshot_id, after_snapshot_id, head_version, reason, actor, happened_at) "
                + "VALUES (?, 'citizen:current', 'rollback', ?, ?, ?, '합성 시작점 비용 시험', 'synthetic-history', ?)", rows);
        jdbc.update("UPDATE publication_heads SET lock_version=1000 WHERE channel_key='citizen:current'");
        var input = fixtures.citizen("education", false); String approved = fixtures.approve(input, true);
        var selected = fixtures.publish(List.of(approved), 1000L);
        var failure = error(detail(CitizenNoticeFixtures.event(input), selected.snapshotId()), 503, "CITIZEN_HISTORY_TOO_LARGE");
        assertThat(failure.path("error").path("retryable").asBoolean()).isFalse();
    }

    private URI uri(String path) { return URI.create("http://127.0.0.1:" + port + path); }
    private String detail(String event, String snapshot) { return "/api/v1/citizen/notices/" + event + "?snapshot_id=" + snapshot; }
    private HttpResponse<String> get(String path) throws Exception {
        var before = CitizenNoticeFixtures.rows(jdbc);
        var response = http.send(HttpRequest.newBuilder(uri(path)).timeout(Duration.ofSeconds(10)).GET().build(), HttpResponse.BodyHandlers.ofString());
        assertThat(CitizenNoticeFixtures.rows(jdbc)).as("공개 GET은 모든 DB 행을 보존한다").isEqualTo(before);
        return response;
    }
    private JsonNode ok(String path) throws Exception {
        var response = get(path); assertThat(response.statusCode()).as(response.body()).isEqualTo(200);
        return mapper.readTree(response.body());
    }
    private JsonNode error(String path, int status, String code) throws Exception {
        var response = get(path); assertThat(response.statusCode()).as(response.body()).isEqualTo(status);
        var body = mapper.readTree(response.body()); assertThat(body.path("error").path("code").asText()).isEqualTo(code);
        assertThat(body.path("request_id").asText()).isEqualTo(response.headers().firstValue("X-Request-ID").orElseThrow());
        assertThat(body.path("error").path("field_errors").isArray()).isTrue(); return body;
    }
    private Set<String> keys(JsonNode node) { var result = new HashSet<String>(); node.fieldNames().forEachRemaining(result::add); return result; }
}
