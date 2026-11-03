# 개발 DB 백업·복원·기동 인계

[B08](../../docs/spec/10_인원별WBS.md)·[DB 백업 기준](../../docs/spec/09_DB설계와트랜잭션.md#스키마-변경백업복구)의 전용 개발 DB 인계 절차다. MySQL8.4.13·Java21·Python3.13·표준 tar·POSIX 권한을 사용한다. 새 운영 백업 서비스나 공개 API는 없다. 아래 명령은 운영자가 선택한 개발 DB용이며 실제 연구실 서비스의 복구·배포를 수행한 기록이 아니다.

`local-publication rollback`은 같은 채널의 공개 포인터·감사 기록만 바꾼다. DB schema·작업 행·원본 파일 복원과 구별한다([공개 복구](review-publication.md#공개-내용실패복구)). Compose 볼륨 유지도 별도 백업을 대신하지 않는다.

## 먼저 정할 값과 중지 범위

- 원본과 대상은 운영자가 소유한 전용 개발 MySQL이다. 대상은 **새 서버의 새 빈 폐기 가능 schema**이며 기존 연구실 DB·계정은 사용하지 않는다.
- DB와 파일을 기록하기 **전에** 공개 앱·로컬 import/검토/공개·추출/인계 작업 및 다른 세션·예약 작업의 모든 쓰기와 DDL을 중지한다. 백업과 기준값 기록이 끝날 때까지 중지를 유지한다. `--single-transaction`만으로 DB와 파일의 공동 일관성을 보장하지 않는다.
- D03 원본·성공/실패 D05·사람 인계 중 DB가 참조하는 경로를 명시적으로 선택한다. D05 `raw_ref`와 인계 `directory`는 **같은 실제 절대 경로**로 복원해야 한다. SQL 경로 문자열 치환·symlink 우회·새 identity 발급을 복구로 세지 않는다.
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
