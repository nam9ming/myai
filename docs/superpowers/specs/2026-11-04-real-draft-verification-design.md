# 실제 개발 공지의 숨김 D06 저장 검증

## 목표

이미 추출한 공사·행사·교통 개발 공지3건을 새 격리 MySQL8.4.13에 저장하고 D03/D05/D06 출처·재실행·공개 차단을 실제 Java JAR로 확인한다. 자료·AI 원출력·기존 초안은 편집하지 않는다.

## 범위와 경계

- 기존 source-import-v1, frozen v1 실패/v2 성공 D05, 개발 후보를 연결한 ai-draft-import-v1 파일을 그대로 사용한다. source·AI 입력·raw asset/hash·등록 보관본이 연결되는지 먼저 확인한다.
- 개발 구역/사전 후보는 확정 사실이 아니다. area_membership=uncertain, 장소 geometry=null·미검토, origin=ai_draft·draft/hidden·reviewer/time=null·human_overrides=[]를 유지한다.
- 실제 사람 수정본·승인·정답표를 생성하지 않는다. 새 모델/API/키 접근·외부 배포·기존 DB/연구실 서비스 변경을 하지 않는다.
- Java21·기존 실행 JAR/Python3.13·표준 라이브러리와 Docker만 사용한다. 새 런타임 의존성·공개 계약·DB migration은 추가하지 않는다.
- 사용자 .gitignore 변경·기존 AGENTS·기존 원문/보관본·다른 작업 공간을 보존한다. main 병합은 사람 담당이다.

## 완료 증거

1. 선택한 원본 전체의 상대 경로·바이트 hash·권한을 실행 전후 비교한다. 원래 source/초안 파일을 수정하거나 권한을 넓히지 않는다.
2. 새로운 localhost 전용 MySQL8.4.13·빈 DB를 식별하고 기존 JAR의 Flyway로 준비한다. 명령은 실제 local-import/local-extraction을 사용한다.
3. D03 3문서/3버전·D05 v1실패3/v2성공3·D06 숨김 사건3/revision3을 저장한다. D05 원래 상태·mode·receipt/metadata/hash·D03/근거·출처를 DB와 대조한다.
4. 동일 source·6실행·3초안의 재실행이 같은 참조를 반환하고 DB의 모든 application 행/기존 revision 바이트를 바꾸지 않아야 한다.
5. v1실패 초안 생성·AI 초안 직접 approve·새 파일의 의미값 위조·D03/D05 참조 불일치는 거부하며 기존 DB를 보존한다. 부정 시험은 새 복사 파일/자체 DB에서만 수행하고 보관본을 변조하지 않는다.
6. snapshots/snapshot_revisions/publication_heads/publication_audits는 전후 비어 있어야 한다. D06에 사람 검토 메타데이터·좌표·공개 intent를 만들지 않는다.
7. 독립 전체 리뷰1회·유효 지적 모두 수정·현재 단계 PR의 CI/자동/도착한 사람 리뷰를 확인하고 develop만 병합한다. 실제 자료/AI 원출력/개인 기록/키는 Git/Actions artifact에 올리지 않는다.
8. 실행 명령·검증 결과·실제 사람/금표/40문서·운영 미완료를 한국어 문서에 반영하고 private 증거를 체크섬과 함께 보존한다.

## 실행 결과의 의미

이는 개발 자료3건의 저장·무결성 검증이다. 실제 사실/이용권한의 독립 검토·구역/좌표 확정·사람 승인·모델 성능·공개/배포 완료를 뜻하지 않는다. 원문과 읽기 전용 경로는 실제 사용 전에도 보존·재검증해야 한다.

