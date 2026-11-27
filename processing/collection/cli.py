"""수집 명령의 공통 인자 처리."""

import argparse
import sys


class CollectionArguments(argparse.ArgumentParser):
    """인자 오류를 종료 1로 알린다. 종료 2는 원본·실패 기록을 남긴 부분 결과에만 쓴다."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: 입력 오류: {message}\n")
