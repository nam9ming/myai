# 로컬 공지 검토 보고서

`local-review-report`는 원문·AI 원출력·사람 수정값을 비교하는 비공개 HTML을 만듭니다. S10의 파일 관리 대안입니다. 수정·보류·승인·공개는 기존 [import](reviewed-import.md)·[사람 인계](human-handoff-import.md)·[승인·공개 명령](review-publication.md)을 사용합니다. 공개 HTTP 경로는 추가하지 않습니다.

## 실행

저장소 루트에서 Java21·MySQL8.4·Python3.13 환경을 준비합니다. DB는 `DB_URL/DB_USERNAME/DB_PASSWORD`, Python은 `MYAI_PYTHON_EXECUTABLE/MYAI_PYTHON_WORKDIR` 설정을 따릅니다. 비밀번호·키를 명령 인자나 문서에 넣지 않습니다. AI API는 호출하지 않습니다.

```bash
./backend/gradlew -p backend bootJar --no-daemon
mkdir -p data/private/review-reports
chmod 700 data/private/review-reports
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-review-report \
  --myai.report.document-version-id=10000000-0000-4000-8000-000000000007 \
  --myai.report.source-root="$PWD" \
  --myai.report.directory="$PWD/data/private/review-reports"
```

예제 ID는 합성 자리표시자입니다. 등록된 `document_version_id`로 바꿉니다. `source-root`는 D03 상대 원문 경로의 기준입니다. 출력은 그 루트의 `data/private/` 또는 `evaluation/private/` 아래 기존0700 디렉터리만 허용하며 중간 링크도 거부합니다. 파일은0600입니다. 동일 내용은 hash로 재사용하며 다른 파일·링크·공개 권한 파일은 보존한 채 충돌 오류를 냅니다.

stdout receipt에는 버전·문서 ID·파일명·SHA-256·재사용 여부만 나옵니다. HTML을 로컬 브라우저로 엽니다. 외부 자원·스크립트·원문 HTML 실행 없이 모든 값을 텍스트로 표시합니다. 보고서에는 원문·검토자·private 경로가 들어갈 수 있으므로 Git·Actions artifact·공개 게시판에 올리지 않습니다.

## 확인할 항목

| 항목 | 표시 내용 |
| --- | --- |
| 원문·출처 | 관련 사건 전체 revision의 출처, D03 원본 metadata·본문/블록·raw 파일, 확인·사용권 운영 이력, 사건0개를 포함한 사람 인계 import 원본 |
| AI 원출력 | 관련 출처의 모든 D05와 실패·legacy 행. 모든 시도의 prompt/output·API response/exchange, 크기·hash·검증 오류 |
| 사람 검토값 | 과거 출처 연결이 제거되어도 현재·과거 revision 전체, 근거·미상·수정 전후·이유·인계 원본 |
| 검토·공개 이력 | 승인·반려, 공개/복구 전후 snapshot·사건 포함 관계, 관련 채널의 현재 공개 포인터 |
| 공개 미리보기 | 명시한 preview 요청의 기존 공개 게이트 결과와 공개 묶음 비교 |

PC는 원문/AI/수정값3열, 좁은 화면은 세로로 표시합니다. JSON 키·타입·null을 유지하며 AI나 사람 출력을 D06에서 역으로 만들지 않습니다. 비UTF8 원본은 base64로 표시하고 `.response`에만 남은 불완전 AI 응답도 보존합니다.

`valid`는 명시된 schema/hash/reference 검사의 통과입니다. 사실 정확도·실제 사람 검토·사용권·독립 정답표 인증이 아닙니다. 무효/부재 항목은 원래 DB 행과 `invalid/code/field`를 남깁니다. D05의 `failed`와 archive 무결성 `valid`는 동시에 성립할 수 있습니다.

D05의 `archive_validation`, `database_validation`, 각 artifact의 검증을 구별합니다. archive 전체 검증은 통과했으나 DB 등록값과 다르면, 전체 상태는 `invalid`로 두고 안전하게 검증한 원출력은 계속 표시합니다. 이 원출력을 등록 일치·승인 자료로 간주하지 않습니다. 크기는 실제 archive 파일을 먼저 확인하며, 불일치한 DB receipt의 크기를 사실로 사용하지 않습니다.

사건이 없는 사람 검토도 `documents[].imports`에 인계 원본·경고·변경 기록을 표시합니다. 저장된 비공개 반려 인계는 미상/부분값을 그대로 검사하며, 승인·공개는 완전한 필수 검토를 계속 요구합니다.

## 공개 미리보기

기존 `publication-command-v1`의 `action: "preview"` 요청을 준비하고 `--myai.report.preview-file=/절대/비공개/preview.json`을 추가합니다. 선택 문서의 관련 사건을 최소1개 포함해야 합니다. 다른 승인 사건도 같은 묶음으로 검사할 수 있습니다. approve/publish/rollback 입력은 실행하지 않습니다. 미승인·pending 사용권·미확정 지점은 기존 게이트에서 거부됩니다.

성공 시 별도 조회한 현재 공개본의 정확한 ID·hash·포인터 버전과 비교해 새 사건·revision ID 변경·제거·동일 사건 및 preview의 취소 사건 수를 표시합니다. 사실의 의미상 변경을 추측하지 않습니다. 공개본이 없으면 빈 기준을 명시하고, 기준본을 검증하지 못하면 오류와 미상/null을 남깁니다. 검사 시점이 다르므로 향후 공개를 확정하는 결과가 아닙니다.

preview의 snapshot ID·checksum은 검토용이며 실제 포인터를 바꾸지 않습니다. 미지정은 `not_requested`, 실패는 `invalid`와 원래 코드/필드입니다. 공개 직전 최신 revision·원문 상태를 다시 확인하고 별도 공개합니다.

## 읽기 전용·한도·제한

DB 행은 읽기 전용 `REPEATABLE_READ`로 수집합니다. 운영 상태·파일 검증·preview는 별도 검사 시각을 표시하므로 동일 순간의 snapshot으로 간주하지 않습니다. 웹·다른 프로필 혼합, Flyway·Hibernate DDL·SQL 초기화는 기동 전에 차단합니다. D05는 `verify-sealed`로 이미 봉인된 원본만 검사하며 파일 생성·복사·수리·chmod를 하지 않습니다. 변경 가능한 원본은 기존 등록부터 완료해야 합니다.

조회당1000행, 원본 파일당8MiB, 전체 JSON/HTML64MiB 한도입니다. 초과는 전체 `REPORT_TOO_LARGE`이며 잘라서 성공으로 표시하지 않습니다. 보존된 수동 실패 output은8MiB를 넘을 수 있어 별도 검토가 필요합니다. 원래 파일은 유지합니다.

종료0 성공,2 입력·미등록·크기 오류,3 출력 충돌,4 DB 미준비,5 출력 I/O,1 내부 오류입니다. 항목 검증 실패가 있어도 보고서 저장 성공이면 종료0일 수 있으므로 receipt만으로 승인하지 않습니다.

기능 시험은 합성 자료를 사용합니다. 아래 실자료 실행과 구별하며, 실제 사람 검토·권리 확인·독립 평가/40문서·실기기 인수·운영 보존 정책·main 병합/배포는 후속 작업입니다.

## 실제 개발 자료의 검토 인계 준비

2026-11-04에 기존 백업의 D03 47문서·D05 23실행·숨김 revision20개를 새 전용 MySQL8.4.13에 복원했습니다. SELECT만 허용한 계정으로 실제 JAR의 `local-review-report`를20회 실행해 처리한 고유 문서20건의 비공개 HTML과 검토 대기 목록을 만들었습니다. 쓰기 권한 거부1142도 확인했습니다.

- D05는 기계 검증 통과19/실패4·전체25시도입니다. 재시도나 이전 실패를 새 문서로 세지 않습니다. 보고서의 artifact146개를 원본 바이트·해시와 대조했고, archive·DB 참조·원문·초안의 항목 검사에서 `invalid/not_checked`는0개였습니다.
- 검토 감사20행은 기존 `import` 기록입니다. 사람 승인 기록은0개이며 초안20개는 `draft/hidden`, 검토자·검토 시각은 null을 유지합니다. preview·승인·공개는 요청하지 않았고 공개4테이블은0행입니다.
- 원문 경로는 등록 묶음 기준 상대경로입니다. 서로 다른 기존 루트를 고치지 않고 원문47파일을 해시 대조한 새 private `source-view`에 읽기 전용 사본으로 배치했습니다. 보고서 출력도 이 새 루트의 `data/private/` 아래에 둡니다. 사본과 원본의 identity는 다르며 매핑·해시를 별도 보관합니다.
- 생성 전후16테이블206행의 전체 데이터·스키마 해시와 소비한 원본285파일의 hash·mode·fileKey를 대조했습니다. 원본/DB는 불변이며 소유 시험 DB·임시 credential은 정리하고 다른 컨테이너 목록은 보존했습니다.

비공개 인계 위치는 `data/private/evaluation/evidence/real-review-readiness-2026-11-04/index.html`입니다. Git·Actions artifact에는 올리지 않습니다. HTML의 JSON 전체·링크 대상·외부 자원/스크립트 부재를 기계 검사했으며, 실제 브라우저·기기 인수나 사람이 내용을 검토한 결과는 아닙니다. 형식 검증 통과를 사실 정확도·사용권 승인으로 표시하지 않습니다.
