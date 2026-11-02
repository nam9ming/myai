package kr.ac.myai.backend.extraction;

public class ExtractionException extends RuntimeException {
    private final String code;
    private final String field;
    private final boolean retryable;

    public ExtractionException(String code, String field, boolean retryable) {
        super("AI 실행 기록을 등록하지 못했습니다. 설정·원본 무결성·DB 상태를 확인해 주세요.");
        this.code = code; this.field = field; this.retryable = retryable;
    }

    public String code() { return code; }
    public String field() { return field; }
    public boolean retryable() { return retryable; }
}
