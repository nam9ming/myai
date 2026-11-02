package kr.ac.myai.backend.importing;

import java.time.Instant;
import java.util.List;

public record ReviewedBatch(String schemaVersion, String inputSha256, String dataKind,
                            List<Document> documents, List<Event> events, String originatingRunId) {
    public ReviewedBatch {
        documents = List.copyOf(documents);
        events = List.copyOf(events);
    }

    public record Document(String id, String versionId, long versionNo, String sourceUrl,
                           String textSha256, String metadataJson, String privateContentRef, List<SourceCheck> checks) {
        public Document { checks = List.copyOf(checks); }
    }

    public record SourceCheck(String id, Instant checkedAt, String result, String lastSuccessRef, String note) { }

    public record Event(String id, String revisionId, long revisionNo, long expectedRevisionNo,
                        String payloadJson, String payloadSha256, String reviewStatus, String publicationIntent,
                        String reviewerId, Instant reviewedAt, List<String> originatingRunIds,
                        List<String> sourceVersionIds, List<String> suspectedDuplicateIds) {
        public Event {
            originatingRunIds = List.copyOf(originatingRunIds);
            sourceVersionIds = List.copyOf(sourceVersionIds);
            suspectedDuplicateIds = List.copyOf(suspectedDuplicateIds);
        }
    }
}
