package kr.ac.myai.backend.local;

import kr.ac.myai.backend.exception.ApiException;
import org.springframework.context.annotation.Profile;
import org.springframework.core.MethodParameter;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpInputMessage;
import org.springframework.http.HttpStatus;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.web.bind.annotation.ControllerAdvice;
import org.springframework.web.servlet.mvc.method.annotation.RequestBodyAdviceAdapter;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Type;

@ControllerAdvice(assignableTypes = LocalManagementController.class)
@Profile("local-api")
public class LocalBodyLimitAdvice extends RequestBodyAdviceAdapter {
    private static final int LIMIT = 8 * 1024 * 1024;

    @Override
    public boolean supports(MethodParameter parameter, Type type, Class<? extends HttpMessageConverter<?>> converter) { return true; }

    @Override
    public HttpInputMessage beforeBodyRead(HttpInputMessage input, MethodParameter parameter, Type type,
                                           Class<? extends HttpMessageConverter<?>> converter) throws IOException {
        if (input.getHeaders().getContentLength() > LIMIT) throw tooLarge();
        byte[] body = input.getBody().readNBytes(LIMIT + 1);
        if (body.length > LIMIT) throw tooLarge();
        return new HttpInputMessage() {
            public InputStream getBody() { return new ByteArrayInputStream(body); }
            public HttpHeaders getHeaders() { return input.getHeaders(); }
        };
    }

    private ApiException tooLarge() {
        return new ApiException(HttpStatus.PAYLOAD_TOO_LARGE, "PAYLOAD_TOO_LARGE", "로컬 관리 요청 본문은8MiB 이하여야 합니다.", null);
    }
}
