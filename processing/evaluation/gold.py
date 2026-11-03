"""독립 정답 제공자의 선언·근거·사건 슬롯을 검사한다. 의미 정확성은 인증하지 않는다."""

import hashlib
from pathlib import Path
import unicodedata

from processing.extraction.archive import _json, _read, _root
from processing.extraction.metadata import stamp
from processing.extraction.schema import HASH
from processing.extraction.validation import array, decode, ids, parse_input, parse_output, require, shape, text
from .dataset import _id, _label, _parse_manifest
from .storage import DEFAULT_ROOT, verify_dataset

FIELDS = ('date_start','date_end','time_start','time_end','locations','types','applicability','exceptions')


def _check(condition, code='GOLD_INVALID'):
    require(condition, kind='input', code=code)


def _header(content):
    value = decode(content, 'input')
    shape(value, 'schema_version gold_version dataset_ref manifest_sha256 instructions authorship documents adjudications', kind='input')
    _check(value['schema_version'] == 'dataset-gold-v1')
    _label(value['gold_version'],100)
    for key in ('dataset_ref','manifest_sha256'): text(value[key],kind='input',pattern=HASH)
    review = value['authorship']
    shape(review, 'author reviewer authored_at reviewed_at independent_source_reading cross_reviewed no_unresolved_disagreements',kind='input')
    author, reviewer = _label(review['author']), _label(review['reviewer'])
    _check(unicodedata.normalize('NFC',author.strip()).casefold() != unicodedata.normalize('NFC',reviewer.strip()).casefold())
    _check(all(review[key] is True for key in ('independent_source_reading','cross_reviewed','no_unresolved_disagreements')))
    _check(stamp(review['authored_at'],'$') <= stamp(review['reviewed_at'],'$'))
    instructions = value['instructions']
    shape(instructions,'version normalization_version text synonyms',kind='input')
    _label(instructions['version'],100); text(instructions['text'],kind='input')
    _check(instructions['normalization_version'] == 'gold-exact-v1')
    seen = set()
    for synonym in array(instructions['synonyms'],'$.synonyms','input'):
        shape(synonym,'field canonical variants',kind='input')
        _check(synonym['field'] in ('locations','applicability','exceptions'))
        text(synonym['canonical'],kind='input'); ids(synonym['variants'],'$.variants','input',1)
        for spelling in [synonym['canonical'],*synonym['variants']]:
            normalized = unicodedata.normalize('NFC',' '.join(spelling.split()))
            key = (synonym['field'],normalized)
            _check(key not in seen); seen.add(key)
    seen = set()
    for doc in array(value['documents'],'$.documents','input',1):
        shape(doc,'document_version_id input_path output anchors',kind='input')
        version = _id(doc['document_version_id']); _check(version not in seen); seen.add(version)
        text(doc['input_path'],kind='input'); _check('\x00' not in doc['input_path'])
    return value


def _validate_gold(content, manifest_bytes, sources):
    value = _header(content)
    manifest, dataset = _parse_manifest(manifest_bytes)
    _check(value['dataset_ref'] == dataset['dataset_ref'] and value['manifest_sha256'] == dataset['manifest_sha256'],
           'GOLD_DATASET_MISMATCH')
    versions = {v['document_version_id']:(d['document_id'],v['input_sha256'])
                for d in manifest['documents'] for v in d['versions']}
    _check(set(sources) == set(versions) == {d['document_version_id'] for d in value['documents']},'GOLD_COVERAGE_INVALID')
    events = {e['event_id']:set(e['document_ids']) for e in manifest['events']}
    slots, evidence_by_version = set(), {}
    for doc in value['documents']:
        version = doc['document_version_id']; document_id, expected_hash = versions[version]
        document = parse_input(sources[version])
        _check(document['document_version_id'] == version and document['data_kind'] == manifest['data_kind']
               and hashlib.sha256(sources[version]).hexdigest() == expected_hash,'GOLD_SOURCE_MISMATCH')
        try:
            output_bytes = _json(doc['output'])
        except (TypeError,ValueError):
            require(False,kind='input',code='GOLD_INVALID')
        output = parse_output(output_bytes,document)
        evidence = {e['evidence_id'] for e in output['evidence']}; evidence_by_version[version] = evidence
        expected_slots = {item['local_item_id'] for item in output['items']}
        seen, event_ids = set(), set()
        for anchor in array(doc['anchors'],'$.anchors','input'):
            shape(anchor,'slot_id event_id evidence_ids',kind='input')
            slot = text(anchor['slot_id'],kind='input'); event = _id(anchor['event_id'])
            _check(slot in expected_slots and slot not in seen and event not in event_ids)
            _check(event in events and document_id in events[event])
            _check(ids(anchor['evidence_ids'],'$.anchor.evidence_ids','input',1) <= evidence)
            seen.add(slot); event_ids.add(event); slots.add((version,slot))
        _check(seen == expected_slots)
    seen = set(); review = value['authorship']
    for entry in array(value['adjudications'],'$.adjudications','input'):
        shape(entry,'document_version_id slot_id field disagreement resolution reason evidence_ids adjudicated_by adjudicated_at',kind='input')
        version = _id(entry['document_version_id']); slot = text(entry['slot_id'],kind='input')
        _check((version,slot) in slots and entry['field'] in FIELDS)
        key = (version,slot,entry['field']); _check(key not in seen); seen.add(key)
        for field in ('disagreement','resolution','reason'): text(entry[field],kind='input')
        _label(entry['adjudicated_by'])
        _check(ids(entry['evidence_ids'],'$.adjudication.evidence_ids','input',1) <= evidence_by_version[version])
        _check(stamp(review['authored_at'],'$') <= stamp(entry['adjudicated_at'],'$') <= stamp(review['reviewed_at'],'$'))
    return dict(protocol_version='gold-check-v1',status='validated',
                gold_ref=hashlib.sha256(value['gold_version'].encode()).hexdigest(),
                gold_sha256=hashlib.sha256(content).hexdigest(),dataset_ref=value['dataset_ref'],
                manifest_sha256=value['manifest_sha256'],instructions_sha256=hashlib.sha256(_json(value['instructions'])).hexdigest(),
                data_kind=manifest['data_kind'],review_status='declared_cross_reviewed',
                counts=dict(documents=len(manifest['documents']),document_versions=len(versions),slots=len(slots),
                            adjudications=len(value['adjudications'])))


def _load_gold(content, dataset_root):
    value = _header(content)
    frozen = verify_dataset(value['dataset_ref'],dataset_root)
    manifest_bytes = _read(_root(dataset_root,create=False)/value['dataset_ref']/'manifest.json')
    _check(hashlib.sha256(manifest_bytes).hexdigest() == frozen['manifest_sha256'] == value['manifest_sha256'],
           'GOLD_DATASET_MISMATCH')
    sources = {}
    for doc in value['documents']:
        path = Path(doc['input_path']).expanduser().absolute()
        sources[doc['document_version_id']] = _read(_root(path.parent,create=False)/path.name)
    return manifest_bytes,sources,_validate_gold(content,manifest_bytes,sources)


def check_gold(content,dataset_root=DEFAULT_ROOT):
    return _load_gold(content,dataset_root)[2]
