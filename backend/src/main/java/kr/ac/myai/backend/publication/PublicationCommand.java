package kr.ac.myai.backend.publication;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

public sealed interface PublicationCommand {
    String schemaVersion();
    String action();
    String reason();

    record Decision(@NotBlank String schemaVersion, @NotBlank String action, @NotBlank @Size(max = 4000) String reason,
                    @NotNull UUID eventId, @Min(1) @Max(Long.MAX_VALUE - 1) long expectedRevisionNo,
                    @NotNull List<@NotBlank @Size(max = 128) String> evidenceIds) implements PublicationCommand { }

    record Publish(@NotBlank String schemaVersion, @NotBlank String action, @NotBlank @Size(max = 4000) String reason,
                   @NotBlank @Pattern(regexp = "current|replay") String mode, UUID caseId, LocalDate anchorDate,
                   Instant referenceInstant, Instant knowledgeCutoff, String historyFidelity,
                   @NotBlank @Pattern(regexp = "synthetic|real") String dataKind, @NotNull @Valid Area area,
                   @NotBlank @Size(max = 100) String rulesVersion, @NotBlank @Size(max = 100) String dictionaryVersion,
                   @NotNull @Size(max = 1000) List<@NotNull UUID> revisionIds,
                   @NotNull @Size(min = 5, max = 5) List<@NotNull @Valid Point> points,
                   @Min(0) @Max(Long.MAX_VALUE - 1) Long expectedHeadVersion) implements PublicationCommand { }

    record Rollback(@NotBlank String schemaVersion, @NotBlank String action, @NotBlank @Size(max = 4000) String reason,
                    @NotBlank @Pattern(regexp = "current|replay") String mode, UUID caseId, @NotNull UUID snapshotId,
                    @NotNull @Min(0) @Max(Long.MAX_VALUE - 1) Long expectedHeadVersion) implements PublicationCommand { }

    record Area(@NotNull UUID areaId, @NotBlank @Size(max = 255) String name, @NotBlank @Size(max = 4000) String description) { }

    record Point(@NotNull UUID pointId, @NotNull UUID areaId, @NotBlank @Size(max = 255) String label,
                 @NotNull @DecimalMin("-90") @DecimalMax("90") @Digits(integer = 3, fraction = 7) BigDecimal lat,
                 @NotNull @DecimalMin("-180") @DecimalMax("180") @Digits(integer = 3, fraction = 7) BigDecimal lon,
                 @NotBlank @Pattern(regexp = "verified") String verificationStatus,
                 @NotBlank @Size(max = 4096) String coordinateSource, @NotNull Instant checkedAt,
                 @NotBlank @Size(max = 128) String checkedBy, @NotBlank @Size(max = 100) String dictionaryVersion,
                 @NotNull List<@NotBlank @Size(max = 255) String> aliases,
                 @NotNull @AssertTrue Boolean active, @NotNull @AssertTrue Boolean isTestReference, @Min(1) long version) { }
}
