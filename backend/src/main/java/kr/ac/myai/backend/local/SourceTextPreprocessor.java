package kr.ac.myai.backend.local;

import com.fasterxml.jackson.core.JsonFactory;
import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.exception.ApiException;
import org.springframework.http.HttpStatus;

import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

public final class SourceTextPreprocessor {
    private static final int BODY_LIMIT = 200_000;
    private static final int BLOCK_LIMIT = 2_000;
    private static final String POLICY = "source-text-v1:nfc-lf:contacts-v1:blocks-2000-lf";
    // shortcut: 고정 전화·이메일만 치환하고 외부 호출은 없다. AI 전송 도입 시 별도 개인정보 검토·탐지 범위가 필요하다.
    private static final Pattern CONTACT = Pattern.compile(
            "(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])(?<email>[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}"
            + "@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?){1,10})(?![A-Za-z0-9-])"
            + "|(?<phone>(?<![0-9])(?:0(?:2|[3-6][1-5]|70|1[016789]))[- .]?[0-9]{3,4}[- .]?[0-9]{4}(?![0-9]))");
    private static final ObjectMapper JSON = new ObjectMapper(JsonFactory.builder()
            .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION).build())
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS);

    public record Prepared(String cleanedText, List<Block> blocks, List<Redaction> redactionLog,
                           String preprocessingVersion, String textScope, boolean textReviewRequired) { }
    public record Block(String blockId, Integer page, String text) { }
    public record Redaction(String category, String location) { }

    private final PdfTextExtractor pdf;

    public SourceTextPreprocessor(PdfTextExtractor pdf) { this.pdf = pdf; }

    public Prepared prepare(String format, byte[] raw) {
        if (raw == null || raw.length == 0) throw invalid();
        if (raw.length > 20 * 1024 * 1024) throw tooLarge();
        List<String> pages;
        boolean isPdf = "pdf".equals(format);
        String policy = POLICY;
        if (isPdf) {
            var extracted = pdf.extract(raw);
            pages = extracted.pages();
            policy += ":pdftotext-" + extracted.toolVersion();
        } else if ("txt".equals(format)) {
            pages = List.of(decode(raw));
        } else if ("json".equals(format)) {
            try {
                var body = JSON.readTree(decode(raw));
                if (body == null || !body.isObject() || body.size() != 2
                        || !body.path("schema_version").isTextual() || !body.path("schema_version").asText().equals("text-body-v1")
                        || !body.path("text").isTextual()) throw invalid();
                pages = List.of(body.path("text").textValue());
            } catch (java.io.IOException ex) { throw invalid(); }
        } else throw invalid();

        var blocks = new ArrayList<Block>();
        var redactions = new ArrayList<Redaction>();
        int size = 0;
        for (int i = 0; i < pages.size(); i++) {
            String normalized = normalize(pages.get(i));
            String text = redact(normalized, isPdf ? "page:" + (i + 1) + ":" : "", redactions);
            size += text.codePointCount(0, text.length()) + (i == 0 ? 0 : 1);
            if (size > BODY_LIMIT) throw tooLarge();
            for (String line : text.split("\n", -1)) {
                int remaining = line.codePointCount(0, line.length());
                int start = 0;
                while (remaining > 0) {
                    int count = Math.min(BLOCK_LIMIT, remaining);
                    int end = line.offsetByCodePoints(start, count);
                    String part = line.substring(start, end);
                    if (!blank(part)) blocks.add(new Block("block-" + (blocks.size() + 1), isPdf ? i + 1 : null, part));
                    start = end;
                    remaining -= count;
                }
            }
        }
        if (blocks.isEmpty()) throw invalid();
        String cleaned = blocks.stream().map(Block::text).collect(Collectors.joining("\n"));
        if (cleaned.codePointCount(0, cleaned.length()) > BODY_LIMIT) throw tooLarge();
        // PDF 완전성 대조 플래그다. txt/json의 개인정보·사실 검토 완료를 뜻하지 않는다.
        return new Prepared(cleaned, List.copyOf(blocks), List.copyOf(redactions), policy,
                isPdf ? "embedded_text_only" : "provided_text", isPdf);
    }

    private static String decode(byte[] raw) {
        try {
            return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(raw)).toString();
        } catch (CharacterCodingException ex) { throw invalid(); }
    }

    private static String normalize(String text) {
        for (int i = 0; i < text.length(); i++) {
            char value = text.charAt(i);
            if (Character.isHighSurrogate(value)) {
                if (++i >= text.length() || !Character.isLowSurrogate(text.charAt(i))) throw invalid();
            } else if (Character.isLowSurrogate(value)
                    || Character.isISOControl(value) && value != '\r' && value != '\n' && value != '\t') throw invalid();
        }
        return Normalizer.normalize(text.replace("\r\n", "\n").replace('\r', '\n'), Normalizer.Form.NFC);
    }

    private static String redact(String text, String prefix, List<Redaction> log) {
        var matcher = CONTACT.matcher(text);
        var result = new StringBuilder();
        int previousEnd = 0;
        int previousCodePoint = 0;
        int outputSize = 0;
        while (matcher.find()) {
            String category = matcher.start("email") >= 0 ? "email" : "phone";
            String replacement = category.equals("email") ? "[EMAIL]" : "[PHONE]";
            int before = text.codePointCount(previousEnd, matcher.start());
            int start = previousCodePoint + before;
            int end = start + text.codePointCount(matcher.start(), matcher.end());
            outputSize += before + replacement.length();
            if (outputSize > BODY_LIMIT) throw tooLarge();
            log.add(new Redaction(category, prefix + "codepoints:" + start + "-" + end));
            matcher.appendReplacement(result, replacement);
            previousEnd = matcher.end();
            previousCodePoint = end;
        }
        return matcher.appendTail(result).toString();
    }

    private static boolean blank(String text) {
        return text.codePoints().allMatch(value -> Character.isWhitespace(value) || Character.isSpaceChar(value));
    }

    private static ApiException invalid() {
        return new ApiException(HttpStatus.UNPROCESSABLE_ENTITY, "SOURCE_TEXT_INVALID",
                "파일 형식·UTF-8 본문·허용 문자를 확인해 주세요.", "file");
    }

    private static ApiException tooLarge() {
        return new ApiException(HttpStatus.PAYLOAD_TOO_LARGE, "SOURCE_TEXT_TOO_LARGE",
                "파일은20MiB, 전처리 본문은200,000자 이하여야 합니다. 분할하거나 별도로 검토해 주세요.", "file");
    }
}
