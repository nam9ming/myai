"""배포 산출물에 브라우저용 JavaScript 키만 넣는다. 키와 원본 파일은 출력하지 않는다."""
import json
import re
import stat
import sys
from pathlib import Path


def parse_key(text):
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')]
    if len(lines) != 1 or not re.fullmatch(r'KAKAO_MAP_JS_KEY=[a-fA-F0-9]{32}', lines[0]):
        raise ValueError('KAKAO_MAP_JS_KEY 형식을 확인해 주세요. JavaScript 키 한 개만 허용합니다.')
    return lines[0].split('=', 1)[1]


def inject(build):
    private = Path('/cephfs/home/team_asai1/.config/myai/kakao-maps.env')
    if private.is_symlink() or private.parent.is_symlink():
        raise ValueError('키 경로의 심볼릭 링크는 허용하지 않습니다.')
    if stat.S_IMODE(private.stat().st_mode) != 0o600:
        raise ValueError('키 파일 권한은 600이어야 합니다.')
    key = parse_key(private.read_text())
    target = Path(build) / 'map-config.js'
    if not target.is_file() or target.is_symlink():
        raise ValueError('빌드의 map-config.js가 필요합니다.')
    target.write_text('// 도메인 제한을 적용한 브라우저용 JavaScript 키입니다.\nwindow.myaiMapKey = ' + json.dumps(key) + ';\n')
    print('PASS JavaScript map key injected; original private file not copied')


if __name__ == '__main__':
    if sys.argv[1:] == ['--check']:
        assert parse_key('# comment\nKAKAO_MAP_JS_KEY=' + 'a' * 32 + '\n') == 'a' * 32
        for text in ['', 'ADMIN_KEY=' + 'a' * 32, 'KAKAO_MAP_JS_KEY=$(id)',
                     'KAKAO_MAP_JS_KEY=' + 'a' * 32 + '\nOTHER_KEY=x']:
            try:
                parse_key(text)
            except ValueError:
                continue
            raise AssertionError('잘못된 키 파일 형식을 허용했습니다.')
        print('PASS map key parser')
    else:
        inject(sys.argv[1])
