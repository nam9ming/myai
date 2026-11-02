package kr.ac.myai.backend.exception;

import org.springframework.http.HttpStatus;

public class ApiException extends RuntimeException {
    private final HttpStatus status;
    private final String code;
    private final String field;
    private final String currentSnapshotId;

    public ApiException(HttpStatus status, String code, String message, String field) {
        this(status, code, message, field, null);
    }

    public ApiException(HttpStatus status, String code, String message, String field, String currentSnapshotId) {
        super(message);
        this.status = status;
        this.code = code;
        this.field = field;
        this.currentSnapshotId = currentSnapshotId;
    }

    public static ApiException invalid(String field, String message) {
        return new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "INVALID_REQUEST", message, field);
    }

    public HttpStatus status() { return status; }
    public String code() { return code; }
    public String field() { return field; }
    public String currentSnapshotId() { return currentSnapshotId; }
}
