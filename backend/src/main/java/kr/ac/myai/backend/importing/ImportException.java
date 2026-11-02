package kr.ac.myai.backend.importing;

public class ImportException extends RuntimeException {
    private final String code;
    private final String field;

    public ImportException(String code, String message, String field) {
        super(message);
        this.code = code;
        this.field = field;
    }

    public String code() { return code; }
    public String field() { return field; }
}
