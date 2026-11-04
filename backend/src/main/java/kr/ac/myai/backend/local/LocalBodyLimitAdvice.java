package kr.ac.myai.backend.local;

import kr.ac.myai.backend.exception.ApiException;
import org.springframework.context.annotation.Profile;
import org.springframework.core.MethodParameter;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpInputMessage;
import org.springframework.http.HttpStatus;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.servlet.mvc.method.annotation.RequestBodyAdviceAdapter;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Type;

@ControllerAdvice(assignableTypes = LocalManagementController.class)
@Profile("local-api")
public class LocalBodyLimitAdvice extends RequestBodyAdviceAdapter {
    private static final int LIMIT = 8 * 1024 * 1024;
    private static final int METADATA_LIMIT = 64 * 1024;

    @Override
    public boolean supports(MethodParameter parameter, Type type, Class<? extends HttpMessageConverter<?>> converter) { return true; }

    @Override
    public HttpInputMessage beforeBodyRead(HttpInputMessage input, MethodParameter parameter, Type type,
                                           Class<? extends HttpMessageConverter<?>> converter) throws IOException {
        int limit = parameter.hasParameterAnnotation(RequestPart.class) ? METADATA_LIMIT : LIMIT;
        if (input.getHeaders().getContentLength() > limit) throw tooLarge(limit);
        byte[] body = input.getBody().readNBytes(limit + 1);
        if (body.length > limit) throw tooLarge(limit);
        return new HttpInputMessage() {
            public InputStream getBody() { return new ByteArrayInputStream(body); }
            public HttpHeaders getHeaders() { return input.getHeaders(); }
        };
    }

    private ApiException tooLarge(int limit) {
        if (limit == METADATA_LIMIT) return new ApiException(HttpStatus.PAYLOAD_TOO_LARGE,
                "SOURCE_UPLOAD_TOO_LARGE", "업로드 metadata는64KiB 이하여야 합니다.", "metadata");
        return new ApiException(HttpStatus.PAYLOAD_TOO_LARGE, "PAYLOAD_TOO_LARGE", "로컬 관리 요청 본문은8MiB 이하여야 합니다.", null);
    }
}
