"""원문을 출력하지 않는 추출 기록·초안 검증 CLI."""

import argparse
import json
import sys

from .archive import DEFAULT_ROOT, freeze_run, import_run, prepare, verify_run, verify_sealed_run
from .draft import check_draft, draft_run
from .rule_runs import RULE_ROOT, run_rules, verify_rules_run
from .validation import MAX_BYTES, ExtractionError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ExtractionError('ARGUMENT_INVALID', kind='input')


def main():
    parser = Parser(description='AI 추출 입력 준비·수동 원출력 기록·무결성 검증')
    commands = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    for name in ('prepare', 'import', 'verify', 'verify-sealed', 'freeze', 'draft', 'check-draft', 'run', 'rules-run', 'rules-verify'):
        command = commands.add_parser(name)
        command.add_argument('--root', default=RULE_ROOT if name.startswith('rules-') else DEFAULT_ROOT)
        if name in ('verify', 'verify-sealed', 'freeze', 'draft', 'check-draft', 'rules-verify'):
            command.add_argument('run_id')
        else:
            command.add_argument('--input', required=True)
        if name == 'import':
            command.add_argument('--metadata', required=True)
            command.add_argument('--attempt', nargs=2, action='append', required=True, metavar=('PROMPT', 'OUTPUT'))
        if name in ('run', 'rules-run'):
            command.add_argument('--preprocessing-version', required=True)
            command.add_argument('--run-id')
            if name == 'run':
                command.add_argument('--model')
            else:
                command.add_argument('--profile', required=True)
        if name == 'draft':
            for option in ('source', 'output', 'area-id', 'split-group-id', 'dictionary-version'):
                command.add_argument('--' + option, required=True)
    try:
        args = parser.parse_args()
        if args.command == 'prepare':
            result = prepare(args.input, args.root)
        elif args.command == 'import':
            result = import_run(args.input, args.metadata, args.attempt, args.root)
        elif args.command == 'run':
            from .api import run_api
            result = run_api(args.input, args.preprocessing_version, args.root, args.run_id, args.model)
        elif args.command == 'rules-run':
            result = run_rules(args.input, args.profile, args.preprocessing_version, args.root, args.run_id)
        elif args.command == 'rules-verify':
            result = verify_rules_run(args.run_id, args.root)
        elif args.command == 'freeze':
            result = freeze_run(args.run_id, args.root)
        elif args.command == 'verify-sealed':
            result = verify_sealed_run(args.run_id, args.root)
        elif args.command == 'draft':
            result = draft_run(args.run_id, args.source, args.output, args.area_id, args.split_group_id,
                               args.dictionary_version, args.root)
        elif args.command == 'check-draft':
            result = check_draft(args.run_id, sys.stdin.buffer.read(MAX_BYTES + 1), args.root)
        else:
            result = verify_run(args.run_id, args.root)
        sys.stdout.write(json.dumps(result, ensure_ascii=True, separators=(',', ':')) + '\n')
        status = result['receipt']['status'] if args.command in ('freeze', 'verify-sealed') else result['status']
        return 4 if status == 'failed' else 0
    except ExtractionError as error:
        sys.stderr.write(error.code + '\n')
        return 3 if error.kind == 'archive' else 2
    except OSError:
        sys.stderr.write('EXTRACTION_IO_FAILED\n')
        return 5
    except Exception:
        sys.stderr.write('EXTRACTION_INTERNAL_FAILED\n')
        return 1


if __name__ == '__main__':
    sys.exit(main())
