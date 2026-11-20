package kr.ac.myai.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import kr.ac.myai.backend.dto.MatchRequest;

import java.util.UUID;

public interface PublicNoticeService {
    JsonNode config(String mode, UUID caseId);
    JsonNode matches(MatchRequest query);
    JsonNode event(UUID eventId, UUID snapshotId);
}
