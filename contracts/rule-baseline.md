# 규칙 추출 기준선·실행 원본

규칙/AI/사람 수정후 비교의 **규칙 실행기**다. Python3.13 표준 라이브러리만 사용하며 키·AI·네트워크·DB를 호출하지 않는다. 실제 성능이나 사전 검토를 인증하지 않는다.

## 고정 프로필

`rule-profile-v1`의 필수 키는 `schema_version`, `profile_version`, `rule_version`, `data_kind`, `type_keywords`, `target_keywords`, `exception_keywords`, `places`다. 추가 키·중복 JSON 키는 거부한다. `rule_version=rule-extract-v1`, data_kind는 입력과 같은 real/synthetic이다. 프로필 버전은100자, 키워드/지명/별칭은160자 이하 NFC·양끝 공백/제어문자 없는 문자열이다.

type_keywords는 construction/event/traffic 세 배열이며 배열당32개 이하 리터럴이다. 대상/예외 키워드도 각각32개 이하이다. places는 최대256개의 `{name,aliases,kind}`이며 aliases는 최대16개, kind는 point/segment/stops/area 또는 null이다. canonical name을 포함한 별칭은 프로필 전체에서 중복할 수 없다. 정규식 실행·좌표·외부 사전 조회는 없다. [공개 예제](../processing/examples/rule-profile.json)는 합성 전용이다. 실제 확인 평가에는 개발용에서 검토·고정한 프로필을 먼저 준비하며 같은 자료/지침으로 비교한다.

## 추출·미상

본문 유형 키워드가 있으면 문서당 사건/일정1건을 만든다. 없으면 `items=[]`/`NO_EVENT_FOUND`다. 복수 사건·복수 일정을 분리하지 않는 약한 기준선이며 `RULE_SINGLE_EVENT_BASELINE` 경고를 남긴다. 단순 리터럴이므로 부정문·동음이의·부분 지명 일치의 의미를 판정하지 않는다.

- 전체 날짜는 YYYY-MM-DD, YYYY.MM.DD, YYYY/MM/DD, YYYY년 M월 D일을 지원한다. 단일 날짜는 양끝에 쓰고 명시 범위(~, ～, 〜, –, —, -, 부터)는 순서를 검사한다. 연도 없는 날짜·열린/축약 범위·끝만 주어진 범위·충돌·복수/미지원 범위는 null/ambiguous다. 게시일/현재 날짜로 연도·미정 종료일을 채우지 않는다.
- 시간은 `H:mm[:ss]`의 명시 두 시각 범위다. 익일/다음날은 범위 기호 뒤 명시된 경우만1이며 종료가 이르다고 자동 이월하지 않는다. 명시한 서로 다른 종료 날짜에는 offset0을 사용한다. 단일/열린/미지원/복수 시간은 ambiguous, 미기재는 not_stated다. 인식한 시각 외 추가 한글/잘못된 시각이나 미지원 오전/오후/AM/PM 수식어가 있으면 일부 시각만 확정하지 않는다. 종일만 명시하면 all_day=true·시각null, 종일과 시각이 충돌하면 ambiguous다.
- 장소는 프로필의 이름/별칭 리터럴 일치와 선언한 kind다. 주소는 미상으로 남기고 geometry를 만들지 않는다. 일치가 없으면 미상 장소와 빈 location_refs·LOCATION_BINDING_UNKNOWN을 남긴다.
- 대상/예외 키워드가 있는 주변 문장을 원문 그대로 보존한다. 여러 대상 문장은 ambiguous다. 명시 `예외 없음`/`제외 없음`만 빈 예외 배열이며 다른 예외와 충돌하면 ambiguous다. 나머지 경로/정류장/방향/취소/반복은 미상이다.

known에는 실제 본문의 전체 블록 인용·Unicode code point 범위·블록 UTF-8 SHA-256을 붙인다. 결과는 기존 extract-schema-v1 검증과 8필드 채점기를 사용한다. 입력/프로필/출력은 각각8MiB·JSON 깊이100 제한이다. 대상/예외의 서로 다른 문장은 각각256개까지 보관한다. 출력/문장 예산 초과는 실제 생성한 작은 `{"rule_error":"RULE_OUTPUT_LIMIT"}` 바이트와 실패 코드를 반환하며 성공으로 잘라 보관하지 않는다. 첫/최종 결과는 동일한1회 실행이다. 사건 대응·생성 여부의 의미 판정은 기존과 같이 사람 annotation이 필요하다.

## 보관·후속 범위

실행 원본은 별도 `rules-run-v1`이다. AI D05로 등록하거나 모델/토큰/금액을 꾸미지 않는다. D08 `method=rules` 선택/최초·재시험 연결, 사람 수정값·세 방법 비교 및 실제 gold/40문서 성능은 후속 작업이다.

## CLI·6파일 보관

```sh
python3.13 -m processing.extraction rules-run \
  --input INPUT --profile PROFILE --preprocessing-version VERSION [--run-id UUID]
python3.13 -m processing.extraction rules-verify UUID
```

각 명령의 `--root` 기본값은 Git 제외 `data/private/rule-runs`다. 저장소 안의 공개 폴더는 root로 사용할 수 없다. UUID는 소문자 정규형이며 전처리 버전은 비어 있지 않은100자 이하 문자열이다.

UUID 디렉터리에는 `input.json`, `profile.json`, `output.json`, `metadata.json`, `identity.json`, `receipt.json`만 있다. 원본 입력/프로필/출력 바이트를 그대로 보관한다. metadata는 rules-metadata-v1·실행/문서ID·data_kind·실행 모드 rules·규칙/프로필/전처리 버전·시작/종료 UTC 시각이다. identity는 rules-run-v1·run_id·4개 payload의 SHA-256/size·recorded_at이다. metadata·identity·receipt는 기존 canonical UTF-8 JSON+LF다.

receipt에는 형식/실행/문서ID·data_kind·버전·입력/프로필/metadata SHA·4파일 hash/size·시각·attempts=1·status(validated/failed)·validation_error·review_required=true를 반환한다. 모델/토큰/비용·원문·절대 경로는 없다. 파일0400/디렉터리0500·정확한 파일 집합·symlink 거부·전체 hash·started_at≤finished_at≤recorded_at·결정적 재계산을 검증한 뒤 macOS/Linux 배타 rename으로 설치한다.

동일 UUID의 입력/프로필 바이트와 전처리 버전이 같으면 원래 시각/원본을 재사용하며 다른 원본은 RULE_RUN_CONFLICT다. 원래 경로가 없어도 재검증한다. 실패 원본을 지우거나 성공으로 덮어쓰지 않는다. stdout은 receipt JSON 한 건, stderr는 고정 오류 코드다. 성공0·추출 실패4·입력2·보관 손상/충돌3·I/O5·내부1이며 손상 검증은 RULE_RUN_INTEGRITY다. POSIX 권한은 관리자 변경·삭제를 막는 WORM이 아니며 Windows/전원 중단 내구성은 미검증이다.
