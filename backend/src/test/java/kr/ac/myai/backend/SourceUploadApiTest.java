package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.controller.ApiExceptionHandler;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.local.*;
import kr.ac.myai.backend.logging.PublicRequestLogFilter;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.MediaType;
import org.springframework.http.converter.ByteArrayHttpMessageConverter;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockPart;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockMultipartHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class SourceUploadApiTest {
    private static final String TOKEN = "SYNTHETIC_LOCAL_TOKEN_0123456789_abcdef";
    private static final String VERSION = "55555555-5555-4555-8555-555555555555";
    private final ObjectMapper json = new ObjectMapper().findAndRegisterModules().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    @TempDir Path temporary;
    private Path sources, requests;
    private LocalManagementService management;
    private MockMvc mvc;
    private final List<JsonNode> imported = new ArrayList<>();

    @BeforeEach void setup() throws Exception {
        sources = directory("sources"); requests = directory("requests");
        var reader = new ReviewedImportReader();
        management = mock(LocalManagementService.class);
        doAnswer(call -> {
            byte[] body = call.getArgument(0); reader.read(body, sources); imported.add(reader.parseJson(body));
            var result = new kr.ac.myai.backend.service.ReviewedImportService.ImportResult(
                    "77777777-7777-4777-8777-777777777777", List.of(), List.of(VERSION), imported.size() > 1);
            return new LocalManagementService.Result("local-management-result-v1", ReviewedImportReader.sha256(body), result);
        }).when(management).documents(any());
        String tool = Files.isExecutable(Path.of("/opt/homebrew/bin/pdftotext")) ? "/opt/homebrew/bin/pdftotext" : "/usr/bin/pdftotext";
        var service = new SourceUploadService(management, reader, new SourceUploadStore(sources.toString(), requests.toString()),
                new SourceTextPreprocessor(new PdfTextExtractor(tool)), new LocalRequestStore(requests.toString()), sources.toString());
        var env = new MockEnvironment().withProperty("myai.local-api.token", TOKEN);
        mvc = MockMvcBuilders.standaloneSetup(new LocalManagementController(management, service))
                .setControllerAdvice(new ApiExceptionHandler(), new LocalBodyLimitAdvice())
                .setMessageConverters(new ByteArrayHttpMessageConverter(), new MappingJackson2HttpMessageConverter(json))
                .addFilters(new PublicRequestLogFilter(), new LocalApiSecurityFilter(env, json)).build();
    }

    @ParameterizedTest @ValueSource(strings = {"txt", "pdf", "json"})
    void threeMultipartFormatsRegisterPendingDocumentsWithoutUsingTheFilename(String format) throws Exception {
        byte[] raw = switch (format) { case "pdf" -> pdf(); case "json" -> bytes("{\"schema_version\":\"text-body-v1\",\"text\":\"합성 본문\"}"); default -> bytes("합성 본문"); };
        var response = mvc.perform(request(format, raw, true)).andExpect(status().isOk())
                .andExpect(jsonPath("$.schema_version").value("source-upload-result-v1"))
                .andExpect(jsonPath("$.document_version_id").value(VERSION))
                .andExpect(jsonPath("$.use_review").value("pending"))
                .andExpect(jsonPath("$.check_result").value("unchecked"))
                .andExpect(jsonPath("$.data.document_version_ids[0]").value(VERSION))
                .andExpect(jsonPath("$.data.already_imported").value(false))
                .andExpect(jsonPath("$.text_review_required").value(format.equals("pdf")))
                .andReturn().getResponse();
        assertThat(imported).hasSize(1);
        JsonNode doc = imported.getFirst().path("documents").get(0);
        assertThat(Files.readAllBytes(sources.resolve(doc.path("raw_asset_path").asText()))).isEqualTo(raw);
        assertThat(response.getContentAsString()).doesNotContain("PRIVATE_FILENAME", sources.toString(), requests.toString(), TOKEN);
        if (format.equals("pdf")) assertThat(doc.path("block_index").get(0).path("page").asInt()).isEqualTo(1);
    }

    @Test void authenticationAndOriginFailuresNeverStoreTheMultipartParts() throws Exception {
        mvc.perform(request("txt", bytes("본문"), false)).andExpect(status().isUnauthorized());
        mvc.perform(request("txt", bytes("본문"), true).with(req -> {
            req.removeHeader("Origin"); req.addHeader("Origin", "https://outside.invalid"); return req;
        })).andExpect(status().isForbidden());
        noWrites();
    }

    @Test void rejectsExtraDuplicateAndMissingPartsBeforeSourceRegistration() throws Exception {
        mvc.perform(request("txt", bytes("본문"), true).part(part("extra", null, bytes("ignored"), "text/plain")))
                .andExpect(status().isUnprocessableEntity());
        mvc.perform(request("txt", bytes("본문"), true).part(part("file", "other.txt", bytes("other"), "text/plain")))
                .andExpect(status().isUnprocessableEntity());
        mvc.perform(auth(multipart("/local/documents").part(part("metadata", null, bytes(metadata("txt").toString()), "application/json")), true))
                .andExpect(status().isUnprocessableEntity());
        noWrites();
    }

    @Test void metadataAndActualFileStreamLimitsUseSafe413Envelopes() throws Exception {
        var hugeMeta = auth(multipart("/local/documents").part(part("metadata", null, new byte[64 * 1024 + 1], "application/json"),
                part("file", "source.txt", bytes("본문"), "text/plain")), true);
        var response = mvc.perform(hugeMeta).andExpect(status().isPayloadTooLarge())
                .andExpect(jsonPath("$.error.code").value("SOURCE_UPLOAD_TOO_LARGE")).andReturn().getResponse();
        assertThat(json.readTree(response.getContentAsByteArray()).path("request_id").asText()).isEqualTo(response.getHeader("X-Request-ID"));
        mvc.perform(auth(multipart("/local/documents").part(
                part("metadata", null, new byte[9 * 1024 * 1024], "application/json"),
                part("file", "source.txt", bytes("본문"), "text/plain")), true))
                .andExpect(status().isPayloadTooLarge())
                .andExpect(jsonPath("$.error.code").value("SOURCE_UPLOAD_TOO_LARGE"));
        mvc.perform(request("txt", new byte[20 * 1024 * 1024 + 1], true)).andExpect(status().isPayloadTooLarge());
        noWrites();
        byte[] metadata = bytes(metadata("txt").toString());
        byte[] maximum = Arrays.copyOf(metadata, 64 * 1024);
        Arrays.fill(maximum, metadata.length, maximum.length, (byte) ' ');
        mvc.perform(auth(multipart("/local/documents").part(
                part("metadata", null, maximum, "application/json"),
                part("file", "source.txt", bytes("본문"), "text/plain")), true)).andExpect(status().isOk());
    }

    @Test void mediaAndAcceptFailuresKeepJsonErrorsAndPrivateInformationOut() throws Exception {
        var mismatch = auth(multipart("/local/documents").part(part("metadata", null, bytes(metadata("txt").toString()), "application/json"),
                part("file", "source.txt", bytes("본문"), "application/pdf")), true);
        mvc.perform(mismatch).andExpect(status().isUnsupportedMediaType());
        var response = mvc.perform(request("txt", bytes("본문"), true).accept(MediaType.TEXT_HTML))
                .andExpect(status().isNotAcceptable()).andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andReturn().getResponse();
        assertThat(response.getContentAsString()).doesNotContain(TOKEN, sources.toString(), "PRIVATE_FILENAME", "Exception");
        noWrites();
    }

    @Test void metadataPartRequiresJsonAndUtf8BeforeWritingAnyOriginal() throws Exception {
        for (String media : List.of("text/plain", "application/octet-stream", "application/json;charset=UTF-16")) {
            var request = auth(multipart("/local/documents").part(
                    part("metadata", null, bytes(metadata("txt").toString()), media),
                    part("file", "source.txt", bytes("본문"), "text/plain")), true);
            mvc.perform(request).andExpect(status().isUnsupportedMediaType())
                    .andExpect(jsonPath("$.error.code").value("UNSUPPORTED_MEDIA_TYPE"));
        }
        var absentMedia = new MockPart("metadata", bytes(metadata("txt").toString()));
        mvc.perform(auth(multipart("/local/documents").part(absentMedia,
                part("file", "source.txt", bytes("본문"), "text/plain")), true))
                .andExpect(status().isUnsupportedMediaType());
        noWrites();
        mvc.perform(auth(multipart("/local/documents").part(
                part("metadata", null, bytes(metadata("txt").toString()), "application/json;charset=UTF-8"),
                part("file", "source.txt", bytes("본문"), "text/plain")), true)).andExpect(status().isOk());
    }

    @Test void unexpectedDatabaseFailureHasARequestIdAndPreservesThePreparedOriginal() throws Exception {
        doThrow(new IllegalStateException("PRIVATE_SQL " + sources)).when(management).documents(any());
        var response = mvc.perform(request("txt", bytes("본문"), true)).andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.error.code").value("INTERNAL_ERROR")).andReturn().getResponse();
        assertThat(json.readTree(response.getContentAsByteArray()).path("request_id").asText()).isEqualTo(response.getHeader("X-Request-ID"));
        assertThat(response.getContentAsString()).doesNotContain(TOKEN, sources.toString(), "PRIVATE_SQL", "Exception");
        assertThat(new SourceUploadStore(sources.toString(), requests.toString()).find(VERSION, bytes(metadata("txt").toString()), bytes("본문"))).isNotNull();
    }

    private MockMultipartHttpServletRequestBuilder request(String format, byte[] raw, boolean authorized) {
        String media = switch (format) { case "txt" -> "text/plain"; case "pdf" -> "application/pdf"; default -> "application/json"; };
        return auth(multipart("/local/documents").part(part("metadata", null, bytes(metadata(format).toString()), "application/json"),
                part("file", "../../PRIVATE_FILENAME." + format, raw, media)), authorized);
    }

    private MockMultipartHttpServletRequestBuilder auth(MockMultipartHttpServletRequestBuilder request, boolean authorized) {
        request.header("Host", "127.0.0.1:49123").header("Origin", "http://127.0.0.1:49123");
        if (authorized) request.header("Authorization", "Bearer " + TOKEN);
        request.with(req -> { req.setLocalAddr("127.0.0.1"); req.setRemoteAddr("127.0.0.1"); req.setLocalPort(49123); req.setServerPort(49123); return req; });
        return request;
    }

    private MockPart part(String name, String filename, byte[] bytes, String media) {
        var part = filename == null ? new MockPart(name, bytes) : new MockPart(name, filename, bytes);
        part.getHeaders().setContentType(MediaType.parseMediaType(media)); return part;
    }

    private ObjectNode metadata(String format) {
        return json.createObjectNode().put("schema_version", "source-upload-v1").put("format", format).put("data_kind", "synthetic")
                .put("document_id", "44444444-4444-4444-8444-444444444444").put("document_version_id", VERSION).put("version_no", 1)
                .put("publisher", "합성 기관").put("official_url", "https://example.invalid/notice/1").put("title", "합성 공지")
                .putNull("official_number").putNull("published_date").put("collected_at", "2026-11-02T00:00:00Z")
                .put("collection_method", "synthetic fixture").put("use_note", "synthetic only");
    }

    private Path directory(String name) throws Exception { return Files.createDirectory(temporary.resolve(name), PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------"))).toRealPath(); }
    private byte[] bytes(String text) { return text.getBytes(StandardCharsets.UTF_8); }
    private void noWrites() throws Exception { assertThat(imported).isEmpty(); try (var a = Files.list(sources); var b = Files.list(requests)) { assertThat(a.toList()).isEmpty(); assertThat(b.toList()).isEmpty(); } }

    private byte[] pdf() throws Exception {
        var objects = List.of("<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
                "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>");
        var all = new ArrayList<>(objects); String stream = "BT /F1 12 Tf 72 720 Td (SYNTHETIC NOTICE) Tj ET\n";
        all.add("<< /Length " + stream.length() + " >>\nstream\n" + stream + "endstream");
        var output = new ByteArrayOutputStream(); output.write(bytes("%PDF-1.4\n")); var offsets = new ArrayList<Integer>();
        for (int i = 0; i < all.size(); i++) { offsets.add(output.size()); output.write(bytes((i + 1) + " 0 obj\n" + all.get(i) + "\nendobj\n")); }
        int xref = output.size(); output.write(bytes("xref\n0 6\n0000000000 65535 f \n"));
        for (int offset : offsets) output.write(bytes(String.format(java.util.Locale.ROOT, "%010d 00000 n \n", offset)));
        output.write(bytes("trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" + xref + "\n%%EOF\n")); return output.toByteArray();
    }
}
