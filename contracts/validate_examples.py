"""Check cross-file consistency of synthetic interface examples (stdlib only)."""
from pathlib import Path
import hashlib
import json
from datetime import datetime
from uuid import UUID


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

    def field_value(value, allowed_evidence):
        assert set(value) == {"value", "knowledge", "evidence_ids", "reason"}
        assert value["knowledge"] in {"known", "not_stated", "ambiguous", "not_applicable"}
        assert set(value["evidence_ids"]) <= allowed_evidence
        if value["knowledge"] == "known":
            assert value["value"] is not None and value["evidence_ids"]
        else:
            assert value["value"] is None and value["reason"]

    def fields(value, allowed_evidence):
        if isinstance(value, dict):
            for key in ["evidence_ids", "lifecycle_evidence_ids"]:
                if key in value:
                    assert set(value[key]) <= allowed_evidence
            if value.get("lifecycle") == "cancelled":
                assert value["lifecycle_evidence_ids"]
            if set(value) == {"value", "knowledge", "evidence_ids", "reason"}:
                field_value(value, allowed_evidence)
            for field in value.get("field_values", {}).values():
                field_value(field, allowed_evidence)
            for child in value.values():
                fields(child, allowed_evidence)
        elif isinstance(value, list):
            for child in value:
                fields(child, allowed_evidence)

    fields(extraction["items"], evidence_ids)
    facts = data["event-facts-response"]
    assert set(facts) == {"schema_version", "snapshot_id", "generated_at", "data"}
    assert facts["schema_version"] == "api-v1" and facts["data"]["data_kind"] == "synthetic"
    event = facts["data"]["event"]
    for identifier in [facts["snapshot_id"], event["revision_id"]]:
        assert str(UUID(identifier)) == identifier
    assert facts["generated_at"].endswith("Z")
    datetime.fromisoformat(facts["generated_at"].replace("Z", "+00:00"))
    assert not {"classification", "reason_codes", "distance_m", "distance_basis", "time_overlap_minutes", "matched_occurrence_ids"} & event.keys()
    assert event["area_membership"] in {"verified", "uncertain"}
    reviewed = json.loads((folder.parent.parent / "backend/examples/reviewed-import.json").read_text(encoding="utf-8"))
    documents = {doc["document_version_id"]: doc for doc in reviewed["documents"]}
    refs = {ref["document_version_id"]: ref for ref in event["source_refs"]}
    assert len(refs) == len(event["source_refs"]) and set(refs) == set(event["source_version_ids"])
    for version, ref in refs.items():
        doc = documents[version]
        assert ref["document_id"] == doc["document_id"] and ref["url"] == doc["official_url"] and ref["is_fixture"]
    citations = {item["evidence_id"] for item in event["evidence"]}
    assert len(citations) == len(event["evidence"])
    for item in event["evidence"]:
        doc = documents[item["document_version_id"]]
        text = next(block["text"] for block in doc["block_index"] if block["block_id"] == item["block_id"])
        assert text[item["start_char"]:item["end_char"]] == item["quote"]
        assert item["text_sha256"] == doc["text_sha256"] == hashlib.sha256(doc["cleaned_text"].encode("utf-8")).hexdigest()
        assert item["source_document_id"] == doc["document_id"] and item["document_version_id"] in refs and item["is_fixture"]
    fields(event, citations)
    assert set(event["field_values"]) == {"applicability", "exceptions", "route_names", "stop_names", "directions"}
    for name, value in event["field_values"].items():
        assert event[name] == value["value"]
    for location in event["locations"]:
        assert set(location["field_values"]) == {"name", "address"}
        for name, value in location["field_values"].items():
            assert location[name] == value["value"]
    print(f"PASS: {len(data)} JSON files; config/request/selection/detail/source/AI evidence consistent (synthetic only).")


if __name__ == "__main__":
    main()
