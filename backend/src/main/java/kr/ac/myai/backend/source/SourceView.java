package kr.ac.myai.backend.source;

import kr.ac.myai.backend.repository.PublicationRepository;

import java.time.Instant;
import java.util.Map;
import java.util.Objects;

public final class SourceView {
    private final PublicationRepository.Document original;
    private final String effectiveMetadata;
    private final long reviewNo;
    private final String reviewSha256;
    private final Map<String, Instant> checkRecordedAt;
    private final Instant lastRecordedAt;
    private final long historyBytes;

    public SourceView(PublicationRepository.Document original) { this(original, original.metadata(), 0, null, Map.of()); }

    public SourceView(PublicationRepository.Document original, String effectiveMetadata, long reviewNo,
                      String reviewSha256, Map<String, Instant> checkRecordedAt) {
        this(original, effectiveMetadata, reviewNo, reviewSha256, checkRecordedAt, null, 0);
    }

    SourceView(PublicationRepository.Document original, String effectiveMetadata, long reviewNo,
               String reviewSha256, Map<String, Instant> checkRecordedAt, Instant lastRecordedAt, long historyBytes) {
        this.original = Objects.requireNonNull(original);
        this.effectiveMetadata = Objects.requireNonNull(effectiveMetadata);
        this.reviewNo = reviewNo;
        this.reviewSha256 = reviewSha256;
        this.checkRecordedAt = Map.copyOf(checkRecordedAt);
        this.lastRecordedAt = lastRecordedAt;
        this.historyBytes = historyBytes;
    }

    public PublicationRepository.Document original() { return original; }
    public String effectiveMetadata() { return effectiveMetadata; }
    public long reviewNo() { return reviewNo; }
    public String reviewSha256() { return reviewSha256; }
    public Map<String, Instant> checkRecordedAt() { return checkRecordedAt; }
    Instant lastRecordedAt() { return lastRecordedAt; }
    long historyBytes() { return historyBytes; }

    public boolean checkVisible(String checkId, Instant cutoff) {
        Instant recordedAt = checkRecordedAt.get(checkId);
        return cutoff == null || recordedAt == null || !recordedAt.isAfter(cutoff);
    }

    @Override
    public boolean equals(Object other) {
        return other instanceof SourceView view && reviewNo == view.reviewNo && original.equals(view.original)
                && effectiveMetadata.equals(view.effectiveMetadata) && Objects.equals(reviewSha256, view.reviewSha256)
                && checkRecordedAt.equals(view.checkRecordedAt);
    }

    @Override
    public int hashCode() { return Objects.hash(original, effectiveMetadata, reviewNo, reviewSha256, checkRecordedAt); }
}
