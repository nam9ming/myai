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
@RequestMapping(value = "/local", produces = MediaType.APPLICATION_JSON_VALUE)
public class LocalManagementController {
    private final LocalManagementService management;
    private final SourceUploadService uploads;

    public LocalManagementController(LocalManagementService management, SourceUploadService uploads) {
        this.management = management; this.uploads = uploads;
    }

    @PostMapping(value = "/documents", consumes = MediaType.APPLICATION_JSON_VALUE)
    public LocalManagementService.Result documents(@RequestBody byte[] body) { return management.documents(body); }

    @PostMapping(value = "/documents", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public SourceUploadService.Result upload(HttpServletRequest request, @RequestPart("metadata") byte[] metadata,
                                             @RequestPart("file") MultipartFile file) throws IOException, ServletException {
        var names = request.getParts().stream().map(part -> part.getName()).sorted().toList();
        if (!names.equals(List.of("file", "metadata"))) throw new ApiException(HttpStatus.UNPROCESSABLE_ENTITY,
                "SOURCE_UPLOAD_INVALID", "metadata·file part를 각각 한 개씩 전달해 주세요.", null);
        if (metadata.length > 64 * 1024 || file.getSize() > 20 * 1024 * 1024) throw tooLarge();
        metadataMedia(request.getPart("metadata").getContentType());
        byte[] raw;
        try (var input = file.getInputStream()) { raw = input.readNBytes(20 * 1024 * 1024 + 1); }
        if (raw.length > 20 * 1024 * 1024) throw tooLarge();
        return uploads.upload(metadata, raw, file.getContentType());
    }

    @PostMapping(value = "/extractions/import", consumes = MediaType.APPLICATION_JSON_VALUE)
    public LocalManagementService.Result extraction(@RequestBody byte[] body) { return management.extraction(body); }

    @PutMapping(value = "/events/{eventId}/review", consumes = MediaType.APPLICATION_JSON_VALUE)
    public LocalManagementService.Result review(@PathVariable String eventId, @RequestBody byte[] body) {
        return management.review(eventId, body);
    }

    @PostMapping(value = "/reviews/import", consumes = MediaType.APPLICATION_JSON_VALUE)
    public LocalManagementService.Result reviews(@RequestBody byte[] body) { return management.reviews(body); }

    @PostMapping(value = "/publish", consumes = MediaType.APPLICATION_JSON_VALUE)
    public LocalManagementService.Result publish(@RequestBody byte[] body) { return management.publish(body); }

    private void metadataMedia(String declared) {
        try {
            MediaType type = MediaType.parseMediaType(declared == null ? "" : declared);
            if (!"application".equalsIgnoreCase(type.getType()) || !"json".equalsIgnoreCase(type.getSubtype())
                    || type.getCharset() != null && !type.getCharset().equals(StandardCharsets.UTF_8)) {
                throw new IllegalArgumentException();
            }
        } catch (IllegalArgumentException error) {
            throw new ApiException(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "UNSUPPORTED_MEDIA_TYPE",
                    "metadata는 UTF-8 application/json으로 전달해 주세요.", "metadata");
        }
    }

    private ApiException tooLarge() { return new ApiException(HttpStatus.PAYLOAD_TOO_LARGE, "SOURCE_UPLOAD_TOO_LARGE",
            "업로드 크기 한도를 초과했습니다. 파일을 나누거나 별도 검토해 주세요.", null); }
}
