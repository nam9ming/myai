import copy
import json
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]


def payload():
    return json.loads((ROOT / 'processing/examples/match-input.json').read_text(encoding='utf-8'))


def event_copy(event, number):
    event = copy.deepcopy(event)
    event['event_id'] = str(UUID(int=number))
    event['revision_id'] = str(UUID(int=number + 1000))
    event['occurrences'][0]['occurrence_id'] = str(UUID(int=number + 2000))
    return event


def unknown_time(event):
    event['occurrences'][0].update(precision='date_only', time_start=None, time_end=None, end_day_offset=None)


def select(p, value):
    p['query']['selection'] = value
    return p
