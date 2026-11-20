CREATE TABLE publication_audits (
    audit_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    channel_key VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    action VARCHAR(16) NOT NULL,
    before_snapshot_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin,
    after_snapshot_id CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    head_version BIGINT NOT NULL,
    reason TEXT NOT NULL,
    actor VARCHAR(128) NOT NULL,
    happened_at DATETIME(6) NOT NULL,
    KEY ix_publication_history (channel_key, after_snapshot_id),
    FOREIGN KEY (before_snapshot_id) REFERENCES snapshots(snapshot_id),
    FOREIGN KEY (after_snapshot_id) REFERENCES snapshots(snapshot_id),
    CHECK (action IN ('publish', 'rollback')),
    CHECK (head_version >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_as_cs;
