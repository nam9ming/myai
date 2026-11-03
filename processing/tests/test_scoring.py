import copy
import hashlib
import json
import unittest

from processing.evaluation.scoring import score_document
from processing.extraction.validation import ExtractionError

VERSION='60000000-0000-4000-8000-000000000001'


def fv(value=None,knowledge=None):
    known=knowledge=='known' or value is not None
    return dict(value=value,knowledge='known' if known else knowledge or 'not_stated',
                evidence_ids=['e1'] if known else [],reason=None if known else '합성 원문 미기재')


def fixture():
    text='합성 공사. 2026-11-07 10:00부터16:00까지, 익일 아님. 가상로 A, 주변 점포 대상. 예외 없음.'
    document=dict(data_kind='synthetic',document_version_id=VERSION,title='합성 공사',published_date='2026-11-01',
                  blocks=[dict(block_id='b1',page=None,text=text)])
    output=dict(schema_version='extract-schema-v1',document_version_id=VERSION,warnings=[],
        evidence=[dict(evidence_id='e1',block_id='b1',quote=text,start_char=0,end_char=len(text),
                       text_sha256=hashlib.sha256(text.encode()).hexdigest())],
        items=[dict(local_item_id='s1',title=fv('합성 공사'),types=fv(['construction']),
            occurrences=[dict(local_occurrence_id='o1',date_start=fv('2026-11-07'),date_end=fv('2026-11-07'),
                time_start=fv('10:00'),time_end=fv('16:00'),end_day_offset=fv(0),all_day=fv(False),
                recurrence_text=fv(),location_refs=['l1'])],
            locations=[dict(local_location_id='l1',name=fv('가상로 A'),address=fv(),kind=fv('point'))],
            applicability=fv('주변 점포'),exceptions=fv([]),route_names=fv(),stop_names=fv(),directions=fv(),lifecycle=fv('active'))])
    annotation=dict(schema_version='score-links-v1',item_links=[dict(slot_id='s1',local_item_id='s1',kind='match',
        occurrence_links=[dict(gold_occurrence_id='o1',local_occurrence_id='o1')])],generation_reviews=[])
    instructions=dict(version='synthetic-judgment-v1',normalization_version='gold-exact-v1',text='합성 판정 지침',synonyms=[])
    return document,output,annotation,instructions


class ScoringTest(unittest.TestCase):
    def setUp(self):
        self.document,self.gold,self.links,self.instructions=fixture()

    def score(self,prediction=None,links=None):
        raw=prediction if type(prediction) is bytes else json.dumps(prediction if prediction is not None else self.gold).encode()
        return score_document(json.dumps(self.document).encode(),json.dumps(self.gold).encode(),raw,
            json.dumps(links if links is not None else self.links).encode(),self.instructions)

    def source_text(self,text):
        self.document['blocks'][0]['text']=text
        self.gold['evidence'][0].update(quote=text,end_char=len(text),text_sha256=hashlib.sha256(text.encode()).hexdigest())

    def test_exact_fields_score_eight_without_subdividing_arrays(self):
        result=self.score()
        self.assertEqual(result['summary']['known_fields'],8)
        self.assertEqual(result['summary']['correct_fields'],8)
        self.assertEqual(result['summary']['accuracy_percent'],100.0)
        self.assertEqual(len(result['field_results']),8)
        self.assertEqual(result['summary']['generation_errors'],0)
        self.assertEqual(result['summary']['generation_rate_percent'],0.0)

    def test_failed_output_keeps_all_known_denominators(self):
        links=dict(schema_version='score-links-v1',item_links=[],generation_reviews=[])
        result=self.score(b'PRIVATE_BAD_OUTPUT',links)
        self.assertTrue(result['summary']['document_failed'])
        self.assertEqual((result['summary']['correct_fields'],result['summary']['known_fields']),(0,8))
        self.assertEqual(result['summary']['missing_events'],1)
        self.assertIsNone(result['summary']['generation_rate_percent'])
        self.assertNotIn('PRIVATE_',json.dumps(result))

    def test_missing_event_does_not_disappear_from_denominator(self):
        prediction=copy.deepcopy(self.gold);prediction.update(items=[],warnings=['NO_EVENT_FOUND'])
        links=dict(schema_version='score-links-v1',item_links=[],generation_reviews=[])
        result=self.score(prediction,links)
        self.assertEqual((result['summary']['correct_fields'],result['summary']['known_fields']),(0,8))
        self.assertEqual(result['summary']['missing_events'],1)
        self.assertFalse(result['summary']['document_failed'])

    def test_null_field_is_wrong_and_explicit_empty_is_not_unknown(self):
        prediction=copy.deepcopy(self.gold);prediction['items'][0]['exceptions']=fv()
        result=self.score(prediction)
        self.assertEqual((result['summary']['correct_fields'],result['summary']['known_fields']),(7,8))

    def test_all_unknown_core_fields_have_no_accuracy_and_no_fake_hundred(self):
        self.source_text('합성 공지. 세부 사항과 일정·장소·유형·대상·예외는 아직 안내되지 않았다.')
        self.document['title']='합성 공지';self.gold['items'][0]['title']=fv('합성 공지')
        item=self.gold['items'][0]
        for key in ('types','applicability','exceptions','route_names','stop_names','directions'):
            item[key]=fv(knowledge='ambiguous' if key=='types' else 'not_stated')
        for key in ('date_start','date_end','time_start','time_end','end_day_offset','all_day'):
            item['occurrences'][0][key]=fv()
        for key in ('name','address','kind'):item['locations'][0][key]=fv()
        result=self.score()
        self.assertEqual(result['summary']['known_fields'],0)
        self.assertIsNone(result['summary']['accuracy_percent'])

    def test_known_empty_value_at_unknown_gold_is_a_generation_error(self):
        self.source_text(self.document['blocks'][0]['text'].replace(' 예외 없음.',''))
        self.gold['items'][0]['exceptions']=fv()
        prediction=copy.deepcopy(self.gold);prediction['items'][0]['exceptions']=fv([])
        result=self.score(prediction)
        self.assertEqual((result['summary']['correct_fields'],result['summary']['known_fields']),(7,7))
        self.assertEqual(result['summary']['generation_errors'],1)
        self.assertEqual(result['summary']['output_fields'],8)
        self.assertEqual(result['summary']['generation_rate_percent'],12.5)

    def test_extra_known_claim_requires_semantic_generation_review(self):
        prediction=copy.deepcopy(self.gold);prediction['items'][0]['applicability']=fv('주변 점포와 모든 차량')
        result=self.score(prediction)
        self.assertEqual(result['summary']['correct_fields'],7)
        self.assertEqual(result['summary']['generation_review_pending'],1)
        self.assertIsNone(result['summary']['generation_rate_percent'])
        links=copy.deepcopy(self.links);links['generation_reviews']=[dict(local_item_id='s1',field='applicability',
                                                                       unsupported=True,reason='합성 추가 주장 판정')]
        result=self.score(prediction,links)
        self.assertEqual((result['summary']['generation_errors'],result['summary']['generation_rate_percent']),(1,12.5))

    def test_reviewed_unsupported_field_cannot_stay_correct(self):
        links=copy.deepcopy(self.links)
        links['generation_reviews']=[dict(local_item_id='s1',field='applicability',unsupported=True,
                                           reason='합성 근거 지지 여부의 부정 판정')]
        result=self.score(links=links)
        self.assertEqual(result['summary']['correct_fields'],7)
        self.assertFalse(next(r['correct'] for r in result['field_results'] if r['field']=='applicability'))

    def test_clock_zero_seconds_are_equal_and_wrong_offset_affects_end_only(self):
        prediction=copy.deepcopy(self.gold);prediction['items'][0]['occurrences'][0]['time_start']=fv('10:00:00')
        self.assertEqual(self.score(prediction)['summary']['correct_fields'],8)
        self.gold['items'][0]['occurrences'][0]['date_end']=fv('2026-11-08')
        self.source_text(self.document['blocks'][0]['text']+' 합성 추가 조건: 종료일은2026-11-08이다.')
        prediction=copy.deepcopy(self.gold)
        prediction['items'][0]['occurrences'][0]['end_day_offset']=fv(1)
        result=self.score(prediction)
        wrong=[r['field'] for r in result['field_results'] if r['correct'] is False]
        self.assertEqual(wrong,['time_end'])

    def test_explicit_all_day_is_a_known_time_answer_distinct_from_unstated(self):
        self.source_text(self.document['blocks'][0]['text'].replace('10:00부터16:00까지, 익일 아님','명시 종일'))
        occ=self.gold['items'][0]['occurrences'][0]
        occ.update(time_start=fv(),time_end=fv(),end_day_offset=fv(),all_day=fv(True))
        self.assertEqual(self.score()['summary']['known_fields'],8)
        prediction=copy.deepcopy(self.gold);prediction['items'][0]['occurrences'][0]['all_day']=fv()
        result=self.score(prediction)
        self.assertEqual((result['summary']['correct_fields'],result['summary']['known_fields']),(6,8))

    def test_all_day_cannot_hide_added_clocks_or_end_offset(self):
        self.source_text('합성 공사는 명시 종일이다. 시각과 익일 여부는 별도로 명시하지 않았다.')
        occ=self.gold['items'][0]['occurrences'][0]
        occ.update(time_start=fv(),time_end=fv(),end_day_offset=fv(),all_day=fv(True))
        for kind,correct,pending in (('clocks',6,2),('offset',7,1)):
            prediction=copy.deepcopy(self.gold);actual=prediction['items'][0]['occurrences'][0]
            if kind=='clocks':actual.update(time_start=fv('10:00'),time_end=fv('16:00'),end_day_offset=fv(0))
            else:actual['end_day_offset']=fv(0)
            with self.subTest(kind=kind):
                summary=self.score(prediction)['summary']
                self.assertEqual((summary['correct_fields'],summary['known_fields']),(correct,8))
                self.assertEqual(summary['generation_review_pending'],pending)
                self.assertIsNone(summary['generation_rate_percent'])

    def test_kind_only_location_is_known_and_unknown_kind_generation_is_counted(self):
        self.source_text('합성 공사는 점 위치에 해당하지만 이름과 주소는 미기재다.')
        location=self.gold['items'][0]['locations'][0];location.update(name=fv(),address=fv(),kind=fv('point'))
        self.assertEqual(self.score()['summary']['known_fields'],8)
        prediction=copy.deepcopy(self.gold);prediction['items'][0]['locations'][0]['kind']=fv('area')
        result=self.score(prediction)
        self.assertEqual((result['summary']['correct_fields'],result['summary']['known_fields']),(7,8))
        self.assertEqual(result['summary']['fields']['locations']['known'],1)
        self.assertIsNone(result['summary']['generation_rate_percent'])
        location['kind']=fv()
        summary=self.score(prediction)['summary']
        self.assertEqual(summary['known_fields'],7);self.assertEqual(summary['generation_errors'],1)

    def test_offset_only_claim_is_preserved_without_inventing_a_clock_denominator(self):
        self.source_text('합성 공사의 시각과 종일·익일 여부는 미기재다.')
        self.gold['items'][0]['occurrences'][0].update(time_start=fv(),time_end=fv(),end_day_offset=fv(),all_day=fv())
        prediction=copy.deepcopy(self.gold);prediction['items'][0]['occurrences'][0]['end_day_offset']=fv(1)
        result=self.score(prediction);summary=result['summary']
        self.assertEqual((summary['correct_fields'],summary['known_fields']),(6,6))
        self.assertEqual((summary['generation_errors'],summary['generation_rate_percent']),(1,12.5))
        end=next(r for r in result['field_results'] if r['field']=='time_end')
        self.assertFalse(end['gold_known']);self.assertTrue(end['output_auxiliary_claims'])

    def test_changed_offset_at_unknown_clock_cannot_be_cleared_by_review(self):
        self.source_text('합성 공사는 익일 이월이 아니며 시각·종일 여부는 미기재다.')
        self.gold['items'][0]['occurrences'][0].update(time_start=fv(),time_end=fv(),end_day_offset=fv(0),all_day=fv())
        self.assertEqual(self.score()['summary']['generation_errors'],0)
        prediction=copy.deepcopy(self.gold);prediction['items'][0]['occurrences'][0]['end_day_offset']=fv(1)
        summary=self.score(prediction)['summary']
        self.assertEqual((summary['correct_fields'],summary['known_fields']),(6,6))
        self.assertEqual((summary['generation_errors'],summary['generation_rate_percent']),(1,12.5))
        links=copy.deepcopy(self.links);links['generation_reviews']=[dict(local_item_id='s1',field='time_end',unsupported=False,
            reason='합성 오판 선언으로 알려진 익일 값을 바꾸는 오류를 상쇄할 수 없음')]
        with self.assertRaises(ExtractionError):self.score(prediction,links)

    def test_auxiliary_offset_cannot_move_between_unknown_clock_occurrences(self):
        self.two_occurrences()
        first,second=self.gold['items'][0]['occurrences']
        first.update(time_end=fv(),end_day_offset=fv(1));second.update(time_end=fv(),end_day_offset=fv())
        prediction=copy.deepcopy(self.gold);a,b=prediction['items'][0]['occurrences']
        a['end_day_offset'],b['end_day_offset']=b['end_day_offset'],a['end_day_offset']
        result=self.score(prediction)['summary']
        self.assertEqual(result['fields']['time_end']['known'],0)
        self.assertEqual(result['generation_errors'],1)

    def test_swapped_dates_with_equal_relations_still_require_correspondence_review(self):
        self.source_text(self.document['blocks'][0]['text']+' 같은 장소·시간으로2026-11-08에도 진행한다.')
        other=copy.deepcopy(self.gold['items'][0]['occurrences'][0])
        other.update(local_occurrence_id='o2',date_start=fv('2026-11-08'),date_end=fv('2026-11-08'))
        self.gold['items'][0]['occurrences'].append(other)
        self.links['item_links'][0]['occurrence_links'].append(dict(gold_occurrence_id='o2',local_occurrence_id='o2'))
        prediction=copy.deepcopy(self.gold);a,b=prediction['items'][0]['occurrences']
        for key in ('date_start','date_end'):a[key],b[key]=b[key],a[key]
        summary=self.score(prediction)['summary']
        self.assertEqual((summary['correct_fields'],summary['known_fields']),(6,8))
        self.assertEqual(summary['binding_errors'],0)
        self.assertEqual(summary['generation_review_pending'],2);self.assertIsNone(summary['generation_rate_percent'])
        links=copy.deepcopy(self.links);links['generation_reviews']=[dict(local_item_id='s1',field=key,unsupported=False,
            reason='합성 대응 오류지만 값 자체는 원문에 존재한다는 검토 선언') for key in ('date_start','date_end')]
        reviewed=self.score(prediction,links)['summary']
        self.assertEqual(reviewed['correct_fields'],6);self.assertEqual(reviewed['generation_rate_percent'],0)

    def test_approved_aliases_and_space_normalization_are_fixed(self):
        prediction=copy.deepcopy(self.gold);prediction['items'][0]['locations'][0]['name']=fv('  가상로   A ')
        self.assertEqual(self.score(prediction)['summary']['correct_fields'],8)
        prediction['items'][0]['locations'][0]['name']=fv('승인 별칭')
        self.instructions['synonyms']=[dict(field='locations',canonical='가상로 A',variants=['승인 별칭'])]
        self.assertEqual(self.score(prediction)['summary']['correct_fields'],8)
        prediction['items'][0]['locations'][0]['name']=fv('가까운 다른 장소')
        self.assertEqual(self.score(prediction)['summary']['correct_fields'],7)

    def test_types_and_target_directions_are_part_of_core_fields(self):
        self.source_text(self.document['blocks'][0]['text']+' 공사 대상 방향은 북향이다.')
        self.gold['items'][0]['directions']=fv(['북향'])
        prediction=copy.deepcopy(self.gold);prediction['items'][0]['directions']=fv(['남향'])
        prediction['items'][0]['types']=fv(['construction','traffic'])
        result=self.score(prediction)
        self.assertEqual(result['summary']['correct_fields'],6)
        self.assertEqual([r['field'] for r in result['field_results'] if r['correct'] is False],['types','applicability'])

    def two_occurrences(self):
        self.source_text(self.document['blocks'][0]['text']+' 추가 합성 일정은2026-11-08 10:00부터16:00까지 가상로 B이다.')
        item=self.gold['items'][0];other=copy.deepcopy(item['occurrences'][0])
        other.update(local_occurrence_id='o2',date_start=fv('2026-11-08'),date_end=fv('2026-11-08'),location_refs=['l2'])
        item['occurrences'].append(other)
        location=copy.deepcopy(item['locations'][0]);location.update(local_location_id='l2',name=fv('가상로 B'))
        item['locations'].append(location)
        self.links['item_links'][0]['occurrence_links'].append(dict(gold_occurrence_id='o2',local_occurrence_id='o2'))

    def test_swapped_places_are_wrong_despite_equal_value_sets(self):
        self.two_occurrences();prediction=copy.deepcopy(self.gold)
        a,b=prediction['items'][0]['occurrences'];a['location_refs'],b['location_refs']=b['location_refs'],a['location_refs']
        result=self.score(prediction)
        self.assertTrue(result['summary']['binding_errors'])
        for field in ('date_start','date_end','locations'):
            self.assertFalse(next(r['correct'] for r in result['field_results'] if r['field']==field))

    def test_single_value_error_does_not_corrupt_unrelated_fields(self):
        prediction=copy.deepcopy(self.gold);prediction['items'][0]['occurrences'][0]['time_end']=fv('15:00')
        result=self.score(prediction)
        self.assertEqual(result['summary']['binding_errors'],0)
        self.assertEqual([r['field'] for r in result['field_results'] if r['correct'] is False],['time_end'])

    def test_one_wrong_time_among_shared_values_does_not_corrupt_dates_or_places(self):
        self.two_occurrences();prediction=copy.deepcopy(self.gold)
        prediction['items'][0]['occurrences'][0]['time_end']=fv('15:00')
        result=self.score(prediction)
        self.assertEqual([r['field'] for r in result['field_results'] if r['correct'] is False],['time_end'])
        self.assertEqual(result['summary']['binding_errors'],0)

    def test_higher_order_binding_detects_parity_with_equal_pair_marginals(self):
        item=self.gold['items'][0];prototype=copy.deepcopy(item['occurrences'][0])
        location=copy.deepcopy(item['locations'][0]);location.update(local_location_id='l2',name=fv('가상로 B'))
        item['locations'].append(location);item['occurrences']=[]
        self.links['item_links'][0]['occurrence_links']=[]
        for index,(date,hour,ref) in enumerate((('2026-11-07',10,'l1'),('2026-11-07',11,'l2'),
                                               ('2026-11-08',10,'l2'),('2026-11-08',11,'l1'))):
            occ=copy.deepcopy(prototype);identity=f'joint{index}'
            occ.update(local_occurrence_id=identity,date_start=fv(date),date_end=fv(date),
                       time_start=fv(f'{hour}:00'),time_end=fv(f'{hour+1}:00'),location_refs=[ref])
            item['occurrences'].append(occ)
            self.links['item_links'][0]['occurrence_links'].append(dict(gold_occurrence_id=identity,local_occurrence_id=identity))
        self.source_text('합성 결합 시험: 11/7 10~11 A, 11/7 11~12 B, 11/8 10~11 B, 11/8 11~12 A. 나머지 조건과 예외 없음은 동일.')
        prediction=copy.deepcopy(self.gold)
        for occ in prediction['items'][0]['occurrences']:
            occ['location_refs']=['l2' if occ['location_refs']==['l1'] else 'l1']
        result=self.score(prediction)
        self.assertEqual(result['summary']['known_fields'],8)
        self.assertEqual(result['summary']['correct_fields'],3)

    def test_additional_event_is_reported_with_unassessed_generation(self):
        prediction=copy.deepcopy(self.gold);other=copy.deepcopy(prediction['items'][0])
        other['local_item_id']='extra';other['occurrences'][0]['local_occurrence_id']='extra-o'
        other['locations'][0].update(local_location_id='extra-l',name=fv('합성 추가 장소'))
        other['occurrences'][0]['location_refs']=['extra-l'];prediction['items'].append(other)
        links=copy.deepcopy(self.links);links['item_links'].append(dict(slot_id=None,local_item_id='extra',kind='additional',occurrence_links=[]))
        result=self.score(prediction,links)
        self.assertEqual(result['summary']['additional_events'],1)
        self.assertEqual(result['summary']['generation_review_pending'],8)
        self.assertIsNone(result['summary']['generation_rate_percent'])

    def test_missing_occurrence_keeps_its_known_fields_even_when_sets_overlap(self):
        self.two_occurrences();prediction=copy.deepcopy(self.gold);prediction['items'][0]['occurrences'].pop()
        links=copy.deepcopy(self.links);links['item_links'][0]['occurrence_links'].pop()
        result=self.score(prediction,links)
        self.assertFalse(next(r['correct'] for r in result['field_results'] if r['field']=='time_start'))

    def test_pure_occurrence_omission_is_wrong_without_unassessed_generation(self):
        self.two_occurrences()
        for keep_unused in (False,True):
            prediction=copy.deepcopy(self.gold);prediction['items'][0]['occurrences'].pop()
            if not keep_unused:prediction['items'][0]['locations'].pop()
            links=copy.deepcopy(self.links);links['item_links'][0]['occurrence_links'].pop()
            with self.subTest(keep_unused=keep_unused):
                summary=self.score(prediction,links)['summary']
                self.assertEqual((summary['correct_fields'],summary['known_fields']),(3,8))
                self.assertEqual(summary['generation_review_pending'],0)
                self.assertEqual(summary['generation_rate_percent'],0)
                self.assertEqual(summary['binding_errors'],0)

    def test_partial_known_fact_omissions_are_not_new_assertions(self):
        self.source_text(self.document['blocks'][0]['text']+' 교통도 해당한다. 가상주소. 노선R1/R2. 예외A/B.')
        item=self.gold['items'][0];item['types']=fv(['construction','traffic']);item['exceptions']=fv(['예외A','예외B'])
        item['route_names']=fv(['R1','R2']);item['locations'][0]['address']=fv('가상주소')
        prediction=copy.deepcopy(self.gold);actual=prediction['items'][0]
        actual.update(types=fv(['construction']),exceptions=fv(['예외A']),route_names=fv(['R1']))
        actual['locations'][0].update(address=fv(),kind=fv());actual['occurrences'][0]['end_day_offset']=fv()
        summary=self.score(prediction)['summary']
        self.assertEqual((summary['correct_fields'],summary['known_fields']),(3,8))
        self.assertEqual(summary['generation_review_pending'],0);self.assertEqual(summary['generation_rate_percent'],0)
        actual['exceptions']=fv([])
        self.assertGreater(self.score(prediction)['summary']['generation_review_pending'],0)

    def test_crossed_location_components_still_require_generation_review(self):
        item=self.gold['items'][0];item['locations'][0]['address']=fv('주소A')
        other=copy.deepcopy(item['locations'][0]);other.update(local_location_id='l2',name=fv('장소B'),address=fv('주소B'))
        item['locations'].append(other)
        prediction=copy.deepcopy(self.gold);prediction['items'][0]['locations'][0]['address']=fv('주소B')
        summary=self.score(prediction)['summary']
        self.assertEqual(summary['correct_fields'],7)
        self.assertEqual(summary['generation_review_pending'],1);self.assertIsNone(summary['generation_rate_percent'])

    def test_duplicate_events_are_not_merged_into_one_free_extra_match(self):
        prediction=copy.deepcopy(self.gold);other=copy.deepcopy(prediction['items'][0]);other['local_item_id']='p2'
        other['occurrences'][0]['local_occurrence_id']='p2o';other['locations'][0]['local_location_id']='p2l'
        other['occurrences'][0]['location_refs']=['p2l'];prediction['items'].append(other)
        links=copy.deepcopy(self.links);links['item_links'].append(dict(slot_id='s1',local_item_id='p2',kind='duplicate',occurrence_links=[]))
        result=self.score(prediction,links)
        self.assertEqual((result['summary']['correct_fields'],result['summary']['known_fields']),(8,8))
        self.assertEqual(result['summary']['duplicate_events'],1);self.assertEqual(result['summary']['output_fields'],16)
        links['item_links'][-1]['kind']='match'
        with self.assertRaises(ExtractionError):self.score(prediction,links)

    def test_annotations_must_cover_output_without_reusing_occurrences(self):
        for mode in ('missing-item','wrong-slot','duplicate-occurrence'):
            links=copy.deepcopy(self.links)
            if mode=='missing-item':links['item_links']=[]
            elif mode=='wrong-slot':links['item_links'][0]['slot_id']='unknown'
            else:links['item_links'][0]['occurrence_links']*=2
            with self.subTest(mode=mode),self.assertRaises(ExtractionError):self.score(links=links)
