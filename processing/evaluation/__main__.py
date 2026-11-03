"""원문과 정답을 출력하지 않는 데이터셋 검증 CLI."""

import argparse
import json
import sys

from processing.extraction.archive import _read
from processing.extraction.validation import ExtractionError
from .dataset import validate_manifest
from .bindings import EXTRACTION_ROOT, check_bindings
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
    try:
        args = parser.parse_args()
        if args.command == 'check':
            result = validate_manifest(_read(args.input))
        elif args.command == 'freeze':
            result = freeze_dataset(args.input, args.root)
        elif args.command == 'check-bindings':
            result = check_bindings(_read(args.input), args.dataset_root, args.run_root)
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
