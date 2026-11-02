package kr.ac.myai.backend.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import kr.ac.myai.backend.exception.ApiException;

import java.time.LocalTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

public record MatchRequest(
        @NotNull UUID pointId,
        @NotNull @Size(min = 7, max = 7) Map<@Pattern(regexp = "monday|tuesday|wednesday|thursday|friday|saturday|sunday") String, @NotNull @Valid DayHours> weeklyHours,
        @NotNull @Pattern(regexp = "current|replay") String mode,
        UUID caseId,
        @NotNull @Size(max = 3) List<@NotNull @Pattern(regexp = "construction|event|traffic") String> types,
        UUID snapshotId,
        @Pattern(regexp = "candidate|needs_check|cancelled") String selection,
        @Pattern(regexp = "start|distance") String sort) {

    public MatchRequest {
        selection = selection == null ? "candidate" : selection;
        sort = sort == null ? "start" : sort;
    }

    public record DayHours(
            @NotNull @Pattern(regexp = "unknown|open|closed") String state,
            @NotNull Boolean fullDay,
            @Size(max = 3) List<@NotNull @Valid Interval> intervals) {
        public DayHours {
            intervals = intervals == null ? List.of() : intervals;
        }
    }

    public record Interval(
            @NotNull @Pattern(regexp = "(?:[01][0-9]|2[0-3]):[0-5][0-9]") String start,
            @NotNull @Pattern(regexp = "(?:[01][0-9]|2[0-3]):[0-5][0-9]") String end,
            @NotNull @Min(0) @Max(1) Integer endDayOffset) {}

    public void validateSemantics() {
        validateMode(mode, caseId);
        weeklyHours.forEach((day, hours) -> {
            String field = "weekly_hours." + day;
            if (!hours.state().equals("open")) {
                if (hours.fullDay() || !hours.intervals().isEmpty()) throw ApiException.invalid(field, "휴무·미상은 영업 구간 없이 입력해 주세요.");
            } else if (hours.fullDay()) {
                if (!hours.intervals().isEmpty()) throw ApiException.invalid(field, "종일 영업은 intervals를 비워 주세요.");
            } else {
                if (hours.intervals().isEmpty()) throw ApiException.invalid(field, "영업 구간을 입력해 주세요.");
                for (Interval interval : hours.intervals()) {
                    int start = LocalTime.parse(interval.start()).toSecondOfDay() / 60;
                    int end = LocalTime.parse(interval.end()).toSecondOfDay() / 60;
                    int minutes = end + interval.endDayOffset() * 1440 - start;
                    if (minutes <= 0 || minutes > 1440 || start == end) throw ApiException.invalid(field, "시작·종료·익일 여부를 확인해 주세요. 24시간 영업은 full_day를 사용합니다.");
                }
            }
        });
    }

    public static void validateMode(String mode, UUID caseId) {
        if (!mode.equals("current") && !mode.equals("replay")) throw ApiException.invalid("mode", "current 또는 replay를 사용해 주세요.");
        if ((mode.equals("current") && caseId != null) || (mode.equals("replay") && caseId == null)) throw ApiException.invalid("case_id", "current는 null, replay는 case_id가 필요합니다.");
    }
}
