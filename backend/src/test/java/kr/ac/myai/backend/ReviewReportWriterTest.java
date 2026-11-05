package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationException;
import kr.ac.myai.backend.review.ReviewReportWriter;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;

import static org.assertj.core.api.Assertions.*;

class ReviewReportWriterTest {
    @TempDir Path root;
    final String id = "10000000-0000-4000-8000-000000000007";
    final ReviewReportWriter writer = new ReviewReportWriter();

    @Test
    void preservesEverySectionAsInertTextAndReusesIdenticalFile() throws Exception {
        Path output = directory("data/private/reports");
        var report = report();
        String hostile = "</pre><script>alert('raw')</script><img src=https://bad.invalid> & null 🧪";
        report.withArray("documents").addObject().put("cleaned_text", hostile);
        report.withArray("extractions").addObject().put("output_base64", "/wA=").putNull("unknown");
        report.withArray("events").addObject().put("before", "A").put("after", "B");
        var result = writer.write(report, root, output);
        Path file = output.resolve(result.fileName());
        byte[] bytes = Files.readAllBytes(file); String html = new String(bytes, StandardCharsets.UTF_8);
        assertThat(result.documentVersionId()).isEqualTo(id);
        assertThat(result.checksum()).isEqualTo(ReviewedImportReader.sha256(bytes));
        assertThat(result.alreadyWritten()).isFalse();
        assertThat(html).contains("lang=\"ko\"", "원문·출처", "AI 원출력", "사람 검토값", "검토·승인 이력", "공개 이력", "공개 미리보기", "&lt;/pre&gt;&lt;script&gt;", "&amp; null 🧪", "output_base64", "null", "not_requested", "data_kind");
        assertThat(html).doesNotContain("<script", "<img", "href=\"https://bad", "src=\"https://bad");
        assertThat(html).contains("default-src 'none'", "connect-src 'none'", "script-src 'none'", "overflow-wrap:anywhere", "minmax(0,1fr)");
        assertThat(Files.getPosixFilePermissions(file)).isEqualTo(PosixFilePermissions.fromString("rw-------"));
        assertThat(writer.write(report, root, output).alreadyWritten()).isTrue();
        try (var files = Files.list(output)) { assertThat(files.count()).isEqualTo(1); }
    }

    @Test
    void rejectsPublicExternalSymlinkAndPermissiveDirectories() throws Exception {
        for (Path bad : new Path[]{directory("data/public/reports"), root.getParent()}) {
            assertCode(() -> writer.write(report(), root, bad), "REPORT_VALIDATION_ERROR");
        }
        Path output = directory("evaluation/private/reports");
        Files.setPosixFilePermissions(output, PosixFilePermissions.fromString("rwxr-x---"));
        assertCode(() -> writer.write(report(), root, output), "REPORT_VALIDATION_ERROR");
        Files.setPosixFilePermissions(output, PosixFilePermissions.fromString("rwx------"));
        Path link = root.resolve("data/private/link"); Files.createDirectories(link.getParent()); Files.createSymbolicLink(link, output);
        assertCode(() -> writer.write(report(), root, link), "REPORT_VALIDATION_ERROR");
        Path intermediate = root.resolve("data/private/alias"); Files.createSymbolicLink(intermediate, output.getParent());
        assertCode(() -> writer.write(report(), root, intermediate.resolve("reports")), "REPORT_VALIDATION_ERROR");
    }

    @Test
    void preservesConflictingFilesAndLinksAndPrivateModes() throws Exception {
        Path output = directory("data/private/reports"); var report = report();
        var first = writer.write(report, root, output); Path file = output.resolve(first.fileName());
        Files.writeString(file, "EXISTING");
        assertCode(() -> writer.write(report, root, output), "REPORT_FILE_CONFLICT");
        assertThat(Files.readString(file)).isEqualTo("EXISTING"); Files.delete(file);
        Path target = root.resolve("unrelated"); Files.writeString(target, "UNRELATED"); Files.createSymbolicLink(file, target);
        assertCode(() -> writer.write(report, root, output), "REPORT_FILE_CONFLICT");
        assertThat(Files.readString(target)).isEqualTo("UNRELATED"); Files.delete(file);
        writer.write(report, root, output); Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("rw-r--r--"));
        assertCode(() -> writer.write(report, root, output), "REPORT_FILE_CONFLICT");
    }

    @Test
    void rejectsOversizeWithoutLeavingPartialFile() throws Exception {
        Path output = directory("data/private/reports"); var report = report();
        report.withArray("documents").add("<".repeat(17 * 1024 * 1024));
        assertCode(() -> writer.write(report, root, output), "REPORT_TOO_LARGE");
        try (var files = Files.list(output)) { assertThat(files.count()).isZero(); }
    }

    @Test
    void rejectsIncompleteOrUnexpectedReportBeforeCreatingFile() throws Exception {
        Path output = directory("data/private/reports");
        var missing = report(); missing.remove("preview");
        assertCode(() -> writer.write(missing, root, output), "REPORT_VALIDATION_ERROR");
        var invalid = report(); invalid.put("document_version_id", "PRIVATE_BAD");
        assertCode(() -> writer.write(invalid, root, output), "REPORT_VALIDATION_ERROR");
        try (var files = Files.list(output)) { assertThat(files.count()).isZero(); }
    }

    ObjectNode report() {
        var report = new ObjectMapper().createObjectNode().put("format_version", "local-review-report-v1").put("document_version_id", id);
        report.putObject("capture").put("data_kind", "synthetic");
        for (String section : new String[]{"documents", "extractions", "events", "review_audits"}) report.putArray(section);
        report.putObject("publication"); report.putObject("preview").put("status", "not_requested");
        return report;
    }

    Path directory(String relative) throws Exception {
        Path result = root.resolve(relative); Files.createDirectories(result);
        Files.setPosixFilePermissions(result, PosixFilePermissions.fromString("rwx------")); return result;
    }
    void assertCode(org.assertj.core.api.ThrowableAssert.ThrowingCallable action, String code) {
        assertThatThrownBy(action).isInstanceOfSatisfying(PublicationException.class, ex -> assertThat(ex.code()).isEqualTo(code));
    }
}
