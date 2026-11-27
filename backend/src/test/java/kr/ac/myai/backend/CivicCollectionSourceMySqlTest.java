package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import kr.ac.myai.backend.importing.ImportException;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.service.ReviewedImportService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.*;

// 도로 공사·시청 공지·안성배움e 공지·시청 공지 매체 수집 묶음이 Python D03 준비를 거쳐 기존 Java 등록 경로로 들어가는지 확인한다.
@SpringBootTest
@ActiveProfiles("public")
@EnabledIfEnvironmentVariable(named = "MYAI_MYSQL_TESTS", matches = "true")
class CivicCollectionSourceMySqlTest {
    static final String DOWNLOADED_AT = "2026-11-20T04:00:00Z";
    static final byte[] PNG = "\u0089PNG\r\n\u001a\nsynthetic".getBytes(StandardCharsets.ISO_8859_1);
    // 수집 경로가 쓰는 공식 원문 주소. Python d03.prepare가 수집 기록의 주소와 다시 대조한다.
    static final List<Source> SOURCES = List.of(
            new Source("road", "road-trial", "9", "https://www.anseong.go.kr/depart/roadConstruction/view.do?idx=9&mId=0901020100&state=1",
                    "collection-road-works/road-trial/detail-9.html", "official-web-road-works"),
            new Source("board", "board-trial", "9", "https://www.anseong.go.kr/portal/bbs/view.do?bIdx=9&mId=0501010000&ptIdx=16",
                    "collection-boards/board-trial/detail-9.html", "official-web-board"),
            new Source("media", "city-image", "1", "https://www.anseong.go.kr/portal/bbs/view.do?bIdx=203043&mId=0501010000&ptIdx=16",
                    "collection-media/city-image/media.png", "official-web-media-manual"),
            // 안성배움e는 contextPath /edu·ptIdx=300이라 시청(루트·16)과 다른 상세 주소로 등록되어야 한다.
            new Source("board", "edu-trial", "3838", "https://www.anseong.go.kr/edu/portal/bbs/view.do?bIdx=3838&mId=0901040000&ptIdx=300",
                    "collection-boards/edu-trial/detail-3838.html", "official-web-board"));

    record Source(String kind, String archive, String asset, String url, String rawRef, String method) {}

    @Autowired JdbcTemplate jdbc;
    @Autowired ReviewedImportReader reader;
    @Autowired ReviewedImportService importer;
    @TempDir Path root;
    final ObjectMapper mapper = new ObjectMapper();

    @Test
    void roadBoardAndCityMediaOriginalsRegisterAsPendingSourcesThroughPython() throws Exception {
        Path privateRoot = root.toRealPath();
        Files.write(privateRoot.resolve("download.png"), PNG);
        List<String> versionIds = SOURCES.stream().map(source -> UUID.randomUUID().toString()).toList();
        List<String> reviewedTexts = SOURCES.stream().map(source -> "사람 검토 " + source.kind() + " 합성 본문 😀\n확인한 내용").toList();
        for (int i = 0; i < SOURCES.size(); i++) {
            var source = SOURCES.get(i);
            var review = mapper.createObjectNode().put("archive_kind", source.kind())
                    .put("archive_name", source.archive()).put("data_kind", "synthetic");
            review.putArray("documents").addObject().put("asset", source.asset()).put("official_url", source.url())
                    .put("document_id", UUID.randomUUID().toString()).put("document_version_id", versionIds.get(i))
                    .put("version_no", 1).put("publisher", "합성 기관").put("title", "검토한 합성 " + source.kind())
                    .putNull("published_date").putNull("official_number").putNull("collected_at")
                    .put("cleaned_text", reviewedTexts.get(i)).putArray("redaction_log");
            Files.writeString(privateRoot.resolve("review-" + source.archive() + ".json"), review.toString());
        }
        Path diagnostics = privateRoot.resolve("prepare.log");
        // 공식 사이트 요청은 기존 Python 시험 고정 HTML로 대체하고, 수집·준비 함수는 실제 코드를 그대로 쓴다.
        // 고정 HTML은 processing.tests 시험 모듈(비공개 helper 포함)에 묶여 있어 그 모듈을 고치면 MySQL 시험에서만 깨진다.
        var process = new ProcessBuilder(PythonProbe.PYTHON, "-B", "-c", """
                import sys
                from pathlib import Path
                from unittest.mock import patch
                from processing.collection import media
                from processing.collection.board_batch import BOARD_SECTION, capture_board_batch
                from processing.collection.d03 import prepare
                from processing.collection.road_batch import ROAD_SECTION, capture_road_batch
                from processing.tests.test_board_batch import board_detail, board_page
                from processing.tests.test_board_media import city_notice
                from processing.tests.test_board_notices import _listing
                from processing.tests.test_edu_board import ATTACHMENT, _edu_notice, _edu_row
                from processing.tests.test_road_batch import road_detail, road_page

                root, downloaded_at = Path(sys.argv[1]), sys.argv[2]
                with (patch("processing.collection.road_batch.sleep"),
                      patch("processing.collection.road_batch.fetch_road_listing", return_value=road_page(1, 1, "9")),
                      patch("processing.collection.road_batch.fetch_road_detail", return_value=road_detail("9"))):
                    assert capture_road_batch("ongoing", "road-trial", root / ROAD_SECTION)["status"] == "complete"
                with (patch("processing.collection.board_batch.sleep"),
                      patch("processing.collection.board_batch.fetch_board_listing", return_value=board_page(1, 1, ["9"])),
                      patch("processing.collection.board_batch.fetch_board_detail", return_value=board_detail("9"))):
                    assert capture_board_batch("city", "board-trial", root / BOARD_SECTION)["status"] == "complete"
                with (patch("processing.collection.board_batch.sleep"),
                      patch("processing.collection.board_batch.fetch_board_listing",
                            return_value=_listing(_edu_row("3838", "330"), total=1).encode()),
                      patch("processing.collection.board_batch.fetch_board_detail",
                            return_value=_edu_notice(attachment=ATTACHMENT).encode())):
                    assert capture_board_batch("edu", "edu-trial", root / BOARD_SECTION)["status"] == "complete"
                with patch.object(media, "fetch_board_detail", return_value=city_notice()):
                    assert media.inspect_notice(root, "203043", "city-notice", board="city")["status"] == "parsed"
                media.store_media(root, "city-notice", 1, root / "download.png", "city-image", downloaded_at)
                for review in sorted(root.glob("review-*.json")):
                    prepare(review, "prepared-" + review.stem.removeprefix("review-"), root)
                """, privateRoot.toString(), DOWNLOADED_AT).directory(PythonProbe.REPO.toFile())
                .redirectErrorStream(true).redirectOutput(diagnostics.toFile()).start();
        try {
            assertThat(process.waitFor(30, TimeUnit.SECONDS)).as("Python 수집·D03 준비 시간 초과 %s", Files.readString(diagnostics)).isTrue();
            assertThat(process.exitValue()).as("Python 수집·D03 준비 결과 %s", Files.readString(diagnostics)).isZero();
        } finally {
            if (process.isAlive()) process.destroyForcibly().waitFor(5, TimeUnit.SECONDS);
        }

        var beforeExtractionRuns = jdbc.queryForObject("SELECT COUNT(*) FROM extraction_runs", Long.class);
        for (int i = 0; i < SOURCES.size(); i++) {
            var source = SOURCES.get(i);
            String id = versionIds.get(i);
            Path prepared = privateRoot.resolve("collection-d03/prepared-" + source.archive() + "/source-import.json");
            Path raw = privateRoot.resolve(source.rawRef());
            byte[] original = Files.readAllBytes(raw);
            byte[] tampered = java.util.Arrays.copyOf(original, original.length + 1);
            tampered[original.length] = ' ';
            Files.write(raw, tampered);
            try {
                assertThatThrownBy(() -> reader.read(prepared, privateRoot)).as(source.archive())
                        .isInstanceOfSatisfying(ImportException.class, error -> {
                            assertThat(error.code()).isEqualTo("IMPORT_VALIDATION_ERROR");
                            assertThat(error.field()).isEqualTo("documents.raw_sha256");
                        });
            } finally {
                Files.write(raw, original);
            }

            var before = counts();
            var first = importer.importBatch(reader.read(prepared, privateRoot), "synthetic-source-collector");
            var afterFirst = counts();
            var repeated = importer.importBatch(reader.read(prepared, privateRoot), "synthetic-source-collector");
            assertThat(first.alreadyImported()).as(source.archive()).isFalse();
            assertThat(first.documentVersionIds()).containsExactly(id);
            assertThat(first.revisionIds()).isEmpty();
            assertThat(repeated.alreadyImported()).isTrue();
            assertThat(repeated.importId()).isEqualTo(first.importId());
            assertThat(repeated.documentVersionIds()).containsExactly(id);
            assertThat(afterFirst.subList(0, 4)).isEqualTo(before.subList(0, 4));
            assertThat(afterFirst.get(4)).isEqualTo(before.get(4) + 1);
            assertThat(counts()).isEqualTo(afterFirst);
            assertThat(jdbc.queryForObject("SELECT source_kind FROM import_batches WHERE import_id = ?", String.class, first.importId())).isEqualTo("source");

            var row = jdbc.queryForMap("""
                    SELECT d.source_url, v.private_content_ref, v.text_sha256, v.metadata_json
                    FROM document_versions v JOIN documents d ON v.document_id = d.document_id
                    WHERE v.document_version_id = ?
                    """, id);
            assertThat(row.get("source_url")).isEqualTo(source.url());
            assertThat(row.get("private_content_ref")).isEqualTo(source.rawRef());
            assertThat(row.get("text_sha256")).isEqualTo(ReviewedImportReader.sha256(reviewedTexts.get(i).getBytes(StandardCharsets.UTF_8)));
            var metadata = mapper.readTree((String) row.get("metadata_json"));
            var doc = metadata.path("document");
            assertThat(metadata.path("data_kind").asText()).isEqualTo("synthetic");
            assertThat(doc.path("raw_sha256").asText()).isEqualTo(ReviewedImportReader.sha256(original));
            assertThat(doc.path("collection_method").asText()).isEqualTo(source.method());
            assertThat(doc.path("collected_at").asText()).isEqualTo(collectedAt(privateRoot, source, original));
            assertThat(doc.path("use_review").asText()).isEqualTo("pending");
            assertThat(doc.path("check_result").asText()).isEqualTo("unchecked");
            assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM source_checks WHERE document_version_id=?", Long.class, id)).isZero();
        }
        assertThat(Files.readAllBytes(privateRoot.resolve(SOURCES.get(2).rawRef()))).isEqualTo(PNG);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM extraction_runs", Long.class)).isEqualTo(beforeExtractionRuns);
    }

    // 웹 묶음은 batch.json의 상세 수신 시각, 매체는 운영자가 지정한 다운로드 시각이 D03 수집 시각이 된다.
    private String collectedAt(Path privateRoot, Source source, byte[] original) throws Exception {
        if (source.kind().equals("media")) return DOWNLOADED_AT;
        var item = mapper.readTree(privateRoot.resolve(Path.of(source.rawRef()).resolveSibling("batch.json")).toFile())
                .path("items").get(0);
        assertThat(item.path("sha256").asText()).isEqualTo(ReviewedImportReader.sha256(original));
        return item.path("fetched_at").asText().replace("+00:00", "Z");
    }

    private List<Long> counts() {
        return List.of("events", "event_revisions", "snapshots", "publication_heads", "document_versions").stream()
                .map(table -> jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Long.class)).toList();
    }
}
