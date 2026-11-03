package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import kr.ac.myai.backend.extraction.ExtractionArchiveReader;
import kr.ac.myai.backend.extraction.ExtractionException;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationCommand;
import kr.ac.myai.backend.publication.PublicationCommandReader;
import kr.ac.myai.backend.service.ExtractionImportService;
import kr.ac.myai.backend.service.HumanHandoffImportService;
import kr.ac.myai.backend.service.PublicationService;
import kr.ac.myai.backend.service.ReviewedImportService;
import kr.ac.myai.backend.service.SnapshotExportService;
import kr.ac.myai.backend.service.SourceReviewService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.builder.SpringApplicationBuilder;
import org.springframework.boot.web.servlet.context.ServletWebServerApplicationContext;
import org.springframework.jdbc.core.JdbcTemplate;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.sql.ResultSetMetaData;
import java.sql.Types;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static kr.ac.myai.backend.SourceReviewFixtures.document;
import static kr.ac.myai.backend.SourceReviewFixtures.version;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class DatabaseRecoveryTest {
    private final ObjectMapper mapper = new ObjectMapper();
    @TempDir Path root;

    @AfterEach
    void unsealOnlyOwnedTemporaryMaterials() throws Exception {
        ExtractionArchiveReaderTest.unseal(root);
    }

    @Test
    void restoresAllRowsFrozenPathsAndPublicBehaviorOnANewServer() throws Exception {
        root = root.toRealPath();
        Files.setPosixFilePermissions(root, PosixFilePermissions.fromString("rwx------"));
        Path materials = directory(root.resolve("materials"));
        Path proof = proofDirectory();
        Path dump = proof.resolve("database.sql"), tar = proof.resolve("materials.tar");
        Path dataDump = proof.resolve("database-data.sql");
        JsonNode before, files, api;
        byte[] snapshot;
        Seed seed;
        try (var source = RecoveryDatabase.start(directory(root.resolve("source-db")));
             var target = RecoveryDatabase.start(directory(root.resolve("target-db")))) {
            assertThat(source.id()).isNotEqualTo(target.id());
            assertThat(source.jdbc().queryForObject("SELECT VERSION()", String.class)).isEqualTo("8.4.13");
            assertThat(target.jdbc().queryForObject("SELECT VERSION()", String.class)).isEqualTo("8.4.13");
            try (var application = application(source)) {
                seed = seed(application, materials);
                before = database(source.jdbc());
                populated(before);
                api = publicResponses(application, seed);
                snapshot = export(application, seed.snapshotId(), directory(proof.resolve("source-export")));
                files = fileTree(materials);
                frozenModes(source.jdbc(), seed);
            }
            // DB와 선택 원본의 공동 시점을 위해 앱의 모든 쓰기를 닫은 뒤 백업한다.
            assertThat(database(source.jdbc())).isEqualTo(before);
            source.dump(dump);
            source.dumpData(dataDump);
            Files.createFile(tar, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
            command(List.of("tar", "-cpf", tar.toString(), "-C", root.toString(), "materials"), proof, "tar-create");
            Files.setPosixFilePermissions(tar, PosixFilePermissions.fromString("rw-------"));
            write(proof.resolve("database-before.json"), before);
            write(proof.resolve("ddl-before.json"), rawDdl(source.jdbc(), before));
            write(proof.resolve("materials-before.json"), files);
            write(proof.resolve("api-before.json"), api);
            command(List.of(PythonProbe.PYTHON, "--version"), proof, "python-version");
            command(List.of("tar", "--version"), proof, "tar-version");
            write(proof.resolve("metadata.json"), metadata(source, target, seed, dump, tar, snapshot, materials));

            target.restore(dump);
            assertThat(database(target.jdbc())).isEqualTo(before);
            write(proof.resolve("ddl-after.json"), rawDdl(target.jdbc(), before));
            Path restoredDump = proof.resolve("database-restored.sql");
            target.dump(restoredDump);
            write(proof.resolve("dump-comparison.json"), mapper.createObjectNode()
                    .put("byte_equal", java.util.Arrays.equals(Files.readAllBytes(dump), Files.readAllBytes(restoredDump)))
                    .put("source_dump_sha256", sha(Files.readAllBytes(dump)))
                    .put("restored_dump_sha256", sha(Files.readAllBytes(restoredDump))));
            Path restoredDataDump = proof.resolve("database-data-restored.sql");
            target.dumpData(restoredDataDump);
            byte[] sourceData = Files.readAllBytes(dataDump), restoredData = Files.readAllBytes(restoredDataDump);
            assertThat(restoredData).isEqualTo(sourceData);
            write(proof.resolve("data-dump-comparison.json"), mapper.createObjectNode().put("byte_equal", true)
                    .put("source_data_dump_sha256", sha(sourceData)).put("restored_data_dump_sha256", sha(restoredData)));
            Path lost = root.resolve("lost-materials");
            Files.move(materials, lost);
            try (var application = application(target)) {
                assertThat(Files.exists(materials, LinkOption.NOFOLLOW_LINKS)).isFalse();
                assertThatThrownBy(() -> application.getBean(ExtractionImportService.class)
                        .importRun(seed.validatedRun(), seed.validatedArchive(), "synthetic-recovery-replay"))
                        .isInstanceOf(ExtractionException.class);
                assertThatThrownBy(() -> application.getBean(HumanHandoffImportService.class)
                        .importFile(seed.handoff().file(), materials, seed.handoff().directory(), "synthetic-recovery-replay"))
                        .isInstanceOf(ImportException.class);
                Path relocatedArchive = lost.resolve(materials.relativize(seed.validatedArchive()));
                assertThatThrownBy(() -> application.getBean(ExtractionImportService.class)
                        .importRun(seed.validatedRun(), relocatedArchive, "synthetic-recovery-replay"))
                        .isInstanceOfSatisfying(ExtractionException.class, ex -> assertThat(ex.code()).isEqualTo("EXTRACTION_CONFLICT"));
                Path relocatedHandoffFile = lost.resolve(materials.relativize(seed.handoff().file()));
                Path relocatedHandoffRoot = lost.resolve(materials.relativize(seed.handoff().directory()));
                assertThatThrownBy(() -> application.getBean(HumanHandoffImportService.class)
                        .importFile(relocatedHandoffFile, lost, relocatedHandoffRoot, "synthetic-recovery-replay"))
                        .isInstanceOfSatisfying(ImportException.class, ex -> assertThat(ex.code()).isEqualTo("IMPORT_VALIDATION_ERROR"));
                assertThat(database(target.jdbc())).isEqualTo(before);
                assertThat(fileTree(lost)).isEqualTo(files);
                write(proof.resolve("materials-relocated-after.json"), fileTree(lost));
                assertThat(publicResponses(application, seed)).isEqualTo(api);
                write(proof.resolve("api-without-materials.json"), publicResponses(application, seed));

                command(List.of("tar", "-xpf", tar.toString(), "-C", root.toString()), proof, "tar-restore");
                assertThat(materials.toRealPath()).isEqualTo(materials);
                assertThat(fileTree(materials)).isEqualTo(files);
                frozenModes(target.jdbc(), seed);
                verifyPrivateReplay(application, seed, materials);
                assertThat(database(target.jdbc())).isEqualTo(before);
                assertThat(fileTree(materials)).isEqualTo(files);
                assertThat(publicResponses(application, seed)).isEqualTo(api);
                assertThat(export(application, seed.snapshotId(), directory(proof.resolve("target-export")))).isEqualTo(snapshot);
                write(proof.resolve("database-after.json"), database(target.jdbc()));
                write(proof.resolve("materials-after.json"), fileTree(materials));
                write(proof.resolve("api-after.json"), publicResponses(application, seed));
            }
            try (var restarted = application(target)) {
                assertThat(database(target.jdbc())).isEqualTo(before);
                verifyPrivateReplay(restarted, seed, materials);
                assertThat(database(target.jdbc())).isEqualTo(before);
                assertThat(publicResponses(restarted, seed)).isEqualTo(api);
                assertThat(export(restarted, seed.snapshotId(), directory(proof.resolve("restart-export")))).isEqualTo(snapshot);
                write(proof.resolve("database-restarted.json"), database(target.jdbc()));
                write(proof.resolve("api-restarted.json"), publicResponses(restarted, seed));
                assertThat(fileTree(materials)).isEqualTo(files);
                write(proof.resolve("materials-restarted.json"), fileTree(materials));
            }
        }
        write(proof.resolve("cleanup.json"), mapper.createObjectNode().put("owned_databases_closed", true));
        try (var paths = Files.walk(proof)) {
            for (Path path : paths.toList())
                assertThat(PosixFilePermissions.toString(Files.getPosixFilePermissions(path)))
                        .isEqualTo(Files.isDirectory(path) ? "rwx------" : "rw-------");
        }
        write(proof.resolve("result.json"), mapper.createObjectNode().put("status", "passed")
                .put("synthetic", true).put("operator_backup_performed", false)
                .put("same_absolute_materials_root", materials.toString()).put("all_tables_equal", true)
                .put("missing_materials_reimport_rejected", true).put("public_http_and_export_equal", true)
                .put("restart_rows_unchanged", true).put("data_dump_bytes_equal", true)
                .put("relocated_materials_reimport_rejected", true));
        System.out.println("Synthetic database recovery proof: " + proof);
    }

    private ServletWebServerApplicationContext application(RecoveryDatabase database) {
        var application = new SpringApplicationBuilder(MyaiBackendApplication.class).web(WebApplicationType.SERVLET).profiles("public")
                .initializers(context -> assertThat(context.getEnvironment().getProperty("spring.datasource.url")).isEqualTo(database.url()))
                .run("--spring.datasource.url=" + database.url(), "--spring.datasource.username=" + database.username(),
                        "--spring.datasource.password=" + database.password(), "--server.address=127.0.0.1", "--server.port=0",
                        "--app.calculation.python-executable=" + PythonProbe.PYTHON,
                        "--app.calculation.workdir=" + PythonProbe.REPO, "--app.extraction.timeout-ms=10000",
                        "--app.calculation.timeout-ms=10000", "--spring.main.banner-mode=off");
        assertThat(application.getEnvironment().getProperty("spring.datasource.url")).isEqualTo(database.url());
        return (ServletWebServerApplicationContext) application;
    }

    private Seed seed(ServletWebServerApplicationContext application, Path materials) throws Exception {
        var jdbc = application.getBean(JdbcTemplate.class);
        var fixtures = new SourceReviewFixtures(materials, jdbc, application.getBean(ReviewedImportReader.class),
                application.getBean(ReviewedImportService.class));
        ObjectNode source = fixtures.source(false); fixtures.register(source);
        String validated = UUID.randomUUID().toString(), failed = UUID.randomUUID().toString();
        Path goodArchive = fixtures.archive(source, validated);
        Path failedArchive = fixtures.extraction.archive(source, failed, true);
        var extraction = application.getBean(ExtractionImportService.class);
        assertThat(extraction.importRun(validated, goodArchive, "synthetic-recovery-registrant").status()).isEqualTo("validated");
        assertThat(extraction.importRun(failed, failedArchive, "synthetic-recovery-registrant").status()).isEqualTo("failed");
        var handoff = fixtures.handoff(source, validated, goodArchive);
        var imported = application.getBean(HumanHandoffImportService.class)
                .importFile(handoff.file(), materials, handoff.directory(), "synthetic-recovery-reviewer");
        assertThat(imported.revisionIds()).hasSize(1);
        String revision = imported.revisionIds().getFirst();
        String event = jdbc.queryForObject("SELECT event_id FROM event_revisions WHERE revision_id=?", String.class, revision);
        var review = mapper.createObjectNode().put("schema_version", "source-review-v1").put("review_id", UUID.randomUUID().toString())
                .put("document_version_id", version(source)).put("expected_review_no", 0)
                .put("expected_text_sha256", document(source).path("text_sha256").asText())
                .put("use_review", "allowed").put("use_note", "합성 복구 시험 사용권 이력 😀").put("reason", "합성 이력 백업 검증");
        review.putObject("check").put("checked_at", "2026-11-03T01:00:00.123456Z").put("result", "verified")
                .put("text_sha256", document(source).path("text_sha256").asText()).put("note", "합성 원문 대조 확인");
        application.getBean(SourceReviewService.class).review(write(materials.resolve("source-review.json"), review), materials, "synthetic-recovery-reviewer");
        JsonNode payload = mapper.readTree(jdbc.queryForObject("SELECT payload_json FROM event_revisions WHERE revision_id=?", String.class, revision));
        var evidence = new ArrayList<String>(); payload.path("evidence").forEach(item -> evidence.add(item.path("evidence_id").asText()));
        var publication = application.getBean(PublicationService.class);
        var approved = publication.execute(new PublicationCommand.Decision("publication-command-v1", "approve", "합성 원문 대조 승인",
                UUID.fromString(event), 1, evidence), materials, "synthetic-recovery-approver");
        var request = (ObjectNode) mapper.readTree(Path.of("examples/publish.json").toFile());
        String caseId = UUID.randomUUID().toString();
        request.put("mode", "replay").put("case_id", caseId).put("anchor_date", "2026-11-03")
                .put("reference_instant", "2026-11-03T00:00:00Z").put("knowledge_cutoff", "2026-11-03T00:00:00Z")
                .put("history_fidelity", "reconstructed").putNull("expected_head_version");
        for (var point : request.path("points")) ((ObjectNode) point).put("point_id", UUID.randomUUID().toString());
        request.putArray("revision_ids").add(approved.revisionId());
        var commands = application.getBean(PublicationCommandReader.class);
        String first = publication.execute(commands.read(write(materials.resolve("publish-first.json"), request)), materials, "synthetic-recovery-publisher").snapshotId();
        request.put("expected_head_version", 0);
        publication.execute(commands.read(write(materials.resolve("publish-second.json"), request)), materials, "synthetic-recovery-publisher");
        publication.execute(new PublicationCommand.Rollback("publication-command-v1", "rollback", "합성 공개 이력 복구", "replay",
                UUID.fromString(caseId), UUID.fromString(first), 1L), null, "synthetic-recovery-publisher");
        var query = (ObjectNode) mapper.readTree(PythonProbe.REPO.resolve("contracts/examples/matches-request.json").toFile());
        query.put("mode", "replay").put("case_id", caseId).put("snapshot_id", first)
                .put("point_id", request.path("points").get(0).path("point_id").asText()).put("selection", "needs_check");
        return new Seed(validated, failed, goodArchive, failedArchive, handoff, revision, event, caseId, first, query);
    }

    private void verifyPrivateReplay(ServletWebServerApplicationContext application, Seed seed, Path materials) {
        var jdbc = application.getBean(JdbcTemplate.class);
        for (String run : List.of(seed.validatedRun(), seed.failedRun())) {
            Path stored = Path.of(jdbc.queryForObject("SELECT raw_ref FROM extraction_runs WHERE run_id=?", String.class, run));
            assertThat(application.getBean(ExtractionArchiveReader.class).read(run, stored.getParent()).directory()).isEqualTo(stored);
            assertThat(application.getBean(ExtractionImportService.class).importRun(run, stored.getParent(), "synthetic-recovery-replay")
                    .alreadyRegistered()).isTrue();
        }
        var replay = application.getBean(HumanHandoffImportService.class)
                .importFile(seed.handoff().file(), materials, seed.handoff().directory(), "synthetic-recovery-replay");
        assertThat(replay.alreadyImported()).isTrue();
        assertThat(replay.revisionIds()).containsExactly(seed.handoffRevision());
    }

    private JsonNode publicResponses(ServletWebServerApplicationContext application, Seed seed) throws Exception {
        String base = "http://127.0.0.1:" + application.getWebServer().getPort();
        var responses = mapper.createObjectNode();
        responses.set("config", http(base + "/api/v1/config?mode=replay&case_id=" + seed.caseId(), null));
        responses.set("detail", http(base + "/api/v1/events/" + seed.eventId() + "?snapshot_id=" + seed.snapshotId(), null));
        responses.set("matches", http(base + "/api/v1/matches", seed.query()));
        for (String name : List.of("config", "detail", "matches")) {
            var response = (ObjectNode) responses.path(name);
            assertThat(response.path("snapshot_id").asText()).isEqualTo(seed.snapshotId());
            assertThat(Instant.parse(response.path("generated_at").asText())).isNotNull();
            response.remove("generated_at");
        }
        var config = (ObjectNode) responses.path("config").path("data");
        assertThat(Instant.parse(config.path("server_now").asText())).isNotNull();
        config.remove("server_now");
        assertThat(responses.path("detail").path("data").path("event").path("event_id").asText()).isEqualTo(seed.eventId());
        assertThat(responses.path("matches").path("data").path("items")).isNotEmpty();
        return responses;
    }

    private JsonNode http(String url, ObjectNode body) throws Exception {
        var request = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(20));
        if (body == null) request.GET();
        else request.header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(body.toString()));
        try (var client = HttpClient.newHttpClient()) {
            var response = client.send(request.build(), HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            assertThat(response.statusCode()).as("HTTP %s: %s", url, response.body()).isEqualTo(200);
            return mapper.readTree(response.body());
        }
    }

    private byte[] export(ServletWebServerApplicationContext application, String snapshot, Path directory) throws Exception {
        var result = application.getBean(SnapshotExportService.class).export(UUID.fromString(snapshot), directory);
        Path file = directory.resolve(result.fileName());
        Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("rw-------"));
        byte[] bytes = Files.readAllBytes(file);
        assertThat(sha(bytes)).isEqualTo(result.checksum());
        return bytes;
    }

    private JsonNode database(JdbcTemplate jdbc) {
        var state = mapper.createObjectNode(); var tables = state.putObject("tables");
        for (String table : jdbc.queryForList("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME", String.class)) {
            assertThat(table).matches("[A-Za-z0-9_]+");
            var data = tables.putObject(table);
            String ddl = jdbc.queryForMap("SHOW CREATE TABLE `" + table + "`").get("Create Table").toString();
            var columnSchema = jdbc.queryForList(
                    "SELECT * FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=? ORDER BY ORDINAL_POSITION", table);
            data.put("ddl", schemaDdl(ddl, columnSchema));
            data.set("column_schema", mapper.valueToTree(columnSchema));
            jdbc.query("SELECT * FROM `" + table + "`", result -> {
                ResultSetMetaData metadata = result.getMetaData();
                var columns = data.putArray("columns");
                for (int i = 1; i <= metadata.getColumnCount(); i++) columns.addObject().put("name", metadata.getColumnName(i))
                        .put("type", metadata.getColumnTypeName(i)).put("precision", metadata.getPrecision(i))
                        .put("scale", metadata.getScale(i)).put("nullable", metadata.isNullable(i));
                var rows = new ArrayList<JsonNode>();
                while (result.next()) {
                    ArrayNode row = mapper.createArrayNode();
                    for (int i = 1; i <= metadata.getColumnCount(); i++) {
                        if (result.getObject(i) == null) row.addNull();
                        else if (List.of(Types.BINARY, Types.VARBINARY, Types.LONGVARBINARY, Types.BLOB).contains(metadata.getColumnType(i)))
                            row.add(Base64.getEncoder().encodeToString(result.getBytes(i)));
                        else row.add(result.getString(i));
                    }
                    rows.add(row);
                }
                rows.sort(Comparator.comparing(JsonNode::toString));
                var output = data.putArray("rows"); rows.forEach(output::add);
                return null;
            });
        }
        return state;
    }

    @Test
    void normalizesOnlyRedundantColumnCharset() {
        var columns = List.<Map<String, Object>>of(Map.of("COLUMN_NAME", "note", "COLUMN_TYPE", "varchar(255)",
                "CHARACTER_SET_NAME", "utf8mb4", "COLLATION_NAME", "utf8mb4_0900_as_cs"));
        String phrase = "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs";
        String implicit = "CREATE TABLE `example` (\n  `note` varchar(255) COLLATE utf8mb4_0900_as_cs DEFAULT '" + phrase
                + "',\n  CONSTRAINT `literal_check` CHECK (`note` <> '" + phrase + "')\n)";
        String explicit = implicit.replace("`note` varchar(255) COLLATE", "`note` varchar(255) CHARACTER SET utf8mb4 COLLATE");
        assertThat(schemaDdl(explicit, columns)).isEqualTo(implicit);
        assertThat(schemaDdl(implicit, columns)).isEqualTo(implicit);
        String differentType = explicit.replace("varchar(255)", "varchar(256)");
        assertThat(schemaDdl(differentType, columns)).isEqualTo(differentType);
        String differentCollation = explicit.replace("utf8mb4_0900_as_cs", "utf8mb4_0900_ai_ci");
        assertThat(schemaDdl(differentCollation, columns)).isEqualTo(differentCollation);
        var differentMetadata = List.<Map<String, Object>>of(Map.of("COLUMN_NAME", "note", "COLUMN_TYPE", "varchar(255)",
                "CHARACTER_SET_NAME", "ascii", "COLLATION_NAME", "ascii_bin"));
        assertThat(schemaDdl(explicit, differentMetadata)).isEqualTo(explicit);
    }

    private String schemaDdl(String ddl, List<Map<String, Object>> columns) {
        return String.join("\n", ddl.lines().map(line -> {
            for (var column : columns) {
                if (!"utf8mb4".equals(column.get("CHARACTER_SET_NAME"))
                        || !"utf8mb4_0900_as_cs".equals(column.get("COLLATION_NAME"))) continue;
                String prefix = "  `" + column.get("COLUMN_NAME").toString().replace("`", "``") + "` " + column.get("COLUMN_TYPE");
                // MySQL의 동일 charset 명시만 접고 DEFAULT·CHECK 문자열 등 나머지 DDL은 그대로 비교한다.
                if (line.startsWith(prefix + " CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_as_cs"))
                    return prefix + line.substring((prefix + " CHARACTER SET utf8mb4").length());
            }
            return line;
        }).toList());
    }

    private JsonNode rawDdl(JdbcTemplate jdbc, JsonNode state) {
        var ddl = mapper.createObjectNode();
        state.path("tables").fieldNames().forEachRemaining(table ->
                ddl.put(table, jdbc.queryForMap("SHOW CREATE TABLE `" + table + "`").get("Create Table").toString()));
        return ddl;
    }

    private void populated(JsonNode state) {
        for (String table : List.of("flyway_schema_history", "documents", "document_versions", "source_checks", "source_reviews",
                "extraction_runs", "events", "event_revisions", "review_audits", "snapshots", "snapshot_revisions", "publication_heads", "import_batches", "publication_audits"))
            assertThat(state.path("tables").path(table).path("rows")).as(table).isNotEmpty();
        assertThat(state.path("tables").path("extraction_runs").path("rows")).hasSize(2);
        assertThat(state.path("tables").path("publication_audits").path("rows")).hasSize(3);
    }

    private JsonNode fileTree(Path base) throws Exception {
        var manifest = mapper.createArrayNode();
        try (var paths = Files.walk(base)) {
            for (Path path : paths.sorted().toList()) {
                assertThat(Files.isSymbolicLink(path)).isFalse();
                var item = manifest.addObject().put("path", base.relativize(path).toString())
                        .put("mode", PosixFilePermissions.toString(Files.getPosixFilePermissions(path)))
                        .put("kind", Files.isDirectory(path) ? "directory" : "file");
                if (Files.isRegularFile(path)) item.put("size", Files.size(path)).put("sha256", sha(Files.readAllBytes(path)));
            }
        }
        return manifest;
    }

    private void frozenModes(JdbcTemplate jdbc, Seed seed) throws Exception {
        for (String run : List.of(seed.validatedRun(), seed.failedRun())) {
            Path stored = Path.of(jdbc.queryForObject("SELECT raw_ref FROM extraction_runs WHERE run_id=?", String.class, run));
            assertThat(PosixFilePermissions.toString(Files.getPosixFilePermissions(stored))).isEqualTo("r-x------");
            try (var paths = Files.list(stored)) {
                for (Path file : paths.toList()) assertThat(PosixFilePermissions.toString(Files.getPosixFilePermissions(file))).isEqualTo("r--------");
            }
        }
        try (var paths = Files.walk(seed.handoff().image())) {
            for (Path path : paths.toList()) assertThat(PosixFilePermissions.toString(Files.getPosixFilePermissions(path)))
                    .isEqualTo(Files.isDirectory(path) ? "r-x------" : "r--------");
        }
    }

    private JsonNode metadata(RecoveryDatabase source, RecoveryDatabase target, Seed seed, Path dump, Path tar, byte[] snapshot, Path materials) throws Exception {
        var metadata = mapper.createObjectNode().put("synthetic", true).put("operator_backup_performed", false)
                .put("materials_absolute_root", materials.toString()).put("source_container_id", source.id()).put("target_container_id", target.id())
                .put("mysql_version", source.jdbc().queryForObject("SELECT VERSION()", String.class))
                .put("java_version", System.getProperty("java.version")).put("spring_boot_version", org.springframework.boot.SpringBootVersion.getVersion())
                .put("python_version", Files.readString(dump.getParent().resolve("python-version.stdout")).strip())
                .put("tar_version", Files.readString(dump.getParent().resolve("tar-version.stdout")).strip())
                .put("snapshot_id", seed.snapshotId()).put("snapshot_sha256", sha(snapshot))
                .put("dump_sha256", sha(Files.readAllBytes(dump))).put("tar_sha256", sha(Files.readAllBytes(tar)))
                .put("data_dump_sha256", sha(Files.readAllBytes(dump.resolveSibling("database-data.sql"))));
        metadata.put("reference_instant", "2026-11-03T00:00:00Z").put("git_code_sha", codeVersion());
        metadata.put("ddl_display_normalization", "Column CHARACTER SET utf8mb4 before COLLATE utf8mb4_0900_as_cs; full information_schema.COLUMNS and raw DDL retained");
        metadata.put("internal_request_id", "production-generated; each response ID and input SHA checked by PythonCalculator");
        metadata.putArray("normalized_http_fields").add("*.generated_at").add("config.data.server_now");
        var versions = metadata.putArray("flyway_versions");
        source.jdbc().queryForList("SELECT version,checksum,success FROM flyway_schema_history ORDER BY installed_rank").forEach(versions::addPOJO);
        Path code = Path.of("src/test/java/kr/ac/myai/backend/DatabaseRecoveryTest.java");
        metadata.put("recovery_test_sha256", sha(Files.readAllBytes(code)));
        var migrations = metadata.putObject("migration_sha256");
        try (var paths = Files.list(Path.of("src/main/resources/db/migration"))) {
            for (Path path : paths.sorted().toList()) migrations.put(path.getFileName().toString(), sha(Files.readAllBytes(path)));
        }
        return metadata;
    }

    private String codeVersion() throws Exception {
        var process = new ProcessBuilder("git", "rev-parse", "HEAD").directory(PythonProbe.REPO.toFile()).start();
        try {
            assertThat(process.waitFor(5, TimeUnit.SECONDS)).isTrue();
            assertThat(process.exitValue()).isZero();
            String version = new String(process.getInputStream().readAllBytes(), StandardCharsets.US_ASCII).strip();
            assertThat(version).matches("[0-9a-f]{40}");
            return version;
        } finally { if (process.isAlive()) process.destroyForcibly(); }
    }

    private Path proofDirectory() throws Exception {
        String configured = System.getenv("MYAI_RECOVERY_PROOF_ROOT");
        Path base = configured == null || configured.isBlank() ? Path.of("build/recovery-proof") : Path.of(configured);
        Files.createDirectories(base, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        return directory(base.toRealPath().resolve(UUID.randomUUID().toString()));
    }

    private Path directory(Path path) throws Exception {
        return Files.createDirectory(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
    }

    private Path write(Path path, JsonNode value) throws Exception {
        Files.createFile(path, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        return Files.writeString(path, mapper.writerWithDefaultPrettyPrinter().writeValueAsString(value), StandardOpenOption.WRITE);
    }

    private void command(List<String> arguments, Path proof, String name) throws Exception {
        Path stdout = proof.resolve(name + ".stdout"), stderr = proof.resolve(name + ".stderr");
        Files.createFile(stdout, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        Files.createFile(stderr, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        Process process = new ProcessBuilder(arguments).redirectInput(ProcessBuilder.Redirect.from(Path.of("/dev/null").toFile()))
                .redirectOutput(stdout.toFile()).redirectError(stderr.toFile()).start();
        try {
            assertThat(process.waitFor(30, TimeUnit.SECONDS)).as(name + " timeout").isTrue();
            assertThat(process.exitValue()).as(name + ": " + Files.readString(stderr)).isZero();
        } finally {
            process.descendants().forEach(ProcessHandle::destroyForcibly);
            if (process.isAlive()) process.destroyForcibly();
        }
    }

    private String sha(byte[] bytes) { return ReviewedImportReader.sha256(bytes); }

    private record Seed(String validatedRun, String failedRun, Path validatedArchive, Path failedArchive,
                        SourceReviewFixtures.Handoff handoff, String handoffRevision, String eventId,
                        String caseId, String snapshotId, ObjectNode query) { }
}
