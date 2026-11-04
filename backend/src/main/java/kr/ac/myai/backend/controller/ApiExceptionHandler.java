package kr.ac.myai.backend.controller;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.annotation.JsonInclude;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.logging.PublicRequestLogContext;
import org.springframework.core.MethodParameter;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpMediaTypeNotAcceptableException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;
import org.springframework.web.servlet.NoHandlerFoundException;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyAdvice;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.multipart.MultipartException;
import org.springframework.web.multipart.support.MissingServletRequestPartException;
import org.apache.tomcat.util.http.fileupload.impl.SizeException;
import org.springframework.dao.DataAccessResourceFailureException;
import org.springframework.dao.RecoverableDataAccessException;
import org.springframework.dao.TransientDataAccessException;
import org.springframework.transaction.CannotCreateTransactionException;

import java.util.List;

@RestControllerAdvice
public class ApiExceptionHandler implements ResponseBodyAdvice<Object> {
    private static final PropertyNamingStrategies.SnakeCaseStrategy names = new PropertyNamingStrategies.SnakeCaseStrategy();

    public record FieldError(String field, String message) {}
    public record ErrorDetail(String code, String message, List<FieldError> fieldErrors, boolean retryable) {}
    public record ErrorResponse(ErrorDetail error, String requestId, @JsonInclude(JsonInclude.Include.NON_NULL) String currentSnapshotId) {
        public ErrorResponse(ErrorDetail error, String requestId) { this(error, requestId, null); }
    }

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<ErrorResponse> domain(ApiException error) {
        String requestId = PublicRequestLogContext.requestId();
        var fields = error.field() == null ? List.<FieldError>of() : List.of(new FieldError(error.field(), error.getMessage()));
        return ResponseEntity.status(error.status()).body(new ErrorResponse(
                new ErrorDetail(error.code(), error.getMessage(), fields, error.retryable()), requestId, error.currentSnapshotId()));
    }

    @ExceptionHandler({DataAccessResourceFailureException.class, TransientDataAccessException.class,
            RecoverableDataAccessException.class, CannotCreateTransactionException.class})
    public ResponseEntity<ErrorResponse> databaseUnavailable() {
        return response(HttpStatus.SERVICE_UNAVAILABLE, "DATABASE_UNAVAILABLE", "공개 자료 저장소에 연결할 수 없습니다.", List.of());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> validation(MethodArgumentNotValidException error) {
        var fields = error.getBindingResult().getFieldErrors().stream()
                .map(field -> new FieldError(names.translate(field.getField()), field.getDefaultMessage())).toList();
        return response(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_REQUEST", "입력 조건을 확인해 주세요.", fields);
    }

    @ExceptionHandler({HttpMessageNotReadableException.class, MissingServletRequestParameterException.class,
            MethodArgumentTypeMismatchException.class, MissingServletRequestPartException.class})
    public ResponseEntity<ErrorResponse> malformed(Exception error) {
        return response(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_REQUEST", "요청 형식과 필수 필드를 확인해 주세요.", List.of());
    }

    @ExceptionHandler(MaxUploadSizeExceededException.class)
    public ResponseEntity<ErrorResponse> uploadTooLarge() {
        return response(HttpStatus.PAYLOAD_TOO_LARGE, "SOURCE_UPLOAD_TOO_LARGE",
                "업로드 크기 한도를 초과했습니다. 파일을 나누거나 별도 검토해 주세요.", List.of());
    }

    @ExceptionHandler(MultipartException.class)
    public ResponseEntity<ErrorResponse> malformedUpload(MultipartException error) {
        if (error.contains(MaxUploadSizeExceededException.class) || error.contains(SizeException.class)) return uploadTooLarge();
        return response(HttpStatus.UNPROCESSABLE_ENTITY, "SOURCE_UPLOAD_INVALID", "multipart 요청 형식과 part를 확인해 주세요.", List.of());
    }

    @ExceptionHandler({NoResourceFoundException.class, NoHandlerFoundException.class})
    public ResponseEntity<ErrorResponse> notFound() {
        return response(HttpStatus.NOT_FOUND, "NOT_FOUND", "요청 경로를 찾을 수 없습니다.", List.of());
    }

    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<ErrorResponse> methodNotAllowed() {
        return response(HttpStatus.METHOD_NOT_ALLOWED, "METHOD_NOT_ALLOWED", "지원하지 않는 요청 방식입니다.", List.of());
    }

    @ExceptionHandler(HttpMediaTypeNotSupportedException.class)
    public ResponseEntity<ErrorResponse> unsupportedMedia() {
        return response(HttpStatus.UNSUPPORTED_MEDIA_TYPE, "UNSUPPORTED_MEDIA_TYPE", "application/json 요청을 사용해 주세요.", List.of());
    }

    @ExceptionHandler(HttpMediaTypeNotAcceptableException.class)
    public ResponseEntity<ErrorResponse> notAcceptable() {
        return ResponseEntity.status(HttpStatus.NOT_ACCEPTABLE).contentType(MediaType.APPLICATION_JSON).body(new ErrorResponse(
                new ErrorDetail("NOT_ACCEPTABLE", "application/json 응답을 허용해 주세요.", List.of(), false), PublicRequestLogContext.requestId()));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> unexpected(Exception error) {
        String requestId = PublicRequestLogContext.requestId();
        return ResponseEntity.internalServerError().body(new ErrorResponse(
                new ErrorDetail("INTERNAL_ERROR", "요청 처리 중 오류가 발생했습니다.", List.of(), false), requestId));
    }

    private ResponseEntity<ErrorResponse> response(HttpStatus status, String code, String message, List<FieldError> fields) {
        return ResponseEntity.status(status).body(new ErrorResponse(
                new ErrorDetail(code, message, fields, status == HttpStatus.SERVICE_UNAVAILABLE), PublicRequestLogContext.requestId()));
    }

    @Override
    public boolean supports(MethodParameter returnType, Class<? extends HttpMessageConverter<?>> converterType) {
        return true;
    }

    @Override
    public Object beforeBodyWrite(Object body, MethodParameter returnType, MediaType contentType,
                                  Class<? extends HttpMessageConverter<?>> converterType,
                                  ServerHttpRequest request, ServerHttpResponse response) {
        if (body instanceof ErrorResponse errorResponse) {
            if (errorResponse.error() != null) PublicRequestLogContext.error(errorResponse.error().code());
        } else if (body instanceof JsonNode json) {
            PublicRequestLogContext.response(json.path("snapshot_id").textValue(), json.path("data").path("rules_version").textValue());
        }
        return body;
    }
}
