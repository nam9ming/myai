package kr.ac.myai.backend.review;

import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationException;
import org.springframework.stereotype.Component;

import java.io.*;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.List;
import java.util.Set;

@Component
public class ReviewReportWriter {
    private static final int LIMIT = 64 * 1024 * 1024;
    private static final List<String> SECTIONS = List.of("capture", "documents", "extractions", "events", "review_audits", "publication", "preview");
    private static final List<String> TITLES = List.of("수집·검증 시점", "원문·출처", "AI 원출력", "사람 검토값·수정 이력", "검토·승인 이력", "공개 이력", "공개 미리보기");

    public record Result(String documentVersionId, String fileName, String checksum, boolean alreadyWritten) {}

    public Result write(ObjectNode report, Path sourceRoot, Path outputDirectory) {
        validate(report != null && report.path("format_version").asText().equals("local-review-report-v1")
                && report.path("document_version_id").asText().matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"));
        var names = new java.util.HashSet<String>(); report.fieldNames().forEachRemaining(names::add);
        validate(names.equals(Set.of("format_version", "document_version_id", "capture", "documents", "extractions", "events", "review_audits", "publication", "preview")));
        try {
            Path output = directory(sourceRoot, outputDirectory);
            byte[] bytes = render(report);
            String hash = ReviewedImportReader.sha256(bytes), id = report.path("document_version_id").asText();
            String name = "review-" + id + "-" + hash + ".html";
            Path target = output.resolve(name);
            if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) return existing(target, id, hash, name);
            Path temporary = Files.createTempFile(output, ".review-", ".tmp", PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
            try {
                Files.write(temporary, bytes, StandardOpenOption.WRITE);
                try { Files.createLink(target, temporary); }
                catch (FileAlreadyExistsException ex) { return existing(target, id, hash, name); }
                return new Result(id, name, hash, false);
            } finally { Files.deleteIfExists(temporary); }
        } catch (TooLarge ex) { throw error("REPORT_TOO_LARGE", "보고서가64MiB를 초과합니다. 문서·이력을 별도 검토해 주세요."); }
        catch (IOException | UnsupportedOperationException | SecurityException ex) {
            throw error("REPORT_IO_ERROR", "보고서를 저장하지 못했습니다. 원본과 DB는 변경하지 않았습니다.");
        }
    }

    private Path directory(Path sourceRoot, Path outputDirectory) throws IOException {
        validate(sourceRoot != null && outputDirectory != null);
        Path statedRoot = sourceRoot.toAbsolutePath().normalize(), statedOutput = outputDirectory.toAbsolutePath().normalize();
        validate(statedOutput.startsWith(statedRoot));
        Path relative = statedRoot.relativize(statedOutput);
        validate(relative.startsWith(Path.of("data", "private")) || relative.startsWith(Path.of("evaluation", "private")));
        Path current = statedRoot.toRealPath();
        for (Path part : relative) {
            current = current.resolve(part);
            validate(Files.isDirectory(current, LinkOption.NOFOLLOW_LINKS));
        }
        validate(Files.getPosixFilePermissions(current, LinkOption.NOFOLLOW_LINKS).equals(PosixFilePermissions.fromString("rwx------")));
        return current;
    }

    private Result existing(Path target, String id, String hash, String name) throws IOException {
        if (Files.isRegularFile(target, LinkOption.NOFOLLOW_LINKS)
                && Files.getPosixFilePermissions(target, LinkOption.NOFOLLOW_LINKS).equals(PosixFilePermissions.fromString("rw-------"))) {
            try (var stream = Files.newInputStream(target, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                byte[] bytes = stream.readNBytes(LIMIT + 1);
                if (bytes.length <= LIMIT && ReviewedImportReader.sha256(bytes).equals(hash)) return new Result(id, name, hash, true);
            }
        }
        throw error("REPORT_FILE_CONFLICT", "출력 위치에 다른 파일·링크 또는 공개 권한 파일이 있습니다. 기존 항목을 보존했습니다.");
    }

    private byte[] render(ObjectNode report) throws IOException {
        var bytes = new LimitedBytes();
        try (var html = new OutputStreamWriter(bytes, StandardCharsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT))) {
            html.write("""
                    <!doctype html><html lang="ko"><head><meta charset="utf-8">
                    <meta name="viewport" content="width=device-width,initial-scale=1">
                    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'none'; connect-src 'none'; img-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
                    <meta name="referrer" content="no-referrer"><title>팀 공지 검토 보고서</title>
                    <style>
                    *{box-sizing:border-box}body{margin:auto;max-width:1600px;padding:16px;font:16px/1.6 system-ui,sans-serif;color:#172533;background:#fff}
                    nav{display:flex;flex-wrap:wrap;gap:8px}a{display:inline-flex;align-items:center;min-height:44px;padding:8px;color:#143da2}a:focus-visible{outline:3px solid #b24b00}
                    .comparison{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}section{min-width:0}h2{font-size:1.2rem}
                    pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;background:#f4f6f8;border:1px solid #c1cbd4;padding:12px;direction:ltr;unicode-bidi:plaintext}
                    @media(max-width:1023px){.comparison{grid-template-columns:minmax(0,1fr)}}
                    </style></head><body><h1>팀 공지 검토 보고서</h1>
                    <p>비공개 로컬 검토용입니다. 기계 검증과 사람 승인·공개는 별개입니다. 이 파일을 공개 저장소·게시판에 올리지 마세요.</p>
                    <p>원문·AI 시도별 원출력·현재 및 과거 수정값을 비교합니다. null·미상·실패는 원래 값으로 표시합니다.
                    비UTF8 원본은 base64·크기·SHA로 확인하세요. 보고서 수집과 별도 검증·미리보기의 시점을 확인하세요.</p>
                    <p>수정·보류·승인·공개는 기존 파일 명령으로 진행합니다. 이 보고서에는 실행 버튼이 없습니다.
                    공개 미리보기의 snapshot은 실제 공개가 아니며, 미실행·실패는 성공을 뜻하지 않습니다.</p><nav aria-label="보고서 항목">
                    """);
            for (int i = 0; i < SECTIONS.size(); i++) html.write("<a href=\"#" + SECTIONS.get(i) + "\">" + TITLES.get(i) + "</a>");
            html.write("</nav><p>문서 버전: "); escaped(html, report.path("document_version_id").asText()); html.write("</p>");
            section(html, report, 0); html.write("<main class=\"comparison\">");
            for (int i = 1; i <= 3; i++) section(html, report, i);
            html.write("</main>");
            for (int i = 4; i < SECTIONS.size(); i++) section(html, report, i);
            html.write("<footer><p>local-review-report-v1 · 전체 값은 JSON 표기로 보존합니다. 형식 검증은 사실 정확도·사용권·실제 사람 검토를 인증하지 않습니다.</p></footer></body></html>");
        }
        return bytes.toByteArray();
    }

    private void section(Writer html, ObjectNode report, int index) throws IOException {
        html.write("<section id=\"" + SECTIONS.get(index) + "\"><h2>" + TITLES.get(index) + "</h2><pre>");
        escaped(html, report.get(SECTIONS.get(index)).toPrettyString()); html.write("</pre></section>");
    }

    private void escaped(Writer output, String value) throws IOException {
        int start = 0;
        for (int i = 0; i < value.length(); i++) {
            String replacement = switch (value.charAt(i)) { case '&' -> "&amp;"; case '<' -> "&lt;"; case '>' -> "&gt;"; default -> null; };
            if (replacement != null) { output.write(value, start, i - start); output.write(replacement); start = i + 1; }
        }
        output.write(value, start, value.length() - start);
    }

    private static class TooLarge extends IOException {}
    private static class LimitedBytes extends OutputStream {
        private final ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        @Override public void write(int value) throws IOException {
            if (bytes.size() == LIMIT) throw new TooLarge();
            bytes.write(value);
        }
        @Override public void write(byte[] values, int offset, int length) throws IOException {
            if (length > LIMIT - bytes.size()) throw new TooLarge();
            bytes.write(values, offset, length);
        }
        byte[] toByteArray() { return bytes.toByteArray(); }
    }
    private static void validate(boolean condition) { if (!condition) throw error("REPORT_VALIDATION_ERROR", "보고서 형식과 private 출력 경로·0700 권한을 확인해 주세요."); }
    private static PublicationException error(String code, String message) { return new PublicationException(code, message, null); }
}
