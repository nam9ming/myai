"""같은 gold의 세 동결 평가를 필드별로 짝지어 관측 차이를 집계한다."""

from datetime import datetime, timezone
import hashlib

from processing.extraction.archive import REPO, _json, _read, _read_checked, _root
from processing.extraction.metadata import stamp
from processing.extraction.schema import HASH
from processing.extraction.validation import MAX_BYTES, decode, require, shape, text
from .dataset import _id
from .evaluation_storage import verify_evaluation
from .gold import FIELDS
from .records import EVALUATION_ROOT, _aggregate, _collect

COMPARISON_ROOT = REPO / 'data/private/evaluation/comparisons'
METHODS = dict(rules='final_auto', ai_auto='final_auto', human_reviewed='human_reviewed')
PAIRS = dict(rules_to_ai=('rules', 'ai_auto'), ai_to_human=('ai_auto', 'human_reviewed'),
             rules_to_human=('rules', 'human_reviewed'))
STATES = ('improved', 'worsened', 'unchanged_correct', 'unchanged_incorrect', 'not_scored')


def _check(condition, code='COMPARISON_INVALID'):
    require(condition, kind='input', code=code)


def _header(content):
    value = decode(content, 'input')
    shape(value, 'schema_version comparison_id evaluations', kind='input')
    _check(value['schema_version'] == 'extraction-comparison-v1')
    _id(value['comparison_id'])
    shape(value['evaluations'], 'rules ai_auto human_reviewed', kind='input')
    for selected in value['evaluations'].values():
        shape(selected, 'evaluation_ref receipt_sha256', kind='input')
        for key in selected: text(selected[key], kind='input', pattern=HASH)
    return value


def _load(value, root, compared_at):
    base = _root(root, create=False)
    results, sources = {}, {}
    for method in METHODS:
        selected = value['evaluations'][method]; ref = selected['evaluation_ref']
        directory = base / ref
        receipt = verify_evaluation(ref, base)
        raw = _read(directory / 'receipt.json')
        _check(raw == _json(receipt) and hashlib.sha256(raw).hexdigest() == selected['receipt_sha256'],
               'COMPARISON_RECEIPT_MISMATCH')
        _check(stamp(receipt['frozen_at'], '$') <= stamp(compared_at, '$'), 'COMPARISON_TIME_INVALID')
        result = decode(_read_checked(directory / 'result.json', receipt['artifacts']['result.json']), 'archive')
        _check(result['method'] == method, 'COMPARISON_METHOD_MISMATCH')
        results[method] = result
        sources.update(_collect(directory, [*receipt['artifacts'], 'identity.json', 'receipt.json'], f'evaluations/{ref}'))
    common = ('phase', 'scorer_version', 'gold_ref', 'gold_sha256', 'gold_receipt_sha256',
              'manifest_sha256', 'instructions_sha256')
    first = results['rules']
    _check(all(all(result[key] == first[key] for key in common) for result in results.values()),
           'COMPARISON_COHORT_MISMATCH')
    return results, sources


def _paired(results):
    documents = {method: {d['document_version_id']: d for d in result['documents']} for method, result in results.items()}
    versions = documents['rules'].keys()
    _check(all(docs.keys() == versions for docs in documents.values()), 'COMPARISON_COHORT_MISMATCH')
    cells, provenance = [], []
    for version in sorted(versions):
        docs = {method: documents[method][version] for method in METHODS}
        first = docs['rules']; ai, human = docs['ai_auto'], docs['human_reviewed']
        _check(all(d['document_id'] == first['document_id'] and d['split'] == first['split'] for d in docs.values()),
               'COMPARISON_COHORT_MISMATCH')
        _check(human['source_run_id'] == ai['run_id'] and human['source_receipt_sha256'] == ai['receipt_sha256'],
               'COMPARISON_PARENT_MISMATCH')
        provenance.append(dict(document_version_id=version, document_id=first['document_id'], split=first['split'],
            rules_run_id=first['run_id'], ai_run_id=ai['run_id'], human_review_id=human['review_id']))
        fields = {method: {(r['slot_id'], r['field']): r for r in docs[method][view]['field_results']}
                  for method, view in METHODS.items()}
        keys = fields['rules'].keys()
        _check(all(rows.keys() == keys for rows in fields.values()), 'COMPARISON_CELLS_MISMATCH')
        for key in sorted(keys):
            rows = {method: fields[method][key] for method in METHODS}; gold = rows['rules']
            _check(all(r['gold_known'] == gold['gold_known'] and r['event_id'] == gold['event_id'] for r in rows.values()),
                   'COMPARISON_CELLS_MISMATCH')
            transitions = {}
            for pair, (before, after) in PAIRS.items():
                a, b = rows[before]['correct'], rows[after]['correct']
                transitions[pair] = ('not_scored' if not gold['gold_known'] else
                    'unchanged_correct' if a is True and b is True else
                    'unchanged_incorrect' if a is False and b is False else
                    'improved' if b is True else 'worsened')
            cells.append(dict(document_version_id=version, document_id=first['document_id'], split=first['split'],
                event_id=gold['event_id'], slot_id=key[0], field=key[1], gold_known=gold['gold_known'],
                methods={method: {k: row[k] for k in ('local_item_id', 'correct', 'reason_codes')} for method, row in rows.items()},
                transitions=transitions))
    return cells, provenance


def _counts(cells, pair):
    counts = {state: 0 for state in STATES}
    for cell in cells: counts[cell['transitions'][pair]] += 1
    known = len(cells) - counts['not_scored']
    return dict(total_fields=len(cells), known_fields=known, **counts,
        delta_percent=(counts['improved'] - counts['worsened']) / known * 100 if known else None)


def _pairs(cells):
    return {pair: dict(**_counts(cells, pair), fields={field: _counts([c for c in cells if c['field'] == field], pair)
                       for field in FIELDS}) for pair in PAIRS}


def _method(result, primary):
    original = result['summary']
    views = {view: _aggregate([d[view]['summary'] for d in result['documents']]) for view in original['views']}
    splits = {split: {view: _aggregate([d[view]['summary'] for d in result['documents'] if d['split'] == split])
                     for view in views} for split in ('dev', 'holdout')}
    # 비율은 검증된 정수 분모로 다시 계산해 JSON Decimal을 근사 사실값으로 변환하지 않는다.
    m02 = dict(original['m02'])
    m02['accuracy_percent'] = splits['holdout'][primary]['accuracy_percent'] if m02['eligible_as_declared'] else None
    return dict(primary_view=primary, views=views, splits=splits, policy_sha256=result['policy_sha256'],
        semantic_feedback_used=original['semantic_feedback_used'], exposure_status=original['exposure_status'],
        initial_ref=original['initial_comparison']['initial_ref'] if original['initial_comparison'] else None, m02=m02)


def compare_evaluations(content, evaluation_root=EVALUATION_ROOT, *, compared_at=None):
    value = _header(content)
    if compared_at is None: compared_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    stamp(compared_at, '$')
    results, sources = _load(value, evaluation_root, compared_at)
    cells, documents = _paired(results)
    first = results['rules']; cohort = first['summary']
    summary = dict(protocol_version='extraction-comparison-summary-v1', data_kind=cohort['data_kind'], phase=first['phase'],
        scorer_version=first['scorer_version'], pairs=_pairs(cells),
        splits={split: _pairs([cell for cell in cells if cell['split'] == split]) for split in ('dev', 'holdout')},
        methods={method: _method(result, METHODS[method]) for method, result in results.items()},
        human_review_time=results['human_reviewed']['summary']['human_review_time'],
        cohort_counts=cohort['cohort_counts'], cohort_shortfall=cohort['cohort_shortfall'],
        cohort_distribution=cohort['cohort_distribution'], holdout_status=cohort['holdout_status'],
        holdout_warnings=cohort['holdout_warnings'], generalization_claim=False)
    result = dict(schema_version='extraction-comparison-result-v1', comparison_id=value['comparison_id'],
        comparison_ref=hashlib.sha256(value['comparison_id'].encode()).hexdigest(),
        selection_sha256=hashlib.sha256(content).hexdigest(), compared_at=compared_at, phase=first['phase'],
        gold_ref=first['gold_ref'], gold_sha256=first['gold_sha256'], gold_receipt_sha256=first['gold_receipt_sha256'],
        manifest_sha256=first['manifest_sha256'], instructions_sha256=first['instructions_sha256'],
        evaluations=value['evaluations'], documents=documents, field_results=cells, summary=summary)
    _check(len(_json(result)) <= MAX_BYTES, 'COMPARISON_RESULT_TOO_LARGE')
    return dict(result=result, sources=sources)
