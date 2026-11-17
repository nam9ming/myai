package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import kr.ac.myai.backend.controller.ApiExceptionHandler;
import kr.ac.myai.backend.controller.CitizenNoticeController;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.logging.PublicRequestLogFilter;
import kr.ac.myai.backend.publication.CitizenPublicationContent;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.repository.PublicSnapshotRepository;
import kr.ac.myai.backend.repository.PublicationRepository;
import kr.ac.myai.backend.service.CitizenNoticeService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Optional;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@ExtendWith(OutputCaptureExtension.class)
class CitizenNoticeApiTest {
    static final String BASE = "/api/v1/citizen/notices";
    static final String ID = "aaaaaaaa-1111-4111-8111-111111111111";
    static final String OTHER = "bbbbbbbb-1111-4111-8111-111111111111";
    static final String EVENT = "cccccccc-1111-4111-8111-111111111111";
    final ObjectMapper mapper = new ObjectMapper().findAndRegisterModules().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    final PublicSnapshotRepository repository = mock(PublicSnapshotRepository.class);
    PublicSnapshotRepository.Published empty;
    MockMvc mvc;

    @BeforeEach
    void publicReaderWithAnEmptyVerifiedPublication() {
        var json = mapper.createObjectNode().put("schema_version", "citizen-snapshot-v1").put("snapshot_id", ID)
                .put("created_at", "2026-11-01T00:00:00Z").put("data_kind", "synthetic").put("mode", "current")
                .putNull("case_id").put("channel_key", "citizen:current").put("timezone", "Asia/Seoul").put("notice_count", 0);
        json.putArray("revision_ids"); json.putArray("notices"); json.putArray("sources");
        String canonical = json.toString();
        var row = new PublicationRepository.Snapshot(ID, "current", null, canonical,
                ReviewedImportReader.sha256(canonical.getBytes(StandardCharsets.UTF_8)), "synthetic", null, null);
        empty = new PublicSnapshotRepository.Published(row, "citizen-snapshot-v1", Instant.parse("2026-11-01T00:00:00Z"), ID);
        when(repository.head("citizen:current")).thenReturn(Optional.of(ID));
        when(repository.citizenPublished(ID)).thenReturn(Optional.of(empty));
        var shared = new PublicationContent(new ReviewedImportReader(), mapper);
        var service = new CitizenNoticeService(repository, new CitizenPublicationContent(shared, mapper), shared, mapper);
        mvc = MockMvcBuilders.standaloneSetup(new CitizenNoticeController(service)).setControllerAdvice(new ApiExceptionHandler())
                .setMessageConverters(new MappingJackson2HttpMessageConverter(mapper)).addFilters(new PublicRequestLogFilter()).build();
    }

    @Test
    void servesEmptyAndPinnedListsWithoutLegacyConditions() throws Exception {
        for (String path : new String[] {BASE, BASE + "?snapshot_id=" + ID}) {
            var response = mvc.perform(get(path)).andExpect(status().isOk())
                    .andExpect(jsonPath("$.schema_version").value("citizen-api-v1"))
                    .andExpect(jsonPath("$.snapshot_id").value(ID)).andExpect(jsonPath("$.data.notice_count").value(0))
                    .andExpect(jsonPath("$.data.notices").isEmpty()).andExpect(jsonPath("$.data.sources").isEmpty()).andReturn().getResponse();
            var body = mapper.readTree(response.getContentAsByteArray());
            assertThat(body.has("rules_version")).isFalse();
            assertThat(body.path("data").has("points")).isFalse();
            assertThat(Instant.parse(body.path("generated_at").asText())).isAfter(empty.createdAt());
        }
    }

    @Test
    void detailRequiresAPinnedPublicationAndDoesNotInventMissingNotices() throws Exception {
        mvc.perform(get(BASE + "/" + EVENT)).andExpect(status().isUnprocessableEntity()).andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
        mvc.perform(get(BASE + "/" + EVENT).param("snapshot_id", ID)).andExpect(status().isNotFound()).andExpect(jsonPath("$.error.code").value("NOTICE_NOT_FOUND"));
    }

    @ParameterizedTest
    @ValueSource(strings = {"", "bad", "1-1-1-1-1", "AAAAAAAA-1111-4111-8111-111111111111", " aaaaaaaa-1111-4111-8111-111111111111"})
    void rejectsNoncanonicalSnapshotIdsBeforeReadingPublicData(String value) throws Exception {
        mvc.perform(get(BASE).param("snapshot_id", value)).andExpect(status().isUnprocessableEntity()).andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
        mvc.perform(get(BASE + "/" + EVENT).param("snapshot_id", value)).andExpect(status().isUnprocessableEntity()).andExpect(jsonPath("$.error.field_errors").isArray());
    }

    @ParameterizedTest
    @ValueSource(strings = {"bad", "1-1-1-1-1", "CCCCCCCC-1111-4111-8111-111111111111"})
    void rejectsNoncanonicalEventIds(String value) throws Exception {
        mvc.perform(get(BASE + "/" + value).param("snapshot_id", ID)).andExpect(status().isUnprocessableEntity()).andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
    }

    @Test
    void rejectsRepeatedAndUnsupportedQueriesInsteadOfIgnoringFilters() throws Exception {
        for (String path : new String[] {BASE, BASE + "/" + EVENT}) {
            mvc.perform(get(path).param("snapshot_id", ID, ID)).andExpect(status().isUnprocessableEntity());
            for (String key : new String[] {"free", "open", "category", "district", "period", "sort", "q", "point_id"}) {
                mvc.perform(get(path).param("snapshot_id", ID).param(key, "private-filter-value"))
                        .andExpect(status().isUnprocessableEntity()).andExpect(jsonPath("$.error.code").value("INVALID_REQUEST"));
            }
        }
    }

    @Test
    void usesCommonNotReadyNotFoundRetiredAndInvalidErrors() throws Exception {
        when(repository.head("citizen:current")).thenReturn(Optional.empty());
        mvc.perform(get(BASE)).andExpect(status().isServiceUnavailable()).andExpect(jsonPath("$.error.code").value("PUBLIC_DATA_NOT_READY"));
        mvc.perform(get(BASE).param("snapshot_id", OTHER)).andExpect(status().isNotFound()).andExpect(jsonPath("$.error.code").value("SNAPSHOT_NOT_FOUND"));
        when(repository.citizenPublished(ID)).thenReturn(Optional.of(new PublicSnapshotRepository.Published(empty.snapshot(), empty.schemaVersion(), empty.createdAt(), OTHER)));
        mvc.perform(get(BASE).param("snapshot_id", ID)).andExpect(status().isConflict()).andExpect(jsonPath("$.current_snapshot_id").value(OTHER));
        var original = empty.snapshot();
        var corrupt = new PublicationRepository.Snapshot(ID, "current", null, original.canonical(), "0".repeat(64), "synthetic", null, null);
        when(repository.citizenPublished(ID)).thenReturn(Optional.of(new PublicSnapshotRepository.Published(corrupt, empty.schemaVersion(), empty.createdAt(), ID)));
        mvc.perform(get(BASE).param("snapshot_id", ID)).andExpect(status().isInternalServerError()).andExpect(jsonPath("$.error.code").value("SNAPSHOT_INVALID"));
    }

    @Test
    void databaseFailureHasOneServerRequestIdAndNoPrivateDetails(CapturedOutput output) throws Exception {
        when(repository.head("citizen:current")).thenThrow(new DataAccessResourceFailureException("PRIVATE_DATABASE_DETAIL"));
        var response = mvc.perform(get(BASE).header("X-Request-ID", "private-request-id"))
                .andExpect(status().isServiceUnavailable()).andExpect(jsonPath("$.error.code").value("DATABASE_UNAVAILABLE"))
                .andExpect(jsonPath("$.error.retryable").value(true)).andReturn().getResponse();
        var body = mapper.readTree(response.getContentAsByteArray());
        assertThat(body.path("request_id").asText()).isEqualTo(response.getHeader("X-Request-ID")).matches("[0-9a-f-]{36}");
        assertThat(response.getContentAsString() + output.getAll()).doesNotContain("PRIVATE_DATABASE_DETAIL", "private-request-id");
    }

    @Test
    void logsOnlyTheVerifiedCitySnapshotAndNoFakeRules(CapturedOutput output) throws Exception {
        var response = mvc.perform(get(BASE).param("snapshot_id", ID).header("X-Request-ID", "private-request-id"))
                .andExpect(status().isOk()).andReturn().getResponse();
        String line = output.getAll().lines().filter(value -> value.contains("public_request ")).reduce((a, b) -> b).orElseThrow();
        var log = mapper.readTree(line.substring(line.indexOf("public_request ") + "public_request ".length()));
        assertThat(log.path("snapshot_id").asText()).isEqualTo(ID);
        assertThat(log.path("rules_version").isNull()).isTrue();
        assertThat(log.path("request_id").asText()).isEqualTo(response.getHeader("X-Request-ID"));
        assertThat(output.getAll()).doesNotContain("private-request-id", "snapshot_id=", "citizen-api-v1");
    }

    @Test
    void hasNoPublicationWriteMethod() throws Exception {
        mvc.perform(post(BASE).contentType("application/json").content("{\"private\":true}"))
                .andExpect(status().isMethodNotAllowed()).andExpect(jsonPath("$.error.code").value("METHOD_NOT_ALLOWED"));
    }
}
