"""포털 CSV와 공식 웹 상세를 비공개 수집 묶음으로 보관한다."""

from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

from processing.extraction.validation import decode

from .__main__ import (
    PORTAL_MAX_BYTES,
    SOURCE_PAGES,
    compare_sources,
    decode_input,
    read_raw,
)
from .cli import CollectionArguments
from .official_web import DETAIL_MAX_BYTES, detail_url, fetch_detail

CAPTURE_ROOT = Path(__file__).resolve().parents[2] / "data" / "private" / "collection"
CAPTURE_RECEIPT_MAX_BYTES = 64 * 1024 * 1024
PORTAL_SECTION = "collection-portal"
_UTC_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:\+00:00|Z)"
)


@contextmanager
def bundle_directory(root: Path, name: str):
    if root.resolve() != root:
        raise ValueError("수집 디렉터리에 심볼릭 링크를 사용할 수 없습니다.")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    options = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    root_fd = os.open(root, options)
    try:
        info = os.fstat(root_fd)
        if (root.resolve() != root or not os.path.samestat(info, root.lstat())
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError("수집 디렉터리는 실행 사용자만 접근할 수 있어야 합니다.")
        try:
            os.mkdir(name, mode=0o700, dir_fd=root_fd)
        except FileExistsError:
            raise ValueError("이미 사용 중인 수집 이름입니다.") from None
        bundle_fd = os.open(name, options, dir_fd=root_fd)
        try:
            yield bundle_fd
        finally:
            os.close(bundle_fd)
    finally:
        os.close(root_fd)


def private_stat(descriptor: int) -> os.stat_result:
    info = os.fstat(descriptor)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("수집 디렉터리와 원본은 실행 사용자만 접근할 수 있어야 합니다.")
    return info


@contextmanager
def open_archive(private_root: Path, relative: Path):
    options = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        with ExitStack() as stack:
            if (relative.is_absolute() or not relative.parts or ".." in relative.parts
                    or not private_root.is_absolute() or private_root.resolve(strict=True) != private_root):
                raise ValueError("수집 원본 루트와 상대 경로에 심볼릭 링크를 사용할 수 없습니다.")
            descriptor = os.open(private_root, options)
            stack.callback(os.close, descriptor)
            if (private_root.resolve(strict=True) != private_root
                    or not os.path.samestat(os.fstat(descriptor), private_root.lstat())):
                raise ValueError("수집 원본 루트가 확인 중에 바뀌었습니다.")
            for part in relative.parts:
                descriptor = os.open(part, options, dir_fd=descriptor)
                stack.callback(os.close, descriptor)
                private_stat(descriptor)
            yield descriptor
    except OSError:
        raise ValueError("수집 원본 또는 기록을 안전하게 읽을 수 없습니다.") from None


def read_capture_file(directory: int, filename: str, limit: int) -> bytes:
    if filename in ("", ".", "..") or Path(filename).name != filename:
        raise ValueError("수집 원본 파일 이름이 올바르지 않습니다.")
    options = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(filename, options, dir_fd=directory), "rb") as stream:
        if not stat.S_ISREG(private_stat(stream.fileno()).st_mode):
            raise ValueError("수집 원본과 기록은 일반 파일이어야 합니다.")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("수집 원본 또는 기록이 허용 크기를 초과했습니다.")
    return raw


def read_receipt(directory: int, filename: str) -> dict:
    data = decode(read_capture_file(directory, filename, CAPTURE_RECEIPT_MAX_BYTES),
                  "input", max_bytes=CAPTURE_RECEIPT_MAX_BYTES)
    if not isinstance(data, dict):
        raise ValueError("수집 기록 형식을 확인할 수 없습니다.")
    return data


def capture_timestamp(value: object) -> str:
    if isinstance(value, str) and _UTC_TIME.fullmatch(value):
        try:
            datetime.fromisoformat(value)
            return value
        except ValueError:
            pass
    raise ValueError("수집 기록의 수신 시각은 UTC 날짜와 시각이어야 합니다.")


def write_new(directory: int, name: str, content: bytes | bytearray) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(name, flags, mode=0o600, dir_fd=directory), "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def validate_name(name: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name) is None:
        raise ValueError("수집 이름은 영문자 또는 숫자로 시작하는 영문자·숫자·밑줄·하이픈 1~80자여야 합니다.")


def write_receipt(directory: int, name: str, record: dict) -> None:
    receipt = bytearray()
    for chunk in json.JSONEncoder(ensure_ascii=False, indent=2).iterencode(record):
        encoded = chunk.encode("utf-8")
        if len(receipt) + len(encoded) + 1 > CAPTURE_RECEIPT_MAX_BYTES:
            raise ValueError("수집 완료 기록이 64 MiB를 초과했습니다.")
        receipt.extend(encoded)
    receipt.extend(b"\n")
    write_complete(directory, name, receipt)


def write_complete(directory: int, name: str, content: bytes | bytearray) -> None:
    temporary = name + ".tmp"
    write_new(directory, temporary, content)
    os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    os.unlink(temporary, dir_fd=directory)


def capture(category: str, portal_file: Path, web_id: str, name: str, root: Path) -> dict:
    validate_name(name)
    directory = root / name
    if root.resolve() != root:
        raise ValueError("수집 디렉터리에 심볼릭 링크를 사용할 수 없습니다.")
    if directory.exists() or directory.is_symlink():
        raise ValueError("이미 사용 중인 수집 이름입니다.")

    url = detail_url(category, web_id)
    portal_raw = read_raw(portal_file, PORTAL_MAX_BYTES, "포털 CSV")
    web_raw = fetch_detail(category, web_id, limit=DETAIL_MAX_BYTES)
    fetched_at = datetime.now(UTC).isoformat()
    web_file = "web.json" if category == "culture" else "web.html"
    with bundle_directory(root, name) as bundle:
        write_new(bundle, "portal.csv", portal_raw)
        write_new(bundle, web_file, web_raw)
        comparison = None
        parse_error = None
        try:
            comparison = compare_sources(
                category, decode_input(portal_raw, "포털 CSV", portal_csv=True),
                decode_input(web_raw, "공식 웹 상세"), web_id,
            )
        except ValueError as error:
            parse_error = str(error)

        status = "parsed" if comparison is not None else "parse_failed"
        record = {
            "schema_version": "citizen-source-capture-v1",
            "capture_id": name,
            "category": category,
            "web_id": web_id,
            "web_fetched_at": fetched_at,
            "status": status,
            "portal": {"file": "portal.csv", "catalog_url": SOURCE_PAGES[category][0],
                       "sha256": hashlib.sha256(portal_raw).hexdigest()},
            "web": {"file": web_file, "source_url": url,
                    "sha256": hashlib.sha256(web_raw).hexdigest()},
            "comparison": comparison,
            "parse_error": parse_error,
        }
        write_receipt(bundle, "capture.json", record)
    return {"capture_id": name, "status": status}


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    parser.add_argument("category", choices=SOURCE_PAGES)
    parser.add_argument("--portal-csv", required=True, type=Path)
    parser.add_argument("--web-id", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    try:
        summary = capture(args.category, args.portal_csv, args.web_id, args.name, CAPTURE_ROOT)
    except ValueError as error:
        print(f"수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("수집 묶음을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "parsed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
