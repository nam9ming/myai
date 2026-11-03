# 공식 공지 D03 등록·백업 검증 설계

## 목적과 선택

준비한 신규44건을 실제 Java/MySQL 경로로 등록하고, 기존 개발3건의 D03·D05 실패3/성공3·숨김 D06 3건을 보존한다. 사용자가 위임한 자율 진행 범위에서 기존 CLI와 `RecoveryDatabase`를 재사용한다. 제품 API·계약·의존성을 바꾸지 않는다.

기존 실제3건 SQL은 V3 시점 data-only·positional INSERT다. V4에 그대로 넣거나 SQL을 변환해 복구라고 부르지 않는다. 기존10개 CLI 입력·원본으로 새 V4 전용 DB의 기준선을 재구성한다. 과거 batch/등록 시각까지 같은 복원은 아니다. 이번47건의 새 full SQL을 새 빈 서버에 복원해 별도로 검증한다. 기존 DB에 직접 추가하는 방식은 소유권·현재 상태가 확정되지 않아 선택하지 않는다.

## 입력과 소유권

신규 입력은 Git 제외 `development-notices/2026-11-04-d03-preparation/current-preparation.json`의 `package-v2/source-import.json`, SHA `eec585520b72a5e7c84ef9691cf78a6dde09c8cc5efea49215b53f65fe065d6e`다. 초기 `package/`는 사용하지 않는다. 원래3건의 source·6개 frozen 실행·3개 candidate draft를 그대로 사용한다. 원문/준비 pack·기존173파일/26디렉터리·AGENTS·사용자.gitignore·키/D09는 변경하지 않는다.

DB는 기존 helper가 만든 UUID/name/owner label의 MySQL8.4.13 두 인스턴스만 사용한다. JAR 실행 전마다 동일 ID/name/owner·이미지·Running·127.0.0.1 포트 바인딩을 확인한다. 자격증명은 새 임시0600 env·자식 환경에만 전달하며 proof/명령 인자에 기록하지 않는다. ambient DB/Spring/MYAI/OpenAI/Java 주입 설정을 제거하고 필요한 값만 명시한다. 부모만 DB·Gradle·Git을 실행한다.

## 검증 계약

새 V4 기준선은 D03 3/3·D05 6·D06 사건/revision3·원래 pending/uncertain·hidden을 유지한다. 공개4테이블·지점·사전은0이다. 신규44 ID/버전/번호 충돌을 JDBC 파라미터 조회로 먼저 확인한다. 실제 입력의 full metadata·상대 raw ref·원본/hash·블록과 신규 운영 head0/null을 DB 모든 열과 대조한다. source-root는 호출 시 제공하며 DB에 절대 root가 저장된다고 주장하지 않는다.

정렬상 마지막 신규 문서의 버전 UUID만 기존3 중 하나로 바꾼 음성 배치를 초회 전에 실행한다. Reader 통과 뒤 충돌3·신규44행0·전체 기준선 불변을 확인한다. canonical44 성공의 허용 증가는 documents+44/document_versions+44/import_batches+1뿐이다. 정확 재실행·다른 root의 동일 바이트 재실행은 같은 batch와 전체 행 불변이어야 한다. 공백만 다른 입력은 새 source batch1개를 만들며 문서/버전은 늘지 않는다. 기존 metadata 변경·원문 누락은 각각 충돌3/입력2로 거부한다. replay 성공을 DB 전체 무결성 검증 대신 쓰지 않는다.

47건의 full/data SQL·전체16테이블 행·schema/Flyway를 저장하고 새 빈 대상에 full SQL을 복원한다. data SQL은 정확 바이트 비교, 모든 열/제약/인덱스/옵션을 대조한다. full DDL의 동등한 utf8mb4 중복 표기만 기존 B08 방식으로 제한적으로 판단하고 원문 diff를 보존한다. 복원 후 기존10개와 신규44 canonical의 정확 재실행·D05 원본 검증에서 행이 늘지 않아야 한다. 원래 자료의 bytes/mode·안정된 경로는 유지한다.

공개 snapshot이 없는 source/restore DB에서 실제 public JAR의 health200·config/matches503 `PUBLIC_DATA_NOT_READY`·상세 snapshot 누락422·유효하지만 없는 snapshot404를 확인한다. 공개본 존재 시 hidden 필터·계산 성공을 인증한 것으로 쓰지 않는다. 기존 전체 DB 시험은 보존 대상 DB에 실행하지 않는다.

## 인계와 한계

새 private `evaluation/evidence/notice-source-registration-2026-11-04/`에0700/0600으로 코드·원본 참조/hash·실제 명령/종료·actor/시각·SQL·검증·복원 증거를 보존한다. source actor/등록 시각이 별도 source 감사행에 저장된다고 가정하지 않는다. 소유한 자식/DB/임시 credential만 정리한다. 원격 source/통합 CI·자동/새 사람 리뷰까지 확인하고 develop만 병합한다.

D03 47건 저장은 추출47건·권리/원문 완전성·사람 승인·지역/관계·gold/20·20 평가가 아니다. 신규 추출 API·로컬 키·D09·main/배포는 실행하지 않으며 실제 데이터셋은 dev3/holdout0을 유지한다.
