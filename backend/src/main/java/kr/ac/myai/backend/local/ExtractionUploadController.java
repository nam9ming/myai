package kr.ac.myai.backend.local;

import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import kr.ac.myai.backend.exception.ApiException;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;

@RestController
@Profile("local-api")
@RequestMapping(value = "/local/extractions/uploads", produces = MediaType.APPLICATION_JSON_VALUE)
public class ExtractionUploadController {
    private static final int CONTROL_LIMIT = 64 * 1024;
    private static final int INPUT_LIMIT = 8 * 1024 * 1024;
    private static final int PROMPT_LIMIT = 20 * 1024 * 1024;
    private static final int OUTPUT_LIMIT = 5 * 1024 * 1024;
    private final ExtractionUploadService uploads;

    public ExtractionUploadController(ExtractionUploadService uploads) { this.uploads = uploads; }

    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ExtractionUploadService.Result initialize(HttpServletRequest request, @RequestPart("control") byte[] control,
                                                     @RequestPart("metadata") byte[] metadata, @RequestPart("input") MultipartFile input)
            throws IOException, ServletException {
        parts(request, List.of("control", "input", "metadata"));
        if (control.length > CONTROL_LIMIT || metadata.length > CONTROL_LIMIT) throw tooLarge();
        media(request.getPart("control").getContentType(), "control", true);
        media(request.getPart("metadata").getContentType(), "metadata", true);
        media(input.getContentType(), "input", true);
        byte[] raw = read(input, INPUT_LIMIT);
        if (control.length == 0 || metadata.length == 0 || raw.length == 0) throw invalid();
        return uploads.initialize(control, metadata, raw);
    }

    @PutMapping(value = "/{runId}/attempts/{attempt}/{artifact}", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ExtractionUploadService.Result put(@PathVariable String runId, @PathVariable int attempt, @PathVariable String artifact,
                                              HttpServletRequest request, @RequestPart("file") MultipartFile file)
            throws IOException, ServletException {
        parts(request, List.of("file"));
        media(file.getContentType(), "file", false);
        int limit = "output".equals(artifact) ? OUTPUT_LIMIT : PROMPT_LIMIT;
        return uploads.put(runId, attempt, artifact, read(file, limit));
    }

    @PostMapping(value = "/{runId}/finalize", consumes = MediaType.APPLICATION_JSON_VALUE)
    public LocalManagementService.Result finalizeUpload(@PathVariable String runId, HttpServletRequest request, @RequestBody byte[] control) {
        if (control.length > CONTROL_LIMIT) throw tooLarge();
        media(request.getContentType(), "control", true);
        return uploads.finalizeUpload(runId, control);
    }

    private void parts(HttpServletRequest request, List<String> expected) throws ServletException, IOException {
        if (!request.getParts().stream().map(part -> part.getName()).sorted().toList().equals(expected)) throw invalid();
    }

    private byte[] read(MultipartFile file, int limit) throws IOException {
        if (file.getSize() > limit) throw tooLarge();
        byte[] raw;
        try (var input = file.getInputStream()) { raw = input.readNBytes(limit + 1); }
        if (raw.length > limit) throw tooLarge();
        return raw;
    }

    private void media(String declared, String field, boolean json) {
        try {
            var type = MediaType.parseMediaType(declared == null ? "" : declared);
            String value = type.getType() + "/" + type.getSubtype();
            boolean allowed = json ? value.equalsIgnoreCase("application/json")
                    : value.equalsIgnoreCase("text/plain") || value.equalsIgnoreCase("application/octet-stream");
            if (!allowed || type.getCharset() != null && !type.getCharset().equals(StandardCharsets.UTF_8)) throw new IllegalArgumentException();
        } catch (IllegalArgumentException error) {
            throw new ApiException(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "UNSUPPORTED_MEDIA_TYPE",
                    "지정한 파일 형식과 UTF-8 charset을 사용해 주세요.", field);
        }
    }

    private ApiException invalid() { return new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "EXTRACTION_UPLOAD_INVALID",
            "지정한 part와 파일을 각각 한 개씩 전달해 주세요.", null); }
    private ApiException tooLarge() { return new ApiException(HttpStatus.PAYLOAD_TOO_LARGE, "EXTRACTION_UPLOAD_TOO_LARGE",
            "업로드 크기 한도를 초과했습니다. 파일을 나누거나 별도 검토해 주세요.", null); }
}
