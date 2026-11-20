ALTER TABLE document_versions
    ADD COLUMN source_review_no BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN source_review_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin,
    ADD CONSTRAINT ck_source_review_head CHECK (
        (source_review_no = 0 AND source_review_sha256 IS NULL)
        OR (source_review_no > 0 AND source_review_sha256 IS NOT NULL)
    );

CREATE TABLE source_reviews (
    review_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    document_version_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    review_no BIGINT NOT NULL,
    input_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    record_json LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    record_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    UNIQUE KEY uq_source_review_number (document_version_id, review_no),
    FOREIGN KEY (document_version_id) REFERENCES document_versions(document_version_id),
    CHECK (review_no > 0),
    CHECK (JSON_VALID(record_json))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;
