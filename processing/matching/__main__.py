"""한 요청·한 응답. 진단에 입력·본문·로컬 경로를 남기지 않는다."""

import json
import sys

def main():
    try:
        from .protocol import MAX_BYTES, OutputLimitError, ProtocolError, run
    except Exception:
        sys.stderr.write('CALCULATION_FAILED\n')
        return 1
    try:
        result = run(sys.stdin.buffer.read(MAX_BYTES + 1))
        content = bytearray()
        encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        for chunk in encoder.iterencode(result):
            encoded = chunk.encode('utf-8')
            if len(content) + len(encoded) + 1 > MAX_BYTES:
                raise OutputLimitError('CALCULATION_OUTPUT_TOO_LARGE')
            content.extend(encoded)
        content.extend(b'\n')
        sys.stdout.buffer.write(content)
        return 0
    except OutputLimitError:
        sys.stderr.write('CALCULATION_OUTPUT_TOO_LARGE\n')
        return 3
    except ProtocolError:
        sys.stderr.write('CALCULATION_INPUT_INVALID\n')
        return 2
    except Exception:
        sys.stderr.write('CALCULATION_FAILED\n')
        return 1


if __name__ == '__main__':
    sys.exit(main())
