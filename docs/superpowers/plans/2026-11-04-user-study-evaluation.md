# User Study Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** D09 프로토콜·기록을 비공개 로컬에서 검증하고 M04/M05·정확도/누락/실패와 JSON/CSV 결과를 계산한다.
**Architecture:** protocol 모듈이 private pack·시각/동의/자료 identity를 준비하고, study 모듈이 모든 기록·분모·유리수 지표를 계산한다. 부모가 기존 CLI와 배타 private export를 연결하고 docs 소유자가 한국어 계약/명세를 갱신한다. 개인정보 원본의 자동 동결 복제는 없다.
**Tech Stack:** Python3.13 표준 라이브러리, 기존 Java21/MySQL8.4.13 bridge 회귀, 새 의존성 없음.
**Spec:** docs/superpowers/specs/2026-11-04-user-study-evaluation-design.md

## Global Constraints

- 기존 public API/DB/calc-v1/D08/Flutter·실자료·키·네트워크·실제 사람/동의/사진·운영 배포 없음. 기존 AGENTS/사용자.gitignore 보존.
- 동의/접근자/보존기한/종료처리는 실제 입력 선언 필수. 만료는 KST 다음자정부터 거부하며 CLI는 records 읽기 전에 검사한다.
- private root/상대 canonical경로·symlink/탈출 거부, raw source/media는 streaming hash만. 자료 identity 검사를 전체 Java publication 인증으로 표시하지 않음.
- 모든 모집/실패/중단/미시작·전문가/파일럿·unknown 분모 보존. paired는6개correct+조건준수만, Fraction/ns 정확계산·20% gate.
- JSON8MiB/깊이100·결과행예산, Decimal원사실 근사변환 없음. stdout summary/receipt·stderr고정코드·0/2/3/5/1.
- 영어 Conventional Commit 제목/본문·제목50자 이내, 문서/주석/PR한국어. 부모만Git, 사용자위임 develop만병합/main사람.

## Review Focus

1. 실패·미시작·동의 철회 후 상세 부재가 분모에서 사라져 M05/개선 성공을 높이는가 — 고정6배정·모집/unknown누락·보호조건 시험.
2. 같은 자료·snapshot hash여도 source 버전/문서 집합·배정/환경/확인시각이 달라 비교쌍으로 남는가 — raw artifact+metadata/순서/조건 deviation 시험.
3. elapsed 소수·나노초·정확히 제한 도달·음수/짝수 중앙값·20% 근접값이 float rounding으로 판정 바뀌는가 — exact ns/Fraction 경계 시험.
4. 만료/미동의·별도 촬영동의 부재·출력 경로/CSVformula·symlink가 실제 개인자료 읽기/공개/덮어쓰기를 허용하는가 — 선검사·0600/0700·배타·안전stdout 시험.
5. pilot/expert/비상인·unknown정답/미상누락·범위밖 사건이 사용자 성과·정답·0누락으로 바뀌는가 — 역할/phase·전체기대incidence·외부집합/nullable 시험.

### Task 1: private 프로토콜·자료 준비

**Owner:** protocol worker. Files: processing/evaluation/study_protocol.py(신규), processing/tests/test_study_protocol.py(신규). 다른 파일/Git/실자료 수정 금지.

**Interfaces:** `validate_protocol(content:bytes, root=STUDY_ROOT, *, evaluated_at=None)->dict`; STUDY_ROOT=REPO/data/private/evaluation/user-studies. 반환 공용 키 `protocol root evaluated_at evaluated_ns deadline_ns protocol_sha256 time_limit_ns sources events tasks task_sets`이며 protocol은 검증된 원형(Decimal 유지), sources는 version→document 선언, events는 snapshot eventID 집합, tasks는 taskID→item, task_sets는 A/B→set. `duration_ns(value, *, positive=True)->int`, `stamp_ns(value)->int`, `day_kst(ns)->str`, `check_retention(prepared, *, evaluated_at=None)` 제공. `_artifact(value,root)->{path:Path,sha256,size}`는 spec의 canonical 상대경로·ancestors/symlink·regular·전체hash를 확인하며 추가 복사 없음. parent export에서 공통 경로 검사 함수 `_path(root,value)->Path` 재사용(존재하지 않는 최종output도 검증, ancestors검사). 기존helper에 새public 옵션을 넣지 않는다.

shared fixture API: test_study_protocol.py `StudyProtocolFixture(unittest.TestCase)`는 self.work(OS임시 root), self.protocol(12키), self.protocol_bytes(), self.prepare(protocol=None,at=STUDY_AT) 제공. `STUDY_AT='2026-11-04T03:00:00Z'`. snapshot.created_at=2026-11-02T23:00:00Z, declared_frozen_at=2026-11-03T00:00:00Z, pilot/confirmed그이전, retention_deadline=2026-12-31, source 체크=2026-11-03T00:30:00Z, 참가 동의=00:45Z, task times=01:00Z 이후로 고정해 실제현재CLI에도 미래 기록이 되지 않게 한다. 원래 source/doc/event/동의/참여는 synthetic뿐이며 실제 사실이라 주장하지 않는다. snapshot은 기존 CalculationFixtures/공개 producer 구조에서 최소 합성27키 구성, 실제 rawbytesSHA 사용한다.

- [x] **RED:** 새API부재 + 정확키/타입/UUID/버전·기한KST경계/나노초·파일럿선언·자료누락/중복/같은doc여러versions·기대사건/과제3종·hash변경/탈출/ancestor symlink/상대root alias 시험. `python3.13 -B -m unittest discover -s processing/tests -p test_study_protocol.py -v`, 의도한 실패 관찰.
- [x] **GREEN:** 기존 JSON/label/UUID/stamp+instant_ns/archive root/fingerprint/read_checked 재사용, protocol 원형불변·검사한 bytesSHA 유지·필수 시간/정책 없음은 거부. snapshot선택identity/집합만 확인하고 공개gate를복제하지 않는다.
- [x] **Verify:** 자신의 전체 모듈과 기존 extraction_validation/dataset 관련 경계. SHA·RED/GREEN/count 보고, 부모가 소유파일 커밋 `feat: validate user study protocols`.

### Task 2: D09 기록·전체 분모·M05 분석

**Owner:** study worker. Files: processing/evaluation/study.py(신규), processing/tests/test_user_study.py(신규 fixture 포함). Task1/root파일 수정 금지.

**Interfaces:** `evaluate_study(content:bytes, protocol:prepared)->dict`는 `{result,summary,records_content}` 반환. records_content는 원래 bytes의 메모리 전용 sidecar이며 저장/공개하지 않는다. result top keys는 spec의13개(privacy/versions 포함)이며 Decimal rawrecord를 포함할 경우 `_json`에 전달하지 않도록 상세 결과를 원형 bytes와 구별한다. 상세 participants에는 명시 schema로 원기록의 문자열/정수/nullable/리스트와 계산된 `elapsed_ns`를 보존하고 elapsed_seconds의 원래 Decimal은 원입력 bytesSHA/정확한 ns로 보존(숫자근사 금지). session.instruction_seconds→instruction_ns, record.elapsed_seconds→elapsed_ns, task.expected_event_ids 추가; participant.analysis와 summary 공용 키는 spec 그대로. 반환 JSON은 일반 str/int/bool/list/dict/null 및 파생 finite float만. `summary.protocol_version='user-study-summary-v1'`. 표적값은 독립 합성 리터럴이다.

공유시험 fixture `UserStudyFixture(StudyProtocolFixture)`는 self.records(7키), `write_records(value=None)->Path`, `study(value=None, protocol=None, at=STUDY_AT)->packet`, self.protocol_path/self.records_path를 제공한다. `self.protocol`/work를 덮어쓰지 않는다. 실제stdout clock에 맞게 synthetic 날짜는 현재보다과거이며 retention은명시미래로. 부모export/CLI가 이fixture 사용.

- [ ] **RED:** 실제 Task1 private pack+독립 기록fixture로 새API부재 관찰. `python3.13 -B -m unittest discover -s processing/tests -p test_user_study.py -v`.
- [ ] **GREEN:** spec의 모집표/동의/역할/순서4주기·A/B3문항/두session·타입/nullable/미래/기간일치/비중첩·도움/동일환경/당일확인/촬영/evidence hash를 검증하고 모든 행을 보존한다.
- [ ] **Metrics RED/GREEN:** M04전체/유형/전문가/pilot,6correct만paired·실패/부분정답 제외사유, 음수/짝수/0명/정확20근접 Fraction, 고정배정/시작/unknown누락incidence·정확도/누락방어 null/false, 범위밖 분리·수동선언/실제reported 재계산·survey분포 시험. 전문가/중단/no_show/withdrawn상세부재를 숨기지 않는다.
- [ ] **Size/round RED/GREEN:** 입력/결과8MiB·깊이100·행생성중예산, protocol/records version/SHA·증빙/원본hash 드리프트·미동의/만료/별도촬영동의 거부. no autoArchive/DB/API.
- [ ] **Verify/Commit:** 전체소유시험GREEN, 보고/count/SHA. 부모커밋 `feat: analyze paired user study records`.

### Task 3: private export·CLI·문서·전체 gate

**Owner:** coordinator. Files: processing/evaluation/study_export.py, processing/evaluation/__main__.py, processing/tests/test_user_study_export.py, backend/src/test/java/kr/ac/myai/backend/UserStudyMaterialTest.java; 문서는 별도docs owner에게 위임(contracts/user-study.md, contracts/README.md, processing/README.md/TASK.md, docs/spec03/05).

CLI check-study/export-study의 root 기본STUDY_ROOT, --protocol/--input 필수상대경로. export --output/--format(json|csv) 필수. `export_study(packet, protocol, output, format)->receipt`; validated protocol를 받아현재retention을 다시확인하고 exactbytes export. receipt는 protocol_version/status/format/output_sha256/output_size/summary만(상대filename/participantID 없음). JSON canonical result; CSV 고정열 participant·task rows와 formula escape, free narratives는JSON/원본에보존. 0600/0700·동일bytes재사용·다른bytes/부분파일/권한확대/symlink거부·자기임시파일정리. helper _write/_path공유재사용, 새동결저장소없음.

- [ ] **RED:** CLI/export부재·새API·privateJSON/CSV 실제row/재계산·NFC/타입/permission/충돌/실패/동시/원본불변·기한records선읽기차단을 시험.
- [ ] **GREEN:** 기존 CLI오류0/2/3/5/1·stdout한JSON/진단값비노출, protocol선검사→records읽기→분석→현재기한재검사→배타privateexport. publicpath/D09자동복제 없음.
- [ ] docs owner는 실제계약/프로세스·모집/동의/보존·M05분모/경고·선언과검증한계·실제후속을 한국어로 기록하고 static링크/bash검사. 실제자료/성과 생성 없음.
- [ ] 실제 Java SnapshotExportService가 쓴 합성 canonical 파일을 Python protocol reader로 읽는 경계 시험을 추가한다. Publication producer를 복제하지 않고 현재 포맷/문서버전·집계의 실제 호환성을 확인한다.
- [ ] Native 전체 Python + Java/MySQL기존bridge/새호환시험 + Node29/JSON9/lint/build, 실제CLI(합성) check→JSON/CSV→재사용/충돌/만료/누출/원본불변 실행.
- [ ] 작성자 전체 리뷰→독립 전체1회→유효지적모두RED→GREEN수정/전체회귀. 정확sourceCI/AI/새사람피드백→develop병합→통합gate/PR20현재기록. main사람.
- [ ] 모든Ruling/비용·원본proof/checksum·보고를 private evidence보존 후이번소유workspace/container/credential만정리. 전체goal의 실제사람/40문서/배포를 완료로 표시하지 않는다.

## Pre-flight

Task1 prepared의source/events/tasks/clock/privacy 인터페이스를Task2/3가사용한다. Task2 sharedfixture가parentCLI/export테스트에사용된다. 실제피험자기록/미동의개인정보를공개예제·CIartifact에넣지않는다. Task1/B조건미확정점은spec을기준으로부모가결정/ledger기록하고다른owner파일을임의수정하지않는다.
