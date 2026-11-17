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
    citizen_input, citizen_output = data["citizen-ai-input"], data["citizen-ai-extraction"]
    assert citizen_input["data_kind"] == "synthetic"
    assert set(citizen_output) == {"schema_version", "document_version_id", "items", "evidence", "warnings"}
    assert citizen_output["schema_version"] == "extract-citizen-v1"
    assert citizen_output["document_version_id"] == citizen_input["document_version_id"]
    citizen_blocks = {block["block_id"]: block["text"] for block in citizen_input["blocks"]}
    citizen_evidence = set()
    for evidence in citizen_output["evidence"]:
        assert set(evidence) == {"evidence_id", "block_id", "quote", "start_char", "end_char", "text_sha256"}
        assert evidence["evidence_id"] not in citizen_evidence
        citizen_evidence.add(evidence["evidence_id"])
        block = citizen_blocks[evidence["block_id"]]
        assert type(evidence["start_char"]) is int and type(evidence["end_char"]) is int
        assert 0 <= evidence["start_char"] < evidence["end_char"] <= len(block)
        assert block[evidence["start_char"]:evidence["end_char"]] == evidence["quote"]
        assert hashlib.sha256(block.encode("utf-8")).hexdigest() == evidence["text_sha256"]
    raw_fields = {"application_period", "occurrences", "regions", "locations", "residency_requirement", "target",
                  "eligibility", "application_method", "preparation", "cost", "recruitment", "lifecycle"}
    categories, item_ids = set(), set()
    for item in citizen_output["items"]:
        assert set(item) == {"local_item_id", "title", "categories"} | raw_fields
        assert item["local_item_id"] not in item_ids
        item_ids.add(item["local_item_id"])
        assert item["title"]["value"] is None or type(item["title"]["value"]) is str
        selected = item["categories"]["value"]
        if selected is None:
            assert item["categories"]["knowledge"] == "ambiguous"
        else:
            assert type(selected) is list and selected and len(selected) == len(set(selected))
            assert set(selected) <= {"education", "support", "culture", "construction_traffic", "living"}
            categories.update(selected)
        for name in raw_fields:
            raw = item[name]["value"]
            assert raw is None or type(raw) is str or type(raw) is list
            if type(raw) is list:
                assert all(type(entry) is str and entry.strip() for entry in raw) and len(raw) == len(set(raw))
    fields(citizen_output["items"], citizen_evidence)
    assert categories == {"education", "support", "culture", "construction_traffic", "living"}
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
    citizen_list = data["citizen-list-response"]
    citizen_detail = data["citizen-detail-response"]
    citizen_input = json.loads((folder.parent.parent / "backend/examples/citizen-reviewed-import.json").read_text(encoding="utf-8"))
    citizen_documents = {doc["document_version_id"]: doc for doc in citizen_input["documents"]}
    for envelope in [citizen_list, citizen_detail]:
        assert set(envelope) == {"schema_version", "snapshot_id", "generated_at", "data"}
        assert envelope["schema_version"] == "citizen-api-v1"
        assert str(UUID(envelope["snapshot_id"])) == envelope["snapshot_id"] == citizen_list["snapshot_id"]
        assert envelope["data"]["data_kind"] == "synthetic" and envelope["data"]["mode"] == "current"
        assert envelope["data"]["timezone"] == "Asia/Seoul"
        assert datetime.fromisoformat(envelope["data"]["created_at"].replace("Z", "+00:00")) <= datetime.fromisoformat(envelope["generated_at"].replace("Z", "+00:00"))
    common = {"created_at", "data_kind", "mode", "timezone", "sources"}
    assert set(citizen_list["data"]) == common | {"notice_count", "notices"}
    assert set(citizen_detail["data"]) == common | {"notice", "history"}
    assert citizen_list["data"]["notice_count"] == len(citizen_list["data"]["notices"]) == 1
    notice = citizen_detail["data"]["notice"]
    assert citizen_list["data"]["notices"] == [notice]
    assert citizen_list["data"]["created_at"] == citizen_detail["data"]["created_at"]
    assert citizen_detail["data"]["sources"] == citizen_list["data"]["sources"]
    fact_names = set("application_period occurrences regions locations residency_requirement target eligibility application_method preparation cost recruitment lifecycle".split())
    assert set(notice) == fact_names | {"event_id", "revision_id", "title", "categories", "source_version_ids", "document_links", "relations", "evidence"}
    assert notice["categories"] and set(notice["categories"]) <= {"education", "support", "culture", "construction_traffic", "living"}
    assert notice["categories"] == citizen_input["events"][0]["revision"]["categories"]
    assert len(set(notice["categories"])) == len(notice["categories"])
    for name in ["event_id", "revision_id"]:
        assert str(UUID(notice[name])) == notice[name]
    public_sources = {item["document_version_id"]: item for item in citizen_detail["data"]["sources"]}
    assert set(public_sources) == set(notice["source_version_ids"])
    for version, source in public_sources.items():
        assert set(source) == set("document_id document_version_id publisher official_url title official_number published_date collected_at text_sha256 last_verified_at latest_check_attempt_at check_result checks".split())
        original = citizen_documents[version]
        assert source["document_id"] == original["document_id"] and source["official_url"] == original["official_url"]
        assert source["text_sha256"] == original["text_sha256"] == hashlib.sha256(original["cleaned_text"].encode("utf-8")).hexdigest()
        assert source["last_verified_at"] == original["last_verified_at"]
        assert source["latest_check_attempt_at"] == original["latest_check_attempt_at"]
        for check in source["checks"]:
            assert set(check) == {"checked_at", "result", "text_sha256"}
    citations = {item["evidence_id"] for item in notice["evidence"]}
    assert len(citations) == len(notice["evidence"])
    for evidence in notice["evidence"]:
        original = citizen_documents[evidence["document_version_id"]]
        block = next(item["text"] for item in original["block_index"] if item["block_id"] == evidence["block_id"])
        assert block[evidence["start_char"]:evidence["end_char"]] == evidence["quote"]
        assert evidence["text_sha256"] == original["text_sha256"]
    fields(notice, citations)
    assert notice["application_period"]["value"] != notice["occurrences"]["value"]
    assert notice["cost"]["value"] is None and notice["cost"]["knowledge"] == "not_stated"
    history = citizen_detail["data"]["history"]
    assert set(history) == {"scope", "completeness", "status", "window", "entries", "error"}
    assert history["scope"] == "same_data_kind_published_snapshots" and history["completeness"] == "unknown"
    assert history["status"] == "available" and history["error"] is None
    window = history["window"]
    assert set(window) == {"from_version", "to_version", "has_more", "next_before_version", "limit"}
    assert all(type(window[name]) is int for name in ["from_version", "to_version", "limit"])
    assert type(window["has_more"]) is bool
    assert window == {"from_version": 0, "to_version": 0, "has_more": False, "next_before_version": None, "limit": 1000}
    assert len(history["entries"]) == 1
    entry = history["entries"][0]
    assert set(entry) == {"kind", "snapshot_id", "published_at", "action", "before", "after"}
    assert entry["kind"] == "first_observed" and entry["before"] is None and entry["action"] == "publish"
    assert entry["snapshot_id"] == citizen_detail["snapshot_id"] and entry["published_at"] == citizen_detail["data"]["created_at"]
    assert entry["after"] == {"notice": notice, "sources": citizen_detail["data"]["sources"]}
    print(f"PASS: {len(data)} JSON files; legacy/citizen list/detail/source/AI evidence consistent (synthetic only).")


if __name__ == "__main__":
    main()
