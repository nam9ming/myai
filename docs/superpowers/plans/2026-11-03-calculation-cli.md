# Python 계산 CLI 구현 계획

## 목표와 범위

`calc-v1` stdin/stdout CLI에서 승인된 snapshot의 C01~C10을 계산한다. Java·Python 작업 범위를 유지한다. 이번 단계는 Python 순수 계산과 CLI·회귀 시험·CI이며, Spring 프로세스 adapter는 다음 단계에서 연결한다. 기존 public matches의 미연결503은 이번 단계에서 바꾸지 않는다.

기준: [계산 규칙](../../spec/04_계산규칙과기술설계.md), [데이터 계약](../../spec/03_데이터와AI.md), [CLI 계약](../../../contracts/calculation-bridge.md). Python3.13 표준 라이브러리와 시스템의 Asia/Seoul 시간대 자료를 사용한다. 외부 패키지·DB·네트워크 호출·조건 저장은 추가하지 않는다.

## 구현 결정

- context에 D07의 `data_kind`, `history_fidelity`를 필수 전달한다. current의 anchor는 server_now의 KST 날짜로 계산하고 입력 anchor와 대조한다. replay는 고정 날짜·기준 시각·cutoff를 검증한다.
- 반복 날짜가 null인 exact_time은 명시된 시작·종료 날짜와 시각의 연속 구간이다. 시작·종료 날짜가 같으면 end_day_offset으로 익일 종료를 표현한다. 다른 종료 날짜가 명시되면 offset을 다시 더하지 않는다. 명시적 recurrence_dates가 있으면 각 날짜의 시간+offset 구간만 전개한다. 빈 배열은 발생 없음이다. 날짜 범위만 보고 매일 반복시키지 않는다.
- unknown 영업일은 그날 시작할 수 있는 최대24시간 구간의 합집합인 그날00시~익일24시를 가능 범위로 사용한다. 실제 영업이나 확정 중첩으로 보고하지 않는다. 알려진 구간으로 이미 덮인 부분은 미상 때문에 다시 강등하지 않는다.
- 사건의 source_version_ids는 현행 검토본이 선택한 의존 출처다. 모든 선택 출처를 검사하며, snapshot의 다른 사건 출처는 영향을 주지 않는다. replay에는 cutoff 이후의 출처·확인을 허용하지 않는다.
- 같은 occurrence의 날짜·영업·장소를 결합한다. 확정 중첩만 matched_occurrence_ids와 동시간 묶음에 사용한다. 미상 구간 때문에 총 중첩을 확정할 수 없으면 분 수는 null이다.
- 사실 필드는 공개 whitelist로 투영한다. 검토자·비공개 원문·알 수 없는 키는 출력하지 않는다. Java가 승인·공개·snapshot checksum을 검증하고 Python은 입력 원문 바이트 hash를 돌려준다.
- 시작순은 조회창 안 첫 시작→거리→event_id, 거리순은 거리→시작→event_id다. 취소는 취소 근거 출처의 성공 확인 시각 최신순이다. 같은 결과의 ID·순서는 결정적이다.

## 단계와 검증

1. 구면 거리·시간 합집합의 실패 시험부터 구현한다. 500m 양쪽, 선분 내부·퇴화, 자정·전날 이월·접점0·초 단위·14일 경계를 확인한다.
2. D06 합성 입력으로 결정표·미상·취소·최신성·재현·필터·정렬·동시간 묶음의 실패 시험을 작성하고 구현한다. 서로 다른 occurrence의 장소를 섞지 않는 반례를 포함한다.
3. 실제 subprocess로 UTF-8·원문 hash·단일 JSON·오염/오류·8MiB·중복 키·잘못된 참조·비정상 값·안전한 종료를 시험한다. README·계약·CI에 실제 명령을 연결한다.
4. `python3.13 -m unittest discover -s processing/tests -v`, 기존 npm lint/test/build를 실행한다. producer와 Java 소비 계약을 포함한 전체 자체 리뷰 및 별도 리뷰를 거친다. 유효한 지적을 고치고 재검증한다.
5. backend/api-foundation 대상 PR을 제출한다. 최신 SHA의 CI와 AI 리뷰 지적0을 확인한 뒤 사용자 지시에 따라 병합한다. main PR은 사람 병합 대기다.

## 전체 리뷰 초점

부분 날짜·시간, recurrence의 빈 배열, 전날 미상 영업과 다음날 휴무, 위경도 극점·날짜변경선·반대편 선분, partial/unknown geometry, 서로 다른 발생 장소, 구형 출처와 현재 출처의 의존성, replay의 미래 지식 유입, 취소의 stale 상태, 알려진 중첩과 미상 총량의 구분, 비공개 키 유출·큰 입력/출력·깊은 JSON·반복 계산 비용을 직접 확인한다. 실제 AI 추출·실자료 품질·HTTP 계산 연결·운영 성능은 이 CLI 시험만으로 완료 주장하지 않는다.
