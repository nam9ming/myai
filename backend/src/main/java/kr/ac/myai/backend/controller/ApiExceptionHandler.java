package kr.ac.myai.backend.controller;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import kr.ac.myai.backend.exception.ApiException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.HttpMediaTypeNotSupportedException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.util.List;
import java.util.UUID;

@RestControllerAdvice
public class ApiExceptionHandler {
    private static final Logger log = LoggerFactory.getLogger(ApiExceptionHandler.class);
    private static final PropertyNamingStrategies.SnakeCaseStrategy names = new PropertyNamingStrategies.SnakeCaseStrategy();

    public record FieldError(String field, String message) {}
    public record ErrorDetail(String code, String message, List<FieldError> fieldErrors, boolean retryable) {}
    public record ErrorResponse(ErrorDetail error, String requestId) {}

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<ErrorResponse> domain(ApiException error) {
        var fields = error.field() == null ? List.<FieldError>of() : List.of(new FieldError(error.field(), error.getMessage()));
        return response(error.status(), error.code(), error.getMessage(), fields);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> validation(MethodArgumentNotValidException error) {
        var fields = error.getBindingResult().getFieldErrors().stream()
                .map(field -> new FieldError(names.translate(field.getField()), field.getDefaultMessage())).toList();
        return response(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_REQUEST", "입력 조건을 확인해 주세요.", fields);
    }

    @ExceptionHandler({HttpMessageNotReadableException.class, MissingServletRequestParameterException.class, MethodArgumentTypeMismatchException.class})
    public ResponseEntity<ErrorResponse> malformed(Exception error) {
        return response(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_REQUEST", "요청 형식과 필수 필드를 확인해 주세요.", List.of());
    }

    @ExceptionHandler(NoResourceFoundException.class)
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

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> unexpected(Exception error) {
        String requestId = UUID.randomUUID().toString();
        log.error("요청 처리 실패 request_id={}", requestId, error);
        return ResponseEntity.internalServerError().body(new ErrorResponse(
                new ErrorDetail("INTERNAL_ERROR", "요청 처리 중 오류가 발생했습니다.", List.of(), false), requestId));
    }

    private ResponseEntity<ErrorResponse> response(HttpStatus status, String code, String message, List<FieldError> fields) {
        return ResponseEntity.status(status).body(new ErrorResponse(
                new ErrorDetail(code, message, fields, status == HttpStatus.SERVICE_UNAVAILABLE), UUID.randomUUID().toString()));
    }
}
