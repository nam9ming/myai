# D08 데이터셋·분할 manifest v1

고정할 문서 버전과 개발/확인 배정표를 검증·보관하는 **비공개 로컬 계약**이다. [D03/D04/D08](../docs/spec/03_데이터와AI.md)와 [자료 분할·평가 기준](../docs/spec/05_시험과인수기준.md)을 따른다. 공개 API·DB 스키마·정답표 형식을 변경하지 않는다.

## 입력

UTF-8 JSON 한 건, 최대8MiB·깊이100. 중복 키·잘못된 Unicode·추가 키는 거부한다. 모든 객체는 아래 키를 정확히 포함한다. ID는 소문자 UUID, hash는 소문자 SHA-256, 시각은 실제 날짜인 UTC RFC3339(소수초 최대9자리)다.

| 객체 | 필수 키·값 |
|---|---|
| 최상위 | `schema_version="dataset-manifest-v1"`, `dataset_version`, `data_kind`, `documents`, `events`, `relations`, `split_assignments`, `grouping_review` |
| documents[] | `document_id`, `official_url`, `versions`, `types`, `feature_tags`, `exposure_status`, `exposure_note` |
| versions[] | `document_version_id`, `input_sha256` |
| events[] | `event_id`, `document_ids`, `split_group_id`, `suspected_duplicate_ids` |
| relations[] | `from_document_id`, `to_document_id`, `type`, `reviewed_by`, `reason`, `created_at` |
| split_assignments[] | `split_group_id`, `document_id`, `split`, `assigned_at`, `assigned_by` |
| grouping_review | `reviewed_by`, `reviewed_at`, `note` |

- dataset_version은100자 이하 비공백 문자열이며 제어 문자를 금지한다. 디렉터리 이름으로 직접 사용하지 않는다. 담당자 식별자는128자 이하 비공백·제어 문자 없는 문자열이다.
- data_kind는 `synthetic|real`. documents·versions는 비어 있을 수 없으며 각 문서에는 배정이 정확히1개 필요하다. 사건 없는 문서도 배정한다.
- input_sha256는 해당 `ai-input-v1` **원본 바이트**의 제공 hash다. 이 CLI는 본문을 읽지 않으므로 실제 입력과의 일치나 공식 자료 여부를 증명하지 않는다. 평가 시 원문/D05와 별도 대조해야 한다.
- official_url은 사용자 인증정보 없는 http/https URL이다. fragment·호스트 대소문자를 정규화한 같은 URL을 다른 document_id로 중복 등록하지 않는다. URL 별칭/다른 게시물의 동일성은 사람이 판단한다. 네트워크 요청은 하지 않는다.
- types는 `construction|event|traffic` 중복 없는 배열이며 `[]`는 분류 미상이다. feature_tags는 `unknown_date|unknown_time|multiple_times|multiple_locations` 중복 없는 배열이다. 이 분포는 제공된 주석 집계이며 정답·정확도가 아니다.
- exposure_status는 `development|unexposed|unknown`, exposure_note는 비공백 문자열이다. 개발·프롬프트 튜닝에 노출된 문서를 unexposed로 바꾸지 않는다. 신원/권한이나 실제 비노출 여부를 이 도구가 인증하지 않는다.
- relations.type은 `corrects|cancels|reposts|duplicates`. 자기 참조·미등록 문서·동일 관계 중복·정정 방향의 순환을 거부한다. 검토자·이유·시각을 보존한다.
- grouping_review의 reviewed_by/at는 함께 null이거나 함께 제공한다. note는 비공백이다. 검토자가 기재돼 있어도 실제 사람이 검토했다고 도구가 보증하지 않는다.

## 연결요소와 분할

같은 사건의 문서, 공유 문서로 이어진 사건, 확정 관계의 문서는 같은 연결요소로 묶는다. 각 연결요소는 하나의 split_group_id 및 `dev|holdout`에 대응해야 하고, 서로 다른 연결요소를 같은 그룹 ID로 합치지 않는다. 같은 문서의 모든 버전은 한 문서 안에 둔다. 공유 문서·정정/재게시를20/20에 맞추려고 쪼갤 수 없다.

suspected_duplicate_ids는 **다른 사건 ID**다. 자동 병합하지 않으며 개발/확인 사이의 의심 중복은 경고한다. 확인 문서가 없으면 holdout_status=absent, 아래 경고가 있으면 review_required, 없으면 unexposed_as_declared다. 마지막 값도 실제 blind 평가 인증이 아니다.

- `GROUPING_UNREVIEWED`: 그룹 검토자/시각 미기재
- `GROUPING_REVIEW_OUTDATED`: 그룹 검토 시각 뒤에 기록된 확정 관계 존재
- `HOLDOUT_DEVELOPMENT_EXPOSURE`: 확인 쪽에 개발 노출 문서 존재
- `HOLDOUT_EXPOSURE_UNKNOWN`: 확인 쪽 노출 이력 미상
- `SUSPECTED_DUPLICATE_CROSSES_SPLIT`: 의심 중복 사건이 두 분할에 걸침

문서·버전·사건·그룹 수, 분할별 수·유형/특징 분포와 **실제40/개발20/확인20** 목표 대비 부족분을 반환한다. 부족분은 data_kind=real인 선언 집계만 차감하며 synthetic이면 문서 수와 무관하게40/20/20을 유지한다. real 선언의 진위·공식 자료 여부는 이 도구가 검증하지 않는다. 의미값/원문/정답/사용자 조건은 출력하지 않는다.

## 명령·불변 보관

```sh
python3.13 -m processing.evaluation check --input processing/examples/dataset-manifest.json
python3.13 -m processing.evaluation freeze --input data/private/dataset.json
python3.13 -m processing.evaluation verify DATASET_REF
```

기본 root는 Git 제외 `data/private/evaluation/datasets`, 각 명령에 `--root ROOT`를 지정할 수 있다. 저장소 안에서는 기존 비공개 경로 검증을 적용해 data/private 아래만 허용한다. dataset_ref는 dataset_version UTF-8의 SHA-256이다. 같은 버전의 다른 원본 바이트는 충돌이며 동일 바이트는 기존 고정 시각·receipt를 재사용한다.

원본 manifest.json, 원본 hash/크기·고정 시각의 identity.json, 재계산 가능한 receipt.json을 별도 staging에서 완성하고 원자적으로 배치한다. 파일0400·디렉터리0500이며 verify는 파일/hash·집계·시각·권한·파일 목록을 다시 확인한다. 배정/관계/검토 시각은 고정 시각보다 미래일 수 없다. 부분 기록·변조·symlink는 거부하고 원본을 자동 수정하지 않는다. 실패 staging만 정리하며 기존 파일·운영자 메모를 지우지 않는다.

stdout은 안전한 집계 JSON 한 건, stderr는 고정 코드다. 성공0, 입력/인자2, archive 충돌/손상/미완료3, 파일 I/O5, 내부 오류1이다. POSIX 권한·원자 rename·hard link가 필요하며 Windows·전원 중단 내구성은 미검증이다. 관리자 권한으로 전체 파일을 바꿀 수 있는 저장소에 전자서명/WORM 보장은 없다.

이 단계는 manifest와 선언한 버전 참조만 고정한다. 원문 파일 보관·D05 실행 연결·금표 동결·8필드 점수·최초/재시험 결과·규칙 기준선은 후속 평가 경로에서 연결한다. 임의 배정 자동화나 사람 검토·공개 승인은 수행하지 않는다.
