# 개발 DB 백업·복원·기동 인계

[B08](../../docs/spec/10_인원별WBS.md)·[DB 백업 기준](../../docs/spec/09_DB설계와트랜잭션.md#스키마-변경백업복구)의 전용 개발 DB 인계 절차다. MySQL8.4.13·Java21·Python3.13·표준 tar·POSIX 권한을 사용한다. 새 운영 백업 서비스나 공개 API는 없다. 아래 명령은 운영자가 선택한 개발 DB용이며 실제 연구실 서비스의 복구·배포를 수행한 기록이 아니다.

`local-publication rollback`은 같은 채널의 공개 포인터·감사 기록만 바꾼다. DB schema·작업 행·원본 파일 복원과 구별한다([공개 복구](review-publication.md#공개-내용실패복구)). Compose 볼륨 유지도 별도 백업을 대신하지 않는다.

## 먼저 정할 값과 중지 범위

- 원본과 대상은 운영자가 소유한 전용 개발 MySQL이다. 대상은 **새 서버의 새 빈 폐기 가능 schema**이며 기존 연구실 DB·계정은 사용하지 않는다.
- DB와 파일을 기록하기 **전에** 공개 앱·로컬 import/검토/공개·추출/인계 작업 및 다른 세션·예약 작업의 모든 쓰기와 DDL을 중지한다. 백업과 기준값 기록이 끝날 때까지 중지를 유지한다. `--single-transaction`만으로 DB와 파일의 공동 일관성을 보장하지 않는다.
- D03 원본·성공/실패 D05·사람 인계 중 DB가 참조하는 경로를 명시적으로 선택한다. D05 `raw_ref`와 인계 `directory`는 **같은 실제 절대 경로**로 복원해야 한다. SQL 경로 문자열 치환·symlink 우회·새 identity 발급을 복구로 세지 않는다.
- [로컬 관리 HTTP](local-management-api.md)를 사용하면 해당 프로세스의 쓰기도 중지하고 `MYAI_LOCAL_API_REQUEST_ROOT`를 별도 선택 root로 백업한다. 요청 root0700·원본 JSON0600·파일명 SHA와 bytes를 보존한다. domain 실패 원본도 포함될 수 있어 요청 파일 수를 DB 성공 건수로 세지 않으며 토큰 환경은 자료 백업에 넣지 않는다.
- 선택 경로에 D09 pack·사진·JSON/CSV 출력·자격증명이 없어야 한다. `data/private/` 전체를 tar로 묶지 않는다. [D09의 동의·기한·사본 처리](../../contracts/user-study.md#private-pack과-경계)는 별도다.
- MySQL client 설정 파일은 `[client]`의 host/port/user/password를 운영자가 따로 준비한 **0600 비공개 파일**이다. 백업/proof 밖에 두고 값·env 파일·SQL을 로그나 공개 PR에 붙이지 않는다. SQL도 비공개 원문·경로·검토 이력을 담는 민감 파일이다.

아래 `RECOVERY_*`는 이 문서의 Bash 변수이며 새 앱 설정이 아니다. 값은 직접 선택하고, 한 Bash 세션에서 실패 시 멈추는 상태로 실행한다.

| 변수 | 운영자가 제공할 값 |
|---|---|
| `RECOVERY_SOURCE_CNF`, `RECOVERY_TARGET_CNF` | 원본/새 대상의 비공개 client 설정 파일 절대 경로 |
| `RECOVERY_SOURCE_SCHEMA`, `RECOVERY_TARGET_SCHEMA` | system schema가 아닌 전용 schema 이름 |
| `RECOVERY_BACKUP_PARENT` | 선택 자료 root 밖에 준비한 비공개0700 부모 실제 절대 경로 |
| `RECOVERY_MATERIALS_ROOT` | 명시 선택한 자료 root 하나의 실제 절대 경로, symlink 없음 |
| `RECOVERY_CODE_VERSION` | 실제 사용한 릴리스 commit/코드 버전, 같은 버전 JAR·processing 소스 |

여러 자료 root가 필요하면 원래 경로별로 별도 tar·manifest 이름을 사용한다. 예제에 맞추려고 등록본을 한 root로 옮기지 않는다. 운영용 백업 위치·접근자·보존·RPO/RTO·점검 주기는 아직 정하지 않았다.

## 백업과 기준값

닫힌 일반 파일·디렉터리만 선택한다. 먼저 두 root의 실제 절대 경로와 포함 관계를 검사하며, 백업 부모가 자료 root와 같거나 그 안쪽이면 파일 생성 전에 종료2로 거부한다. 말미 `/`·`/./`는 경로로 정리하고 symlink 별칭·없는 root는 거부한다. 다음 함수는 표준 라이브러리로 원래 절대 경로와 각 상대 경로·bytes hash·크기·POSIX mode를 기록한다. 원본을 수정하지 않는다.

```bash
set -euo pipefail
set +x
umask 077
: "${RECOVERY_SOURCE_CNF:?private client configuration}"
: "${RECOVERY_SOURCE_SCHEMA:?dedicated source schema}"
: "${RECOVERY_BACKUP_PARENT:?private backup parent}"
: "${RECOVERY_MATERIALS_ROOT:?selected absolute materials root}"
: "${RECOVERY_CODE_VERSION:?verified release code version}"
python3.13 - "$RECOVERY_MATERIALS_ROOT" "$RECOVERY_BACKUP_PARENT" <<'PY'
from pathlib import Path
import sys

try:
    selected, parent = (Path(value) for value in sys.argv[1:])
    if not all(path.is_absolute() and path.is_dir() for path in (selected, parent)):
        raise ValueError
    materials = selected.resolve(strict=True)
    backup_parent = parent.resolve(strict=True)
    if materials != selected or backup_parent != parent:
        raise ValueError
    if backup_parent == materials or materials in backup_parent.parents:
        raise ValueError
except (OSError, ValueError):
    raise SystemExit(2)
PY
RECOVERY_MATERIALS_ROOT=$(cd "$RECOVERY_MATERIALS_ROOT" && pwd -P)
RECOVERY_BACKUP_PARENT=$(cd "$RECOVERY_BACKUP_PARENT" && pwd -P)
case "$(printf '%s' "$RECOVERY_SOURCE_SCHEMA" | tr '[:upper:]' '[:lower:]')" in
  ''|*[!a-z0-9_]*|mysql|sys|information_schema|performance_schema) exit 2 ;;
esac
RECOVERY_BACKUP_DIR=$(mktemp -d "$RECOVERY_BACKUP_PARENT/myai-recovery.XXXXXXXX")

write_materials_manifest() {
  python3.13 - "$RECOVERY_MATERIALS_ROOT" <<'PY'
import hashlib
import json
from pathlib import Path
import stat
import sys

root = Path(sys.argv[1])
if not root.is_absolute() or root.resolve(strict=True) != root or not root.is_dir():
    raise SystemExit("a real absolute materials directory is required")
entries = []
for path in [root, *sorted(root.rglob("*"))]:
    info = path.lstat()
    entry = {"path": path.relative_to(root).as_posix(),
             "mode": f"{stat.S_IMODE(info.st_mode):04o}"}
    if stat.S_ISDIR(info.st_mode):
        entry["kind"] = "directory"
    elif stat.S_ISREG(info.st_mode):
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        entry.update(kind="file", size=info.st_size, sha256=digest.hexdigest())
    else:
        raise SystemExit("symlinks and nonregular materials are not allowed")
    entries.append(entry)
print(json.dumps({"absolute_root": str(root), "entries": entries},
                 ensure_ascii=False, sort_keys=True, indent=2))
PY
}

capture_column_metadata() {
  mysql --defaults-extra-file="$1" --default-character-set=utf8mb4 \
    --batch --raw --skip-column-names --execute="
SELECT JSON_OBJECT(
  'table_catalog', TABLE_CATALOG, 'table_name', TABLE_NAME,
  'ordinal_position', ORDINAL_POSITION, 'column_name', COLUMN_NAME,
  'column_type', COLUMN_TYPE, 'data_type', DATA_TYPE,
  'column_default', COLUMN_DEFAULT, 'is_nullable', IS_NULLABLE,
  'character_set_name', CHARACTER_SET_NAME, 'collation_name', COLLATION_NAME,
  'character_maximum_length', CHARACTER_MAXIMUM_LENGTH,
  'character_octet_length', CHARACTER_OCTET_LENGTH,
  'numeric_precision', NUMERIC_PRECISION, 'numeric_scale', NUMERIC_SCALE,
  'datetime_precision', DATETIME_PRECISION, 'column_key', COLUMN_KEY,
  'extra', EXTRA, 'generation_expression', GENERATION_EXPRESSION,
  'column_comment', COLUMN_COMMENT, 'srs_id', SRS_ID
)
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA='$2'
ORDER BY TABLE_NAME, ORDINAL_POSITION"
}

printf 'code_version=%s\nmaterials_root=%s\n' \
  "$RECOVERY_CODE_VERSION" "$RECOVERY_MATERIALS_ROOT" \
  > "$RECOVERY_BACKUP_DIR/recovery-metadata.txt"
mysql --defaults-extra-file="$RECOVERY_SOURCE_CNF" \
  --default-character-set=utf8mb4 --batch "$RECOVERY_SOURCE_SCHEMA" \
  --execute='SELECT * FROM flyway_schema_history ORDER BY installed_rank' \
  > "$RECOVERY_BACKUP_DIR/schema-history.tsv"
mysql --defaults-extra-file="$RECOVERY_SOURCE_CNF" \
  --default-character-set=utf8mb4 --batch "$RECOVERY_SOURCE_SCHEMA" \
  --execute='SELECT snapshot_id, checksum FROM snapshots ORDER BY snapshot_id' \
  > "$RECOVERY_BACKUP_DIR/snapshot-checksums.tsv"
mysqldump --defaults-extra-file="$RECOVERY_SOURCE_CNF" \
  --single-transaction --no-tablespaces --set-gtid-purged=OFF --hex-blob \
  --default-character-set=utf8mb4 --skip-comments --skip-dump-date \
  --order-by-primary "$RECOVERY_SOURCE_SCHEMA" \
  > "$RECOVERY_BACKUP_DIR/database.sql.partial"
mv "$RECOVERY_BACKUP_DIR/database.sql.partial" "$RECOVERY_BACKUP_DIR/database.sql"
mysqldump --defaults-extra-file="$RECOVERY_SOURCE_CNF" \
  --single-transaction --no-tablespaces --set-gtid-purged=OFF --hex-blob \
  --default-character-set=utf8mb4 --skip-comments --skip-dump-date \
  --order-by-primary --no-create-info --skip-triggers "$RECOVERY_SOURCE_SCHEMA" \
  > "$RECOVERY_BACKUP_DIR/database-data.sql.partial"
mv "$RECOVERY_BACKUP_DIR/database-data.sql.partial" "$RECOVERY_BACKUP_DIR/database-data.sql"
capture_column_metadata "$RECOVERY_SOURCE_CNF" "$RECOVERY_SOURCE_SCHEMA" \
  > "$RECOVERY_BACKUP_DIR/columns.jsonl.partial"
mv "$RECOVERY_BACKUP_DIR/columns.jsonl.partial" "$RECOVERY_BACKUP_DIR/columns.jsonl"
write_materials_manifest > "$RECOVERY_BACKUP_DIR/materials.json.partial"
mv "$RECOVERY_BACKUP_DIR/materials.json.partial" "$RECOVERY_BACKUP_DIR/materials.json"
tar -cpf "$RECOVERY_BACKUP_DIR/materials.tar.partial" \
  -C "$(dirname "$RECOVERY_MATERIALS_ROOT")" "$(basename "$RECOVERY_MATERIALS_ROOT")"
mv "$RECOVERY_BACKUP_DIR/materials.tar.partial" "$RECOVERY_BACKUP_DIR/materials.tar"
(
  cd "$RECOVERY_BACKUP_DIR"
  shasum -a 256 database.sql database-data.sql columns.jsonl materials.tar \
    materials.json recovery-metadata.txt schema-history.tsv snapshot-checksums.tsv \
    > SHA256SUMS
)
```

`--databases`·`--all-databases`·`--force`를 추가하지 않는다. 단일 schema만 덤프하며 계정·권한·system schema·binlog/PITR는 포함하지 않는다. 실패한 `.partial`은 완성 백업으로 사용하지 않는다. 생성한 폴더0700·파일0600과 상위 경로 권한을 확인하고, MySQL/client·JDK·Python·tar 버전 및 실제 명령/종료 상태도 비공개 작업 기록에 남긴다.

## 새 빈 대상과 같은 경로에 복원

원본에서 직접 만든 신뢰할 수 있는 SQL·tar와 별도로 확인한 hash만 사용한다. SQL은 실행 가능한 입력이며 hash 일치만으로 안전성을 인증하지 않는다. 대상 client 설정이 새 전용 서버를 가리키는지 운영자가 먼저 확인한다. 기존 DB를 비우거나 덮어쓰는 절차는 제공하지 않는다.

```bash
: "${RECOVERY_TARGET_CNF:?new dedicated target client configuration}"
: "${RECOVERY_TARGET_SCHEMA:?new disposable target schema}"
case "$(printf '%s' "$RECOVERY_TARGET_SCHEMA" | tr '[:upper:]' '[:lower:]')" in
  ''|*[!a-z0-9_]*|mysql|sys|information_schema|performance_schema) exit 2 ;;
esac
(
  cd "$RECOVERY_BACKUP_DIR"
  shasum -a 256 -c SHA256SUMS
)
mysql --defaults-extra-file="$RECOVERY_TARGET_CNF" \
  --execute="CREATE DATABASE \`$RECOVERY_TARGET_SCHEMA\` CHARACTER SET utf8mb4"
RECOVERY_TABLE_COUNT=$(mysql --defaults-extra-file="$RECOVERY_TARGET_CNF" \
  --batch --skip-column-names \
  --execute="SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$RECOVERY_TARGET_SCHEMA'")
test "$RECOVERY_TABLE_COUNT" = 0
mysql --defaults-extra-file="$RECOVERY_TARGET_CNF" \
  --default-character-set=utf8mb4 "$RECOVERY_TARGET_SCHEMA" \
  < "$RECOVERY_BACKUP_DIR/database.sql"
```

`CREATE DATABASE`는 대상이 이미 있으면 실패한다. 복원 SQL이 중간에 실패하면 DDL/일부 행이 남을 수 있다. 대상에 재시도하거나 `--force`로 계속하지 말고 **그 폐기 가능한 대상 전체를 버린 뒤 새 대상부터 다시 시작한다**. 전체 SQL의 원자적 rollback을 보장하지 않는다.

자료는 같은 UID의 POSIX 환경에서, 원래 root가 없고 부모 경로가 신뢰할 수 있을 때만 복원한다. 원래 root가 있으면 멈추며 삭제·덮어쓰지 않는다. tar의 목록과 기록한 root를 먼저 확인한다.

```bash
test ! -e "$RECOVERY_MATERIALS_ROOT"
test ! -L "$RECOVERY_MATERIALS_ROOT"
RECOVERY_MATERIALS_PARENT=$(dirname "$RECOVERY_MATERIALS_ROOT")
test "$(cd "$RECOVERY_MATERIALS_PARENT" && pwd -P)" = "$RECOVERY_MATERIALS_PARENT"
tar -tf "$RECOVERY_BACKUP_DIR/materials.tar"
tar -xpf "$RECOVERY_BACKUP_DIR/materials.tar" -C "$RECOVERY_MATERIALS_PARENT"
write_materials_manifest > "$RECOVERY_BACKUP_DIR/materials-restored.json"
cmp "$RECOVERY_BACKUP_DIR/materials.json" "$RECOVERY_BACKUP_DIR/materials-restored.json"
mysqldump --defaults-extra-file="$RECOVERY_TARGET_CNF" \
  --single-transaction --no-tablespaces --set-gtid-purged=OFF --hex-blob \
  --default-character-set=utf8mb4 --skip-comments --skip-dump-date \
  --order-by-primary "$RECOVERY_TARGET_SCHEMA" \
  > "$RECOVERY_BACKUP_DIR/database-restored.sql.partial"
mv "$RECOVERY_BACKUP_DIR/database-restored.sql.partial" "$RECOVERY_BACKUP_DIR/database-restored.sql"
mysqldump --defaults-extra-file="$RECOVERY_TARGET_CNF" \
  --single-transaction --no-tablespaces --set-gtid-purged=OFF --hex-blob \
  --default-character-set=utf8mb4 --skip-comments --skip-dump-date \
  --order-by-primary --no-create-info --skip-triggers "$RECOVERY_TARGET_SCHEMA" \
  > "$RECOVERY_BACKUP_DIR/data-restored.sql.partial"
mv "$RECOVERY_BACKUP_DIR/data-restored.sql.partial" "$RECOVERY_BACKUP_DIR/data-restored.sql"
capture_column_metadata "$RECOVERY_TARGET_CNF" "$RECOVERY_TARGET_SCHEMA" \
  > "$RECOVERY_BACKUP_DIR/columns-restored.jsonl.partial"
mv "$RECOVERY_BACKUP_DIR/columns-restored.jsonl.partial" "$RECOVERY_BACKUP_DIR/columns-restored.jsonl"
cmp "$RECOVERY_BACKUP_DIR/database-data.sql" "$RECOVERY_BACKUP_DIR/data-restored.sql"
cmp "$RECOVERY_BACKUP_DIR/columns.jsonl" "$RECOVERY_BACKUP_DIR/columns-restored.jsonl"
RECOVERY_FULL_DIFF_STATUS=0
diff -u "$RECOVERY_BACKUP_DIR/database.sql" "$RECOVERY_BACKUP_DIR/database-restored.sql" \
  > "$RECOVERY_BACKUP_DIR/database-full.diff" || RECOVERY_FULL_DIFF_STATUS=$?
test "$RECOVERY_FULL_DIFF_STATUS" -le 1
(
  cd "$RECOVERY_BACKUP_DIR"
  shasum -a 256 database.sql database-restored.sql database-data.sql \
    data-restored.sql columns.jsonl columns-restored.jsonl database-full.diff \
    > RESTORE_SHA256SUMS
)
```

동일 MySQL/client 버전에서 앱 기동 전 행 전용 SQL과 유효 열 metadata를 정확히 대조한다. 열 metadata는 테이블명·열 순서로 정렬하며 열 이름/형식/default/null/문자셋/collation/길이·정밀도/EXTRA/생성식/키/설명/SRS를 포함한다. 새 schema·계정의 이름 공간이 달라도 비교하도록 TABLE_SCHEMA·계정별 PRIVILEGES는 제외한다. Flyway·source_reviews·부모 운영 번호/hash·실패 D05·revision·공개 head/audit의 모든 행도 빠뜨리지 않는다.

**전체 SQL 두 원문은 수정·덮어쓰기 없이 hash와 diff를 보존한다.** MySQL은 같은 유효 문자셋도 복원 뒤 열 DDL에 `CHARACTER SET utf8mb4`를 명시해 출력할 수 있다. `RECOVERY_FULL_DIFF_STATUS=1`이면 앱 기동 전에 모든 제약·인덱스·테이블 옵션을 포함한 raw diff를 운영자가 확인한다. 유효 열 metadata가 정확히 같고 각 차이가 같은 `COLLATE utf8mb4_0900_as_cs` 앞의 중복 `CHARACTER SET utf8mb4` 표기뿐인지 확인해야 하며, **다른 차이는 중지·조사한다**. 전체 SQL의 문자셋 문자열을 일괄 제거하거나 복원 SQL을 고치지 않는다. 위 명령이 diff를 기록했다는 사실만으로 자동 통과하지 않는다. 합성 통합 시험의 엄격한 전체 schema·행 검증과 수동 운영 점검을 구별한다.

파일 manifest는 D05 frozen 파일0400/디렉터리0500·인계 전체0400/0500을 포함한 **기존 mode 그대로**여야 한다. 원래 경로 부재나 다른 경로 복원은 후속 원본 검증을 통과한 복구가 아니다.

## 앱 기동·재검증·정지

[기존 DB/Python 설정](../README.md#mysql-기초-실행)을 따른다. Compose 원본을 기동할 때는 `docker compose --env-file .env up -d --wait`, DB 정지는 `docker compose stop`이며 볼륨을 삭제하지 않는다. 이 Compose는 `myai_dev`용이므로 새 복원 대상 선택 절차와 혼동하지 않는다. Compose의 `.env`는 Java 프로세스에 자동 전달되지 않는다.

| 환경변수 이름 | 인계 내용 |
|---|---|
| `DB_URL`, `DB_USERNAME`, `DB_PASSWORD` | 새 복원 대상 JDBC URL·계정·비밀값 별도 전달, UTC session/UTF-8 설정 유지 |
| `MYSQL_ROOT_PASSWORD`, `MYSQL_PORT` | 기존 개발 Compose 전용, 실제 값은 공개 기록에서 제외 |
| `MYAI_PYTHON_WORKDIR`, `MYAI_PYTHON_EXECUTABLE` | 같은 릴리스 processing 소스의 절대 경로·Python3.13 실행 파일 |
| `MYAI_CALC_TIMEOUT_MS`, `PORT`, `CORS_ALLOWED_ORIGIN` | 기존 계산 제한·앱 포트·정확한 개발 origin 설정 |

```bash
: "${DB_URL:?restored dedicated database JDBC URL}"
: "${DB_USERNAME:?dedicated application account}"
: "${DB_PASSWORD:?privately supplied password}"
: "${MYAI_PYTHON_WORKDIR:?matching release processing repository}"
export DB_URL DB_USERNAME DB_PASSWORD MYAI_PYTHON_WORKDIR
export MYAI_PYTHON_EXECUTABLE=python3.13
java -jar backend/build/libs/myai-backend-0.1.0.jar --spring.profiles.active=public
```

저장소 루트에서 전경 실행하고 종료는 해당 앱 터미널의 Ctrl-C를 사용한다. JAR에 Python 소스는 들어 있지 않다. `/health`200만으로 복원 성공을 판정하지 않는다. [공개 API](public-snapshot-api.md)의 같은 외부 조회조건·snapshot·고정 replay 문맥으로 config/detail/matches와 [snapshot export](review-publication.md#snapshot-json-내보내기)를 복원 전후 대조한다. 응답의 `generated_at`과 config의 `server_now`만 명시적으로 정규화하고 사실·ID·계산값은 제거하지 않는다.

선택 원본은 기존 [D05 검증/정확 재등록](extraction-run-import.md)·[사람 인계 정확 재사용](human-handoff-import.md) 경로로 다시 검사한다. 공개 snapshot 조회만 정상이어도 원본 소비 준비 완료는 아니다. 앱을 정지·재기동한 뒤에도 행/seed가 늘지 않고 같은 DB·API·export 결과인지 확인한다. 실제 사용권·자료 승인·운영 서버/프록시·계정/권한 재설정은 별도 사람 작업이다.

## 실제 개발 자료47건의 DB 검증

2026-11-04 새 전용 MySQL8.4.13/V4에서 기존10개 CLI 입력으로 D03 3건·D05 실패3/성공3·숨김 D06 3건을 재구성한 뒤 신규44건의 D03만 추가했다. 과거 실제3건 SQL은 V3 data-only·positional INSERT이므로 수정·주입하지 않았으며, 과거 batch ID·등록 시각까지 동일한 복원으로 세지 않는다.

실제 JAR28회로 초회 이전의 늦은 UUID 충돌 전체 rollback·canonical44 등록·exact/다른 root 재실행·공백 alias의 새 batch·metadata 충돌/원문 누락 거부를 확인했다. 전체16테이블/122행의 full/data SQL을 새 빈 서버에 복원하고 기존10개+canonical44를 정확 재실행했다. data SQL bytes와 전체 행/schema/Flyway가 같고 full SQL의 동등한 charset 표시 차이만 제한적으로 대조했으며 두 원문·diff를 보존했다. 공백 alias는 문서/버전 증가 없이 source batch1개만 추가한 실제 대조군이다.

원래 선택2개 root와 final package-v2만 tar로 백업해307파일/30디렉터리의 member bytes/mode/path를 대조했다. 원래 canonical 경로는 삭제·덮어쓰지 않았다. **이번 SQL 복원은 그대로 유지한 같은 경로의 자료를 사용했으며 실자료 파일 유실 후 canonical 경로 복원 시험은 아니다.** 실제 public JAR의 HTTP10회는 빈 공개 snapshot에서 health200·config/matches503·상세422/404 경계를 확인했다. 공개본 존재 시 hidden 필터·계산 성공이나 사람 승인 실적으로 세지 않는다.

증거·SQL·tar·입력 연결·소유권 가드40개 시험은 Git 제외 `data/private/evaluation/evidence/notice-source-registration-2026-11-04/`에 보관한다. 원래199항목과 준비575파일·기존 D05/D06·pending/미확정 상태·공개4테이블0을 유지했고, 시험 서버·자격증명을 정리하며 다른 연구실 서비스는 변경하지 않았다. 운영 서버 복구·backup 접근/보존/RPO/RTO·PITR·40문서 평가·사람 승인/공개·main/배포는 별도다.

## 개발용17건을 추가한 DB 복원 검증

앞47건 V4 full SQL을 새 빈 소유 MySQL8.4.13에 복원한 뒤, 개발용 실제 API17실행의 D05와 성공16실행의 숨김 사건17개를 추가했다. 최종16테이블206행에는 D03 47문서/버전·D05 23개·숨김 revision20개가 포함된다. 실패 D05 1개도 실패 상태로 유지했으며 공개4테이블은 비어 있다.

새 full/data SQL을 두 번째 독립 빈 서버에 복원해 전체 행·스키마·Flyway와 data SQL 바이트를 대조했다. 실제 JAR116회에는 최초 등록·동일 재실행·복원 후 재실행이 포함되며 공개 HTTP10회도 확인했다. 전체 원본1398항목의 바이트/권한과 기존 DB 행을 보존했고 자기 서버·자격증명만 정리했다. full SQL의 원문·차이와 제한된 charset 표시 정규화 파생본은 별도로 남겼다.

증거는 Git 제외 `data/private/development-notices/2026-11-04-development-extraction/`에 보관한다. **이번 검증은 SQL 복원이며 기존 같은 절대 경로의 등록 보관본을 사용했다. 신규 API 원본·등록본·초안은 앞 단계의 tar337항목에 포함되지 않는다.** 이 새 자료 경로도 운영 백업에 포함해야 하며, 이번 작업에서 추가 자료 tar나 실제 파일 유실 후 canonical 경로 복원을 수행한 것은 아니다. 운영 보존·접근권한·RPO/RTO/PITR·실제 사람 검토·main 병합/배포는 미완료다.

## 개발용17건의 선택 파일 유실 복구 검증

위 SQL 복원과 별도로, 후속 단계에서 신규17건의 `extraction-runs/`·`single-sources/`·`drafts/`를 백업하고 실제 canonical 경로 부재에서 복원했다. 선택은321파일/55디렉터리/2606068바이트이며 원래 API archive17개와 등록 보관본17개를 모두 포함한다. 새 tar376항목의 전체 경로·bytes/hash·mode를 대조하고 별도 빈 위치에 풀어 확인했다. 이전 tar337항목과 원본은 그대로 유지했다.

현재206행 full SQL을 새 빈 소유 MySQL8.4.13에 복원했다. 원본 세 디렉터리는0700 보관 위치로 배타 이동해 삭제하지 않았다. canonical 부재와 다른 경로 소비는 성공/실패 D05 각1개·D06 1개씩 총6회 실제 JAR로 거부했다. D05 부재는 `EXTRACTION_IO_ERROR`/종료5·retryable=true, 다른 경로는 `EXTRACTION_CONFLICT`/종료3이며 D06은 `IMPORT_VALIDATION_ERROR`/종료2다.

다른 위치의 D06 입력도 canonical 등록 보관본이 없는 상태에서 부모 참조를 검증해 거부했다. D06 입력 파일 자체의 위치를 일반적으로 고정하는 시험과 구분한다.

tar에서 같은 실제 절대 경로로 복원한 뒤 모든 D05 17개·D06 16개를 실제 JAR로 재실행했다. 원래 실패1건과 `already_registered`/`already_imported`를 유지했으며 새 revision·감사 기록을 만들지 않았다. 총39 CLI·HTTP15회, 전체16테이블206행·스키마/Flyway·data SQL 바이트·공개4테이블0을 대조했다. HTTP는 빈 공개 snapshot의 health200·미준비503·요청422/미등록404 경계이며 실제 공개/계산 성공 증거는 아니다.

보관 원본과 canonical 복원본은 서로 다른 root file key를 갖고 전체 bytes/mode는 일치하는지 대조했다. 이 복원본으로 재실행한 뒤 복원본을 별도 증거 경로에 남기고 처음 보관한 원본을 원위치로 돌려 root identity·기존2618항목의 bytes/mode를 확인했다. 자기 서버·프로세스·임시 credential은 정리했으며 다른7Docker ID/상태/포트는 같았다. 복구 probe에서 추가 추출 API 호출이나 실제 키 접근은 없었다.

증거는 Git 제외 `data/private/evaluation/evidence/development-material-recovery-2026-11-04/`에 보관한다. 이는 새17건의 선택 파일 복구다. 과거 모든 root의 동시 유실·소유자/xattr/hardlink 관계·강제 종료/전원 중단 내구성·운영 접근/보존/RPO/RTO/PITR을 인증하지 않는다. 이동 journal·보관 경로·복귀 경계를 유지하며, 실제 사람 검토·정확도/40문서 평가·운영 등록·main 병합/배포도 미완료다.

전체 리뷰에서 tar 손상/삭제를 원본 복귀 조건으로 묶은 오류를 발견했다. 원본 복귀는 journal에 고정한 manifest hash·경로·원본 identity/bytes/mode로 검증하고 tar 검증은 백업 복원에 유지하도록 분리했다. 손상/삭제·복귀 재실행·변조 거부를 포함한 합성24시험을 통과했다. 출력 수집기가 잘못된 UTF-8을 교체 문자로 바꾸던 경계도 거부하도록 수정해 Java54시험을 통과했다. 위 실제39 CLI/HTTP15 실행 코드·hash·원본 증거는 보존하고, 수정본의 합성 검증과 구분한다.

## 격리된 합성 복구 시험

Docker·Java21·Python3.13·표준 tar가 필요하다. 아래 두 시험은 **자기 MySQL 서버를 새로 만들며 기존 DB_URL을 대상으로 삼지 않는다**. 새 테스트의 최종 실행 결과는 관련 PR의 실제 검증 기록을 따른다.

```bash
MYAI_MYSQL_TESTS=true ./backend/gradlew -p backend test \
  --tests '*RecoveryDatabaseTest' --no-daemon
MYAI_MYSQL_TESTS=true ./backend/gradlew -p backend test \
  --tests '*DatabaseRecoveryTest' --no-daemon
```

기존 전체 DB 시험은 전역 DELETE와 기본 `myai_dev` 설정을 사용하므로 **복원 DB를 DB_URL로 지정해 전체 시험을 실행하지 않는다**. 전체 회귀는 별도 폐기 가능한 시험 DB에서 통합 담당이 실행한다.

proof는 `MYAI_RECOVERY_PROOF_ROOT/<UUID>` 또는 테스트 작업 디렉터리의 `build/recovery-proof/<UUID>`에 남긴다(위 Gradle 실행은 `backend/build/recovery-proof/`). 폴더0700·파일0600의 선택 합성 SQL/tar·경로/hash/mode·코드/schema/snapshot·DB/API 전후 증거만 보관하고 credential/env·전체 임시 root·D09는 넣지 않는다. CI 공개 artifact는 기존 dist/JAR만이며 이 proof를 추가하지 않는다.

이 시험은 같은 UID의 POSIX/tar 경계와 합성 복구를 다룬다. 실제 운영 정책·새 서버의 원래 경로 확보·백업 접근/보존·계정/grants·binlog/PITR·Windows/WORM·전원 중단 내구성·실자료 승인/40문서/D09·main 병합/배포는 완료하지 않는다. CI 산출물14일을 DB 백업 보존기간으로 쓰지 않는다.

표준 동작 근거: [MySQL8.4 mysqldump](https://dev.mysql.com/doc/refman/8.4/en/mysqldump.html), [SQL 형식 dump 복원](https://dev.mysql.com/doc/refman/8.4/en/reloading-sql-format-dumps.html).
