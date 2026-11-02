# 공개 snapshot 조회 구현 계획

**목표:** 승인·공개한 DB snapshot으로 config와 조건 없는 사건 상세를 제공한다.
**기준:** `docs/spec/04_계산규칙과기술설계.md` I01~I03, `contracts/README.md`, 기존 snapshot-v1.
**기술:** 기존 Java21·Spring JDBC·Jackson·MySQL8.4.13. 새 의존성·migration 없음.

## 범위와 제약

- config·상세·matches 사전 검증은 읽기 전용 REPEATABLE READ에서 같은 공개본을 사용한다.
- canonical checksum·문맥을 확인하고 허용 필드만 반환한다. 최신 작업 revision·지점·비공개 수정 전 값을 섞지 않는다.
- 현재 채널 head만 공개한다. 교체된 공개본은 409 SNAPSHOT_RETIRED와 current_snapshot_id, 미등록·미공개본은404다. rollback하면 이전본이 다시 활성화된다.
- I03은 계산 전 사실 응답이다. 기존 표시용 fixture는 유지하고 실제 응답에는 I02 전용 분류·거리·겹침 시간을 만들지 않는다. field_values에 값·knowledge·근거·미상 이유를 보존한다.
- 공개 변경이력은 선택 snapshot 생성 시점까지 같은 채널의 공개·복구 전환에 등장한 revision을 순서대로 비교한다. 이전 canonical의 공개 필드·근거·출처만 사용한다.
- replay는 선택 공개본의 cutoff·당시 확인 상태와 별도의 current_ 상태를 보존한다. 사례 목록은 같은 구역·자료 종류의 활성 replay만 제공한다.
- matches는 snapshot·문맥·지점 검증 뒤 CALCULATOR_NOT_READY503. Python·프런트·관리 UI·배포는 후속 작업이다.

### Task 1: DB 공개 조회와 인계

**대상:** 공개 조회 repository/service, ApiException/handler, PublicationMySqlTest, backend 문서와 contracts/README.
**인터페이스:** 기존 PublicNoticeService·HTTP 경로 유지. 상세의 field_values·공개 history와409 current_snapshot_id를 문서화한다.

1. 실제 MySQL에서 공개 후 config/상세, null·빈 배열·whitelist, 비공개 작업 수정 격리, 교체/복구, 미공개·손상본, replay·계산 미준비를 검증하는 실패 시험을 작성한다.
   실행: 전용 DB 환경에서 `./gradlew test --tests kr.ac.myai.backend.PublicationMySqlTest`.
   Expected: 공개 조회가503이라 새 성공/교체 검증이 실패한다.
2. canonical 조회·허용 필드·과거 공개본 비교·오류 응답을 구현한다.
   같은 명령 실행. Expected: 새 조회 시험과 기존 공개 시험 통과.
3. 전체 Java/실제 MySQL·Node·계약 예제·lint·build·bootJar 검증, 독립 코드 검토 후 한국어 문서를 갱신하고 child PR을 만든다.
   Expected: 전체 성공·Java 생략0개. PR base는 아직 main에 반영하지 않은 backend/api-foundation이다.

## 로컬 검증 기록

Java62개를 실제 전용 MySQL8.4.13에서 실행해 전부 통과했고 생략은0개다. Node15개·계약 예제8개·lint·build·bootJar도 통과했다. 실행 JAR로 import→승인→공개→config/상세→교체409→복구와 matches503·실제 DB 중단503·health200을 확인했다.

독립 검토에서 공개 변경 비교 목록에 구역 소속·문서 연결 등의 누락을 발견했다. source_refs·문서 버전·구역 소속 변경의 실패를 재현하고 공개 응답 필드 전체를 비교해 해결했다. 손상된 current 포인터가 다른 모드의 활성 snapshot을 가리키는 경우도500으로 차단한다. replay 이력은 역사 문맥이 같은 공개본만 비교한다.

사례 목록과 변경이력은 소수 자료를 대상으로 순차 조회한다. 자료 증가 시 목록 projection·이력 pagination이 필요하다. Python·프런트·관리 UI·실제 자료 검수·운영 배포는 후속 범위다. CI·자동 리뷰와 PR 링크는 PR 본문에 기록한다.

OpenAI 리뷰 후 공개 A→공개 B→A 복구→B 재공개에서 이력이1개만 남는 문제를 회귀 시험으로 재현했다. 공개 감사 전환을 head_version 순서로 읽고 연속된 동일 revision만 생략해3개 변경을 보존한다. 마지막 반복 공개는 새 변경을 만들지 않는다. 남아 있던 공개 조회 미구현 설명도 수정했다. 수정 후 전체 Java62개·Node15개·계약8개·lint·build·bootJar를 다시 통과했다.
