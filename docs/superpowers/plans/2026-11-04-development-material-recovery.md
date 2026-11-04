# Development Material Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 신규17건의 선택 파일을 백업·정확한 절대 경로에 복원하고 현재206행 DB의 실제 재소비·원본 복귀를 검증한다.
**Architecture:** 파일 경계 Python과 Java 저장 소비 probe는 병렬 worker가 각각 소유한다. 부모가 baseline·실제 파일 이동/DB/Gradle/Git·통합 검증을 맡고 마지막 새 문맥 전체 리뷰1회로 닫는다.
**Tech Stack:** Python3.13 표준 라이브러리·기존 배타 rename, Java21·기존 RecoveryDatabase/SourceRegistrationGuards·MySQL8.4.13. 새 의존성 없음.
**Spec:** docs/superpowers/specs/2026-11-04-development-material-recovery-design.md

## Global Constraints

- 기준 develop d2920b8·stage38 manifest40f44d0e, 세 subtree321파일/55디렉터리/2606068bytes와 선택 JSON만 사용한다. 원본·기존 manifest·사용자 .gitignore·두 AGENTS·main 불변.
- 현재 full SQL f1920df7의16테이블206행을 새 빈 소유 서버에 복원한다. 이전122행 SQL·경로 치환·가짜 사람/좌표/공개 기록 금지.
- 키/API·gold·D09 접근·worker 실제 파일 이동/DB/Docker/Gradle/Git mutation 금지. 부모만 소유 자원에서 실행하며0600/0700·등록본0400/0500·no-clobber를 지킨다.
- 원본은 보관·복귀하고 복원본도 별도 보존한다. 환경 주입·링크·중복/탈출·중첩·변조·기존 목적지를 거부하며 실패 journal을 유지한다.

## Review Focus

1. 백업 내부 경로·중복 member·링크·권한·원본 변경을 놓치는가 — 설치 전 전체 검증과 경계 시험으로 막는다.
2. 부분 이동/복원 실패가 원본을 덮거나 잃는가 — 배타 rename·journal·실제 실패 복귀 시험을 확인한다.
3. canonical 부재/다른 경로의 거부가 DB를 바꾸는가 — 성공/실패 D05·D06 실제 거부와 전체 DB 전후를 대조한다.
4. 복원본 대신 남겨 둔 원본을 소비하는가 — 원본 보관 위치·canonical 복원 bytes/mode·모든33회 재실행 경로를 확인한다.
5. 새17건 복구를 전체 운영/사람 평가로 과장하는가 — 실제 source/hash·SQL·분모·실패·비공개/미완료를 문서와 대조한다.

### Task 1: 선택 백업·복귀 경계

**Files/Owner:** Python worker는 private `material_backup.py`·`test_material_backup.py`만 소유한다. 부모가 고정 selection/baseline·실제 백업을 작성한다.
**Interfaces:** `create_backup(roots: list[Path], output: Path) -> Path`, `verify_backup(manifest: Path) -> dict`, `displace(manifest: Path, holding: Path)`, `restore(manifest: Path, holding: Path)`, `return_originals(manifest: Path, holding: Path)`. CLI는 create의 반복 `--root`/`--output`, verify의 `--manifest`, 나머지의 `--manifest`/`--holding`을 받는다. manifest는 schema_version·roots의 absolute_root/tar_name/tar_sha256/entries를 보존한다.

- [ ] 쓰기 없는 fixture에서 정상 bytes/mode roundtrip과 링크/중첩/기존root/중복·탈출·변조 tar 거부, 이동/복원 실패의 원본 복귀 시험을 먼저 작성·실패시킨다. Expected: 기능 누락의 실제 RED, 원본 손실 없음.
- [ ] 기존 tar/hash와 배타 rename을 재사용해 최소 구현하고 같은 시험을 통과시킨다. Expected: GREEN·단일 안전 JSON·키/DB/API 접근0.
- [ ] 부모가 정확321파일 선택·현재206행 SQL·이전 manifest/protected baseline을 고정하고 새 백업과 별도 위치 검증을 실행한다. Expected: 전체 구성/hash/mode 일치, canonical 이동은 아직 없음.

### Task 2: 실제 파일 유실·DB 재소비

**Files/Owner:** Java worker는 private `src/DevelopmentMaterialRecovery.java`·`src/DevelopmentMaterialRecoveryTest.java`만 소유한다. 부모가 launcher·실제 실행·독립 checker를 맡는다.
**Interfaces:** Java main은 repo/root/java 세 인자를 받고 새 root의 selection.json·Task1 proof/material-backups/manifest.json·Python helper CLI를 소비한다. Task1 CLI 성공은 exit0/JSON status=passed이며 원본 복귀는 검증 가능한 재실행을 지원한다. 기존 RecoveryDatabase/SourceRegistrationGuards·stage38 build/snapshot helper를 재사용한다.

- [ ] 선택17/상태16+1/초안16·고정 SQL/hash·예상 세 경로·환경/거부 receipt·복귀 finally의 작은 fake 경계 시험부터 RED→GREEN으로 구현한다. Expected: 실제 키·DB·canonical 이동 없는 GREEN.
- [ ] 부모가 현재 source/build/JAR·소유권을 검증하고 새 빈 DB에206행 SQL을 복원한다. Expected: 전체 rows/schema/Flyway·공개0 일치.
- [ ] 부모 실제 probe에서 원본 보관→canonical 부재3회·다른 경로3회 거부→tar canonical 복원→전체 D05 17/D06 16 재실행→복원본 보존/원본 복귀를 수행한다. Expected:39 CLI(거부6/정확재실행33), 각 단계 전체206행 불변·HTTP·dataSQL·기존 파일/서비스/자기 정리 일치. 추가 API0.
- [ ] 부모 독립 읽기 전용 checker로 선택/백업/member/실제 경로/전체 CLI/DB/SQL/HTTP/복귀/기존 manifest를 대조한다. Expected: 실제 실패·미실행을 숨기지 않는 PASS.

### Task 3: 전체 리뷰·원격 gate·인계

**Files/Owner:** 부모 backend/processing README·TASK와 backup-recovery 안내, private report/manifest·원격 증거.

- [ ] 작성자 전체 리뷰·관련 전체 시험과 마지막 새 문맥 전체 리뷰1회 후 모든 유효 지적을 수정한다. Expected: 미해결0·보류0, 실제 검증/제한 정확 기록.
- [ ] source PR·CI/AI/새 사람 피드백→develop 병합→정확 통합 gate를 완료한다. Expected: raw지적과 판단 구별, 기존 보안 이력/cutoff·main 보호.
- [ ] 전체 판단/비용과 private 증거를 동결하고 이 계획 scratch만 정리한다. Expected: 원본·보호파일 보존, 운영/평가/사람 미완료 유지.
