package kr.ac.myai.backend.publication;

public class PublicationException extends RuntimeException {
    private final String code;
    private final String field;

    public PublicationException(String code, String message, String field) {
        super(message);
        this.code = code;
        this.field = field;
    }

    public String code() { return code; }
    public String field() { return field; }
}
