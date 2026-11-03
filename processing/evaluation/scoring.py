"""문서별8필드 채점. 상세 사실은 비공개 결과이며 summary만 CLI에 출력한다."""

from itertools import combinations
import unicodedata

from processing.extraction.archive import _json
from processing.extraction.validation import ExtractionError, array, decode, parse_input, parse_output, require, shape, text
from .gold import FIELDS, _instructions

VERSION = 'field-score-v1'
TEMPORAL = FIELDS[:4]
BOUND = (*TEMPORAL,'locations')


def _check(condition):
    require(condition,kind='input',code='SCORING_ANNOTATION_INVALID')


def _normal(value):
    return unicodedata.normalize('NFC',' '.join(value.split()))


def _aliases(instructions):
    _instructions(instructions)
    result = {}
    for entry in instructions['synonyms']:
        for spelling in [entry['canonical'],*entry['variants']]:
            result[entry['field'],_normal(spelling)] = _normal(entry['canonical'])
    return result


def _projection(item,aliases):
    fields = {key:dict(provided=False,facts=set(),claims=set(),known_count=0) for key in FIELDS}

    def normalized(field,value):
        value = _normal(value)
        return aliases.get((field,value),value)

    def add(field,value):
        if value is not None:
            fields[field]['provided'] = True
            fields[field]['facts'].add(value)
            fields[field]['known_count'] += 1

    locations = {}
    for loc in item['locations']:
        atom = None
        if any(loc[k]['knowledge']=='known' for k in ('name','address','kind')):
            atom = tuple((k,normalized('locations',loc[k]['value']) if k!='kind' else loc[k]['value'])
                         for k in ('name','address','kind') if loc[k]['knowledge']=='known')
        locations[loc['local_location_id']] = atom
        add('locations',atom)
    rows,auxiliary = {},{}
    for occ in item['occurrences']:
        row = {}
        for key in ('date_start','date_end'):
            row[key] = ('date',occ[key]['value']) if occ[key]['knowledge']=='known' else None
        for key in ('time_start','time_end'):
            seconds = None
            claims = set()
            if occ[key]['knowledge']=='known':
                parts = [int(v) for v in occ[key]['value'].split(':')]
                seconds = parts[0]*3600 + parts[1]*60 + (parts[2] if len(parts)==3 else 0)
                claims.add(('clock',seconds))
            if occ['all_day']['knowledge']=='known':claims.add(('all_day',occ['all_day']['value']))
            offset = occ['end_day_offset']['value'] if key=='time_end' and occ['end_day_offset']['knowledge']=='known' else None
            if offset is not None:claims.add(('end_day_offset',offset))
            fields[key]['claims'].update(claims);fields[key]['known_count'] += len(claims)
            auxiliary.setdefault(occ['local_occurrence_id'],{})[key] = claims
            if occ['all_day']['knowledge']=='known' and occ['all_day']['value'] is True:
                value = ('all_day',seconds) + ((offset,) if key=='time_end' else ())
            elif seconds is not None:
                value = ('clock',seconds)
                if key=='time_end':value += (offset,)
            else:
                value = None
            row[key] = value
        for key in TEMPORAL:add(key,row[key])
        refs = {locations[ref] for ref in occ['location_refs'] if locations[ref] is not None}
        row['locations'] = tuple(sorted(refs,key=_json)) if refs else None
        rows[occ['local_occurrence_id']] = row
    for key in ('types','exceptions'):
        value = item[key]
        if value['knowledge']=='known':
            values = tuple(sorted({normalized(key,v) for v in value['value']}))
            add(key,('set',values))
    facets = {}
    for key in ('applicability','route_names','stop_names','directions'):
        value = item[key]
        if value['knowledge']=='known':
            v = value['value']
            v = tuple(sorted({normalized('applicability',x) for x in v})) if type(v) is list else normalized('applicability',v)
            add('applicability',(key,v));facets[key]=v
    return dict(fields=fields,rows=rows,facets=facets,auxiliary=auxiliary)


def _binding_fields(gold,prediction):
    # 값 오류로 줄어든 부분 교집합을 다른 필드의 결합 오류로 전파하지 않는다.
    shared = {key:gold['fields'][key]['facts'] if gold['fields'][key]['facts']==prediction['fields'][key]['facts']
              else set() for key in BOUND}
    failures = []
    for size in range(2,len(BOUND)+1):
        for keys in combinations(BOUND,size):
            if any(set(previous)<=set(keys) for previous in failures):continue
            if any(not shared[key] for key in keys):continue
            def relation(profile):
                result = set()
                for row in profile['rows'].values():
                    if any(row[k] is None for k in keys):continue
                    if any((not set(row[k])<=shared[k]) if k=='locations' else row[k] not in shared[k] for k in keys):continue
                    result.add(tuple(row[k] for k in keys))
                return result
            if relation(gold)!=relation(prediction):failures.append(keys)
    return set().union(*(set(keys) for keys in failures)) if failures else set()


def _annotations(content,gold,prediction):
    value = decode(content,'input')
    shape(value,'schema_version item_links generation_reviews',kind='input')
    _check(value['schema_version']=='score-links-v1')
    expected = {i['local_item_id']:i for i in gold['items']}
    actual = {i['local_item_id']:i for i in prediction['items']} if prediction is not None else {}
    links,matched = {},set()
    for entry in array(value['item_links'],'$.item_links','input'):
        shape(entry,'slot_id local_item_id kind occurrence_links',kind='input')
        local = text(entry['local_item_id'],kind='input')
        _check(local in actual and local not in links and entry['kind'] in ('match','duplicate','additional'))
        slot = entry['slot_id']
        if entry['kind']=='additional':_check(slot is None)
        else:
            text(slot,kind='input');_check(slot in expected)
        occurrences = array(entry['occurrence_links'],'$.occurrence_links','input')
        if entry['kind']=='match':
            _check(slot not in matched);matched.add(slot)
            gold_ids = {o['local_occurrence_id'] for o in expected[slot]['occurrences']}
            pred_ids = {o['local_occurrence_id'] for o in actual[local]['occurrences']}
            used_gold,used_pred = set(),set()
            for pair in occurrences:
                shape(pair,'gold_occurrence_id local_occurrence_id',kind='input')
                a,b = text(pair['gold_occurrence_id'],kind='input'),text(pair['local_occurrence_id'],kind='input')
                _check(a in gold_ids and b in pred_ids and a not in used_gold and b not in used_pred)
                used_gold.add(a);used_pred.add(b)
        else:_check(not occurrences)
        links[local] = entry
    _check(links.keys()==actual.keys())
    reviews = {}
    for entry in array(value['generation_reviews'],'$.generation_reviews','input'):
        shape(entry,'local_item_id field unsupported reason',kind='input')
        local = text(entry['local_item_id'],kind='input')
        _check(local in actual and entry['field'] in FIELDS and type(entry['unsupported']) is bool)
        text(entry['reason'],kind='input');key = (local,entry['field'])
        _check(key not in reviews);reviews[key] = entry
    return links,reviews


def _percentage(numerator,denominator):
    return numerator/denominator*100 if denominator else None


def score_document(input_bytes,gold_bytes,prediction_bytes,annotation_bytes,instructions):
    document = parse_input(input_bytes)
    gold = parse_output(gold_bytes,document)
    aliases = _aliases(instructions)
    error = None
    try:prediction = parse_output(prediction_bytes,document)
    except ExtractionError as failure:
        prediction = None;error = failure.code
    links,reviews = _annotations(annotation_bytes,gold,prediction)
    gold_profiles = {i['local_item_id']:_projection(i,aliases) for i in gold['items']}
    pred_profiles = {i['local_item_id']:_projection(i,aliases) for i in prediction['items']} if prediction is not None else {}
    primary = {link['slot_id']:link for link in links.values() if link['kind']=='match'}
    results,binding_slots = [],0
    auto_generation,correspondence_review = set(),set()
    for slot,expected in gold_profiles.items():
        link = primary.get(slot)
        local = link['local_item_id'] if link else None
        actual = pred_profiles[local] if link else None
        binding = _binding_fields(expected,actual) if actual else set()
        binding_slots += bool(binding)
        paired = {p['gold_occurrence_id']:p['local_occurrence_id'] for p in link['occurrence_links']} if link else {}
        for key in FIELDS:
            g = expected['fields'][key];p = actual['fields'][key] if actual else None
            correct = bool(p and p['provided'] and g['facts']==p['facts'] and key not in binding) if g['provided'] else None
            if actual and key in BOUND:
                for identity,row in expected['rows'].items():
                    predicted_row = actual['rows'].get(paired.get(identity))
                    predicted_value = predicted_row[key] if predicted_row else None
                    if row[key] is not None and row[key]!=predicted_value:
                        correct = False if g['provided'] else None
                        if predicted_value is not None:correspondence_review.add((local,key))
                    if row[key] is None and predicted_value is not None:
                        auto_generation.add((local,key));correct = False if g['provided'] else None
                    if key in ('time_start','time_end'):
                        known_claims = expected['auxiliary'][identity][key]
                        output_claims = actual['auxiliary'].get(paired.get(identity),{}).get(key,set())
                        if output_claims-known_claims:correspondence_review.add((local,key))
                        if not g['provided'] and output_claims-known_claims:
                            auto_generation.add((local,key))
            if actual and key=='applicability' and actual['facets'].keys()-expected['facets'].keys():
                auto_generation.add((local,key))
            if p and p['provided'] and not g['provided']:auto_generation.add((local,key))
            results.append(dict(slot_id=slot,local_item_id=local,field=key,gold_known=g['provided'],correct=correct,
                gold_values=sorted(g['facts'],key=_json),output_values=sorted(p['facts'],key=_json) if p else [],
                gold_auxiliary_claims=sorted(g['claims'],key=_json),
                output_auxiliary_claims=sorted(p['claims'],key=_json) if p else [],
                reason_codes=[] if correct or not g['provided'] else ['MISSING_EVENT' if not actual else
                    'BINDING_MISMATCH' if key in binding else 'VALUE_MISMATCH']))
    generation,pending = [],[]
    for local,actual in pred_profiles.items():
        link = links[local];expected = gold_profiles.get(link['slot_id'])
        binding = _binding_fields(expected,actual) if expected else set()
        for key in FIELDS:
            p = actual['fields'][key];g = expected['fields'][key] if expected else None
            claimed = p['provided'] or bool(p['claims'])
            gold_claimed = g is not None and (g['provided'] or bool(g['claims']))
            automatic = (local,key) in auto_generation or bool(g is not None and not gold_claimed and claimed)
            needs_review = bool(claimed and (g is None or p['facts']!=g['facts'] or p['claims']-g['claims']
                or (local,key) in correspondence_review or key in binding
                or p['known_count']>g['known_count']))
            review = reviews.get((local,key))
            if review:
                _check(claimed and not(automatic and review['unsupported'] is False))
            unsupported = automatic or bool(review and review['unsupported'])
            if unsupported:
                generation.append(dict(local_item_id=local,field=key,
                    reason='GOLD_UNKNOWN_VALUE' if automatic else 'REVIEWED_UNSUPPORTED',
                    review_reason=review['reason'] if review else None))
                for result in results:
                    if result['local_item_id']==local and result['field']==key:
                        if result['gold_known']:result['correct'] = False
                        result['reason_codes'].append('GENERATION_ERROR')
            elif needs_review and review is None:
                pending.append(dict(local_item_id=local,field=key,reason='GENERATION_REVIEW_REQUIRED'))
    by_field = {}
    for key in FIELDS:
        selected = [r for r in results if r['field']==key]
        known = sum(r['gold_known'] for r in selected);correct = sum(r['correct'] is True for r in selected)
        by_field[key] = dict(correct=correct,known=known,accuracy_percent=_percentage(correct,known))
    known = sum(v['known'] for v in by_field.values());correct = sum(v['correct'] for v in by_field.values())
    output_fields = len(pred_profiles)*len(FIELDS)
    summary = dict(scorer_version=VERSION,data_kind=document['data_kind'],known_fields=known,correct_fields=correct,
        accuracy_percent=_percentage(correct,known),fields=by_field,document_failed=prediction is None,
        error_code=error,missing_events=len(gold_profiles)-len(primary),
        duplicate_events=sum(l['kind']=='duplicate' for l in links.values()),
        additional_events=sum(l['kind']=='additional' for l in links.values()),binding_errors=binding_slots,
        output_fields=output_fields,generation_errors=len(generation),generation_review_pending=len(pending),
        generation_review_complete=not pending and prediction is not None,
        generation_rate_percent=_percentage(len(generation),output_fields) if not pending and prediction is not None else None)
    return dict(summary=summary,field_results=results,generation_errors=generation,generation_review_required=pending)
