package kr.ac.myai.backend.controller;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.Valid;
import kr.ac.myai.backend.dto.MatchRequest;
import kr.ac.myai.backend.service.PublicNoticeService;
import org.springframework.context.annotation.Profile;
import org.springframework.web.bind.annotation.*;

import java.util.UUID;

@RestController
@Profile("!local-api")
@RequestMapping("/api/v1")
public class PublicNoticeController {
    private final PublicNoticeService notices;

    public PublicNoticeController(PublicNoticeService notices) {
        this.notices = notices;
    }

    @GetMapping("/config")
    public JsonNode config(@RequestParam(defaultValue = "current") String mode,
                           @RequestParam(name = "case_id", required = false) UUID caseId) {
        MatchRequest.validateMode(mode, caseId);
        return notices.config(mode, caseId);
    }

    @PostMapping("/matches")
    public JsonNode matches(@Valid @RequestBody MatchRequest query) {
        query.validateSemantics();
        return notices.matches(query);
    }

    @GetMapping("/events/{eventId}")
    public JsonNode event(@PathVariable UUID eventId, @RequestParam("snapshot_id") UUID snapshotId) {
        return notices.event(eventId, snapshotId);
    }
}
