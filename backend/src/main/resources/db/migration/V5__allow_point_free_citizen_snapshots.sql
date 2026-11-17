ALTER TABLE snapshots
    MODIFY rules_version VARCHAR(100) NULL,
    MODIFY dictionary_version VARCHAR(100) NULL,
    ADD CONSTRAINT chk_snapshot_version_family CHECK (
        (schema_version = 'citizen-snapshot-v1' AND rules_version IS NULL AND dictionary_version IS NULL)
        OR (schema_version <> 'citizen-snapshot-v1' AND rules_version IS NOT NULL AND dictionary_version IS NOT NULL)
    );
