package kr.ac.myai.backend;

import kr.ac.myai.backend.controller.ApiExceptionHandler;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.multipart.MultipartException;

import static org.assertj.core.api.Assertions.assertThat;

class MultipartErrorTest {
    @AfterEach void clearRequest() { RequestContextHolder.resetRequestAttributes(); }

    @ParameterizedTest
    @CsvSource(value = {
            "''|/local/extractions/uploads|NULL|EXTRACTION",
            "/ctx|/local/extractions/uploads/run/attempts/1/output|NULL|EXTRACTION",
            "/ctx|/prefix|/local/extractions/uploads/run|EXTRACTION",
            "''|/local/documents|NULL|SOURCE",
            "''|/local/extractions/uploads-other|NULL|SOURCE",
            "/ctx|/prefix|/local/documents|SOURCE",
            "''|/local/extractions/uploadsX|NULL|SOURCE"
    }, delimiter = '|', nullValues = "NULL")
    void parserAndSizeErrorsUseTheRequestNamespaceWithoutHandlerAttributes(String context, String servlet,
                                                                           String info, String namespace) {
        RequestContextHolder.resetRequestAttributes();
        var request = new MockHttpServletRequest();
        request.setContextPath(context); request.setServletPath(servlet); request.setPathInfo(info);
        var handler = new ApiExceptionHandler();
        var size = handler.uploadTooLarge(request);
        assertThat(size.getStatusCode().value()).isEqualTo(413);
        assertThat(size.getBody().error().code()).isEqualTo(namespace + "_UPLOAD_TOO_LARGE");
        var parser = handler.malformedUpload(new MultipartException("SYNTHETIC_PRIVATE_PARSER_CONTENT"), request);
        assertThat(parser.getStatusCode().value()).isEqualTo(422);
        assertThat(parser.getBody().error().code()).isEqualTo(namespace + "_UPLOAD_INVALID");
        assertThat(parser.getBody().error().message()).doesNotContain("SYNTHETIC_PRIVATE_PARSER_CONTENT");
    }
}
