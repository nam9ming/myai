package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.handoff.VerifiedHandoff;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.repository.ExtractionRunRepository;
import kr.ac.myai.backend.review.ReviewReportService;
import kr.ac.myai.backend.service.ExtractionImportService;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;

@SpringBootTest
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class CitizenExtractionMySqlTest {
    @Autowired ReviewedImportReader imports;
    @Autowired ReviewedImportService importer;
    @Autowired ExtractionArchiveReader archives;
    @Autowired ExtractionImportService extractions;
    @Autowired ExtractionRunRepository runs;
    @Autowired ReviewReportService reports;
    @Autowired JdbcTemplate jdbc;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();
    final Set<String> ownedRuns = new HashSet<>(), ownedDocuments = new HashSet<>(), ownedVersions = new HashSet<>(), ownedBatchHashes = new HashSet<>();
    Map<String, List<Map<String, Object>>> originalRows;

    @DynamicPropertySource
    static void testDatabaseAndPython(DynamicPropertyRegistry registry) {
        String url = System.getenv("DB_URL");
        if (url == null || !url.startsWith("jdbc:mysql://")
                || !Set.of("/myai_test", "/myai_citizen_test").contains(URI.create(url.substring(5)).getRawPath())) {
            throw new IllegalStateException("시민 추출 시험은 전용 myai_test 또는 myai_citizen_test DB_URL이 필요합니다.");
        }
        registry.add("spring.datasource.url", () -> url);
        registry.add("app.calculation.workdir", () -> PythonProbe.REPO.toString());
        registry.add("app.calculation.python-executable", () -> PythonProbe.PYTHON);
        registry.add("app.extraction.timeout-ms", () -> 20_000);
    }

    @BeforeEach void verifyDatabase() {
        assertThat(jdbc.queryForObject("SELECT DATABASE()", String.class)).isIn("myai_test", "myai_citizen_test");
        originalRows = CitizenNoticeFixtures.rows(jdbc);
    }
    @AfterEach void removeOwnedRowsAndUnsealFiles() throws Exception {
        try {
            if (originalRows == null) return;
            for (String run : ownedRuns) jdbc.update("DELETE FROM extraction_runs WHERE run_id=?", run);
            for (String version : ownedVersions) {
                jdbc.update("DELETE FROM source_reviews WHERE document_version_id=?", version);
                jdbc.update("DELETE FROM source_checks WHERE document_version_id=? ORDER BY checked_at DESC", version);
                jdbc.update("DELETE FROM document_versions WHERE document_version_id=?", version);
            }
            for (String document : ownedDocuments) jdbc.update("DELETE FROM documents WHERE document_id=?", document);
            for (String hash : ownedBatchHashes) jdbc.update("DELETE FROM import_batches WHERE source_kind='source' AND schema_version='source-import-v1' AND input_sha256=?", hash);
            assertThat(CitizenNoticeFixtures.rows(jdbc)).as("시험 소유 행만 정리하고 모든 기존 행을 보존한다").isEqualTo(originalRows);
        } finally { ExtractionArchiveReaderTest.unseal(root); }
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void citizenSuccessAndFailedD05ReplayAndReportKeepAllBytesWithoutCreatingReviewOrPublicRows(boolean failed) throws Exception {
        byte[] output = null;
        if (failed) { output = new byte[5 * 1024 * 1024 + 1]; Arrays.fill(output, (byte) 0xff); }
        var fixture = CitizenExtractionArchiveTest.fixture(root.toRealPath(), output);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM extraction_runs WHERE run_id=?", Long.class, fixture.run())).isZero();
        ownedRuns.add(fixture.run());
        JsonNode input = mapper.readTree(fixture.input().toFile());
        var source = registerSource(input);
        Path raw = root.resolve(source.path("documents").get(0).path("raw_asset_path").asText());
        byte[] originalSource = Files.readAllBytes(raw);
        var beforeRegistration = CitizenNoticeFixtures.rows(jdbc);
        var sourceRows = CitizenNoticeFixtures.rows(jdbc); sourceRows.remove("extraction_runs");
        var receipt = CitizenExtractionArchiveTest.importManual(archives, fixture);
        assertThat(receipt.path("status").asText()).isEqualTo(failed ? "failed" : "validated");
        var registered = extractions.importRun(fixture.run(), fixture.archive(), "synthetic-citizen-registrant");
        assertThat(registered.alreadyRegistered()).isFalse(); assertThat(registered.reviewRequired()).isTrue();
        var row = jdbc.queryForMap("SELECT * FROM extraction_runs WHERE run_id=?", fixture.run());
        assertThat(row.get("schema_version")).isEqualTo("extract-citizen-v1");
        assertThat(row.get("prompt_version")).isEqualTo(CitizenExtractionArchiveTest.PROMPT_LABEL);
        assertThat(row.get("metadata_json")).isEqualTo(Files.readString(fixture.metadata()));
        assertThat(row.get("status")).isEqualTo(failed ? "failed" : "validated");
        Path stored = Path.of((String) row.get("raw_ref"));
        CitizenExtractionArchiveTest.assertArtifacts(fixture, stored, receipt);
        assertThat(row.get("output_sha256")).isEqualTo(ReviewedImportReader.sha256(Files.readAllBytes(fixture.attempts().getFirst().output())));
        var afterRegistration = CitizenNoticeFixtures.rows(jdbc); var archiveBefore = CitizenExtractionArchiveTest.tree(stored);
        assertThat(afterRegistration.get("extraction_runs")).containsAll(beforeRegistration.get("extraction_runs"))
                .hasSize(beforeRegistration.get("extraction_runs").size() + 1);
        assertThat(extractions.importRun(fixture.run(), fixture.archive(), "synthetic-retry").alreadyRegistered()).isTrue();
        assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(afterRegistration);
        assertThat(CitizenExtractionArchiveTest.tree(stored)).isEqualTo(archiveBefore);

        var report = reports.build(UUID.fromString(input.path("document_version_id").asText()), root, null);
        assertThat(report.path("events")).isEmpty();
        assertThat(report.path("extractions")).hasSize(1);
        var extraction = report.path("extractions").get(0);
        assertThat(extraction.path("archive_validation").path("status").asText()).isEqualTo("valid");
        assertThat(extraction.path("database_validation").path("status").asText()).isEqualTo("valid");
        assertThat(extraction.path("metadata").path("schema_version").asText()).isEqualTo("extract-citizen-v1");
        var artifacts = extraction.path("artifacts");
        assertThat(reportBytes(artifacts.path("metadata.json"))).isEqualTo(Files.readAllBytes(fixture.metadata()));
        assertThat(reportBytes(artifacts.path("attempt-1.prompt"))).isEqualTo(Files.readAllBytes(fixture.attempts().getFirst().prompt()));
        byte[] archivedOutput = Files.readAllBytes(fixture.attempts().getFirst().output());
        assertThat(reportBytes(artifacts.path("attempt-1.output"))).isEqualTo(archivedOutput);
        if (!failed) {
            var parsed = mapper.readTree(reportBytes(artifacts.path("attempt-1.output")));
            assertThat(parsed.path("schema_version").asText()).isEqualTo("extract-citizen-v1");
            assertThat(parsed.path("items")).isNotEmpty(); assertThat(parsed.path("evidence")).isNotEmpty();
        }
        assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(afterRegistration);
        assertThat(CitizenExtractionArchiveTest.tree(stored)).isEqualTo(archiveBefore);
        assertThat(Files.readAllBytes(raw)).isEqualTo(originalSource);
        var protectedRows = CitizenNoticeFixtures.rows(jdbc); protectedRows.remove("extraction_runs");
        assertThat(protectedRows).isEqualTo(sourceRows);

        assertThatThrownBy(() -> runs.referenceDirectory(fixture.run())).isInstanceOf(ExtractionException.class);
        var projection = mapper.createObjectNode(); projection.putObject("parent").put("run_id", fixture.run());
        var unsupportedHandoff = new VerifiedHandoff(root, projection, null, null, null);
        assertThatThrownBy(() -> runs.handoffParentDirectory(fixture.run(), unsupportedHandoff)).isInstanceOf(ExtractionException.class);
        assertThat(CitizenNoticeFixtures.rows(jdbc)).isEqualTo(afterRegistration);
    }

    private ObjectNode registerSource(JsonNode input) throws Exception {
        var source = (ObjectNode) mapper.readTree(Path.of("examples/source-import.json").toFile());
        var document = (ObjectNode) source.path("documents").get(0);
        document.put("document_id", UUID.randomUUID().toString());
        for (String field : List.of("document_version_id", "title", "published_date")) document.set(field, input.path(field));
        document.set("block_index", input.path("blocks"));
        var blocks = new ArrayList<String>(); input.path("blocks").forEach(block -> blocks.add(block.path("text").asText()));
        byte[] bytes = String.join("\n", blocks).getBytes(StandardCharsets.UTF_8); String filename = UUID.randomUUID() + ".txt";
        Files.write(root.resolve(filename), bytes);
        document.put("raw_asset_path", filename).put("raw_sha256", ReviewedImportReader.sha256(bytes)).put("cleaned_text", new String(bytes, StandardCharsets.UTF_8))
                .put("text_sha256", ReviewedImportReader.sha256(bytes)).put("preprocessing_version", "fixture-nfc-v1").put("use_review", "pending")
                .put("check_result", "unchecked").putNull("latest_check_attempt_at").putNull("last_verified_at").putArray("checks");
        var batch = imports.read(source.toString().getBytes(StandardCharsets.UTF_8), root);
        String documentId = document.path("document_id").asText(), versionId = document.path("document_version_id").asText();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM documents WHERE document_id=?", Long.class, documentId)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM document_versions WHERE document_version_id=?", Long.class, versionId)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM import_batches WHERE source_kind='source' AND schema_version='source-import-v1' AND input_sha256=?", Long.class, batch.inputSha256())).isZero();
        ownedDocuments.add(documentId); ownedVersions.add(versionId); ownedBatchHashes.add(batch.inputSha256());
        importer.importBatch(batch, "synthetic-source-registrant");
        return source;
    }

    private byte[] reportBytes(JsonNode artifact) {
        assertThat(artifact.path("validation").path("status").asText()).isEqualTo("valid");
        return artifact.path("encoding").asText().equals("base64") ? Base64.getDecoder().decode(artifact.path("base64").asText())
                : artifact.path("text").asText().getBytes(StandardCharsets.UTF_8);
    }
}
