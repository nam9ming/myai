package kr.ac.myai.backend;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import kr.ac.myai.backend.config.WebConfig;
import kr.ac.myai.backend.controller.ApiExceptionHandler;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.local.*;
import kr.ac.myai.backend.logging.PublicRequestLogFilter;
import kr.ac.myai.backend.service.ExtractionImportService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.core.MethodParameter;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpInputMessage;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.converter.ByteArrayHttpMessageConverter;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.mock.env.MockEnvironment;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.mock.web.MockMultipartHttpServletRequest;
import org.springframework.mock.web.MockPart;
import org.springframework.mock.web.MockServletContext;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.RequestBuilder;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import org.springframework.test.web.servlet.request.MockMultipartHttpServletRequestBuilder;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.support.AnnotationConfigWebApplicationContext;
import org.springframework.web.servlet.config.annotation.EnableWebMvc;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.multipart;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ExtractionUploadApiTest {
    private static final String BASE = "/local/extractions/uploads";
    private static final String RUN = "71fb66f0-e610-4f9c-8f26-4bb77655ee8c";
    private static final String DOCUMENT = "e9dc7495-7186-5318-a054-4fc54e9b78cc";
    private static final String TOKEN = "SYNTHETIC_LOCAL_TOKEN_0123456789_abcdef";
    private static final String PRIVATE = "SYNTHETIC_PRIVATE_UPLOAD_BYTES";
    private static final String PRIVATE_PATH = "/synthetic/private/extraction-stage";
    private static final int KIB = 1024, MIB = 1024 * 1024;
    private final ObjectMapper json = mapper();
    private final ExtractionUploadService uploads = mock(ExtractionUploadService.class);
    private final LocalManagementService management = mock(LocalManagementService.class);
    private final SourceUploadService sourceUploads = mock(SourceUploadService.class);
    private final List<Initial> initials = new ArrayList<>();
    private final List<Slot> slots = new ArrayList<>();
    private final List<Finalized> finalized = new ArrayList<>();
    private final List<byte[]> legacyDocuments = new ArrayList<>();
    private final List<MockHttpServletResponse> responses = new ArrayList<>();
    private final Logger logger = (Logger) LoggerFactory.getLogger(PublicRequestLogFilter.class);
    private final ListAppender<ILoggingEvent> appender = new ListAppender<>();
    private Level previousLevel;
    private byte[] control, metadata, input;
    private MockMvc mvc;

    @BeforeEach
    void setup() throws Exception {
        RequestContextHolder.resetRequestAttributes();
        input = Files.readAllBytes(PythonProbe.REPO.resolve("contracts/examples/ai-input.json"));
        metadata = bytes("\n " + Files.readString(PythonProbe.REPO.resolve("processing/examples/extraction-metadata.json"))
                .replace("\"cost\": null", "\"cost\": 0.1234567890123456789") + "\n");
        control = control(input);
        when(uploads.initialize(any(), any(), any())).thenAnswer(call -> {
            byte[] receivedControl = call.getArgument(0), receivedMetadata = call.getArgument(1), receivedInput = call.getArgument(2);
            initials.add(new Initial(receivedControl.clone(), receivedMetadata.clone(), receivedInput.clone()));
            return staged(sha(receivedInput), List.of(artifact("control.json", receivedControl), artifact("metadata.json", receivedMetadata), artifact("input.json", receivedInput)));
        });
        when(uploads.put(anyString(), anyInt(), anyString(), any())).thenAnswer(call -> {
            String run = call.getArgument(0), kind = call.getArgument(2); int attempt = call.getArgument(1);
            byte[] received = call.getArgument(3);
            if (run == null || !run.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
                    || attempt < 1 || attempt > 3 || !List.of("prompt", "output").contains(kind)) throw invalid();
            if (!RUN.equals(run)) throw new ApiException(HttpStatus.NOT_FOUND, "EXTRACTION_UPLOAD_NOT_FOUND", "업로드 실행을 찾을 수 없습니다.", null);
            slots.add(new Slot(run, attempt, kind, received.clone()));
            return staged(sha(input), List.of(artifact("attempt-" + attempt + "." + kind, received)));
        });
        when(uploads.finalizeUpload(anyString(), any())).thenAnswer(call -> {
            String run = call.getArgument(0); byte[] body = call.getArgument(1);
            if (!RUN.equals(run)) throw invalid();
            finalized.add(new Finalized(run, body.clone()));
            return new LocalManagementService.Result("local-management-result-v1", sha(body),
                    new ExtractionImportService.Result(RUN, DOCUMENT, "failed", 3, "synthetic", "b".repeat(64), "c".repeat(64), false, true));
        });
        when(management.documents(any())).thenAnswer(call -> {
            byte[] body = call.getArgument(0); legacyDocuments.add(body.clone());
            return new LocalManagementService.Result("local-management-result-v1", sha(body), Map.of("already_imported", false));
        });
        var environment = new MockEnvironment().withProperty("myai.local-api.token", TOKEN);
        mvc = MockMvcBuilders.standaloneSetup(new ExtractionUploadController(uploads), new LocalManagementController(management, sourceUploads))
                .setControllerAdvice(new ApiExceptionHandler(), new LocalBodyLimitAdvice())
                .setMessageConverters(new ByteArrayHttpMessageConverter(), new MappingJackson2HttpMessageConverter(json))
                .addFilters(new PublicRequestLogFilter(), new LocalApiSecurityFilter(environment, json)).build();
        previousLevel = logger.getLevel(); logger.setLevel(Level.INFO); appender.start(); logger.addAppender(appender);
    }

    @AfterEach
    void assertSafeRequestLogsAndRelease() throws Exception {
        try {
            var rows = new ArrayList<JsonNode>();
            for (var event : appender.list) {
                String line = event.getFormattedMessage();
                int at = line.indexOf("public_request ");
                if (at >= 0) rows.add(json.readTree(line.substring(at + "public_request ".length())));
            }
            for (var row : rows) {
                var fields = new HashSet<String>(); row.fieldNames().forEachRemaining(fields::add);
                assertThat(fields).containsExactlyInAnyOrder("request_id", "error_code", "latency_ms", "snapshot_id", "rules_version");
                assertThat(row.path("latency_ms").asLong()).isGreaterThanOrEqualTo(0);
                assertThat(row.path("snapshot_id").isNull()).isTrue(); assertThat(row.path("rules_version").isNull()).isTrue();
            }
            for (var response : responses) {
                String id = requestId(response);
                var matching = rows.stream().filter(row -> id.equals(row.path("request_id").asText())).toList();
                assertThat(matching).hasSize(1);
                if (response.getStatus() >= 400) assertThat(matching.getFirst().path("error_code").asText())
                        .isEqualTo(json.readTree(response.getContentAsByteArray()).path("error").path("code").asText());
            }
            String visible = appender.list.stream().map(ILoggingEvent::getFormattedMessage).reduce("", String::concat)
                    + responses.stream().map(response -> new String(response.getContentAsByteArray(), StandardCharsets.UTF_8)).reduce("", String::concat);
            assertThat(visible).doesNotContain(TOKEN, PRIVATE, PRIVATE_PATH, "SYNTHETIC_PRIVATE_FILENAME", "SYNTHETIC_PRIVATE_CLIENT_ID", "PRIVATE_SQL", "Exception", "\tat ");
        } finally {
            logger.detachAppender(appender); logger.setLevel(previousLevel); appender.stop(); RequestContextHolder.resetRequestAttributes();
        }
    }

    @Test
    void initializesUsingExactOriginalBytesAndReturnsOnlyTheFixedSnakeCaseReceipt() throws Exception {
        var response = body(perform(initial(control, metadata, input), 200));
        assertThat(initials).hasSize(1);
        assertThat(initials.getFirst().control()).isEqualTo(control);
        assertThat(initials.getFirst().metadata()).isEqualTo(metadata);
        assertThat(initials.getFirst().input()).isEqualTo(input);
        var fields = new HashSet<String>(); response.fieldNames().forEachRemaining(fields::add);
        assertThat(fields).containsExactlyInAnyOrder("schema_version", "run_id", "expected_input_hash", "state", "received_files", "review_required");
        assertThat(response.path("schema_version").asText()).isEqualTo("extraction-upload-result-v1");
        assertThat(response.path("run_id").asText()).isEqualTo(RUN);
        assertThat(response.path("expected_input_hash").asText()).isEqualTo(sha(input));
        assertThat(response.path("state").asText()).isEqualTo("staged");
        assertThat(response.path("review_required").asBoolean()).isTrue();
        assertThat(response.path("received_files")).hasSize(3);
        assertArtifact(response.path("received_files").get(0), "control.json", control);
        assertArtifact(response.path("received_files").get(1), "metadata.json", metadata);
        assertArtifact(response.path("received_files").get(2), "input.json", input);
    }

    @Test
    void putKeepsActualAttemptNumbersKindsAndEmptyOrInvalidUtf8Bytes() throws Exception {
        var values = List.of(new byte[0], new byte[]{(byte) 0xff, 0, 13, 10}, bytes(PRIVATE + " 😀\r\n"));
        for (String kind : List.of("prompt", "output")) for (int index = 0; index < values.size(); index++) {
            byte[] raw = values.get(index);
            var response = body(perform(slot(RUN, index + 1, kind, raw, "application/octet-stream"), 200));
            Slot received = slots.getLast();
            assertThat(received.run()).isEqualTo(RUN); assertThat(received.attempt()).isEqualTo(index + 1); assertThat(received.kind()).isEqualTo(kind);
            assertThat(received.bytes()).isEqualTo(raw);
            assertArtifact(response.path("received_files").get(0), "attempt-" + (index + 1) + "." + kind, raw);
        }
    }

    @Test
    void finalizePassesExactJsonBytesAndKeepsAnArchivedFailureAsA200Result() throws Exception {
        byte[] original = bytes("\n  " + new String(control, StandardCharsets.UTF_8) + "\n");
        var response = body(perform(auth(post(BASE + "/" + RUN + "/finalize")).contentType(MediaType.APPLICATION_JSON).content(original), 200));
        assertThat(finalized).hasSize(1);
        assertThat(finalized.getFirst().run()).isEqualTo(RUN); assertThat(finalized.getFirst().control()).isEqualTo(original);
        assertThat(response.path("schema_version").asText()).isEqualTo("local-management-result-v1");
        assertThat(response.path("request_sha256").asText()).isEqualTo(sha(original));
        assertThat(response.path("data").path("status").asText()).isEqualTo("failed");
        assertThat(response.path("data").path("review_required").asBoolean()).isTrue();
    }

    @Test
    void initializationRejectsEveryMissingDuplicateAndExtraPartBeforeServiceIo() throws Exception {
        for (String absent : List.of("control", "metadata", "input")) {
            var request = auth(multipart(BASE));
            if (!absent.equals("control")) request.part(jsonPart("control", control));
            if (!absent.equals("metadata")) request.part(jsonPart("metadata", metadata));
            if (!absent.equals("input")) request.part(inputPart(input, "application/json"));
            error(request, 422, null);
        }
        error(initial(control, metadata, input).part(jsonPart("control", control)), 422, null);
        error(initial(control, metadata, input).part(jsonPart("metadata", metadata)), 422, null);
        error(initial(control, metadata, input).part(inputPart(input, "application/json")), 422, null);
        error(initial(control, metadata, input).part(part("extra", null, bytes(PRIVATE), "text/plain")), 422, null);
        assertThat(initials).isEmpty();
    }

    @Test
    void slotRejectsMissingDuplicateAndExtraPartsBeforeServiceIo() throws Exception {
        error(auth(multipart(HttpMethod.PUT, slotPath(RUN, 1, "output"))), 422, null);
        error(slot(RUN, 1, "output", bytes("a"), "text/plain").part(part("file", "second", bytes("b"), "text/plain")), 422, null);
        error(slot(RUN, 1, "output", bytes("a"), "text/plain").part(jsonPart("metadata", metadata)), 422, null);
        assertThat(slots).isEmpty();
    }

    @Test
    void initialPartsRequireJsonAndDeclaredUtf8ButPreserveTheirBytes() throws Exception {
        for (String name : List.of("control", "metadata", "input")) for (String media : List.of("text/plain", "application/octet-stream", "application/json;charset=UTF-16", "application/json;charset=US-ASCII")) {
            var request = auth(multipart(BASE).part(part("control", null, control, name.equals("control") ? media : "application/json"),
                    part("metadata", null, metadata, name.equals("metadata") ? media : "application/json"), inputPart(input, name.equals("input") ? media : "application/json")));
            error(request, 415, "UNSUPPORTED_MEDIA_TYPE");
        }
        var absent = new MockPart("metadata", metadata);
        error(auth(multipart(BASE).part(jsonPart("control", control), absent, inputPart(input, "application/json"))), 415, "UNSUPPORTED_MEDIA_TYPE");
        assertThat(initials).isEmpty();
        perform(auth(multipart(BASE).part(part("control", null, control, "application/json;charset=UTF-8"),
                part("metadata", null, metadata, "application/json;charset=UTF-8"), inputPart(input, "application/json;charset=UTF-8"))), 200);
        assertThat(initials.getFirst().input()).isEqualTo(input);
    }

    @Test
    void slotsAcceptOnlyPlainOrOctetStreamWithOptionalUtf8Charset() throws Exception {
        for (String media : List.of("application/json", "application/pdf", "text/plain;charset=UTF-16", "application/octet-stream;charset=US-ASCII"))
            error(slot(RUN, 1, "output", bytes(PRIVATE), media), 415, "UNSUPPORTED_MEDIA_TYPE");
        var absent = new MockPart("file", "SYNTHETIC_PRIVATE_FILENAME", bytes(PRIVATE));
        error(auth(multipart(HttpMethod.PUT, slotPath(RUN, 1, "output")).part(absent)), 415, "UNSUPPORTED_MEDIA_TYPE");
        assertThat(slots).isEmpty();
        for (String media : List.of("text/plain", "application/octet-stream", "text/plain;charset=UTF-8", "application/octet-stream;charset=UTF-8"))
            perform(slot(RUN, 1, "output", bytes(PRIVATE), media), 200);
        assertThat(slots).hasSize(4).allSatisfy(value -> assertThat(value.bytes()).isEqualTo(bytes(PRIVATE)));
    }

    @Test
    void controlAndMetadataHaveTheirOwnExact64KibLimits() throws Exception {
        error(initial(pad(control, 64 * KIB + 1), metadata, input), 413, "EXTRACTION_UPLOAD_TOO_LARGE");
        error(initial(control, pad(metadata, 64 * KIB + 1), input), 413, "EXTRACTION_UPLOAD_TOO_LARGE");
        error(initial(pad(control, 9 * MIB), metadata, input), 413, "EXTRACTION_UPLOAD_TOO_LARGE");
        error(initial(control, pad(metadata, 9 * MIB), input), 413, "EXTRACTION_UPLOAD_TOO_LARGE");
        assertThat(initials).isEmpty();
        byte[] maximumControl = pad(control, 64 * KIB), maximumMetadata = pad(metadata, 64 * KIB);
        perform(initial(maximumControl, maximumMetadata, input), 200);
        assertThat(initials.getFirst().control()).isEqualTo(maximumControl); assertThat(initials.getFirst().metadata()).isEqualTo(maximumMetadata);
    }

    @Test
    void inputAllowsEightMibAndRejectsOneMoreByte() throws Exception {
        byte[] maximum = pad(input, 8 * MIB);
        perform(initial(control(maximum), metadata, maximum), 200);
        assertThat(initials.getFirst().input()).isEqualTo(maximum);
        error(initial(control, metadata, pad(input, 8 * MIB + 1)), 413, "EXTRACTION_UPLOAD_TOO_LARGE");
        assertThat(initials).hasSize(1);
    }

    @Test
    void promptAndOutputUseSeparateExactTwentyAndFiveMibLimits() throws Exception {
        byte[] prompt = new byte[20 * MIB]; Arrays.fill(prompt, (byte) 'p');
        byte[] output = new byte[5 * MIB]; Arrays.fill(output, (byte) 'o');
        var promptResponse = body(perform(slot(RUN, 1, "prompt", prompt, "text/plain"), 200));
        var outputResponse = body(perform(slot(RUN, 1, "output", output, "text/plain"), 200));
        assertArtifact(promptResponse.path("received_files").get(0), "attempt-1.prompt", prompt);
        assertArtifact(outputResponse.path("received_files").get(0), "attempt-1.output", output);
        assertThat(slots.get(0).bytes()).isEqualTo(prompt); assertThat(slots.get(1).bytes()).isEqualTo(output);
        error(slot(RUN, 1, "prompt", new byte[20 * MIB + 1], "application/octet-stream"), 413, "EXTRACTION_UPLOAD_TOO_LARGE");
        error(slot(RUN, 1, "output", new byte[5 * MIB + 1], "application/octet-stream"), 413, "EXTRACTION_UPLOAD_TOO_LARGE");
        assertThat(slots).hasSize(2);
    }

    @Test
    void finalizeIsLimitedTo64KibIncludingAnUndeclaredLengthAdviceStream() throws Exception {
        byte[] maximum = pad(control, 64 * KIB);
        perform(auth(post(BASE + "/" + RUN + "/finalize")).contentType(MediaType.APPLICATION_JSON).content(maximum), 200);
        assertThat(finalized.getFirst().control()).isEqualTo(maximum);
        error(auth(post(BASE + "/" + RUN + "/finalize")).contentType(MediaType.APPLICATION_JSON).content(pad(control, 64 * KIB + 1)), 413, "EXTRACTION_UPLOAD_TOO_LARGE");
        assertThat(finalized).hasSize(1);
        var method = Arrays.stream(ExtractionUploadController.class.getDeclaredMethods()).filter(candidate ->
                Arrays.stream(candidate.getParameters()).anyMatch(parameter -> parameter.isAnnotationPresent(RequestBody.class))).findFirst().orElseThrow();
        int bodyIndex = -1;
        for (int index = 0; index < method.getParameterCount(); index++) if (method.getParameters()[index].isAnnotationPresent(RequestBody.class)) bodyIndex = index;
        var parameter = new MethodParameter(method, bodyIndex);
        var stream = new HttpInputMessage() {
            public HttpHeaders getHeaders() { return new HttpHeaders(); }
            public InputStream getBody() { return new ByteArrayInputStream(pad(control, 64 * KIB + 1)); }
        };
        assertThatThrownBy(() -> new LocalBodyLimitAdvice().beforeBodyRead(stream, parameter, byte[].class, ByteArrayHttpMessageConverter.class))
                .isInstanceOfSatisfying(ApiException.class, error -> assertThat(error.status().value()).isEqualTo(413));
    }

    @Test
    void bytePartAdviceStopsUndeclaredControlAndMetadataStreamsAt64KibPlusOne() throws Exception {
        var method = ExtractionUploadController.class.getMethod("initialize", jakarta.servlet.http.HttpServletRequest.class,
                byte[].class, byte[].class, MultipartFile.class);
        for (int index : List.of(1, 2)) {
            var stream = new ProbeStream(64 * KIB + 1024);
            var message = new HttpInputMessage() {
                public HttpHeaders getHeaders() { return new HttpHeaders(); }
                public InputStream getBody() { return stream; }
            };
            var parameter = new MethodParameter(method, index);
            assertThatThrownBy(() -> new LocalBodyLimitAdvice().beforeBodyRead(message, parameter, byte[].class, ByteArrayHttpMessageConverter.class))
                    .isInstanceOfSatisfying(ApiException.class, error -> assertThat(error.code()).isEqualTo("EXTRACTION_UPLOAD_TOO_LARGE"));
            assertThat(stream.read).isEqualTo(64 * KIB + 1);
        }
    }

    @Test
    void actualFileStreamsAreBoundedEvenWhenTheirDeclaredSizeIsWrong() throws Exception {
        var controller = new ExtractionUploadController(uploads);
        var inputRequest = new MockMultipartHttpServletRequest();
        inputRequest.addPart(jsonPart("control", control)); inputRequest.addPart(jsonPart("metadata", metadata));
        inputRequest.addPart(inputPart(new byte[0], "application/json"));
        var inputStream = new ProbeStream(8 * MIB + 1024);
        var inputFile = streamingFile("input", "application/json", inputStream);
        assertThatThrownBy(() -> controller.initialize(inputRequest, control, metadata, inputFile))
                .isInstanceOfSatisfying(ApiException.class, error -> assertThat(error.code()).isEqualTo("EXTRACTION_UPLOAD_TOO_LARGE"));
        assertThat(inputStream.read).isEqualTo(8 * MIB + 1); assertThat(inputStream.closed).isTrue();
        for (String kind : List.of("prompt", "output")) {
            int limit = kind.equals("prompt") ? 20 * MIB : 5 * MIB;
            var stream = new ProbeStream(limit + 1024);
            var request = new MockMultipartHttpServletRequest();
            request.addPart(part("file", "stream", new byte[0], "application/octet-stream"));
            assertThatThrownBy(() -> controller.put(RUN, 1, kind, request, streamingFile("file", "application/octet-stream", stream)))
                    .isInstanceOfSatisfying(ApiException.class, error -> assertThat(error.code()).isEqualTo("EXTRACTION_UPLOAD_TOO_LARGE"));
            assertThat(stream.read).isEqualTo(limit + 1); assertThat(stream.closed).isTrue();
        }
        assertNoServiceIo();
    }

    @Test
    void finalizeRejectsADeclaredNonUtf8JsonCharsetBeforeServiceIo() throws Exception {
        error(auth(post(BASE + "/" + RUN + "/finalize")).contentType("application/json;charset=UTF-16").content(control),
                415, "UNSUPPORTED_MEDIA_TYPE");
        assertThat(finalized).isEmpty();
    }

    @Test
    void existingJsonEightMibAndSourceMetadata64KibBoundariesRemainSeparate() throws Exception {
        byte[] source = Files.readAllBytes(PythonProbe.REPO.resolve("backend/examples/source-import.json"));
        byte[] maximum = pad(source, 8 * MIB);
        var response = body(perform(auth(post("/local/documents")).contentType(MediaType.APPLICATION_JSON).content(maximum), 200));
        assertThat(legacyDocuments).hasSize(1); assertThat(legacyDocuments.getFirst()).isEqualTo(maximum);
        assertThat(response.path("request_sha256").asText()).isEqualTo(sha(maximum));
        error(auth(post("/local/documents")).contentType(MediaType.APPLICATION_JSON).content(pad(source, 8 * MIB + 1)), 413, "PAYLOAD_TOO_LARGE");
        error(auth(multipart("/local/documents").part(jsonPart("metadata", new byte[64 * KIB + 1]),
                part("file", "source.txt", bytes("합성 본문"), "text/plain"))), 413, "SOURCE_UPLOAD_TOO_LARGE");
        verifyNoInteractions(sourceUploads);
    }

    @Test
    void routeBindingAndServiceRejectionsUseTheCommonErrorEnvelope() throws Exception {
        error(slot("not-a-uuid", 1, "output", bytes(PRIVATE), "text/plain"), 422, "EXTRACTION_UPLOAD_INVALID");
        error(slot("10000000-0000-4000-8000-000000000001", 1, "output", bytes(PRIVATE), "text/plain"), 404, "EXTRACTION_UPLOAD_NOT_FOUND");
        for (int attempt : List.of(0, 4)) error(slot(RUN, attempt, "output", bytes(PRIVATE), "text/plain"), 422, "EXTRACTION_UPLOAD_INVALID");
        error(slot(RUN, 1, "other", bytes(PRIVATE), "text/plain"), 422, "EXTRACTION_UPLOAD_INVALID");
        error(auth(multipart(HttpMethod.PUT, BASE + "/" + RUN + "/attempts/not-a-number/output")
                .part(part("file", "source", bytes(PRIVATE), "text/plain"))), 422, "INVALID_REQUEST");
        assertThat(slots).isEmpty();
    }

    @Test
    void unsupportedTopLevelMediaIsRejectedForAllThreeRoutes() throws Exception {
        error(auth(post(BASE)).contentType(MediaType.APPLICATION_JSON).content(control), 415, "UNSUPPORTED_MEDIA_TYPE");
        error(auth(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put(slotPath(RUN, 1, "output")))
                .contentType(MediaType.APPLICATION_JSON).content(control), 415, "UNSUPPORTED_MEDIA_TYPE");
        error(auth(post(BASE + "/" + RUN + "/finalize")).contentType(MediaType.TEXT_PLAIN).content(control), 415, "UNSUPPORTED_MEDIA_TYPE");
        assertNoServiceIo();
    }

    @Test
    void acceptHtmlFailsSafelyBeforeAnyServiceIo() throws Exception {
        error(initial(control, metadata, input).accept(MediaType.TEXT_HTML), 406, "NOT_ACCEPTABLE");
        error(slot(RUN, 1, "output", bytes(PRIVATE), "text/plain").accept(MediaType.TEXT_HTML), 406, "NOT_ACCEPTABLE");
        error(auth(post(BASE + "/" + RUN + "/finalize")).contentType(MediaType.APPLICATION_JSON).content(control)
                .accept(MediaType.TEXT_HTML), 406, "NOT_ACCEPTABLE");
        assertNoServiceIo();
    }

    @Test
    void authenticationOriginAndHostFailuresDoNotReachServiceIo() throws Exception {
        for (int route = 0; route < 3; route++) {
            var unauthorized = route(route); unauthorized.with(request -> { request.removeHeader("Authorization"); return request; });
            error(unauthorized, 401, "LOCAL_API_UNAUTHORIZED");
            var wrongOrigin = route(route); wrongOrigin.with(request -> { request.removeHeader("Origin"); request.addHeader("Origin", "https://outside.invalid"); return request; });
            error(wrongOrigin, 403, "LOCAL_API_FORBIDDEN");
            var wrongHost = route(route); wrongHost.with(request -> { request.removeHeader("Host"); request.addHeader("Host", "localhost:49123"); return request; });
            error(wrongHost, 403, "LOCAL_API_FORBIDDEN");
        }
        assertNoServiceIo();
    }

    @Test
    void safeDomainAndUnexpectedErrorsDoNotExposeServicePathsOrBodies() throws Exception {
        doThrow(new ApiException(HttpStatus.CONFLICT, "EXTRACTION_UPLOAD_CONFLICT", "원본이 다릅니다.", null))
                .when(uploads).put(anyString(), anyInt(), anyString(), any());
        error(slot(RUN, 1, "output", bytes(PRIVATE), "text/plain"), 409, "EXTRACTION_UPLOAD_CONFLICT");
        doThrow(new IllegalStateException("PRIVATE_SQL " + PRIVATE_PATH + " " + PRIVATE)).when(uploads).initialize(any(), any(), any());
        error(initial(control, metadata, input), 500, "INTERNAL_ERROR");
    }

    @Test
    void publicAndFixtureContextsHaveNoUploadRoutesEvenForMultipartFiles() throws Exception {
        for (String profile : List.of("public", "fixture")) try (var context = new AnnotationConfigWebApplicationContext()) {
            context.setServletContext(new MockServletContext());
            context.setEnvironment(new MockEnvironment().withProperty("app.cors-origin", "http://localhost:5173"));
            context.getEnvironment().setActiveProfiles(profile);
            context.register(ProfileMvcConfiguration.class, WebConfig.class, ExtractionUploadController.class, ApiExceptionHandler.class);
            context.refresh();
            var publicMvc = MockMvcBuilders.webAppContextSetup(context).addFilters(new PublicRequestLogFilter()).build();
            perform(publicMvc, initial(control, metadata, pad(input, 2 * MIB)), 404);
            perform(publicMvc, slot(RUN, 1, "output", bytes(PRIVATE), "text/plain"), 404);
            perform(publicMvc, auth(post(BASE + "/" + RUN + "/finalize")).contentType(MediaType.APPLICATION_JSON).content(control), 404);
            verifyNoInteractions(context.getBean(ExtractionUploadService.class));
        }
    }

    @TestConfiguration
    @EnableWebMvc
    static class ProfileMvcConfiguration implements WebMvcConfigurer {
        @Bean ExtractionUploadService uploadService() { return mock(ExtractionUploadService.class); }
        @Override public void configureMessageConverters(List<HttpMessageConverter<?>> converters) {
            converters.add(new ByteArrayHttpMessageConverter()); converters.add(new MappingJackson2HttpMessageConverter(mapper()));
        }
    }

    private MockHttpServletRequestBuilder route(int number) {
        return switch (number) {
            case 0 -> initial(control, metadata, input);
            case 1 -> slot(RUN, 1, "output", bytes(PRIVATE), "text/plain");
            default -> auth(post(BASE + "/" + RUN + "/finalize")).contentType(MediaType.APPLICATION_JSON).content(control);
        };
    }
    private MockMultipartHttpServletRequestBuilder initial(byte[] control, byte[] metadata, byte[] input) {
        return auth(multipart(BASE).part(jsonPart("control", control), jsonPart("metadata", metadata), inputPart(input, "application/json")));
    }
    private MockMultipartHttpServletRequestBuilder slot(String run, int attempt, String kind, byte[] raw, String media) {
        return auth(multipart(HttpMethod.PUT, slotPath(run, attempt, kind)).part(part("file", "../../SYNTHETIC_PRIVATE_FILENAME.bin", raw, media)));
    }
    private static String slotPath(String run, int attempt, String kind) { return BASE + "/" + run + "/attempts/" + attempt + "/" + kind; }
    private static MockPart jsonPart(String name, byte[] raw) { return part(name, null, raw, "application/json"); }
    private static MockPart inputPart(byte[] raw, String media) { return part("input", "../../SYNTHETIC_PRIVATE_FILENAME.json", raw, media); }
    private static MockPart part(String name, String filename, byte[] raw, String media) {
        var part = filename == null ? new MockPart(name, raw) : new MockPart(name, filename, raw);
        part.getHeaders().setContentType(MediaType.parseMediaType(media)); return part;
    }
    private <T extends MockHttpServletRequestBuilder> T auth(T request) {
        request.header("Host", "127.0.0.1:49123").header("Origin", "http://127.0.0.1:49123").header("Authorization", "Bearer " + TOKEN)
                .header("X-Request-ID", "SYNTHETIC_PRIVATE_CLIENT_ID");
        request.with(value -> { value.setLocalAddr("127.0.0.1"); value.setRemoteAddr("127.0.0.1"); value.setLocalPort(49123); value.setServerPort(49123); return value; });
        return request;
    }
    private MockHttpServletResponse perform(RequestBuilder request, int expected) throws Exception { return perform(mvc, request, expected); }
    private MockHttpServletResponse perform(MockMvc target, RequestBuilder request, int expected) throws Exception {
        var response = target.perform(request).andExpect(status().is(expected)).andReturn().getResponse();
        responses.add(response); requestId(response);
        if (expected >= 400) {
            assertThat(response.getContentType()).startsWith("application/json");
            var result = body(response);
            assertThat(result.path("request_id").asText()).isEqualTo(response.getHeader("X-Request-ID"));
            assertThat(result.path("error").path("code").asText()).isNotBlank();
            assertThat(result.path("error").path("field_errors").isArray()).isTrue();
        }
        return response;
    }
    private void error(RequestBuilder request, int status, String code) throws Exception {
        var response = body(perform(request, status));
        if (code != null) assertThat(response.path("error").path("code").asText()).isEqualTo(code);
    }
    private JsonNode body(MockHttpServletResponse response) throws Exception { return json.readTree(response.getContentAsByteArray()); }
    private String requestId(MockHttpServletResponse response) {
        String id = response.getHeader("X-Request-ID"); assertThat(UUID.fromString(id).toString()).isEqualTo(id); return id;
    }
    private void assertArtifact(JsonNode value, String name, byte[] original) {
        var fields = new HashSet<String>(); value.fieldNames().forEachRemaining(fields::add);
        assertThat(fields).containsExactlyInAnyOrder("name", "size_bytes", "sha256");
        assertThat(value.path("name").asText()).isEqualTo(name); assertThat(value.path("size_bytes").asLong()).isEqualTo(original.length);
        assertThat(value.path("sha256").asText()).isEqualTo(sha(original));
    }
    private void assertNoServiceIo() { assertThat(initials).isEmpty(); assertThat(slots).isEmpty(); assertThat(finalized).isEmpty(); }
    private static ExtractionUploadService.Result staged(String hash, List<ExtractionUploadStore.Artifact> artifacts) {
        return new ExtractionUploadService.Result("extraction-upload-result-v1", RUN, hash, "staged", artifacts, true);
    }
    private static ExtractionUploadStore.Artifact artifact(String name, byte[] value) { return new ExtractionUploadStore.Artifact(name, value.length, sha(value)); }
    private static ApiException invalid() { return new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "EXTRACTION_UPLOAD_INVALID", "입력 연결을 확인해 주세요.", null); }
    private byte[] control(byte[] input) { return bytes("\n {\"schema_version\":\"extraction-import-request-v1\",\"run_id\":\"" + RUN + "\",\"expected_input_hash\":\"" + sha(input) + "\"} \n"); }
    private static byte[] pad(byte[] original, int size) { byte[] value = Arrays.copyOf(original, size); Arrays.fill(value, original.length, size, (byte) ' '); return value; }
    private static byte[] bytes(String value) { return value.getBytes(StandardCharsets.UTF_8); }
    private static String sha(byte[] value) { return ReviewedImportReader.sha256(value); }
    private static ObjectMapper mapper() { return new ObjectMapper().findAndRegisterModules().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE); }
    private record Initial(byte[] control, byte[] metadata, byte[] input) { }
    private record Slot(String run, int attempt, String kind, byte[] bytes) { }
    private record Finalized(String run, byte[] control) { }
    private static MultipartFile streamingFile(String name, String media, ProbeStream stream) {
        return new MockMultipartFile(name, "SYNTHETIC_PRIVATE_FILENAME", media, new byte[0]) {
            @Override public long getSize() { return 0; }
            @Override public InputStream getInputStream() { return stream; }
        };
    }
    private static final class ProbeStream extends InputStream {
        final int size;
        int read;
        boolean closed;
        ProbeStream(int size) { this.size = size; }
        @Override public int read() { if (read == size) return -1; read++; return 'a'; }
        @Override public int read(byte[] bytes, int offset, int length) {
            if (read == size) return -1;
            int count = Math.min(length, size - read);
            Arrays.fill(bytes, offset, offset + count, (byte) 'a'); read += count; return count;
        }
        @Override public void close() { closed = true; }
    }
}
