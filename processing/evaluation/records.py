"""고정 gold와 명시한 API 실행을 최초 raw·최종 자동 평가로 연결한다."""

from datetime import datetime, timezone
import hashlib

from processing.extraction.archive import (REPO, DEFAULT_ROOT as RUN_ROOT, _fingerprint, _json, _read,
                                            _read_checked, _root, verify_run)
from processing.extraction.metadata import stamp
from processing.extraction.schema import HASH, UUID
from processing.extraction.validation import MAX_BYTES, array, decode, require, shape, text
from .bindings import _frozen
from .dataset import _id, _label, _parse_manifest
from .gold import FIELDS, _header as gold_header
from .gold_storage import GOLD_ROOT, verify_gold
from .scoring import VERSION, score_document
from .storage import _times as manifest_times

EVALUATION_ROOT = REPO/'data/private/evaluation/extractions'
VIEWS = ('first_raw','final_auto')


def _check(condition,code='EVALUATION_INVALID'):
    require(condition,kind='input',code=code)


def _header(content):
    value = decode(content,'input')
    shape(value,'schema_version extraction_eval_id gold_ref gold_receipt_sha256 method phase initial_ref review policy documents',kind='input')
    _check(value['schema_version']=='extraction-evaluation-v1' and value['method']=='ai_auto')
    _id(value['extraction_eval_id'])
    for key in ('gold_ref','gold_receipt_sha256'):text(value[key],kind='input',pattern=HASH)
    _check(value['phase'] in ('initial','retest'))
    if value['phase']=='initial':_check(value['initial_ref'] is None)
    else:
        text(value['initial_ref'],kind='input',pattern=HASH)
        _check(value['initial_ref']!=hashlib.sha256(value['extraction_eval_id'].encode()).hexdigest())
    review = value['review']
    shape(review,'reviewed_by reviewed_at semantic_feedback_used exposure_status exposure_note',kind='input')
    _label(review['reviewed_by']);stamp(review['reviewed_at'],'$');text(review['exposure_note'],kind='input')
    _check(type(review['semantic_feedback_used']) is bool and review['exposure_status'] in ('none_declared','exposed','unknown'))
    _check(not review['semantic_feedback_used'] or review['exposure_status']=='exposed')
    _check(value['phase']!='initial' or not review['semantic_feedback_used'],'EVALUATION_INITIAL_SEMANTIC_FEEDBACK')
    policy = value['policy']
    shape(policy,'provider model_label prompt_version schema_version retry_policy_version',kind='input')
    for field in policy:_label(policy[field],100)
    _check(policy['provider']=='openai' and policy['schema_version']=='extract-schema-v1'
           and policy['retry_policy_version']=='api-structure-retry-v1')
    seen,runs = set(),set()
    for doc in array(value['documents'],'$.documents','input',1):
        shape(doc,'document_version_id run_id snapshot_ref receipt_sha256 first_annotation final_annotation',kind='input')
        version,run = _id(doc['document_version_id']),_id(doc['run_id'])
        _check(version not in seen and run not in runs,'EVALUATION_COVERAGE_INVALID');seen.add(version);runs.add(run)
        reference = text(doc['snapshot_ref'],kind='input',pattern=rf'(?:registered/{HASH}/)?{UUID}')
        _check(reference.split('/')[-1]==run)
        text(doc['receipt_sha256'],kind='input',pattern=HASH)
        _check(type(doc['first_annotation']) is dict and type(doc['final_annotation']) is dict)
    return value


def _collect(directory,names,prefix):
    return {f'{prefix}/{name}':(directory/name,_fingerprint(directory/name)) for name in names}


def _load_sources(value,gold_root,run_root):
    receipt = verify_gold(value['gold_ref'],gold_root)
    directory = _root(gold_root,create=False)/value['gold_ref']
    raw_receipt = _read(directory/'receipt.json')
    _check(raw_receipt==_json(receipt) and hashlib.sha256(raw_receipt).hexdigest()==value['gold_receipt_sha256'],
           'EVALUATION_GOLD_MISMATCH')
    artifacts = receipt['artifacts']
    raw_gold = _read_checked(directory/'gold.json',artifacts['gold.json'])
    gold_value = gold_header(raw_gold)
    manifest_bytes = _read_checked(directory/'manifest.json',artifacts['manifest.json'])
    manifest,dataset = _parse_manifest(manifest_bytes)
    manifest_times(manifest,receipt['frozen_at'])
    versions = {d['document_version_id']:d for d in gold_value['documents']}
    _check({d['document_version_id'] for d in value['documents']}==versions.keys(),'EVALUATION_COVERAGE_INVALID')
    inputs = {v:_read_checked(directory/f'input-{v}.json',artifacts[f'input-{v}.json']) for v in versions}
    gold = dict(receipt=receipt,value=gold_value,manifest=manifest,dataset=dataset,documents=versions,inputs=inputs)
    sources = _collect(directory,[*artifacts,'identity.json','receipt.json'],f"gold/{value['gold_ref']}")
    runs = []
    base = _root(run_root,create=False)
    for doc in value['documents']:
        run_id,reference = doc['run_id'],doc['snapshot_ref']
        folder = _root(base/reference,create=False);_check(folder==base/reference)
        run = verify_run(run_id,folder.parent);_frozen(folder,run)
        _check(run['execution_mode']=='api','EVALUATION_AUTO_REQUIRES_API')
        raw = _read(folder/'receipt.json');digest = hashlib.sha256(raw).hexdigest()
        _check(raw==_json(run) and digest==doc['receipt_sha256'],'EVALUATION_RUN_MISMATCH')
        if reference.startswith('registered/'):_check(reference.split('/')[1]==digest,'EVALUATION_RUN_MISMATCH')
        version = doc['document_version_id']
        run_input = _read_checked(folder/'input.json',run['artifacts']['input.json'])
        _check(run['document_version_id']==version and run['data_kind']==dataset['data_kind']
               and run_input==inputs[version],'EVALUATION_SOURCE_MISMATCH')
        metadata = decode(_read_checked(folder/'metadata.json',run['artifacts']['metadata.json']),'archive')
        _check(all(metadata[k]==value['policy'][k] for k in ('provider','model_label','prompt_version','schema_version')),
               'EVALUATION_POLICY_MISMATCH')
        count = len(run['attempts'])
        if count==1:_check(doc['first_annotation']==doc['final_annotation'],'EVALUATION_SINGLE_ATTEMPT_ANNOTATIONS')
        outputs = {view:_read_checked(folder/f'attempt-{number}.output',run['artifacts'][f'attempt-{number}.output'])
                   for view,number in (('first_raw',1),('final_auto',count))}
        runs.append(dict(document=doc,receipt=run,metadata=metadata,outputs=outputs))
        sources.update(_collect(folder,[*run['artifacts'],'identity.json','receipt.json'],f'runs/{reference}'))
    return gold,runs,sources


def _initial(reference,root):
    from .evaluation_storage import _verify_directory
    directory = _root(root,create=False)/reference
    receipt = _verify_directory(directory,reference,initial_only=True)
    raw = _read_checked(directory/'result.json',receipt['artifacts']['result.json'])
    result = decode(raw,'archive')
    _check(result['phase']=='initial','EVALUATION_INITIAL_REQUIRED')
    return dict(result=result,receipt=receipt,sources=_collect(directory,
                [*receipt['artifacts'],'identity.json','receipt.json'],f'initial/{reference}'))


def _percent(a,b):return a/b*100 if b else None


def _aggregate(scores):
    result = {key:sum(s[key] for s in scores) for key in ('correct_fields','known_fields','missing_events','duplicate_events',
        'additional_events','binding_errors','output_fields','generation_errors','generation_review_pending')}
    result.update(document_count=len(scores),document_failures=sum(s['document_failed'] for s in scores))
    result['document_failure_rate_percent'] = _percent(result['document_failures'],len(scores))
    result['accuracy_percent'] = _percent(result['correct_fields'],result['known_fields'])
    result['fields'] = {}
    for key in FIELDS:
        correct = sum(s['fields'][key]['correct'] for s in scores);known = sum(s['fields'][key]['known'] for s in scores)
        result['fields'][key] = dict(correct=correct,known=known,accuracy_percent=_percent(correct,known))
    complete = bool(scores) and all(s['generation_review_complete'] for s in scores)
    result['generation_review_complete'] = complete
    result['generation_rate_percent'] = _percent(result['generation_errors'],result['output_fields']) if complete else None
    return result


def _compute(value,gold,runs,initial,evaluated_at,selection_sha256):
    now = stamp(evaluated_at,'$');reviewed = stamp(value['review']['reviewed_at'],'$')
    _check(stamp(gold['receipt']['frozen_at'],'$')<=reviewed<=now,'EVALUATION_REVIEW_TIME_INVALID')
    policy_hash = hashlib.sha256(_json(value['policy'])).hexdigest()
    gold_summary = gold['receipt']['summary']
    old = initial['result'] if initial else None
    if value['phase']=='retest':
        _check(old is not None and old['phase']=='initial' and old['evaluation_ref']==value['initial_ref'],'EVALUATION_INITIAL_REQUIRED')
        _check(old['method']==value['method'] and old['manifest_sha256']==gold_summary['manifest_sha256']
               and old['instructions_sha256']==gold_summary['instructions_sha256'],'EVALUATION_COHORT_MISMATCH')
        _check(old['gold_ref']!=value['gold_ref'] or old['gold_sha256']==gold_summary['gold_sha256'],
               'EVALUATION_GOLD_VERSION_CONFLICT')
        _check(stamp(initial['receipt']['frozen_at'],'$')<=reviewed,'EVALUATION_REVIEW_TIME_INVALID')
    versions = {v['document_version_id']:d['document_id'] for d in gold['manifest']['documents'] for v in d['versions']}
    assignments = {a['document_id']:a['split'] for a in gold['manifest']['split_assignments']}
    documents = []
    for packet in runs:
        doc,run,metadata = packet['document'],packet['receipt'],packet['metadata']
        started,finished = stamp(metadata['started_at'],'$'),stamp(metadata['finished_at'],'$')
        _check(started<=finished<=reviewed,'EVALUATION_RUN_TIME_INVALID')
        _check(finished<=stamp(run['recorded_at'],'$')<=now,'EVALUATION_RUN_ARCHIVE_TIME_INVALID')
        if value['phase']=='initial':
            _check(stamp(gold['receipt']['frozen_at'],'$')<started,'EVALUATION_GOLD_AFTER_RUN')
        elif run['run_id'] in old['run_ids']:
            _check(any(d['run_id']==run['run_id'] and d['receipt_sha256']==doc['receipt_sha256']
                       for d in old['documents']),'EVALUATION_RETEST_RUN_MISMATCH')
        else:
            _check(stamp(initial['receipt']['frozen_at'],'$')<started,'EVALUATION_RETEST_RUN_TIME_INVALID')
        version = doc['document_version_id'];expected = gold['documents'][version]
        event_ids = {a['slot_id']:a['event_id'] for a in expected['anchors']}
        scored = {}
        for view,annotation in (('first_raw','first_annotation'),('final_auto','final_annotation')):
            try:annotation_bytes = _json(doc[annotation])
            except (TypeError,ValueError):
                require(False,kind='input',code='EVALUATION_ANNOTATION_INVALID')
            result = score_document(gold['inputs'][version],_json(expected['output']),packet['outputs'][view],
                                    annotation_bytes,gold['value']['instructions'])
            attempt = run['attempts'][0 if view=='first_raw' else -1]
            _check(result['summary']['document_failed']==(attempt['status']=='failed'),'EVALUATION_ATTEMPT_MISMATCH')
            result['source_attempt'] = attempt['attempt'];result['source_error_code'] = attempt['error_code']
            for entry in result['field_results']:
                entry.update(document_version_id=version,event_id=event_ids[entry['slot_id']],run_id=run['run_id'])
            scored[view] = result
        documents.append(dict(document_version_id=version,document_id=versions[version],split=assignments[versions[version]],
            run_id=run['run_id'],receipt_sha256=doc['receipt_sha256'],attempt_count=len(run['attempts']),
            metadata_sha256=run['metadata_sha256'],**scored))
    views = {view:_aggregate([d[view]['summary'] for d in documents]) for view in VIEWS}
    splits = {split:{view:_aggregate([d[view]['summary'] for d in documents if d['split']==split]) for view in VIEWS}
              for split in ('dev','holdout')}
    warnings = []
    dataset = gold['dataset'];holdout = splits['holdout']['final_auto']
    if dataset['data_kind']!='real':warnings.append('SYNTHETIC_DATA')
    if any(dataset['shortfall'].values()):warnings.append('REAL_DOCUMENT_TARGET_SHORTFALL')
    if dataset['counts']['documents']!=dataset['counts']['document_versions']:warnings.append('MULTIPLE_VERSIONS_PER_DOCUMENT')
    if dataset['holdout_status']!='unexposed_as_declared':warnings.append('HOLDOUT_NOT_CLEARED')
    if value['review']['exposure_status']!='none_declared':warnings.append('EXPOSURE_NOT_CLEARED')
    if value['phase']!='initial':warnings.append('RETEST_NOT_INITIAL_GENERALIZATION')
    if not holdout['known_fields']:warnings.append('NO_KNOWN_HOLDOUT_FIELDS')
    eligible = not warnings
    comparison = None
    if old:
        comparison = dict(initial_ref=value['initial_ref'],initial_gold_ref=old['gold_ref'],views={})
        for view in VIEWS:
            previous,current = old['summary']['views'][view],views[view]
            a = float(previous['accuracy_percent']) if previous['accuracy_percent'] is not None else None
            b = current['accuracy_percent']
            comparison['views'][view] = dict(initial_correct=previous['correct_fields'],initial_known=previous['known_fields'],
                initial_accuracy_percent=a,current_correct=current['correct_fields'],current_known=current['known_fields'])
            comparison[f'{view}_delta_percent'] = b-a if a is not None and b is not None else None
    summary = dict(protocol_version='extraction-evaluation-summary-v1',primary_view='final_auto',scorer_version=VERSION,
        data_kind=dataset['data_kind'],phase=value['phase'],method=value['method'],views=views,splits=splits,
        cohort_counts=dataset['counts'],cohort_shortfall=dataset['shortfall'],cohort_distribution=dataset['splits'],
        holdout_status=dataset['holdout_status'],
        holdout_warnings=dataset['holdout_warnings'],policy_sha256=policy_hash,gold_ref=value['gold_ref'],
        gold_changed=bool(old and old['gold_ref']!=value['gold_ref']),policy_changed=bool(old and old['policy_sha256']!=policy_hash),
        initial_comparison=comparison,generalization_claim=False,
        semantic_feedback_used=value['review']['semantic_feedback_used'],exposure_status=value['review']['exposure_status'],
        m02=dict(eligible_as_declared=eligible,accuracy_percent=holdout['accuracy_percent'] if eligible else None,
                 meets_90_percent=holdout['accuracy_percent']>=90 if eligible else None,warnings=warnings))
    return dict(schema_version='extraction-evaluation-result-v1',scorer_version=VERSION,
        extraction_eval_id=value['extraction_eval_id'],evaluation_ref=hashlib.sha256(value['extraction_eval_id'].encode()).hexdigest(),
        selection_sha256=selection_sha256,evaluated_at=evaluated_at,method=value['method'],phase=value['phase'],
        gold_ref=value['gold_ref'],gold_sha256=gold_summary['gold_sha256'],gold_receipt_sha256=value['gold_receipt_sha256'],
        manifest_sha256=gold_summary['manifest_sha256'],instructions_sha256=gold_summary['instructions_sha256'],
        policy_sha256=policy_hash,run_ids=[d['run_id'] for d in documents],summary=summary,documents=documents)


def evaluate_record(content,gold_root=GOLD_ROOT,run_root=RUN_ROOT,initial_root=EVALUATION_ROOT,*,evaluated_at=None):
    value = _header(content)
    gold,runs,sources = _load_sources(value,gold_root,run_root)
    initial = _initial(value['initial_ref'],initial_root) if value['phase']=='retest' else None
    if initial:sources.update(initial['sources'])
    if evaluated_at is None:evaluated_at = datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
    result = _compute(value,gold,runs,initial,evaluated_at,hashlib.sha256(content).hexdigest())
    require(len(_json(result))<=MAX_BYTES,kind='input',code='EVALUATION_RESULT_TOO_LARGE')
    return dict(result=result,sources=sources)
