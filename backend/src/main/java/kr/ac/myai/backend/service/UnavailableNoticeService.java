package kr.ac.myai.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.dto.MatchRequest;
import kr.ac.myai.backend.exception.ApiException;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.util.UUID;

@Service
@Profile("!fixture")
public class UnavailableNoticeService implements PublicNoticeService {
    private ApiException unavailable() {
        return new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "PUBLIC_DATA_NOT_READY", "검토된 공개 snapshot과 Python 계산기가 아직 연결되지 않았습니다.", null);
    }

    @Override
    public JsonNode config(String mode, UUID caseId) { throw unavailable(); }

    @Override
    public JsonNode matches(MatchRequest query) { throw unavailable(); }

    @Override
    public JsonNode event(UUID eventId, UUID snapshotId) { throw unavailable(); }
}
