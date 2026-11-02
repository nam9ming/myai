"""Check cross-file consistency of synthetic interface examples (stdlib only)."""
from pathlib import Path
import hashlib
import json


def main():
    folder = Path(__file__).parent / "examples"
    data = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in folder.glob("*.json")}
    config = data["config-response"]
    request = data["matches-request"]
    response = data["matches-response"]
    detail = data["event-response"]
    events = data["public-events"]
    assert len(config["data"]["points"]) == 5
    assert request["point_id"] in {p["point_id"] for p in config["data"]["points"]}
    assert set(request["weekly_hours"]) == {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
    for envelope in [config, response, detail]:
        assert set(envelope) == {"schema_version", "snapshot_id", "generated_at", "data"}
        assert envelope["snapshot_id"] == config["snapshot_id"]
        assert envelope["data"]["data_kind"] == "synthetic"
    ids = {event["event_id"] for event in events}
    assert len(ids) == len(events)
    counts = {state: sum(e["classification"] == state for e in events) for state in ["candidate", "needs_check", "cancelled"]}
    assert response["data"]["counts"] == counts
    selected = [e for e in events if e["classification"] == request["selection"]]
    assert response["data"]["items"] == selected
    assert detail["data"]["event"] == selected[0]
    assert detail["data"]["event"]["event_id"] in ids
    for group in response["data"]["overlap_groups"]:
        assert set(group["event_ids"]) <= {e["event_id"] for e in selected}
        assert len(set(group["event_ids"])) >= 2
        assert group["start_at"] < group["end_at"]
    for event in events:
        assert event["source_refs"] and all(ref["last_verified_at"] for ref in event["source_refs"])
        assert set(event["types"]) <= {"construction", "event", "traffic"}
    assert {t for e in events for t in e["types"]} == {"construction", "event", "traffic"}
    input_data = data["ai-input"]
    extraction = data["ai-extraction"]
    assert extraction["document_version_id"] == input_data["document_version_id"]
    assert extraction["schema_version"] == "extract-schema-v1"
    blocks = {b["block_id"]: b["text"] for b in input_data["blocks"]}
    evidence_ids = set()
    for evidence in extraction["evidence"]:
        text = blocks[evidence["block_id"]]
        assert text[evidence["start_char"]:evidence["end_char"]] == evidence["quote"]
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == evidence["text_sha256"]
        evidence_ids.add(evidence["evidence_id"])

    def fields(value):
        if isinstance(value, dict):
            if set(value) == {"value", "knowledge", "evidence_ids", "reason"}:
                assert set(value["evidence_ids"]) <= evidence_ids
                if value["knowledge"] == "known":
                    assert value["value"] is not None and value["evidence_ids"]
                else:
                    assert value["value"] is None and value["reason"]
            for child in value.values():
                fields(child)
        elif isinstance(value, list):
            for child in value:
                fields(child)

    fields(extraction["items"])
    print(f"PASS: {len(data)} JSON files; config/request/selection/detail/source/AI evidence consistent (synthetic only).")


if __name__ == "__main__":
    main()
