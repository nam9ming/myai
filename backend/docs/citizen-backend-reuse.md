# 여기:it 백엔드 재사용·변경 조사

조사일: 2026-11-18. 개발 기준은 `develop@6145aac75da2fa071cca72d91c5b113f1b48921d`다. 목표·우선순위는 [현행 명세](../../docs/spec/00_목차.md), 작업 순서는 [W01/W03](../../docs/spec/06_개발실행계획.md)을 따른다. 이 문서는 활성 goal의 **기존 기능 조사 결과**이며 새 API·enum·DB 설계의 확정본이 아니다.

`재사용`은 현재 구현을 유지할 수 있다는 뜻이다. `수정`은 기존 검증·소비자까지 함께 바꿔야 한다는 뜻이며, `추가`는 대응하는 시민 기능이 없다는 뜻이다. 아래 시험 링크는 **시험 코드의 존재** 근거다. 조사 중 Java/Python 앱·DB·외부 AI·Flutter를 실행하지 않았고 private 원문·키·gold/D09는 열지 않았다. 과거 실자료 처리·실제 사람 검토·품질·운영 인수를 새로 검증한 기록이 아니다.

## Java·DB: 기능별 판정

아래 표는 조사 당시 기준이다. 이후 [시민 검토](citizen-review.md)·[공개](citizen-publication.md)·[목록/상세·이력](../../contracts/citizen-api.md)을 추가했다. 이번 [시민 수동 추출](../../contracts/citizen-extraction.md)은 기존 원문 입력·봉인 보관·Python 사람 수정 선언·Java D05/S10을 재사용하고 출력 family와 기존 평가 격리를 보완한다. 시민 D06/Java 사람 인계·검색/정규화·실제 화면/사람 인수는 후속이며, 합성 소프트웨어 검증과 실제 품질은 구별한다. 새 단계의 실제 실행·리뷰/PR 증거는 각 계획을 따른다.

| 사용자 기능 | 현재 동작·구현 근거 | 판정·시민 확장 영향 | 관련 시험 정의 |
| --- | --- | --- | --- |
| 설정·자료 버전 | [공개 controller](../src/main/java/kr/ac/myai/backend/controller/PublicNoticeController.java#L22)와 [snapshot 조회](../src/main/java/kr/ac/myai/backend/service/SnapshotNoticeService.java#L52)가 공개 head·checksum·현재/과거 문맥을 확인한다 | 재사용하되 기존 설정의 단일 구역·5지점·14일/500m는 시민 공통 설정과 분리 | [PublicApiTest](../src/test/java/kr/ac/myai/backend/PublicApiTest.java), [PublicationMySqlTest](../src/test/java/kr/ac/myai/backend/PublicationMySqlTest.java) |
| 기존 소상공인 선별 | [MatchRequest](../src/main/java/kr/ac/myai/backend/dto/MatchRequest.java#L12)는 point_id·7요일 영업조건·3유형·분류·start/distance 정렬을 사용하고 [matches](../src/main/java/kr/ac/myai/backend/service/SnapshotNoticeService.java#L76)가 Python을 호출한다 | 보존. 신청 상태·시민 분야를 기존 classification/types로 치환하지 않는다 | [CalculationMySqlTest](../src/test/java/kr/ac/myai/backend/CalculationMySqlTest.java), [SnapshotCalculationTest](../src/test/java/kr/ac/myai/backend/SnapshotCalculationTest.java) |
| 시민 목록·검색·필터 | controller의 공개 기능은 config/matches/event 세 가지이며 [저장소](../src/main/java/kr/ac/myai/backend/repository/PublicSnapshotRepository.java)는 snapshot/head/history를 조회한다 | 추가. 지점·영업시간 없이 5분야·지역·모집·비용·신청/진행기간을 검색하는 계약·조회는 없다 | 신규 시민 기능 시험 없음. [Y01~Y06·Y08/Y10 초안](../../docs/spec/05_시험과인수기준.md#여기it-새-범위-인수)과 연결 필요 |
| 사실 상세·대상·예외·출처 | [event/publicEvent](../src/main/java/kr/ac/myai/backend/service/SnapshotNoticeService.java#L114)는 일정·장소·applicability/exceptions·근거·확인 상태를 반환한다 | 공통 근거 기반 재사용. 신청기간·모집·조건별 비용·방법·준비사항·자격 지역 구조는 추가 필요 | [PublicationMySqlTest](../src/test/java/kr/ac/myai/backend/PublicationMySqlTest.java), [ReviewedImportReaderTest](../src/test/java/kr/ac/myai/backend/ReviewedImportReaderTest.java) |
| 원문 등록·확인·사용권 | [SourceUploadService](../src/main/java/kr/ac/myai/backend/local/SourceUploadService.java#L49)는 원래 bytes/hash를 보관하고, [SourceReviewService](../src/main/java/kr/ac/myai/backend/service/SourceReviewService.java#L42)는 확인·권한 이력을 추가한다 | 재사용. 시민 사실을 원문 metadata에 임의 삽입하지 않는다. PDF 텍스트화가 전체성·사실 검토 완료는 아니다 | [SourceUploadApiTest](../src/test/java/kr/ac/myai/backend/SourceUploadApiTest.java), [SourceReviewMySqlTest](../src/test/java/kr/ac/myai/backend/SourceReviewMySqlTest.java) |
| AI 성공·실패·사람 인계 | [ExtractionImportService](../src/main/java/kr/ac/myai/backend/service/ExtractionImportService.java#L51)와 [HumanHandoffImportService](../src/main/java/kr/ac/myai/backend/service/HumanHandoffImportService.java#L63)가 원본·명시 revision·projection을 대조한다 | 보관·실패 보존 재사용. [ExtractionArchiveReader](../src/main/java/kr/ac/myai/backend/extraction/ExtractionArchiveReader.java#L155)의 스키마와 Python/인계 검증도 새 계약에 함께 대응해야 한다 | [ExtractionArchiveReaderTest](../src/test/java/kr/ac/myai/backend/ExtractionArchiveReaderTest.java), [HumanHandoffMySqlTest](../src/test/java/kr/ac/myai/backend/HumanHandoffMySqlTest.java) |
| 사람 수정·revision·감사 | [ReviewedImportReader](../src/main/java/kr/ac/myai/backend/importing/ReviewedImportReader.java#L243)의 exact shape·3유형·근거 검사, [HumanReviewChanges](../src/main/java/kr/ac/myai/backend/importing/HumanReviewChanges.java#L17)의 필드 목록, [저장소](../src/main/java/kr/ac/myai/backend/repository/ReviewedImportRepository.java#L129)의 append/CAS·감사를 사용한다 | 수정. 새 필드는 현재 추가 키 거부 대상이다. 수정 전후·검토자·시각·기존 감사 prefix까지 보존해야 한다 | [ReviewedImportMySqlTest](../src/test/java/kr/ac/myai/backend/ReviewedImportMySqlTest.java), [HumanReviewChangesTest](../src/test/java/kr/ac/myai/backend/HumanReviewChangesTest.java) |
| 승인·preview·공개 | [PublicationService](../src/main/java/kr/ac/myai/backend/service/PublicationService.java#L88)가 AI 초안 직접 승인을 차단하고, 공개 때 검증·snapshot·구성원·head·감사를 함께 commit한다. preview는 읽기 전용이다 | 게이트·트랜잭션 재사용. [PublicationContent](../src/main/java/kr/ac/myai/backend/publication/PublicationContent.java#L104)의 명시 투영과 승인/공개 검증에 새 필드 반영 필요 | [PublicationMySqlTest](../src/test/java/kr/ac/myai/backend/PublicationMySqlTest.java), [PublicationContentTest](../src/test/java/kr/ac/myai/backend/PublicationContentTest.java) |
| 변경 전후·rollback | [history](../src/main/java/kr/ac/myai/backend/service/SnapshotNoticeService.java#L194)는 같은 공개 문맥에서 실제 공개/복구된 값 차이를 제공한다. [rollback](../src/main/java/kr/ac/myai/backend/service/PublicationService.java#L157)은 과거 불변 공개본으로 포인터를 바꾼다 | 기반 재사용. 전체 수집/비공개 검토 이력과 다르다. 새 사실도 공개 projection에 포함돼야 차이에 나타난다. 이력 부재는 변경 없음이 아니다 | [PublicationMySqlTest](../src/test/java/kr/ac/myai/backend/PublicationMySqlTest.java) |
| JSON 내보내기 | [SnapshotExportService](../src/main/java/kr/ac/myai/backend/service/SnapshotExportService.java#L63)는 공개 canonical UTF-8/hash를 그대로 보관하고 파일 실패·충돌을 DB 성공과 구분한다 | 수정. exact 공개 allowlist·과거본 reader가 새 구조와 함께 대응해야 한다. 과거 bytes/hash는 재작성하지 않는다 | [SnapshotExportTest](../src/test/java/kr/ac/myai/backend/SnapshotExportTest.java) |
| 검토 보고서 | [ReviewReportService](../src/main/java/kr/ac/myai/backend/review/ReviewReportService.java#L69)가 원문·모든 시도·revision·감사·공개본·명시 preview를 대조한다 | 표시 기반 재사용. 기존 schema 선택·stored validation은 수정 영향 대상이다. 별도 관리 UI 신설은 필수가 아니다 | [ReviewReportMySqlTest](../src/test/java/kr/ac/myai/backend/ReviewReportMySqlTest.java) |
| DB·복구·보안 | [V1](../src/main/resources/db/migration/V1__create_review_and_publication_schema.sql)은 revision/canonical JSON·hash·FK·제약을 분리한다. [관리 필터](../src/main/java/kr/ac/myai/backend/local/LocalApiSecurityFilter.java)와 [안전한 오류](../src/main/java/kr/ac/myai/backend/controller/ApiExceptionHandler.java)를 사용한다 | DB 엔진·로컬 경계 재사용. 적용 V1~V4 불변. 새 저장/색인은 검색·페이지·호환 계약 합의 후 결정. 새 공개 경로의 body limit·CORS·최소 로그 적용도 확인 | [MySqlFoundationTest](../src/test/java/kr/ac/myai/backend/MySqlFoundationTest.java), [DatabaseRecoveryTest](../src/test/java/kr/ac/myai/backend/DatabaseRecoveryTest.java), [LocalApiSecurityTest](../src/test/java/kr/ac/myai/backend/LocalApiSecurityTest.java) |

기존 5지점 조건은 요청 DTO만의 문제가 아니다. [공개 명령](../src/main/java/kr/ac/myai/backend/publication/PublicationCommand.java#L27)의 points, [snapshot 생성](../src/main/java/kr/ac/myai/backend/publication/PublicationContent.java#L83)의 14일/500m, [공개 reader](../src/main/java/kr/ac/myai/backend/service/SnapshotNoticeService.java#L144), [export reader](../src/main/java/kr/ac/myai/backend/service/SnapshotExportService.java#L90)까지 호환 방식이 필요하다. 시민 목록을 기존 matches로 우회하면 이 조건을 물려받는다.

## Python: 재사용 기반과 변경 전파

| 기능 | 판정·현재 경계 | 구현 / 시험 정의 |
| --- | --- | --- |
| 시간·거리 계산 | calc-v1·C01~C10은 재사용. 시민 조회의 공통 지점/기간 제한으로 전용하지 않는다 | [protocol](../../processing/matching/protocol.py#L282), [engine](../../processing/matching/engine.py#L238) / [test_protocol](../../processing/tests/test_protocol.py), [test_engine](../../processing/tests/test_engine.py) |
| 일정·미상 정규화 | KST·반개구간·익일·반복·date_only 의미 재사용. 신청기간·상시·선착순은 별도 의미 합의 필요 | [intervals](../../processing/matching/intervals.py#L90), [draft](../../processing/extraction/draft.py#L84) / [test_intervals](../../processing/tests/test_intervals.py), [test_extraction_draft](../../processing/tests/test_extraction_draft.py) |
| 스키마·근거·knowledge | 현재 3유형·폐쇄 객체·code point/hash 검증. 시민 분류·신청·비용·준비사항 등은 대응 필드가 없다 | [schema](../../processing/extraction/schema.py#L9), [validation](../../processing/extraction/validation.py#L156) / [test_extraction_validation](../../processing/tests/test_extraction_validation.py) |
| 준비·프롬프트·API | 별도 일괄 실행·최대3시도·요청/응답/실패 보존 재사용. 새 필드는 schema/prompt/metadata에 전파된다 | [prompt](../../processing/extraction/prompt.py), [api](../../processing/extraction/api.py#L148) / [test_extraction_prompt_metadata](../../processing/tests/test_extraction_prompt_metadata.py), [test_extraction_api](../../processing/tests/test_extraction_api.py) |
| 원본 보관·봉인 | 같은 바이트 재실행·충돌 검사·읽기 전용 봉인 검증을 유지. 과거본 검증 호환이 신규 스키마 구현의 선행 조건이다 | [archive](../../processing/extraction/archive.py#L208), [metadata](../../processing/extraction/metadata.py#L41) / [test_extraction_archive](../../processing/tests/test_extraction_archive.py), [test_extraction_sealed](../../processing/tests/test_extraction_sealed.py) |
| 장문 분할 | 부분 문맥·문서 cycle/실제 호출 수·실패 보존 재사용. 부분 입력에서 not_stated 확정·자동 사건 병합을 하지 않는다 | [chunks](../../processing/extraction/chunks.py), [chunk_archive](../../processing/extraction/chunk_archive.py), [draft 차단](../../processing/extraction/draft.py#L45) / [test_chunked_extraction](../../processing/tests/test_chunked_extraction.py), [test_chunked_archive_integrity](../../processing/tests/test_chunked_archive_integrity.py) |
| 규칙 기준선 | 실행/보관 구조 재사용. 프로필 3유형과 문서당 사건/일정1건 한계는 시민 추출·정답으로 전용 불가 | [rules](../../processing/extraction/rules.py#L28) / [test_rules](../../processing/tests/test_rules.py), [test_rule_evaluation](../../processing/tests/test_rule_evaluation.py) |
| 초안·사람 수정·Java 인계 | 원본/감사 경계 재사용. 새 필드가 draft 투영에서 빠지면 D06·사람 인계로 전달되지 않는다 | [draft._project_output](../../processing/extraction/draft.py#L56), [human_handoff](../../processing/evaluation/human_handoff.py#L30) / [test_human_reviews](../../processing/tests/test_human_reviews.py), [test_human_handoff](../../processing/tests/test_human_handoff.py) |
| 데이터셋·독립 gold·채점 | 관계 연결요소·누출/노출·전체 버전·최초/재시험 보존 재사용. 기존3유형 집계·고정8필드·90% 분모에 새 분야/필드를 조용히 섞지 않는다 | [dataset](../../processing/evaluation/dataset.py#L42), [gold](../../processing/evaluation/gold.py#L14), [scoring](../../processing/evaluation/scoring.py#L195) / [test_dataset](../../processing/tests/test_dataset.py), [test_scoring](../../processing/tests/test_scoring.py) |
| 비교·선별 평가 | 같은 gold·부모 원본·6뷰·불완전/충돌/실패 분모 보존. 기존 지점/영업시간 평가가 시민 검색 품질 평가는 아니다 | [comparison](../../processing/evaluation/comparison.py), [matching_projection](../../processing/evaluation/matching_projection.py), [matching](../../processing/evaluation/matching.py) / [test_paired_comparison](../../processing/tests/test_paired_comparison.py), [test_matching_evaluation](../../processing/tests/test_matching_evaluation.py) |

**과거 AI 보관본 호환 위험:** 현재 [metadata](../../processing/extraction/metadata.py#L41)는 현행 SCHEMA_VERSION을 검사하고, [archive 검증](../../processing/extraction/archive.py#L208)은 보관 요청을 현행 request_bytes/render_prompt로 재생성한 뒤 출력을 재검증한다. [prompt](../../processing/extraction/prompt.py#L49)의 과거 프롬프트 버전도 현재 output_schema를 사용한다. 따라서 schema.py의 enum/필드 또는 버전 문자열만 교체하면 기존 D05·봉인·사람 인계·평가 원본의 재검증까지 깨질 수 있다. 기존 버전의 의미·바이트를 보존하는 읽기 경계를 먼저 정해야 한다. 이 조사는 새 버전 이름·dispatch 구조를 확정하지 않는다.

[prepare](../../processing/extraction/archive.py#L157)는 같은 root의 동일 입력 bytes에 대해 `prepared/<input_sha256>`를 사용하고 프롬프트도 함께 보관한다. 새 schema/prompt로 프롬프트 bytes가 달라지면 기존 산출물과 `ARCHIVE_CONFLICT`가 발생할 수 있다. 기존 파일을 덮어쓰지 않는 보호는 유지하면서 준비 산출물의 경로·버전 호환도 함께 검토해야 한다.

새 필드의 영향은 `schema → validation/prompt/metadata/api/archive/장문 → draft → 사람 수정/인계 → Java 등록·D06`으로 이어진다. 평가는 `dataset/실행 연결 → gold/채점 → records/comparison/matching_projection → 보관본 재검증`까지 닿는다. 계약 예제 검증기·공개 fixture·테스트 입력·실행/복구 문서도 함께 대조한다.

## 미병합 Flutter 후보와 연동 차이

비교 대상은 `frontend/yeogi-it-flutter@f3bed4f196194ff62c5ed3c3e2fdb411c68114f6`다. develop의 구현·팀 합의로 간주하지 않는다. 후보 변경은 frontend와 Flutter CI이며 backend/processing/contracts는 변경하지 않았다. 아래 링크는 후보의 고정 commit을 가리킨다.

| 화면 기능 | 후보 코드의 현재 상태 | 백엔드/화면 합의·인계 사항 |
| --- | --- | --- |
| 목록·검색 | [repositories.dart:106~185](https://github.com/nam9ming/myai/blob/f3bed4f196194ff62c5ed3c3e2fdb411c68114f6/frontend/lib/data/repositories.dart#L106): prototype 합성16건, backend-fixture 고정 조건 HTTP, api 모드는 config 후 시민 feed 미지원 처리 | 고정 matches 호출은 일반 시민 목록 구현이 아니다. 검색 대상·페이지/건수·정렬·서버 기준 시점을 계약으로 연결 |
| 5분야·카드 | [models.dart:163~196](https://github.com/nam9ming/myai/blob/f3bed4f196194ff62c5ed3c3e2fdb411c68114f6/frontend/lib/data/models.dart#L163): 합성 단일 category와 기존 types[] 투영은 다르며 첫 일정/장소/기관을 대표값으로 사용 | 기존 construction/traffic 축약과 시민 분야를 구별. 새 필드를 서버에 추가해도 fromApi가 자동 소비하지 않음. 복수 분야·대표 일정·일정↔장소 연결 합의 |
| 신청·진행·모집·비용 | [models.dart:199~231](https://github.com/nam9ming/myai/blob/f3bed4f196194ff62c5ed3c3e2fdb411c68114f6/frontend/lib/data/models.dart#L199): 신청일이 있어야 isOpen 판정, 비용 null/0을 구별하나 기존 API 투영은 새 신청/비용 필드를 읽지 않음 | 신청 마감≠진행 종료. 상시/선착순·조기마감·미상·조건별/부대비용·통화·시각 정밀도 합의 |
| 지역·개인화 | [models.dart:245~355](https://github.com/nam9ming/myai/blob/f3bed4f196194ff62c5ed3c3e2fdb411c68114f6/frontend/lib/data/models.dart#L245): 합성 자료의 지역/관심/연령 필터·정렬 신호 | 적용 지역·진행 장소·거주 자격 지역은 별개. 관심·연령은 자격 확정이 아니며 시제품 가중치는 확정 계약이 아님 |
| 근거·변경 | [detail_page.dart:403~669](https://github.com/nam9ming/myai/blob/f3bed4f196194ff62c5ed3c3e2fdb411c68114f6/frontend/lib/features/notices/detail_page.dart#L403): 복수 출처·전후 근거를 표시하나 history=[]의 미확인 안내는 없음 | 개별 공개본 history와 전체 변경 피드를 구별. 확보하지 않은 이력을 생성하거나 변경 없음으로 표시하지 않음 |
| 관심·설정 | [app_state.dart:38~175](https://github.com/nam9ming/myai/blob/f3bed4f196194ff62c5ed3c3e2fdb411c68114f6/frontend/lib/app/app_state.dart#L38): 브라우저 저장과 모드별 저장 문맥 | 서버 계정/동기화 API는 초기 필수 아님. 저장 수명·초기화·폐기 snapshot409·최신본 갱신 의미를 합의 |
| 입력 오류 | [models.dart:365~386](https://github.com/nam9ming/myai/blob/f3bed4f196194ff62c5ed3c3e2fdb411c68114f6/frontend/lib/data/models.dart#L365): field_errors를 Map일 때만 읽음 | **현행 계약 불일치:** [공통 오류 예제](../../contracts/examples/error-response.json)의 field_errors는 배열이다. 프런트 수정 인계 항목이며 백엔드 계약을 후보의 Map 형태로 바꾸지 않음 |
| 기존 가게 기능 | 고정 backend-fixture 요청은 있으나 가게 조건 입력·replay·분류별 counts·동시간 묶음의 사용자 흐름은 확인되지 않음 | 백엔드 보존과 Flutter 인수 완료를 구분. 해당 흐름·같은 snapshot의 계산/상세 연결을 프런트 담당과 확인 |

후보 [API_GAPS.md](https://github.com/nam9ming/myai/blob/f3bed4f196194ff62c5ed3c3e2fdb411c68114f6/frontend/API_GAPS.md#L34)의 새 경로·JSON 조각은 명시적 **논의 제안**이다. 현재 API로 채택된 것이 아니다. 후보의 fixture 복사본5개와 요청은 기존 계약 파일과 바이트가 같지만, 합성 시민16건의 문자열 ID·단일 category·신청일/비용 모델은 기존 UUID·types[]·영업조건 계약과 다르다.

한 문서↔여러 사건, 한 사건↔여러 문서와 일정/장소의 연결을 유지한다. 문서 ID를 사건 카드 ID로 대체하거나 첫 일정/장소만으로 전체 관계를 확정하지 않는다. 후보의 실행/시험 문서는 기존 작성 기록이며 이번 조사에서 재실행하지 않았다.

## 다음 작업과 결정 자료

| 순서 | 준비·변경 범위 | 확인할 산출물·인수 |
| --- | --- | --- |
| 1. 의미·호환 합의 | 분야/복수분류·지역3의미·신청/진행·모집/취소·조건/비용·검색/정렬/페이지, 기존/새 계약의 읽기 호환 | 화면별 필드·필수/미상·요청/응답/오류·집계 단위, 기존 소비자·보관본 유지 방식. 새 경로/enum/DDL은 아직 미정 |
| 2. 기대 결과 고정 | 합의한 의미의 합성 입력·필터/정렬·미상·실패, 과거 archive/snapshot 읽기 회귀 | 기존 계약·hash·보관 bytes·공개 조건 보존을 먼저 검증할 사례, Y01~Y10의 백엔드 대응표 |
| 3. 입력·검토·저장 | 새 필드의 원문 근거·AI/사람 입력·import·수정 전후·승인·감사 | 새 metadata로 기존 사실을 덮지 않음. migration이 필요하면 적용 V1~V4 보존·백업/전환/복구 확인 |
| 4. 공개·시민 조회 | 승인/preview/publish·새 공개 투영·지점 없는 시민 조회·검색/필터 | 승인 전 차단·공개 원자성·오류/개인정보·새 경로의 body limit/CORS/최소 로그, 기존 소상공인 회귀 |
| 5. 전체 소비자·연동 | export/rollback·보고서·Python/평가 원본·프런트 DTO·공통 오류 | 같은 snapshot·조건·출처·미상 의미, 합성/실제 구분, 과거본 재검증과 파일 실패 보존 |
| 6. 반복 검증·수정 | 명묵에게 동일 데이터/초기화·환경·버전·기대 결과 제공, 김윤기 백엔드 원인 조치 | 재현·실제 결과·수정 전후·재검증·실행법·제약/미완료. 실제 담당자의 합의·검증을 대신했다고 기록하지 않음 |

### 제공된 논의 기록과 차별화 검토안

사용자가 2026-11-18 제공한 `001_논의정리.md`는 **2026-11-06 기준의 대화 정리**다. 원문의 발언자 신원·기존 서비스 평가·자료 제공/협의·일정이 검증됐다는 뜻이 아니다. 시민 확대·가입 방식 등의 당시 미확정 표기는 11월17일의 시민 전체·5분야·초기 브라우저 저장 결정을 되돌리지 않는다. 원문 작업본은 이 저장소에 복사하지 않았다.

해당 문서는 정확히3개로 명명한 최종 목록을 제공하지 않는다. 다만 5절의 차별화 가설·8절의 관심 조건·4절의 카드/상세 역할을 다음과 같이 묶어 **개발 검토안**으로 제안할 수 있다. 아래 명칭·3개 묶음은 작성자의 정리이며 당시 합의한 정확한3후보라고 주장하지 않는다.

| 도출한 검토 축 | 제공 기록의 근거·의도 | 백엔드 연결·경계 |
| --- | --- | --- |
| 활동 중심 통합 탐색 | 장소/시설 위치에서 그곳의 교육·행사·공사·프로그램 내용을 확인하는 탐색으로 확장 | 시민 목록/상세·5분야·적용 지역/진행 장소·출처·다중 일정 연결. 지도 서비스 신규 구축·전수 수집·실시간 사고 알림으로 자동 확대하지 않음 |
| 관심 조건별 정보 선별 | 관심 지역·주제·원하는 활동을 직접 선택해 탐색 부담을 줄임 | 합의한 필터/정렬·추천 이유·미선택 기본 탐색. 브라우저 설정·개인정보 최소화 유지, 연령/관심으로 자격 확정 금지 |
| 핵심 내용·참여 안내 | 외부 홈페이지 이동 전에 핵심 내용을 이해하고 신청·참여·방문 조건과 경로를 확인 | 신청/진행 일정·대상/자격·방법/준비사항·비용·근거·원문. 원문에 없는 절차/서류·확인되지 않은 신청 가능 상태 생성 금지 |

최종3후보와의 대응·이번 버전 완료 범위는 미확정으로 남긴다. 4개 AI 구체화 관점을3후보로 대체하지 않는다. 변경 추적·원문 확인 등 기존 신뢰성 요구는 어떤 후보 묶음을 채택하더라도 별도로 유지한다.

2026-11-18 사용자는 모호한 사항을 별도로 정리하고, 확정된 작업부터 진행하며, 해당 내용을 물을 때 보고하도록 지시했다. 현재 미확정 사항은 [별도 기록](citizen-open-items.md)에 보관한다. 이를 이유로 추가 질문을 보내거나 전체 작업을 멈추지 않는다. 미확정 사항에 의존하는 동작은 임의 확정하지 않고, 확정된 5분야·정보 의미·기존 기능/보관본 호환·공개/보안 경계와 검증부터 진행한다.

## 검증 구분·인계

이번 수정 전 Node24.21.0의 인프라34시험과 합성 계약9JSON이 통과했다. 본 문서·링크·도구·PR/원격 검증은 [조사 계획](../../docs/superpowers/plans/2026-11-18-citizen-backend-inventory.md)과 해당 PR의 실제 수행 기록을 따른다. MySQL 시험은 전용 DB·`MYAI_MYSQL_TESTS=true` 등 필요한 환경을 갖춰야 하며 시험 파일 존재만으로 실행 통과를 주장하지 않는다.

현재 단계 산출물은 재사용/변경 조사와 후속 합의 자료다. 새 시민 API·5분야 자료 저장/추출·실제 프런트 연동·독립 gold/40문서·사용자 평가·운영 배포 완료가 아니다. source/fixture/실행 결과·사람 인수를 구분해 인계한다.
