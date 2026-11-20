package kr.ac.myai.backend.source;

public class SourceReviewException extends RuntimeException {
    private final String code;
    private final String field;
    private final boolean retryable;

    public SourceReviewException(String code, String field) { this(code, field, false); }

    public SourceReviewException(String code, String field, boolean retryable) {
        super("원문 확인·사용권 검토 요청 또는 저장 상태를 확인해 주세요.");
        this.code = code;
        this.field = field;
        this.retryable = retryable;
    }

    public String code() { return code; }
    public String field() { return field; }
    public boolean retryable() { return retryable; }
}
