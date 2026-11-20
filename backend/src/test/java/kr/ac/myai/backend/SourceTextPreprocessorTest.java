package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.exception.ApiException;
import kr.ac.myai.backend.local.PdfTextExtractor;
import kr.ac.myai.backend.local.SourceTextPreprocessor;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class SourceTextPreprocessorTest {
    private final SourceTextPreprocessor preprocessor = new SourceTextPreprocessor(new PdfTextExtractor(""));

    @Test
    void normalizesUtf8LineEndingsAndNfcWithoutEmptyEvidenceBlocks() {
        var result = prepare("txt", "가게 😀\r\n둘째\r\n\r\n셋째\r");
        assertThat(result.blocks()).extracting(SourceTextPreprocessor.Block::text)
                .containsExactly("가게 😀", "둘째", "셋째");
        assertThat(result.cleanedText()).isEqualTo("가게 😀\n둘째\n셋째");
        assertThat(result.blocks()).allSatisfy(block -> assertThat(block.page()).isNull());
        assertThat(result.blocks()).extracting(SourceTextPreprocessor.Block::blockId).doesNotHaveDuplicates();
        assertThat(result.preprocessingVersion()).isNotBlank();
        assertThat(prepare("txt", "가게 😀\r\n둘째\r\n\r\n셋째\r")).isEqualTo(result);
    }

    @Test
    void rejectsMalformedUtf8ControlsEmptyBodyAndUnknownFormat() {
        failure("txt", new byte[]{(byte) 0xc3, 0x28}, 422);
        for (String text : List.of("", " \t\r\n", "본문\u0000", "본문\u000b", "본문\u001f", "본문\u007f", "본문\u0085")) {
            failure("txt", text.getBytes(StandardCharsets.UTF_8), 422);
        }
        failure("html", "본문".getBytes(StandardCharsets.UTF_8), 422);
    }

    @Test
    void acceptsOnlyTheExactTextBodyJsonShape() {
        var json = prepare("json", "{\"schema_version\":\"text-body-v1\",\"text\":\"가게\\r\\n공지 😀\"}");
        var text = prepare("txt", "가게\r\n공지 😀");
        assertThat(json.cleanedText()).isEqualTo(text.cleanedText());
        assertThat(json.blocks()).isEqualTo(text.blocks());
        for (String invalid : List.of(
                "{\"schema_version\":\"text-body-v1\",\"text\":\"본문\",\"extra\":true}",
                "{\"schema_version\":\"text-body-v1\",\"text\":\"첫째\",\"text\":\"둘째\"}",
                "{\"schema_version\":\"text-body-v1\",\"text\":\"본문\"} {}",
                "{\"schema_version\":\"other\",\"text\":\"본문\"}",
                "{\"schema_version\":\"text-body-v1\",\"text\":null}",
                "{\"schema_version\":\"text-body-v1\",\"text\":42}",
                "{\"schema_version\":\"text-body-v1\",\"text\":\"\\ud800\"}",
                "{\"schema_version\":\"text-body-v1\",\"text\":\"\\udc00\"}",
                "{\"schema_version\":\"text-body-v1\",\"text\":\"\\u0000\"}",
                "[]", "{\"blocks\":[]}")) {
            failure("json", invalid.getBytes(StandardCharsets.UTF_8), 422);
        }
        failure("json", new byte[]{(byte) 0xff}, 422);
    }

    @Test
    void classifiesAJsonStringBelowTheRawLimitButAboveTheBodyLimitAsTooLarge() {
        byte[] raw = ("{\"schema_version\":\"text-body-v1\",\"text\":\"" + "a".repeat(20_100_000) + "\"}")
                .getBytes(StandardCharsets.UTF_8);
        assertThat(raw.length).isLessThan(20 * 1024 * 1024);
        var error = catchThrowable(() -> preprocessor.prepare("json", raw));
        assertThat(error).isInstanceOf(ApiException.class);
        assertThat(((ApiException) error).status().value()).isEqualTo(413);
        assertThat(((ApiException) error).code()).isEqualTo("SOURCE_TEXT_TOO_LARGE");
    }

    @Test
    void replacesFixedEmailAndPhonePatternsWithoutCopyingValuesToTheLog() throws Exception {
        String original = "담당 😀 notice@example.test / 031-123-4567 / 010-1234-5678, 날짜 2026-11-05";
        var result = prepare("txt", original);
        assertThat(result.cleanedText()).doesNotContain("notice@example.test", "031-123-4567", "010-1234-5678")
                .contains("담당 😀", "날짜 2026-11-05");
        assertThat(result.redactionLog()).extracting(SourceTextPreprocessor.Redaction::category)
                .containsExactly("email", "phone", "phone");
        assertThat(result.redactionLog()).allSatisfy(entry -> assertThat(entry.location()).isNotBlank());
        String log = new ObjectMapper().writeValueAsString(result.redactionLog());
        assertThat(log).doesNotContain("notice", "example.test", "031-123-4567", "010-1234-5678", "담당");
        assertThat(prepare("txt", original)).isEqualTo(result);
    }

    @Test
    void recordsOriginalUnicodeCodePointLocationsAcrossMultipleReplacements() throws Exception {
        var result = prepare("txt", "😀 A a@b.test / 010-1234-5678 😀 b@c.test");
        assertThat(result.cleanedText()).isEqualTo("😀 A [EMAIL] / [PHONE] 😀 [EMAIL]");
        assertThat(result.redactionLog()).containsExactly(
                new SourceTextPreprocessor.Redaction("email", "codepoints:4-12"),
                new SourceTextPreprocessor.Redaction("phone", "codepoints:15-28"),
                new SourceTextPreprocessor.Redaction("email", "codepoints:31-39"));
        assertThat(new ObjectMapper().writeValueAsString(result.redactionLog()))
                .doesNotContain("a@b.test", "b@c.test", "010-1234-5678", "😀");
    }

    @Test
    void rejectsDenseContactsWithinABoundedChildProcess() throws Exception {
        var classpath = new java.util.LinkedHashSet<String>();
        classpath.add(System.getProperty("java.class.path"));
        for (ClassLoader loader = getClass().getClassLoader(); loader != null; loader = loader.getParent()) {
            if (loader instanceof java.net.URLClassLoader urls) {
                for (var url : urls.getURLs()) classpath.add(Path.of(url.toURI()).toString());
            }
        }
        var process = new ProcessBuilder(Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                "-Xmx256m", "-cp", String.join(java.io.File.pathSeparator, classpath), DenseContactProbe.class.getName()).start();
        try {
            assertThat(process.waitFor(12, TimeUnit.SECONDS)).isTrue();
            assertThat(process.exitValue()).isZero();
            assertThat(new String(process.getInputStream().readAllBytes(), StandardCharsets.UTF_8).trim())
                    .isEqualTo("SOURCE_TEXT_TOO_LARGE");
            assertThat(process.getErrorStream().readAllBytes()).isEmpty();
        } finally {
            process.destroyForcibly();
            assertThat(process.waitFor(3, TimeUnit.SECONDS)).isTrue();
        }
    }

    public static final class DenseContactProbe {
        public static void main(String[] args) {
            try {
                new SourceTextPreprocessor(new PdfTextExtractor("")).prepare("txt",
                        ("😀" + "010-1234-5678 ".repeat(150_000)).getBytes(StandardCharsets.UTF_8));
                throw new AssertionError("Expected body limit");
            } catch (ApiException error) {
                if (!error.code().equals("SOURCE_TEXT_TOO_LARGE")) throw error;
                System.out.println(error.code());
            }
        }
    }

    @Test
    void splitsLongLinesWithoutBreakingSurrogatesAndJoinsBlocksDeterministically() {
        String original = "😀".repeat(4_501);
        var result = prepare("txt", original);
        assertThat(result.blocks()).extracting(SourceTextPreprocessor.Block::text)
                .containsExactly("😀".repeat(2_000), "😀".repeat(2_000), "😀".repeat(501));
        assertThat(result.blocks().stream().map(SourceTextPreprocessor.Block::text).collect(Collectors.joining()))
                .isEqualTo(original);
        assertThat(result.cleanedText()).isEqualTo(result.blocks().stream()
                .map(SourceTextPreprocessor.Block::text).collect(Collectors.joining("\n")));
        assertThat(result.blocks()).extracting(SourceTextPreprocessor.Block::blockId).doesNotHaveDuplicates();
    }

    @Test
    void countsTheFinalLfJoinedBodyInUnicodeCodePointsIncludingInsertedSeparators() {
        String maximum = String.join("\n", java.util.Collections.nCopies(100, "😀".repeat(1_999))) + "😀";
        var result = prepare("txt", maximum);
        assertThat(result.cleanedText()).isEqualTo(maximum);
        assertThat(result.cleanedText().codePointCount(0, result.cleanedText().length())).isEqualTo(200_000);
        assertThat(result.blocks()).hasSize(100).allSatisfy(block ->
                assertThat(block.text().codePointCount(0, block.text().length())).isBetween(1, 2_000));
        failure("txt", (maximum + "😀").getBytes(StandardCharsets.UTF_8), 413);
        failure("txt", "😀".repeat(200_000).getBytes(StandardCharsets.UTF_8), 413);
    }

    @ParameterizedTest @ValueSource(strings = {"txt", "json"})
    void discardedWhitespaceDoesNotRejectAnOtherwiseValidFinalBody(String format) {
        String padding = " ".repeat(210_000);
        var redacted = preprocessor.prepare(format, bodyBytes(format, padding + "\n문의 a@b.test\n" + padding));
        assertThat(redacted.cleanedText()).isEqualTo("문의 [EMAIL]");
        assertThat(redacted.redactionLog()).containsExactly(
                new SourceTextPreprocessor.Redaction("email", "codepoints:210004-210012"));
        String maximum = String.join("\n", java.util.Collections.nCopies(100, "😀".repeat(1_999))) + "😀";
        var result = preprocessor.prepare(format, bodyBytes(format, padding + "\n" + maximum + "\n" + padding));
        assertThat(result.cleanedText()).isEqualTo(maximum);
        assertThat(result.cleanedText().codePointCount(0, result.cleanedText().length())).isEqualTo(200_000);
        failure(format, bodyBytes(format, padding + "\n" + maximum + "😀\n" + padding), 413);
    }

    @Test
    void discardsPdfWhitespaceBeforeCountingTheFinalBodyAndKeepsPageNumbers() {
        var pdf = mock(PdfTextExtractor.class);
        byte[] raw = {1};
        String padding = " ".repeat(210_000);
        when(pdf.extract(raw)).thenReturn(new PdfTextExtractor.PdfText(
                List.of(padding + "\nNOTICE\n" + padding, "SECOND"), "25.04.0"));
        var result = new SourceTextPreprocessor(pdf).prepare("pdf", raw);
        assertThat(result.cleanedText()).isEqualTo("NOTICE\nSECOND");
        assertThat(result.blocks()).extracting(SourceTextPreprocessor.Block::page).containsExactly(1, 2);
    }

    @Test
    void projectedBlocksPassActualPythonValidationAndBoundedChunkPlanningWithoutAnApiCall() throws Exception {
        var prepared = prepare("txt", "가😀".repeat(50_000));
        var mapper = new ObjectMapper();
        var input = mapper.createObjectNode().put("data_kind", "synthetic")
                .put("document_version_id", "99999999-9999-4999-8999-999999999999")
                .put("title", "합성 텍스트화 검증").putNull("published_date");
        var blocks = input.putArray("blocks");
        for (var block : prepared.blocks()) {
            var node = blocks.addObject().put("block_id", block.blockId()).put("text", block.text());
            if (block.page() == null) node.putNull("page"); else node.put("page", block.page());
        }
        byte[] bytes = mapper.writeValueAsBytes(input);
        String code = """
                import sys,json,hashlib
                from processing.extraction.validation import parse_input
                from processing.extraction.chunks import plan_chunks
                raw=sys.stdin.buffer.read()
                doc=parse_input(raw)
                plan=plan_chunks(doc,'synthetic-no-api',hashlib.sha256(raw).hexdigest())
                assert plan['status']=='ready'
                assert len(plan['chunks'])>1
                assert all(c['request_bytes']<=plan['request_limit_bytes']-plan['feedback_reserve_bytes'] for c in plan['chunks'])
                print(json.dumps(dict(block_hashes=[hashlib.sha256(b['text'].encode('utf-8')).hexdigest() for b in doc['blocks']],
                                     input_sha256=hashlib.sha256(raw).hexdigest())))
                """;
        var process = new ProcessBuilder(PythonProbe.PYTHON, "-c", code).directory(PythonProbe.REPO.toFile()).start();
        try {
            try (var stdin = process.getOutputStream()) { stdin.write(bytes); }
            assertThat(process.waitFor(10, TimeUnit.SECONDS)).isTrue();
            assertThat(process.exitValue()).isZero();
            assertThat(process.getErrorStream().readAllBytes()).isEmpty();
            var receipt = mapper.readTree(process.getInputStream().readAllBytes());
            assertThat(receipt.path("input_sha256").asText()).isEqualTo(sha(bytes));
            assertThat(mapper.convertValue(receipt.path("block_hashes"), List.class))
                    .isEqualTo(prepared.blocks().stream().map(block -> sha(block.text().getBytes(StandardCharsets.UTF_8))).toList());
        } finally { process.destroyForcibly(); process.waitFor(3, TimeUnit.SECONDS); }
    }

    private SourceTextPreprocessor.Prepared prepare(String format, String text) {
        return preprocessor.prepare(format, text.getBytes(StandardCharsets.UTF_8));
    }

    private byte[] bodyBytes(String format, String body) {
        String text = format.equals("txt") ? body : new ObjectMapper().createObjectNode()
                .put("schema_version", "text-body-v1").put("text", body).toString();
        return text.getBytes(StandardCharsets.UTF_8);
    }

    private void failure(String format, byte[] raw, int status) {
        var error = catchThrowable(() -> preprocessor.prepare(format, raw));
        assertThat(error).isInstanceOf(ApiException.class);
        assertThat(((ApiException) error).status().value()).isEqualTo(status);
        assertThat(error.getMessage()).doesNotContain("notice@example.test", "031-123-4567", "010-1234-5678");
    }

    private static String sha(byte[] bytes) {
        try { return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes)); }
        catch (Exception ex) { throw new AssertionError(ex); }
    }
}
