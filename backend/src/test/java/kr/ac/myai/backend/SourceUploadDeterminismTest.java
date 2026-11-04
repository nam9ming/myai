package kr.ac.myai.backend;

import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.local.LocalManagementService;
import kr.ac.myai.backend.local.LocalRequestStore;
import kr.ac.myai.backend.local.PdfTextExtractor;
import kr.ac.myai.backend.local.SourceTextPreprocessor;
import kr.ac.myai.backend.local.SourceUploadService;
import kr.ac.myai.backend.local.SourceUploadStore;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.env.MockEnvironment;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

class SourceUploadDeterminismTest {
    private static final String VERSION = "55555555-5555-4555-8555-555555555555";
    private static final byte[] METADATA = """
            {"schema_version":"source-upload-v1","format":"txt","data_kind":"synthetic",
             "document_id":"44444444-4444-4444-8444-444444444444",
             "document_version_id":"55555555-5555-4555-8555-555555555555","version_no":1,
             "publisher":"합성 기관","official_url":"https://example.invalid/notice/1","title":"합성 공지",
             "official_number":null,"published_date":null,"collected_at":"2026-11-02T00:00:00Z",
             "collection_method":"synthetic fixture","use_note":"synthetic only; not approved for publication"}
            """.getBytes(StandardCharsets.UTF_8);
    private static final byte[] RAW = "합성 결정성 공지 😀\r\n문의 fixed@example.test / 031-123-4567\n마지막 행"
            .getBytes(StandardCharsets.UTF_8);

    @TempDir Path temporary;

    @Test
    void createsIdenticalSourceAndInputHashesAcrossFourFreshJvmsAndStorageRoots() throws Exception {
        Files.setPosixFilePermissions(temporary, PosixFilePermissions.fromString("rwx------"));
        var classpath = new LinkedHashSet<String>();
        classpath.add(System.getProperty("java.class.path"));
        for (ClassLoader loader = getClass().getClassLoader(); loader != null; loader = loader.getParent()) {
            if (loader instanceof java.net.URLClassLoader urls) {
                for (var url : urls.getURLs()) classpath.add(Path.of(url.toURI()).toString());
            }
        }
        var hashes = new ArrayList<String>();
        for (int run = 0; run < 4; run++) {
            Path root = directory(temporary.resolve("run-" + run)).toRealPath();
            var builder = new ProcessBuilder(Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                    "-Xmx256m", "-cp", String.join(java.io.File.pathSeparator, classpath), Probe.class.getName(), root.toString());
            builder.environment().clear();
            builder.environment().put("LANG", "C");
            builder.environment().put("LC_ALL", "C");
            var process = builder.start();
            try {
                assertThat(process.waitFor(12, TimeUnit.SECONDS)).isTrue();
                assertThat(process.exitValue()).isZero();
                assertThat(process.getErrorStream().readAllBytes()).isEmpty();
                String output = new String(process.getInputStream().readAllBytes(), StandardCharsets.US_ASCII).trim();
                assertThat(output).matches("[0-9a-f]{64} [0-9a-f]{64}");
                hashes.add(output);
            } finally {
                process.destroyForcibly();
                assertThat(process.waitFor(3, TimeUnit.SECONDS)).isTrue();
            }
        }
        assertThat(hashes).hasSize(4).containsOnly(hashes.getFirst());
    }

    public static final class Probe {
        public static void main(String[] args) throws Exception {
            Path root = Path.of(args[0]);
            Path sources = directory(root.resolve("sources"));
            Path requests = directory(root.resolve("requests"));
            Path extractions = directory(root.resolve("extractions"));
            Path handoffs = directory(root.resolve("handoffs"));
            var reader = new ReviewedImportReader();
            var requestStore = new LocalRequestStore(requests.toString());
            var environment = new MockEnvironment().withProperty("myai.local-api.source-root", sources.toString())
                    .withProperty("myai.local-api.extraction-root", extractions.toString())
                    .withProperty("myai.local-api.handoff-root", handoffs.toString())
                    .withProperty("myai.local-api.actor", "synthetic-reviewer");
            var management = new CheckedManagement(reader, requestStore, environment, sources);
            var store = new SourceUploadStore(sources.toString(), requests.toString());
            var service = new SourceUploadService(management, reader, store,
                    new SourceTextPreprocessor(new PdfTextExtractor("")), requestStore, sources.toString());
            var result = service.upload(METADATA, RAW, "text/plain;charset=UTF-8");
            var saved = store.find(VERSION, METADATA, RAW);
            if (saved == null || !result.inputHash().equals(ReviewedImportReader.sha256(saved.aiInput()))) {
                throw new AssertionError("Prepared input hash mismatch");
            }
            try (var paths = Files.walk(root)) {
                for (Path path : paths.toList()) {
                    var expected = PosixFilePermissions.fromString(Files.isDirectory(path) ? "rwx------" : "rw-------");
                    if (!Files.getPosixFilePermissions(path).equals(expected)) throw new AssertionError("Unsafe test storage mode");
                }
            }
            System.out.println(ReviewedImportReader.sha256(saved.sourceImport()) + " " + result.inputHash());
        }
    }

    private static final class CheckedManagement extends LocalManagementService {
        private final ReviewedImportReader reader;
        private final Path sources;

        CheckedManagement(ReviewedImportReader reader, LocalRequestStore requests, MockEnvironment environment, Path sources) {
            super(reader, null, null, null, null, null, requests, environment);
            this.reader = reader;
            this.sources = sources;
        }

        @Override
        public Result documents(byte[] payload) {
            var batch = reader.read(payload, sources);
            if (batch.documents().size() != 1 || !batch.events().isEmpty()) throw new AssertionError("Expected one source document only");
            return new Result("local-management-result-v1", ReviewedImportReader.sha256(payload), Map.of("batch_id", VERSION));
        }
    }

    private static Path directory(Path path) throws Exception {
        return Files.createDirectory(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
    }
}
