package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.*;

class CitizenExtractionArchiveTest {
    static final String PROMPT_LABEL = "supplied-manual-label-without-template-assertion";
    static final ObjectMapper JSON = new ObjectMapper();
    @TempDir Path root;

    @AfterEach void unsealOwnedFiles() throws Exception { ExtractionArchiveReaderTest.unseal(root); }

    @Test
    void readsActualCitizenManualArchiveAndPreservesSuppliedPromptLabel() throws Exception {
        var fixture = fixture(root.toRealPath(), (byte[]) null);
        var reader = reader();
        var receipt = importManual(reader, fixture);
        assertThat(receipt.path("status").asText()).isEqualTo("validated");
        var frozen = reader.read(fixture.run(), fixture.archive());
        assertThat(frozen.metadata().path("schema_version").asText()).isEqualTo("extract-citizen-v1");
        assertThat(frozen.metadata().path("prompt_version").asText()).isEqualTo(PROMPT_LABEL);
        assertThat(frozen.metadataJson().getBytes(StandardCharsets.UTF_8)).isEqualTo(Files.readAllBytes(fixture.metadata()));
        assertArtifacts(fixture, frozen.directory(), frozen.receipt());
        var before = tree(frozen.directory());
        var sealed = reader.readSealed(fixture.run(), frozen.directory().getParent());
        assertThat(sealed.receiptJson()).isEqualTo(frozen.receiptJson());
        assertThat(tree(frozen.directory())).isEqualTo(before);
        assertThat(importManual(reader, fixture)).isEqualTo(receipt);
    }

    @Test
    void actualCitizenFailureKeepsInvalidUtf8EmptyAndOverFiveMiBOutputInSealedArchive() throws Exception {
        byte[] large = new byte[5 * 1024 * 1024 + 1]; Arrays.fill(large, (byte) 0xff);
        var fixture = fixture(root.toRealPath(), new byte[0], new byte[] {(byte) 0xff, 0}, large);
        var receipt = importManual(reader(), fixture);
        assertThat(receipt.path("status").asText()).isEqualTo("failed");
        assertThat(receipt.path("attempts")).hasSize(3).allSatisfy(attempt -> assertThat(attempt.path("status").asText()).isEqualTo("failed"));
        var frozen = reader().read(fixture.run(), fixture.archive());
        assertThat(frozen.status()).isEqualTo("failed");
        assertArtifacts(fixture, frozen.directory(), receipt);
        assertThat(Files.readAllBytes(frozen.directory().resolve("attempt-3.output"))).isEqualTo(large);
        assertThat(reader().readSealed(fixture.run(), frozen.directory().getParent()).status()).isEqualTo("failed");
    }

    @Test
    void citizenMetadataWithLegacyOutputIsArchivedAsFailureWithoutChoosingOutputFamily() throws Exception {
        var fixture = fixture(root.toRealPath(), (byte[]) null);
        var legacy = (ObjectNode) JSON.readTree(PythonProbe.REPO.resolve("contracts/examples/ai-extraction.json").toFile());
        legacy.put("document_version_id", JSON.readTree(fixture.input().toFile()).path("document_version_id").asText());
        Files.writeString(fixture.attempts().getFirst().output(), legacy.toString());
        var receipt = importManual(reader(), fixture);
        assertThat(receipt.path("status").asText()).isEqualTo("failed");
        var frozen = reader().read(fixture.run(), fixture.archive());
        assertArtifacts(fixture, frozen.directory(), receipt);
    }

    @Test
    void citizenManualArchiveStillRejectsChangedSealedOutputAndWritableMetadata() throws Exception {
        var fixture = fixture(root.toRealPath(), (byte[]) null); importManual(reader(), fixture);
        var frozen = reader().read(fixture.run(), fixture.archive());
        Path metadata = frozen.directory().resolve("metadata.json");
        Files.setPosixFilePermissions(metadata, PosixFilePermissions.fromString("rw-------"));
        invalid(() -> reader().readSealed(fixture.run(), frozen.directory().getParent()));
        Files.setPosixFilePermissions(metadata, PosixFilePermissions.fromString("r--------"));
        Path output = frozen.directory().resolve("attempt-1.output");
        Files.setPosixFilePermissions(output, PosixFilePermissions.fromString("rw-------")); Files.writeString(output, "변조한 합성 출력");
        Files.setPosixFilePermissions(output, PosixFilePermissions.fromString("r--------"));
        invalid(() -> reader().readSealed(fixture.run(), frozen.directory().getParent()));
    }

    @Test
    void rejectsCitizenApiPacketEvenWhenHelperClaimsSealedSuccess() throws Exception {
        var fixture = fixture(root.toRealPath(), (byte[]) null); importManual(reader(), fixture);
        var frozen = reader().read(fixture.run(), fixture.archive()); Path directory = frozen.directory();
        ExtractionArchiveReaderTest.unseal(directory);
        var metadata = (ObjectNode) JSON.readTree(frozen.metadataJson()); metadata.put("execution_mode", "api");
        byte[] metadataBytes = metadata.toString().getBytes(StandardCharsets.UTF_8);
        Files.write(directory.resolve("metadata.json"), metadataBytes);
        var receipt = (ObjectNode) frozen.receipt().deepCopy(); receipt.put("execution_mode", "api");
        String hash = ReviewedImportReader.sha256(metadataBytes);
        receipt.put("metadata_sha256", hash);
        ((ObjectNode) receipt.path("artifacts").path("metadata.json")).put("size", metadataBytes.length).put("sha256", hash);
        for (String suffix : List.of("response", "exchange")) {
            byte[] bytes = "{}".getBytes(StandardCharsets.UTF_8); String name = "attempt-1." + suffix;
            Files.write(directory.resolve(name), bytes);
            ((ObjectNode) receipt.path("artifacts")).putObject(name).put("size", bytes.length).put("sha256", ReviewedImportReader.sha256(bytes));
        }
        Files.writeString(directory.resolve("receipt.json"), receipt.toString());
        try (var files = Files.list(directory)) {
            for (Path file : files.toList()) Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("r--------"));
        }
        Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("r-x------"));
        var packet = JSON.createObjectNode().put("protocol_version", "extraction-registration-v1").put("snapshot_ref", fixture.run()); packet.set("receipt", receipt);
        var helper = new ExtractionArchiveReaderTest(); helper.root = root;
        Path probe = helper.probe("print(" + JSON.writeValueAsString(packet.toString()) + ")");
        var reader = new ExtractionArchiveReader(new ReviewedImportReader(), PythonProbe.PYTHON, probe.toString(), 10_000);
        invalid(() -> reader.readSealed(fixture.run(), directory.getParent()));
    }

    @ParameterizedTest
    @ValueSource(strings = {"directory_555", "file_444", "extra_file", "extra_directory", "extra_symlink"})
    void rejectsNonExactCitizenSealAndUnlistedEntriesWithoutRepairEvenWhenHelperClaimsSuccess(String defect) throws Exception {
        var fixture = fixture(root.toRealPath(), (byte[]) null); importManual(reader(), fixture);
        var frozen = reader().read(fixture.run(), fixture.archive()); Path directory = frozen.directory();
        if (defect.equals("directory_555")) Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("r-xr-xr-x"));
        else if (defect.equals("file_444")) Files.setPosixFilePermissions(directory.resolve("metadata.json"), PosixFilePermissions.fromString("r--r--r--"));
        else {
            Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("rwx------"));
            Path extra = directory.resolve("unlisted");
            if (defect.equals("extra_file")) Files.writeString(extra, "합성 미등록 파일");
            else if (defect.equals("extra_directory")) Files.createDirectory(extra);
            else Files.createSymbolicLink(extra, fixture.input());
            Files.setPosixFilePermissions(directory, PosixFilePermissions.fromString("r-x------"));
        }
        var packet = JSON.createObjectNode().put("protocol_version", "extraction-registration-v1").put("snapshot_ref", fixture.run());
        packet.set("receipt", frozen.receipt());
        var helper = new ExtractionArchiveReaderTest(); helper.root = root;
        Path probe = helper.probe("print(" + JSON.writeValueAsString(packet.toString()) + ")");
        var reader = new ExtractionArchiveReader(new ReviewedImportReader(), PythonProbe.PYTHON, probe.toString(), 10_000);
        var before = tree(directory);
        try { invalid(() -> reader.readSealed(fixture.run(), directory.getParent())); }
        finally { assertThat(tree(directory)).isEqualTo(before); }
    }

    static ExtractionArchiveReader reader() { return new ExtractionArchiveReader(new ReviewedImportReader(), PythonProbe.PYTHON, PythonProbe.REPO.toString(), 20_000); }

    static JsonNode importManual(ExtractionArchiveReader reader, Fixture fixture) {
        return reader.importManual(fixture.run(), fixture.archive(), fixture.input(), fixture.metadata(), fixture.attempts());
    }

    static Fixture fixture(Path work, byte[]... suppliedOutputs) throws Exception {
        Files.createDirectories(work); work = work.toRealPath();
        String run = UUID.randomUUID().toString(), version = UUID.randomUUID().toString();
        var input = (ObjectNode) JSON.readTree(PythonProbe.REPO.resolve("contracts/examples/citizen-ai-input.json").toFile());
        input.put("document_version_id", version);
        Path inputFile = Files.writeString(work.resolve("input.json"), "\n" + input.toPrettyString() + "\n");
        var metadata = (ObjectNode) JSON.readTree(PythonProbe.REPO.resolve("processing/examples/extraction-metadata.json").toFile());
        metadata.put("run_id", run).put("document_version_id", version).put("attempts", suppliedOutputs.length)
                .put("schema_version", "extract-citizen-v1").put("prompt_version", PROMPT_LABEL);
        Path metadataFile = Files.writeString(work.resolve("metadata.json"), " \n" + metadata.toPrettyString() + "\n ");
        Path archive = Files.createDirectory(work.resolve("archive"));
        var attempts = new ArrayList<ExtractionArchiveReader.AttemptFiles>();
        for (int index = 0; index < suppliedOutputs.length; index++) {
            Path prompt = Files.writeString(work.resolve("prompt-" + index), "제공한 수동 prompt 전문 " + index + " 😀\r\n");
            byte[] raw = suppliedOutputs[index];
            if (raw == null) {
                var output = (ObjectNode) JSON.readTree(PythonProbe.REPO.resolve("contracts/examples/citizen-ai-extraction.json").toFile());
                output.put("document_version_id", version); raw = output.toString().getBytes(StandardCharsets.UTF_8);
            }
            attempts.add(new ExtractionArchiveReader.AttemptFiles(prompt, Files.write(work.resolve("output-" + index), raw)));
        }
        return new Fixture(run, archive, inputFile, metadataFile, List.copyOf(attempts));
    }

    static void assertArtifacts(Fixture fixture, Path directory, JsonNode receipt) throws Exception {
        var expected = new LinkedHashMap<String, Path>(); expected.put("input.json", fixture.input()); expected.put("metadata.json", fixture.metadata());
        for (int index = 0; index < fixture.attempts().size(); index++) {
            expected.put("attempt-" + (index + 1) + ".prompt", fixture.attempts().get(index).prompt());
            expected.put("attempt-" + (index + 1) + ".output", fixture.attempts().get(index).output());
        }
        assertThat(Files.getPosixFilePermissions(directory)).isEqualTo(PosixFilePermissions.fromString("r-x------"));
        for (var entry : expected.entrySet()) {
            byte[] bytes = Files.readAllBytes(entry.getValue()); Path file = directory.resolve(entry.getKey());
            assertThat(Files.readAllBytes(file)).isEqualTo(bytes);
            assertThat(Files.getPosixFilePermissions(file)).isEqualTo(PosixFilePermissions.fromString("r--------"));
            assertThat(receipt.path("artifacts").path(entry.getKey()).path("size").asLong()).isEqualTo(bytes.length);
            assertThat(receipt.path("artifacts").path(entry.getKey()).path("sha256").asText()).isEqualTo(ReviewedImportReader.sha256(bytes));
        }
    }

    static Map<String, String> tree(Path root) throws Exception {
        var result = new LinkedHashMap<String, String>();
        try (var files = Files.walk(root)) {
            for (Path file : files.sorted().toList()) result.put(root.relativize(file).toString(), PosixFilePermissions.toString(Files.getPosixFilePermissions(file))
                    + (Files.isRegularFile(file) ? ":" + ReviewedImportReader.sha256(Files.readAllBytes(file)) : ""));
        }
        return result;
    }

    private void invalid(org.assertj.core.api.ThrowableAssert.ThrowingCallable action) {
        assertThatThrownBy(action).isInstanceOfSatisfying(ExtractionException.class, error -> assertThat(error.code()).isEqualTo("EXTRACTION_ARCHIVE_INVALID"));
    }

    record Fixture(String run, Path archive, Path input, Path metadata, List<ExtractionArchiveReader.AttemptFiles> attempts) { }
}
