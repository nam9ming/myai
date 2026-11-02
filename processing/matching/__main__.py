"""한 요청·한 응답. 진단에 입력·본문·로컬 경로를 남기지 않는다."""

import json
import sys

def main():
    try:
        from .protocol import MAX_BYTES, ProtocolError, run
    except Exception:
        sys.stderr.write('CALCULATION_FAILED\n')
        return 1
    try:
        result = run(sys.stdin.buffer.read(MAX_BYTES + 1))
        content = (json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n').encode('utf-8')
        if len(content) > MAX_BYTES:
            sys.stderr.write('CALCULATION_OUTPUT_TOO_LARGE\n')
            return 3
        sys.stdout.buffer.write(content)
        return 0
    except ProtocolError:
        sys.stderr.write('CALCULATION_INPUT_INVALID\n')
        return 2
    except Exception:
        sys.stderr.write('CALCULATION_FAILED\n')
        return 1


if __name__ == '__main__':
    sys.exit(main())
