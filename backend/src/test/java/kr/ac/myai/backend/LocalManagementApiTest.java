package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import jakarta.validation.Validation;
import jakarta.validation.ValidatorFactory;
import kr.ac.myai.backend.controller.ApiExceptionHandler;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.local.*;
import kr.ac.myai.backend.logging.PublicRequestLogFilter;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.service.*;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.core.MethodParameter;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpInputMessage;
import org.springframework.http.MediaType;
import org.springframework.http.converter.ByteArrayHttpMessageConverter;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class LocalManagementApiTest {
    @TempDir Path root;
    final String token = "SYNTHETIC_LOCAL_TOKEN_0123456789_abcdef";
    final String eventId = "10000000-0000-4000-8000-000000000004";
    final ObjectMapper mapper = new ObjectMapper().findAndRegisterModules()
            .setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    final ValidatorFactory validators = Validation.buildDefaultValidatorFactory();
    final ReviewedImportService imports = mock(ReviewedImportService.class);
    final ExtractionImportService extractions = mock(ExtractionImportService.class);
    final HumanHandoffImportService handoffs = mock(HumanHandoffImportService.class);
    final PublicationService publication = mock(PublicationService.class);
    Path requests;
    MockMvc mvc;

    @BeforeEach void setup() throws Exception {
        root = root.toRealPath();
        Path sources = Files.createDirectory(root.resolve("sources"));
        Files.copy(Path.of("examples/synthetic-source.txt"), sources.resolve("synthetic-source.txt"));
        requests = Files.createDirectory(root.resolve("requests"),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        var env = new MockEnvironment().withProperty("myai.local-api.token", token)
                .withProperty("myai.local-api.actor", "synthetic-actor")
                .withProperty("myai.local-api.source-root", sources.toString())
                .withProperty("myai.local-api.extraction-root", root.resolve("extractions").toString())
                .withProperty("myai.local-api.handoff-root", root.resolve("handoffs").toString());
        var reader = new ReviewedImportReader();
        var service = new LocalManagementService(reader, new PublicationCommandReader(reader, validators.getValidator()),
                imports, extractions, handoffs, publication, new LocalRequestStore(requests.toString()), env);
        mvc = MockMvcBuilders.standaloneSetup(new LocalManagementController(service, mock(kr.ac.myai.backend.local.SourceUploadService.class)))
                .setControllerAdvice(new ApiExceptionHandler(), new LocalBodyLimitAdvice())
                .setMessageConverters(new ByteArrayHttpMessageConverter(), new MappingJackson2HttpMessageConverter(mapper))
                .addFilters(new PublicRequestLogFilter(), new LocalApiSecurityFilter(env, mapper)).build();
    }

    @AfterEach void closeValidators() { validators.close(); }

    @Test void documentEndpointReturnsSnakeCaseResultAndKeepsRawBody() throws Exception {
        byte[] body = Files.readAllBytes(Path.of("examples/source-import.json"));
        when(imports.importBatch(any(), eq("synthetic-actor"))).thenReturn(imported());
        mvc.perform(auth(post("/local/documents")).content(body))
                .andExpect(status().isOk()).andExpect(jsonPath("$.schema_version").value("local-management-result-v1"))
                .andExpect(jsonPath("$.request_sha256").value(ReviewedImportReader.sha256(body)))
                .andExpect(jsonPath("$.data.already_imported").value(false));
        assertThat(requests.resolve(ReviewedImportReader.sha256(body) + ".json")).hasBinaryContent(body);
    }

    @Test void extractionEndpointPreservesFailedRunAndExplicitExpectedHash() throws Exception {
        String run = "71fb66f0-e610-4f9c-8f26-4bb77655ee8c";
        when(extractions.importRun(run, root.resolve("extractions"), "synthetic-actor", "a".repeat(64)))
                .thenReturn(new ExtractionImportService.Result(run, "10000000-0000-4000-8000-000000000002",
                        "failed", 1, "synthetic", "b".repeat(64), "c".repeat(64), false, true));
        var body = mapper.createObjectNode().put("schema_version", "extraction-import-request-v1")
                .put("run_id", run).put("expected_input_hash", "a".repeat(64));
        mvc.perform(auth(post("/local/extractions/import")).content(mapper.writeValueAsBytes(body)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.status").value("failed"))
                .andExpect(jsonPath("$.data.review_required").value(true));
    }

    @Test void reviewAndExplicitBatchRoutesUseExistingReviewedInput() throws Exception {
        when(imports.importBatch(any(), eq("synthetic-actor"))).thenReturn(imported());
        byte[] body = Files.readAllBytes(Path.of("examples/reviewed-import.json"));
        mvc.perform(auth(put("/local/events/" + eventId + "/review")).content(body))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.import_id").value("synthetic-import"));
        mvc.perform(auth(post("/local/reviews/import")).content(body)).andExpect(status().isOk());
        mvc.perform(auth(put("/local/events/20000000-0000-4000-8000-000000000004/review")).content(body))
                .andExpect(status().isUnprocessableEntity());
    }

    @Test void previewReturnsExistingResultWithoutSavingARequest() throws Exception {
        var body = mapper.readTree(Path.of("examples/publish.json").toFile());
        ((com.fasterxml.jackson.databind.node.ObjectNode) body).put("action", "preview");
        when(publication.execute(any(PublicationCommand.Publish.class), any(), eq("synthetic-actor")))
                .thenReturn(new PublicationService.Result("preview", null, null, eventId, "a".repeat(64), null,
                        mapper.createObjectNode().put("data_kind", "synthetic")));
        mvc.perform(auth(post("/local/publish")).content(mapper.writeValueAsBytes(body)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.preview.data_kind").value("synthetic"));
        noRequests();
    }

    @Test void contentTypeAndDeclaredOrStreamingOversizeStopBeforeStorageAndDomain() throws Exception {
        mvc.perform(auth(post("/local/documents")).contentType(MediaType.TEXT_PLAIN).content("PRIVATE_BODY"))
                .andExpect(status().isUnsupportedMediaType());
        byte[] body = new byte[8 * 1024 * 1024 + 1]; Arrays.fill(body, (byte) ' ');
        mvc.perform(auth(post("/local/documents")).content(body))
                .andExpect(status().isPayloadTooLarge()).andExpect(jsonPath("$.error.code").value("PAYLOAD_TOO_LARGE"));
        var parameter = new MethodParameter(LocalManagementController.class.getMethod("documents", byte[].class), 0);
        var input = new HttpInputMessage() {
            public HttpHeaders getHeaders() { return new HttpHeaders(); }
            public InputStream getBody() { return new ByteArrayInputStream(body); }
        };
        assertThatThrownBy(() -> new LocalBodyLimitAdvice().beforeBodyRead(input, parameter, byte[].class, ByteArrayHttpMessageConverter.class))
                .isInstanceOfSatisfying(kr.ac.myai.backend.exception.ApiException.class,
                        error -> assertThat(error.status().value()).isEqualTo(413));
        noRequests(); verifyNoInteractions(imports, extractions, handoffs, publication);
    }

    @Test void malformedUnknownSchemaAndEmptyJsonReturn422WithoutStorage() throws Exception {
        for (String body : List.of("{", " ", "{}", "null", "[]", "{\"schema_version\":\"unknown\"}",
                "{\"schema_version\":\"source-import-v1\",\"schema_version\":\"source-import-v1\"}")) {
            mvc.perform(auth(post("/local/documents")).content(body)).andExpect(status().isUnprocessableEntity());
        }
        noRequests(); verifyNoInteractions(imports, extractions, handoffs, publication);
    }

    @Test void unsupportedResponseMediaReturnsSafe406BeforeAnyDomainWork() throws Exception {
        mvc.perform(auth(post("/local/documents")).accept(MediaType.TEXT_HTML)
                        .content(Files.readAllBytes(Path.of("examples/source-import.json"))))
                .andExpect(status().isNotAcceptable()).andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.error.code").value("NOT_ACCEPTABLE"));
        noRequests(); verifyNoInteractions(imports, extractions, handoffs, publication);
    }

    @Test void authenticationAndOriginFailuresCannotArchiveOversizedInput() throws Exception {
        byte[] body = new byte[8 * 1024 * 1024 + 1];
        mvc.perform(auth(post("/local/documents")).header("Authorization", "Bearer wrong").content(body))
                .andExpect(status().isUnauthorized());
        mvc.perform(auth(post("/local/documents")).header("Origin", "http://evil.example").content(body))
                .andExpect(status().isForbidden());
        noRequests(); verifyNoInteractions(imports, extractions, handoffs, publication);
    }

    @Test void authenticatedUnknownPublicAndHealthRoutesRemain404() throws Exception {
        for (String route : List.of("/local/unknown", "/api/v1/config", "/health")) {
            var result = mvc.perform(auth(get(route))).andReturn();
            assertThat(result.getResponse().getStatus()).as("route %s, resolved %s", route,
                    result.getResolvedException() == null ? null : result.getResolvedException().getClass().getSimpleName()).isEqualTo(404);
        }
        noRequests(); verifyNoInteractions(imports, extractions, handoffs, publication);
    }

    @Test void typedDomainFailureSharesServerRequestIdAndDoesNotReflectPrivateDetails() throws Exception {
        when(imports.importBatch(any(), anyString())).thenThrow(new ImportException(
                "IMPORT_DATABASE_UNAVAILABLE", "PRIVATE_SQL " + root, "PRIVATE_PATH"));
        var result = mvc.perform(auth(post("/local/documents")).header("X-Request-ID", "PRIVATE_CLIENT_ID")
                        .content(Files.readAllBytes(Path.of("examples/source-import.json"))))
                .andExpect(status().isServiceUnavailable()).andExpect(jsonPath("$.error.retryable").value(true))
                .andReturn().getResponse();
        assertThat(mapper.readTree(result.getContentAsByteArray()).path("request_id").asText())
                .isEqualTo(result.getHeader("X-Request-ID")).doesNotContain("PRIVATE");
        assertThat(result.getContentAsString()).doesNotContain("PRIVATE", root.toString(), token, "Exception");
    }

    @Test void unexpectedFailureReturnsSafe500() throws Exception {
        when(imports.importBatch(any(), anyString())).thenThrow(new IllegalStateException("PRIVATE_SQL " + root));
        var response = mvc.perform(auth(post("/local/documents")).content(Files.readAllBytes(Path.of("examples/source-import.json"))))
                .andExpect(status().isInternalServerError()).andExpect(jsonPath("$.error.code").value("INTERNAL_ERROR"))
                .andReturn().getResponse();
        assertThat(response.getContentAsString()).doesNotContain("PRIVATE", root.toString(), token, "Exception");
    }

    private MockHttpServletRequestBuilder auth(MockHttpServletRequestBuilder builder) {
        return builder.contentType(MediaType.APPLICATION_JSON).header("Authorization", "Bearer " + token)
                .header("Host", "127.0.0.1:49123").header("Origin", "http://127.0.0.1:49123").with(request -> {
                    request.setLocalAddr("127.0.0.1"); request.setRemoteAddr("127.0.0.1");
                    request.setLocalPort(49123); request.setServerPort(49123); return request;
                });
    }
    private ReviewedImportService.ImportResult imported() {
        return new ReviewedImportService.ImportResult("synthetic-import", List.of(), List.of(), false);
    }
    private void noRequests() throws Exception {
        try (var files = Files.list(requests)) { assertThat(files.toList()).isEmpty(); }
    }
}
