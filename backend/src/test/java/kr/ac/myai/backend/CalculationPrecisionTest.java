package kr.ac.myai.backend;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.node.ArrayNode;
import kr.ac.myai.backend.calculation.PythonCalculator;
import kr.ac.myai.backend.dto.MatchRequest;
import kr.ac.myai.backend.importing.ReviewedImportReader;
import kr.ac.myai.backend.publication.PublicationContent;
import kr.ac.myai.backend.repository.PublicSnapshotRepository;
import kr.ac.myai.backend.service.SnapshotNoticeService;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

import java.math.BigDecimal;
import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class CalculationPrecisionTest {
    private final ObjectMapper mapper = new ObjectMapper().setPropertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE);
    private final ReviewedImportReader json = new ReviewedImportReader();

    @Test
    void highPrecisionCoordinateDoesNotBreakMatches() throws Exception {
        // 사람 검토 이력은 18자리 이상 좌표를 그대로 보존한다. Python은 double로 읽어 돌려주므로 대조가 실패하면 안 된다.
        for (String longitude : new String[] {"127.27", "127.270000000000001"}) {
            var snapshot = CalculationFixtures.snapshot(mapper);
            var coordinates = (ArrayNode) snapshot.path("event_public_payloads").get(0).path("locations").get(0)
                    .path("geometry").path("coordinates");
            coordinates.set(0, mapper.getNodeFactory().numberNode(new BigDecimal(longitude)));
            var repository = mock(PublicSnapshotRepository.class);
            var row = CalculationFixtures.published(snapshot, mapper);
            when(repository.head("current")).thenReturn(Optional.of(row.snapshot().id()));
            when(repository.published(row.snapshot().id())).thenReturn(Optional.of(row));
            var transactions = mock(PlatformTransactionManager.class);
            when(transactions.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
            var service = new SnapshotNoticeService(repository, new PublicationContent(json, mapper), mapper,
                    new PythonCalculator(mapper, json, PythonProbe.PYTHON, PythonProbe.REPO.toString(), 5000),
                    Clock.fixed(Instant.parse("2026-11-03T02:00:00Z"), ZoneOffset.UTC), transactions);
            var query = mapper.treeToValue(mapper.readTree(PythonProbe.REPO.resolve("processing/examples/match-input.json").toFile())
                    .path("query"), MatchRequest.class);
            assertThatCode(() -> service.matches(query)).as(longitude).doesNotThrowAnyException();
        }
    }
}
