CREATE TABLE test_points (
    point_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    area_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    label VARCHAR(255) NOT NULL,
    longitude DECIMAL(10,7) NOT NULL,
    latitude DECIMAL(9,7) NOT NULL,
    evidence_json JSON NOT NULL,
    version BIGINT NOT NULL,
    data_kind VARCHAR(16) NOT NULL,
    CHECK (longitude BETWEEN -180 AND 180 AND latitude BETWEEN -90 AND 90),
    CHECK (version > 0),
    CHECK (data_kind IN ('synthetic', 'real'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE place_dictionary (
    place_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    dictionary_version VARCHAR(100) NOT NULL,
    aliases_json JSON NOT NULL,
    geometry_json JSON,
    coverage VARCHAR(32) NOT NULL,
    evidence_json JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE documents (
    document_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_external_id VARCHAR(255),
    source_type VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE document_versions (
    document_version_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    document_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_no BIGINT NOT NULL,
    text_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    metadata_json JSON NOT NULL,
    private_content_ref TEXT,
    UNIQUE KEY uq_document_version (document_id, version_no),
    FOREIGN KEY (document_id) REFERENCES documents(document_id),
    CHECK (version_no > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE source_checks (
    check_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    document_version_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    checked_at DATETIME(6) NOT NULL,
    result VARCHAR(32) NOT NULL,
    last_success_ref CHAR(36) CHARACTER SET ascii COLLATE ascii_bin,
    note TEXT,
    UNIQUE KEY uq_check_version (check_id, document_version_id),
    FOREIGN KEY (document_version_id) REFERENCES document_versions(document_version_id),
    FOREIGN KEY (last_success_ref, document_version_id) REFERENCES source_checks(check_id, document_version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE extraction_runs (
    run_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    document_version_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    input_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    output_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin,
    provider VARCHAR(100) NOT NULL,
    model VARCHAR(100) NOT NULL,
    prompt_version VARCHAR(100) NOT NULL,
    status VARCHAR(32) NOT NULL,
    raw_ref TEXT,
    FOREIGN KEY (document_version_id) REFERENCES document_versions(document_version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE events (
    event_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    current_review_revision_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin,
    lock_version BIGINT NOT NULL DEFAULT 0,
    CHECK (lock_version >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE event_revisions (
    revision_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    event_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    revision_no BIGINT NOT NULL,
    review_status VARCHAR(32) NOT NULL,
    publication_intent VARCHAR(16) NOT NULL,
    payload_json LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    payload_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    reviewed_at DATETIME(6),
    reviewed_by VARCHAR(128),
    UNIQUE KEY uq_event_revision (event_id, revision_no),
    UNIQUE KEY uq_revision_event (revision_id, event_id),
    FOREIGN KEY (event_id) REFERENCES events(event_id),
    CHECK (revision_no > 0),
    CHECK (JSON_VALID(payload_json)),
    CHECK (review_status IN ('draft', 'needs_review', 'approved', 'rejected')),
    CHECK (publication_intent IN ('hidden', 'public')),
    CHECK (review_status <> 'approved' OR (reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL)),
    CHECK (publication_intent <> 'public' OR review_status = 'approved')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

ALTER TABLE events ADD CONSTRAINT fk_current_event_revision
    FOREIGN KEY (current_review_revision_id, event_id) REFERENCES event_revisions(revision_id, event_id);

CREATE TABLE review_audits (
    audit_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    event_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    revision_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    action VARCHAR(64) NOT NULL,
    before_ref TEXT,
    after_ref TEXT,
    reason TEXT NOT NULL,
    evidence_json JSON NOT NULL,
    actor VARCHAR(128) NOT NULL,
    happened_at DATETIME(6) NOT NULL,
    FOREIGN KEY (revision_id, event_id) REFERENCES event_revisions(revision_id, event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE snapshots (
    snapshot_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    mode VARCHAR(16) NOT NULL,
    case_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin,
    schema_version VARCHAR(100) NOT NULL,
    rules_version VARCHAR(100) NOT NULL,
    dictionary_version VARCHAR(100) NOT NULL,
    canonical_json LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
    checksum CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    metadata_json JSON NOT NULL,
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    data_kind VARCHAR(16) NOT NULL,
    CHECK (JSON_VALID(canonical_json)),
    CHECK (data_kind IN ('synthetic', 'real')),
    CHECK ((mode = 'current' AND case_id IS NULL) OR (mode = 'replay' AND case_id IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE snapshot_revisions (
    snapshot_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    event_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    revision_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (snapshot_id, event_id),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id),
    FOREIGN KEY (revision_id, event_id) REFERENCES event_revisions(revision_id, event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE publication_heads (
    channel_key VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    snapshot_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    lock_version BIGINT NOT NULL DEFAULT 0,
    changed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id),
    CHECK (lock_version >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;

CREATE TABLE import_batches (
    import_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    source_kind VARCHAR(32) NOT NULL,
    input_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    schema_version VARCHAR(100) NOT NULL,
    status VARCHAR(32) NOT NULL,
    result_refs_json JSON,
    UNIQUE KEY uq_import_identity (source_kind, input_sha256, schema_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;
