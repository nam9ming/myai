"""동결 원본의 전체 관측을 독립 수동 기대와 비교한다."""

from datetime import datetime, timezone
import hashlib
import unicodedata
from uuid import NAMESPACE_URL, uuid5

from processing.extraction.archive import REPO, _json, _read, _read_checked, _root
from processing.extraction.metadata import stamp
from processing.extraction.schema import HASH
from processing.extraction.validation import (MAX_BYTES, ExtractionError, array, decode, parse_input,
                                               parse_output, require, shape, text)
from processing.matching.engine import OutputLimitError, _encoded_size
from .comparison import COMPARISON_ROOT, METHODS
from .comparison_storage import verify_comparison
from .dataset import _id, _label
from .records import _collect, _header as evaluation_header, _load_sources
from . import matching_projection as projection

MATCHING_ROOT = REPO / 'data/private/evaluation/matching'
MATCHER_VERSION = 'matching-evaluation-v1'
VIEWS = ('gold_engine', 'rules_first_raw', 'rules_final_auto', 'ai_first_raw', 'ai_final_auto', 'human_reviewed')
CLASSES = ('candidate', 'needs_check', 'cancelled', 'excluded')
UNRESOLVED = ('missing', 'failed', 'not_computable', 'unavailable', 'partial', 'conflict')
REASONS = {'WINDOW_OUTSIDE', 'BUSINESS_CLOSED', 'TIME_NO_OVERLAP', 'DISTANCE_OUTSIDE', 'DATE_UNKNOWN',
           'TIME_UNKNOWN', 'BUSINESS_UNKNOWN', 'LOCATION_UNKNOWN', 'AREA_UNCERTAIN', 'SOURCE_STALE',
           'SOURCE_UNREACHABLE', 'RELATION_UNCERTAIN', 'CANCELLED'}


def _check(condition, code='MATCHING_INVALID'):
    require(condition, kind='input', code=code)


def _normal(value):
    return unicodedata.normalize('NFC', ' '.join(value.split())).casefold()


def _reference(value, name):
    shape(value, f'{name} receipt_sha256', kind='input')
    for field in value: text(value[field], kind='input', pattern=HASH)


def _header(content):
    value = decode(content, 'input')
    shape(value, 'schema_version matching_eval_id phase case_version comparison expectations_review context_review dictionary cases initial', kind='input')
    _check(value['schema_version'] == 'matching-evaluation-v1')
    _id(value['matching_eval_id']); _label(value['case_version'], 100)
    _check(value['phase'] in ('initial', 'retest'))
    _reference(value['comparison'], 'comparison_ref')
    if value['phase'] == 'initial': _check(value['initial'] is None)
    else:
        _reference(value['initial'], 'matching_ref')
        _check(value['initial']['matching_ref'] != hashlib.sha256(value['matching_eval_id'].encode()).hexdigest())
    review = value['expectations_review']
    shape(review, 'author reviewer authored_at reviewed_at basis cross_reviewed no_unresolved_disagreements', kind='input')
    for key in ('author', 'reviewer'): _label(review[key])
    _check(_normal(review['author']) != _normal(review['reviewer']))
    _check(review['basis'] in ('source_only', 'model_outputs_seen', 'engine_outputs_seen', 'unknown'))
    _check(review['cross_reviewed'] is True and review['no_unresolved_disagreements'] is True)
    _check(stamp(review['authored_at'], '$') <= stamp(review['reviewed_at'], '$'))
    context = value['context_review']
    shape(context, 'reviewer reviewed_at note', kind='input')
    _label(context['reviewer']); text(context['note'], kind='input'); stamp(context['reviewed_at'], '$')
    seen = set()
    for case in array(value['cases'], '$.cases', 'input', 1):
        shape(case, 'case_id context point query source_versions area_memberships expected', kind='input')
        _id(case['case_id']); _check(case['case_id'] not in seen); seen.add(case['case_id'])
        events = set()
        for target in array(case['expected'], '$.expected', 'input'):
            shape(target, 'event_id classification reason_codes note', kind='input')
            _id(target['event_id']); _check(target['event_id'] not in events); events.add(target['event_id'])
            _check(target['classification'] in CLASSES)
            codes = array(target['reason_codes'], '$.reason_codes', 'input')
            _check(all(type(code) is str and code in REASONS for code in codes) and len(codes) == len(set(codes)))
            text(target['note'], kind='input')
    return value


def _load(value, root, evaluated_at):
    selected = value['comparison']; ref = selected['comparison_ref']
    directory = _root(root, create=False) / ref
    receipt = verify_comparison(ref, root)
    raw = _read(directory / 'receipt.json')
    _check(raw == _json(receipt) and hashlib.sha256(raw).hexdigest() == selected['receipt_sha256'], 'MATCHING_COMPARISON_RECEIPT_MISMATCH')
    _check(stamp(receipt['frozen_at'], '$') <= stamp(evaluated_at, '$'), 'MATCHING_TIME_INVALID')
    artifacts = receipt['artifacts']; identity = _read(directory / 'identity.json')
    result = decode(_read_checked(directory / 'result.json', artifacts['result.json']), 'archive')
    methods = {}
    for method in METHODS:
        evaluation_ref = result['evaluations'][method]['evaluation_ref']
        prefix = f'evaluations/{evaluation_ref}'
        folder = directory / prefix
        control = evaluation_header(_read_checked(folder / 'selection.json', artifacts[f'{prefix}/selection.json']))
        gold, runs, _ = _load_sources(control, folder / 'gold', folder / 'runs')
        methods[method] = dict(selection=control, gold=gold, runs={r['document']['document_version_id']: r for r in runs})
    gold = methods['rules']['gold']
    documents = {d['document_id']: d for d in gold['manifest']['documents']}
    assignments = {d['document_id']: d for d in gold['manifest']['split_assignments']}
    versions = {v['document_version_id']: d['document_id'] for d in documents.values() for v in d['versions']}
    cohort = {}
    for version, answer in gold['documents'].items():
        document_id = versions[version]; assigned = assignments[document_id]
        cohort[version] = dict(document_id=document_id, official_url=documents[document_id]['official_url'],
            split=assigned['split'], split_group_id=assigned['split_group_id'], input=parse_input(gold['inputs'][version]),
            input_sha256=hashlib.sha256(gold['inputs'][version]).hexdigest(),
            anchors={a['slot_id']: a['event_id'] for a in answer['anchors']}, gold_output=answer['output'])
    sources = _collect(directory, [*artifacts, 'identity.json', 'receipt.json'], f'comparisons/{ref}')
    _check(all(sources[f'comparisons/{ref}/{name}'][1] == metadata for name, metadata in artifacts.items())
           and sources[f'comparisons/{ref}/receipt.json'][1]['sha256'] == selected['receipt_sha256']
           and sources[f'comparisons/{ref}/identity.json'][1] == dict(sha256=hashlib.sha256(identity).hexdigest(), size=len(identity)), 'MATCHING_SOURCE_CHANGED')
    return result, methods, cohort, sources


def _initial(value, root, evaluated_at):
    from .matching_storage import _verify_directory
    selected = value['initial']; ref = selected['matching_ref']
    directory = _root(root, create=False) / ref
    receipt = _verify_directory(directory, ref, initial_only=True)
    raw = _read(directory / 'receipt.json')
    _check(raw == _json(receipt) and hashlib.sha256(raw).hexdigest() == selected['receipt_sha256'], 'MATCHING_INITIAL_RECEIPT_MISMATCH')
    _check(stamp(receipt['frozen_at'], '$') <= stamp(evaluated_at, '$'), 'MATCHING_TIME_INVALID')
    artifacts = receipt['artifacts']; identity = _read(directory / 'identity.json')
    result = decode(_read_checked(directory / 'result.json', artifacts['result.json']), 'archive')
    selection = _header(_read_checked(directory / 'selection.json', artifacts['selection.json']))
    sources = _collect(directory, [*artifacts, 'identity.json', 'receipt.json'], f'initial/{ref}')
    _check(all(sources[f'initial/{ref}/{name}'][1] == metadata for name, metadata in artifacts.items())
           and sources[f'initial/{ref}/receipt.json'][1]['sha256'] == selected['receipt_sha256']
           and sources[f'initial/{ref}/identity.json'][1] == dict(sha256=hashlib.sha256(identity).hexdigest(), size=len(identity)), 'MATCHING_SOURCE_CHANGED')
    return dict(result=result, selection=selection, receipt=receipt, sources=sources)


def _consensus(rows):
    primary = [r for r in rows if r['kind'] in ('match', 'missing', 'failed')]
    known = {r['classification'] for r in rows if r['state'] == 'classified'}
    complete = all(r['state'] == 'classified' for r in rows)
    if len(known) > 1:
        state = 'conflict'
    elif primary and complete:
        reasons = {tuple(sorted(r['reason_codes'])) if r['reason_codes'] is not None else None for r in rows}
        return dict(state='classified', classification=next(iter(known)),
                    reason_codes=list(next(iter(reasons))) if len(reasons) == 1 and None not in reasons else None)
    elif not any(r['state'] == 'classified' for r in primary):
        states = {r['state'] for r in primary}
        state = next(iter(states)) if len(states) == 1 else 'partial'
    else: state = 'partial'
    return dict(state=state, classification=None, reason_codes=None)


def _percent(correct, total):
    return correct / total * 100 if total else None


def _agreement(correct, total):
    return dict(correct=correct, total=total, accuracy_percent=_percent(correct, total))


def _effect(gold, actual):
    left = {r['event_id']: r for r in gold}; total = len(left)
    classified = reasons = comparable = 0
    for row in actual:
        base = left[row['event_id']]
        valid = base['state'] == row['state'] == 'classified'
        comparable += valid
        same = valid and base['classification'] == row['classification']
        classified += same
        reasons += same and base['reason_codes'] is not None and row['reason_codes'] is not None and base['reason_codes'] == row['reason_codes']
    return dict(classification_agreement=_agreement(classified, total),
        classification_and_reasons=_agreement(reasons, total), comparable_events=comparable,
        gold_unresolved=sum(r['state'] != 'classified' for r in gold), method_unresolved=sum(r['state'] != 'classified' for r in actual))


def _metrics(rows, events, expected, *, documents=(), investigation=False):
    candidates = {('event', r['event_id']) if r['event_id'] is not None else
                  ('orphan', r['document_version_id'], r['local_item_id'])
                  for r in rows if r['state'] == 'classified' and r['classification'] == 'candidate'}
    observed = {}
    for row in rows:
        if row['state'] == 'classified' and row['event_id'] is not None:
            observed.setdefault(row['event_id'], set()).add(row['classification'])
    target = {('event', event) for event, value in expected.items() if value['classification'] == 'candidate'}
    tp, fp, fn = len(candidates & target), len(candidates - target), len(target - candidates)
    correct = reasons = over = needs_correct = needs_missing = cancel_missing = cancel_exposure = 0
    confusion = {c: {state: 0 for state in (*CLASSES, *UNRESOLVED)} for c in CLASSES}
    for row in events:
        wanted = expected[row['event_id']]; classification = row['classification'] if row['state'] == 'classified' else None
        equal = classification is not None and classification == wanted['classification']
        correct += equal
        reasons += equal and row['reason_codes'] is not None and sorted(row['reason_codes']) == sorted(wanted['reason_codes'])
        confusion[wanted['classification']][classification or row['state']] += 1
        present = ('event', row['event_id']) in candidates
        if wanted['classification'] == 'needs_check':
            needs_correct += equal; over += present; needs_missing += 'needs_check' not in observed.get(row['event_id'], ())
        if wanted['classification'] == 'cancelled':
            cancel_missing += 'cancelled' not in observed.get(row['event_id'], ()); cancel_exposure += present
    primary = [r for r in rows if r['kind'] in ('match', 'missing', 'failed')]
    anchor_correct = sum(r['state'] == 'classified' and r['classification'] == expected[r['event_id']]['classification'] for r in primary)
    anchor_reasons = sum(r['state'] == 'classified' and r['classification'] == expected[r['event_id']]['classification']
        and r['reason_codes'] is not None and sorted(r['reason_codes']) == sorted(expected[r['event_id']]['reason_codes']) for r in primary)
    return dict(events=len(expected), anchors=len(primary), document_versions=len(documents),
        document_failures=sum(d['document_failed'] for d in documents), empty_documents=sum(d['empty_output'] for d in documents),
        retrieval_presence=dict(tp=tp, fp=fp, fn=fn, predicted=len(candidates), expected=len(target),
            precision_percent=_percent(tp, tp + fp), recall_percent=_percent(tp, tp + fn)),
        complete_classification=_agreement(correct, len(expected)), classification_and_reasons=_agreement(reasons, len(expected)),
        target_agreement=dict(classification=_agreement(anchor_correct, len(primary)), classification_and_reasons=_agreement(anchor_reasons, len(primary))),
        confusion=confusion, states={state: sum(r['state'] == state for r in events) for state in ('classified', *UNRESOLVED)},
        needs_check=dict(expected=sum(v['classification'] == 'needs_check' for v in expected.values()), correct=needs_correct,
            candidate_overconfirmation=over, missing=needs_missing),
        cancelled=dict(expected=sum(v['classification'] == 'cancelled' for v in expected.values()), missing=cancel_missing, candidate_exposure=cancel_exposure),
        duplicate_outputs=sum(r['kind'] == 'duplicate' for r in rows),
        candidate_duplicates=sum(r['kind'] == 'duplicate' and r['classification'] == 'candidate' for r in rows),
        additional_outputs=sum(r['kind'] == 'additional' for r in rows),
        investigation_required=len(expected) - correct if investigation else 0)


def _aggregate(metrics):
    summed = {key: sum(m[key] for m in metrics) for key in ('events', 'anchors', 'document_versions', 'document_failures',
        'empty_documents', 'duplicate_outputs', 'candidate_duplicates', 'additional_outputs', 'investigation_required')}
    for key in ('complete_classification', 'classification_and_reasons'):
        summed[key] = _agreement(sum(m[key]['correct'] for m in metrics), sum(m[key]['total'] for m in metrics))
    summed['target_agreement'] = {key: _agreement(sum(m['target_agreement'][key]['correct'] for m in metrics),
        sum(m['target_agreement'][key]['total'] for m in metrics)) for key in ('classification', 'classification_and_reasons')}
    counts = {key: sum(m['retrieval_presence'][key] for m in metrics) for key in ('tp', 'fp', 'fn', 'predicted', 'expected')}
    summed['retrieval_presence'] = dict(**counts, precision_percent=_percent(counts['tp'], counts['tp'] + counts['fp']),
        recall_percent=_percent(counts['tp'], counts['tp'] + counts['fn']))
    for key, fields in (('needs_check', ('expected', 'correct', 'candidate_overconfirmation', 'missing')),
                        ('cancelled', ('expected', 'missing', 'candidate_exposure')), ('states', ('classified', *UNRESOLVED))):
        summed[key] = {field: sum(m[key][field] for m in metrics) for field in fields}
    summed['confusion'] = {c: {state: sum(m['confusion'][c][state] for m in metrics) for state in (*CLASSES, *UNRESOLVED)} for c in CLASSES}
    return summed


class _Budget:
    def __init__(self): self.size = 0

    def add(self, value):
        try: self.size += _encoded_size(value, MAX_BYTES - self.size) + 1
        except OutputLimitError: _check(False, 'MATCHING_RESULT_TOO_LARGE')
        _check(self.size <= MAX_BYTES, 'MATCHING_RESULT_TOO_LARGE')


def _observations(output, annotation, document, prepared, dictionary, view, budget):
    namespace = str(uuid5(NAMESPACE_URL, f"matching-evaluation:{prepared['case_id']}:{document['input']['document_version_id']}:{view}"))
    classified = projection.classify_output(output, annotation, document, prepared, dictionary, projection_id=namespace)
    version = document['input']['document_version_id']; failed = output is None
    available = prepared['source_availability'][version]
    links = annotation['item_links']; primary = {r['slot_id']: r for r in links if r['kind'] == 'match'}
    rows = []

    def append(kind, slot, link):
        local = link['local_item_id'] if link else None
        state = ('unavailable' if not available else 'failed' if failed else 'missing')
        calculated = dict(state=state, classification=None, reason_codes=None,
            disposition='not_available_at_cutoff' if not available else 'document_failed' if failed else 'missing',
            projection_limitations=[], projection_body_sha256=None, source_text_sha256=prepared['source_versions'][version]['text_sha256'])
        if link: calculated = classified[local]
        row = dict(kind=kind, document_version_id=version, document_id=document['document_id'],
            input_sha256=document['input_sha256'], slot_id=slot, local_item_id=local,
            event_id=document['anchors'].get(slot), split=document['split'], document_failed=failed,
            empty_output=output is not None and not output['items'], source_available=available, **calculated)
        budget.add(row); rows.append(row)

    for slot in sorted(document['anchors']):
        link = primary.get(slot)
        append('match' if link else 'failed' if failed else 'missing', slot, link)
    for link in links:
        if link['kind'] != 'match': append(link['kind'], link['slot_id'], link)
    status = dict(document_version_id=version, split=document['split'], document_failed=failed,
        empty_output=output is not None and not output['items'], source_available=available,
        **{key: prepared['source_versions'][version][key] for key in ('last_verified_at', 'latest_check_attempt_at',
            'check_result', 'current_last_verified_at', 'current_latest_check_attempt_at', 'current_check_result')})
    return rows, status


def _output(packet, view, document):
    try: return parse_output(packet['outputs'][view], document['input'])
    except ExtractionError: return None


def _case(value, prepared, cohort, methods, dictionary, budget):
    expected = {r['event_id']: r for r in value['expected']}
    events = {event: doc['split'] for doc in cohort.values() for event in doc['anchors'].values()}
    _check(expected.keys() == events.keys(), 'MATCHING_EXPECTED_COVERAGE_INVALID')
    observations = {view: [] for view in VIEWS}; statuses = {view: [] for view in VIEWS}
    for version, doc in sorted(cohort.items()):
        gold_annotation = dict(item_links=[dict(slot_id=slot, local_item_id=slot, kind='match', occurrence_links=[])
                                          for slot in doc['anchors']], generation_reviews=[], schema_version='score-links-v1')
        for view in VIEWS:
            if view == 'gold_engine': output, annotation = doc['gold_output'], gold_annotation
            else:
                method, source_view = ('human_reviewed', 'human_reviewed') if view == 'human_reviewed' else (
                    'rules' if view.startswith('rules_') else 'ai_auto', view.split('_', 1)[1])
                packet = methods[method]['runs'][version]
                output = _output(packet, source_view, doc)
                key = 'annotation' if method == 'human_reviewed' else 'first_annotation' if source_view == 'first_raw' else 'final_annotation'
                annotation = packet['document'][key]
            rows, status = _observations(output, annotation, doc, prepared, dictionary, view, budget)
            observations[view].extend(rows); statuses[view].append(status)
    results, metrics, splits = {}, {}, {split: {} for split in ('dev', 'holdout')}
    for view, rows in observations.items():
        grouped = {event: [] for event in events}
        for row in rows:
            if row['event_id'] is not None: grouped[row['event_id']].append(row)
        results[view] = []
        for event, linked in grouped.items():
            row = dict(event_id=event, split=events[event], expected=expected[event], **_consensus(linked))
            budget.add(row); results[view].append(row)
        metrics[view] = _metrics(rows, results[view], expected, documents=statuses[view], investigation=view == 'gold_engine')
        for split in splits:
            selected = {event: target for event, target in expected.items() if events[event] == split}
            splits[split][view] = _metrics([r for r in rows if r['split'] == split], [r for r in results[view] if r['split'] == split], selected,
                documents=[r for r in statuses[view] if r['split'] == split], investigation=view == 'gold_engine')
    effects = {}
    for view in VIEWS[1:]:
        effects[view] = dict(**_effect(results['gold_engine'], results[view]), additional_outputs=metrics[view]['additional_outputs'],
                            missing_outputs=sum(r['state'] in ('missing', 'failed') for r in observations[view]))
    context_warnings = []
    if prepared['context']['history_fidelity'] == 'reconstructed': context_warnings.append('RECONSTRUCTED_HISTORY')
    if prepared['context']['mode'] == 'replay' and any(source['current_check_result'] != 'verified' for source in prepared['source_versions'].values()):
        context_warnings.append('CURRENT_SOURCE_CONFIRMATION_REQUIRED')
    return dict(case_id=value['case_id'], observations=observations, event_results=results,
        target_agreement={view: metrics[view]['target_agreement'] for view in VIEWS}, extraction_effects=effects,
        summary=dict(views=metrics, splits=splits, documents=statuses, context=prepared['context'], context_warnings=context_warnings,
                     investigation_scope='projection_context_engine_and_manual_target'))


def _initial_comparison(value, old, comparison, cases):
    if old is None: return None
    previous = old['result']; selected = old['selection']
    _check(previous['manifest_sha256'] == comparison['manifest_sha256'], 'MATCHING_COHORT_MISMATCH')
    _check(previous['gold_ref'] != comparison['gold_ref'] or previous['gold_sha256'] == comparison['gold_sha256'], 'MATCHING_GOLD_VERSION_CONFLICT')
    same = selected['dictionary'] == value['dictionary'] and selected['cases'] == value['cases']
    _check(previous['case_version'] != value['case_version'] or same, 'MATCHING_CASE_VERSION_CONFLICT')
    old_cases = {case['case_id']: case for case in selected['cases']}
    old_results = {case['case_id']: case for case in previous['cases']}
    pairs = []
    for case, result in zip(value['cases'], cases):
        unchanged = (selected['dictionary'] == value['dictionary'] and case == old_cases.get(case['case_id'])
                     and previous['gold_sha256'] == comparison['gold_sha256'])
        before = old_results.get(case['case_id']); deltas = None
        if unchanged:
            deltas = {}
            for view in VIEWS:
                a, b = before['summary']['views'][view]['complete_classification'], result['summary']['views'][view]['complete_classification']
                deltas[view] = dict(initial_correct=a['correct'], initial_total=a['total'], current_correct=b['correct'], current_total=b['total'],
                    delta_percent=_percent(b['correct'], b['total']) - _percent(a['correct'], a['total']) if a['total'] and b['total'] else None)
        pairs.append(dict(case_id=case['case_id'], paired=unchanged, initial_metrics={view: _aggregate([before['summary']['views'][view]]) for view in VIEWS} if before else None,
                          current_metrics=result['summary']['views'], paired_deltas=deltas))
    return dict(initial_ref=value['initial']['matching_ref'], case_version_changed=previous['case_version'] != value['case_version'],
        dictionary_changed=selected['dictionary'] != value['dictionary'], cases_changed=selected['cases'] != value['cases'],
        gold_changed=previous['gold_ref'] != comparison['gold_ref'], source_changed=selected['comparison'] != value['comparison'], cases=pairs)


def evaluate_matching(content, comparison_root=COMPARISON_ROOT, initial_root=MATCHING_ROOT, *, evaluated_at=None):
    value = _header(content)
    if evaluated_at is None: evaluated_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    now = stamp(evaluated_at, '$')
    _check(stamp(value['expectations_review']['reviewed_at'], '$') <= now and stamp(value['context_review']['reviewed_at'], '$') <= now, 'MATCHING_TIME_INVALID')
    comparison, methods, cohort, sources = _load(value, comparison_root, evaluated_at)
    old = _initial(value, initial_root, evaluated_at) if value['phase'] == 'retest' else None
    if old: sources.update(old['sources'])
    dictionary = projection.validate_dictionary(value['dictionary'], evaluated_at)
    budget = _Budget(); cases = []
    for case in value['cases']:
        prepared = projection.prepare_case(case, cohort, dictionary, data_kind=comparison['summary']['data_kind'], evaluated_at=evaluated_at)
        result = _case(case, prepared, cohort, methods, dictionary, budget); budget.add(result['summary']); cases.append(result)
    initial = _initial_comparison(value, old, comparison, cases)
    source = comparison['summary']; warnings = []
    if value['phase'] != 'initial': warnings.append('RETEST_NOT_INITIAL_GENERALIZATION')
    if comparison['phase'] != 'initial': warnings.append('SOURCE_RETEST_NOT_INITIAL_GENERALIZATION')
    if value['expectations_review']['basis'] != 'source_only': warnings.append('EXPECTATIONS_OUTPUT_EXPOSURE_DECLARED')
    if stamp(value['expectations_review']['authored_at'], '$') >= stamp(comparison['compared_at'], '$'):
        warnings.append('EXPECTATIONS_AUTHORED_AFTER_SOURCE_COMPARISON')
    method_summary = {}
    for method, packet in methods.items():
        selection = packet['selection']; original = source['methods'][method]
        method_summary[method] = dict(policy_sha256=original['policy_sha256'], semantic_feedback_used=original['semantic_feedback_used'],
            exposure_status=original['exposure_status'], initial_ref=original['initial_ref'], warnings=original['m02']['warnings'],
            profile_basis=selection['policy'].get('profile_basis'),
            human_review_bases=sorted({run['human']['review']['basis'] for run in packet['runs'].values()}) if method == 'human_reviewed' else [])
    summary = dict(protocol_version='matching-evaluation-summary-v1', data_kind=source['data_kind'], phase=value['phase'],
        source_phase=comparison['phase'], case_version=value['case_version'], matcher_version=MATCHER_VERSION, case_count=len(cases),
        cohort_counts=source['cohort_counts'], cohort_shortfall=source['cohort_shortfall'], cohort_distribution=source['cohort_distribution'],
        holdout_status=source['holdout_status'], holdout_warnings=source['holdout_warnings'], methods=method_summary,
        human_review_time=source['human_review_time'], expectations_basis=value['expectations_review']['basis'], warnings=warnings,
        initial_changed=bool(initial and (initial['dictionary_changed'] or initial['cases_changed'] or initial['gold_changed'] or initial['source_changed'])),
        generalization_claim=False, views={view: _aggregate([case['summary']['views'][view] for case in cases]) for view in VIEWS},
        splits={split: {view: _aggregate([case['summary']['splits'][split][view] for case in cases]) for view in VIEWS} for split in ('dev', 'holdout')})
    result = dict(schema_version='matching-evaluation-result-v1', matching_eval_id=value['matching_eval_id'],
        matching_ref=hashlib.sha256(value['matching_eval_id'].encode()).hexdigest(), matcher_version=MATCHER_VERSION,
        selection_sha256=hashlib.sha256(content).hexdigest(), evaluated_at=evaluated_at, phase=value['phase'], case_version=value['case_version'],
        comparison=value['comparison'], gold_ref=comparison['gold_ref'], gold_sha256=comparison['gold_sha256'],
        manifest_sha256=comparison['manifest_sha256'], initial_comparison=initial, cases=cases, summary=summary)
    _Budget().add(result)
    _check(len(_json(result)) <= MAX_BYTES, 'MATCHING_RESULT_TOO_LARGE')
    return dict(result=result, sources=sources)
