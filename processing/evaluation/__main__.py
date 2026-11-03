"""원문과 정답을 출력하지 않는 데이터셋 검증 CLI."""

import argparse
import json
import sys

from processing.extraction.archive import _read
from processing.extraction.validation import ExtractionError
from .dataset import validate_manifest
from .bindings import EXTRACTION_ROOT, check_bindings
from .gold import check_gold
from .gold_storage import GOLD_ROOT, freeze_gold, verify_gold
from .records import EVALUATION_ROOT, evaluate_record
from .evaluation_storage import freeze_evaluation, verify_evaluation
from .reviews import REVIEW_ROOT, check_review, freeze_review, verify_review
from .comparison import COMPARISON_ROOT, compare_evaluations
from .comparison_storage import freeze_comparison, verify_comparison
from .matching import MATCHING_ROOT, evaluate_matching
from .matching_storage import freeze_matching, verify_matching
from .human_handoff import HANDOFF_ROOT, project_handoff
from .handoff_storage import freeze_handoff, verify_handoff
from .storage import DEFAULT_ROOT, freeze_dataset, verify_dataset


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ExtractionError('ARGUMENT_INVALID', kind='input')


def main():
    parser = Parser(description='D08 데이터셋·분할 검증·불변 보관')
    commands = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    for name in ('check', 'freeze', 'verify'):
        command = commands.add_parser(name)
        command.add_argument('--root', default=DEFAULT_ROOT)
        if name == 'verify':
            command.add_argument('dataset_ref')
        else:
            command.add_argument('--input', required=True)
    command = commands.add_parser('check-bindings')
    command.add_argument('--input', required=True)
    command.add_argument('--dataset-root', default=DEFAULT_ROOT)
    command.add_argument('--run-root', default=EXTRACTION_ROOT)
    for name in ('check-gold', 'freeze-gold', 'verify-gold'):
        command = commands.add_parser(name)
        if name != 'check-gold': command.add_argument('--root', default=GOLD_ROOT)
        if name == 'verify-gold':
            command.add_argument('gold_ref')
        else:
            command.add_argument('--input', required=True)
            command.add_argument('--dataset-root', default=DEFAULT_ROOT)
    for name in ('check-evaluation', 'freeze-evaluation', 'verify-evaluation'):
        command = commands.add_parser(name)
        if name != 'check-evaluation':command.add_argument('--root', default=EVALUATION_ROOT)
        if name == 'verify-evaluation':command.add_argument('evaluation_ref')
        else:
            command.add_argument('--input', required=True)
            command.add_argument('--gold-root', default=GOLD_ROOT)
            command.add_argument('--run-root')
            command.add_argument('--initial-root', default=EVALUATION_ROOT)
    for name in ('check-review', 'freeze-review', 'verify-review'):
        command = commands.add_parser(name)
        if name != 'check-review': command.add_argument('--root', default=REVIEW_ROOT)
        if name == 'verify-review': command.add_argument('review_ref')
        else:
            command.add_argument('--input', required=True)
            command.add_argument('--run-root', default=EXTRACTION_ROOT)
    for name in ('check-comparison', 'freeze-comparison', 'verify-comparison'):
        command = commands.add_parser(name)
        if name != 'check-comparison': command.add_argument('--root', default=COMPARISON_ROOT)
        if name == 'verify-comparison': command.add_argument('comparison_ref')
        else:
            command.add_argument('--input', required=True)
            command.add_argument('--evaluation-root', default=EVALUATION_ROOT)
    for name in ('check-matching', 'freeze-matching', 'verify-matching'):
        command = commands.add_parser(name)
        if name != 'check-matching': command.add_argument('--root', default=MATCHING_ROOT)
        if name == 'verify-matching': command.add_argument('matching_ref')
        else:
            command.add_argument('--input', required=True)
            command.add_argument('--comparison-root', default=COMPARISON_ROOT)
            command.add_argument('--initial-root', default=MATCHING_ROOT)
    for name in ('check-handoff', 'freeze-handoff', 'verify-handoff'):
        command = commands.add_parser(name)
        if name != 'check-handoff': command.add_argument('--root', default=HANDOFF_ROOT)
        if name == 'verify-handoff': command.add_argument('handoff_ref')
        else:
            command.add_argument('--input', required=True)
            command.add_argument('--review-root', default=REVIEW_ROOT)
    try:
        args = parser.parse_args()
        if args.command == 'check':
            result = validate_manifest(_read(args.input))
        elif args.command == 'freeze':
            result = freeze_dataset(args.input, args.root)
        elif args.command == 'check-bindings':
            result = check_bindings(_read(args.input), args.dataset_root, args.run_root)
        elif args.command == 'check-gold':
            result = check_gold(_read(args.input), args.dataset_root)
        elif args.command == 'freeze-gold':
            result = freeze_gold(args.input, args.root, args.dataset_root)
        elif args.command == 'verify-gold':
            result = verify_gold(args.gold_ref, args.root)
        elif args.command == 'check-evaluation':
            result = evaluate_record(_read(args.input), args.gold_root, args.run_root, args.initial_root)['result']['summary']
        elif args.command == 'freeze-evaluation':
            result = freeze_evaluation(args.input, args.root, args.gold_root, args.run_root, args.initial_root)
        elif args.command == 'verify-evaluation':
            result = verify_evaluation(args.evaluation_ref, args.root)
        elif args.command == 'check-comparison':
            result = compare_evaluations(_read(args.input), args.evaluation_root)['result']['summary']
        elif args.command == 'freeze-comparison':
            result = freeze_comparison(args.input, args.root, args.evaluation_root)
        elif args.command == 'verify-comparison':
            result = verify_comparison(args.comparison_ref, args.root)
        elif args.command == 'check-matching':
            result = evaluate_matching(_read(args.input), args.comparison_root, args.initial_root)['result']['summary']
        elif args.command == 'freeze-matching':
            result = freeze_matching(args.input, args.root, args.comparison_root, args.initial_root)
        elif args.command == 'verify-matching':
            result = verify_matching(args.matching_ref, args.root)
        elif args.command == 'check-handoff':
            result = project_handoff(_read(args.input), args.review_root)['summary']
        elif args.command == 'freeze-handoff':
            result = freeze_handoff(args.input, args.root, args.review_root)
        elif args.command == 'verify-handoff':
            result = verify_handoff(args.handoff_ref, args.root)
        elif args.command == 'check-review':
            result = check_review(_read(args.input), args.run_root)
        elif args.command == 'freeze-review':
            result = freeze_review(args.input, args.root, args.run_root)
        elif args.command == 'verify-review':
            result = verify_review(args.review_ref, args.root)
        else:
            result = verify_dataset(args.dataset_ref, args.root)
        sys.stdout.write(json.dumps(result, ensure_ascii=True, separators=(',', ':')) + '\n')
        return 0
    except ExtractionError as error:
        sys.stderr.write(error.code + '\n')
        return 3 if error.kind == 'archive' else 2
    except OSError:
        sys.stderr.write('DATASET_IO_FAILED\n')
        return 5
    except Exception:
        sys.stderr.write('DATASET_INTERNAL_FAILED\n')
        return 1


if __name__ == '__main__':
    sys.exit(main())
