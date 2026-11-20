"""부모가 deadline에 종료하는 내부 HTTP 작업. stdout은 상태 한 줄과 수신 본문이다."""

import http.client
import os
import sys

from .validation import MAX_BYTES


def main():
    key = os.environ.get('OPENAI_API_KEY', '')
    if not key or not all(33 <= ord(c) <= 126 for c in key):
        return 3
    request = sys.stdin.buffer.read()
    connection = http.client.HTTPSConnection('api.openai.com', timeout=120)
    response = None
    size = 0
    try:
        connection.request('POST', '/v1/responses', request,
                           {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
        response = connection.getresponse()
        sys.stdout.buffer.write(str(response.status).encode('ascii') + b'\n')
        sys.stdout.buffer.flush()
        while True:
            chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
            if not chunk:
                return 0 if response.length in (None, 0) else 3
            sys.stdout.buffer.write(chunk); sys.stdout.buffer.flush()
            size += len(chunk)
            if size > MAX_BYTES:
                return 4
            if response.length == 0:
                return 0
    except TimeoutError:
        return 2
    except (OSError, http.client.HTTPException):
        return 3
    finally:
        if response is not None:
            response.close()
        connection.close()


if __name__ == '__main__':
    raise SystemExit(main())
