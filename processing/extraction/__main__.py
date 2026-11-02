"""원문을 출력하지 않는 prepare/import/verify CLI."""

import argparse
import json
import sys

from .archive import DEFAULT_ROOT, freeze_run, import_run, prepare, verify_run
from .validation import ExtractionError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ExtractionError('ARGUMENT_INVALID', kind='input')


def main():
    parser = Parser(description='AI 추출 입력 준비·수동 원출력 기록·무결성 검증')
    commands = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    for name in ('prepare', 'import', 'verify', 'freeze'):
        command = commands.add_parser(name)
        command.add_argument('--root', default=DEFAULT_ROOT)
        if name in ('verify', 'freeze'):
            command.add_argument('run_id')
        else:
            command.add_argument('--input', required=True)
        if name == 'import':
            command.add_argument('--metadata', required=True)
            command.add_argument('--attempt', nargs=2, action='append', required=True, metavar=('PROMPT', 'OUTPUT'))
    try:
        args = parser.parse_args()
        if args.command == 'prepare':
            result = prepare(args.input, args.root)
        elif args.command == 'import':
            result = import_run(args.input, args.metadata, args.attempt, args.root)
        elif args.command == 'freeze':
            result = freeze_run(args.run_id, args.root)
        else:
            result = verify_run(args.run_id, args.root)
        sys.stdout.write(json.dumps(result, ensure_ascii=True, separators=(',', ':')) + '\n')
        status = result['receipt']['status'] if args.command == 'freeze' else result['status']
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
