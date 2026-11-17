# 시민 추출 추가 전 legacy 회귀 기준본

현재 코드로 expected를 다시 생성하지 않는다. 이 폴더는 시민 family 구현 전에 고정한 공개 합성 bytes의 일부다. 실제 공지·API 호출·사람 검토·독립 gold·D09·품질평가 실적이 아니다.

## 출처·원본 보존

- 원래13개 입력/출력/schema/prompt/request/feedback: `/tmp/yeogi-citizen-python-legacy-baseline/`. 출처 commit `1e17c83d14dbad3be07f6b21dee6c357e6e826c0`, processing은 `4c2dd1b06487162f75ebb340c7f6cf50e2b8c366` 이후 같았다.
- 원래96개 archive 파일: `/tmp/yeogi-citizen-python-legacy-archives/original/`. 생성 실행 소스 commit `4c2dd1b06487162f75ebb340c7f6cf50e2b8c366`, processing tree `2c168855ea53a8ea14160f7bf4e237c7763278d8`.
- `archive-manifest.json`은 원래 manifest bytes 그대로다. SHA-256 `0cdb9589b6f1acc66075cec2a2651e23546a3dbb8747e127ff17349b67eab77f`.
- `prompt-manifest.json` SHA-256 `a58fa2d587a69ce08dbd08c0c757264ab99136c27b6dcbdfa8a4860e90553ad1`.
- `cli-verification.json`은 기존 코드의 실제 offline CLI stdout/stderr hash·예상 종료코드를 보존한다. SHA-256 `f2fe83b08929f1a18aa301f1636de0873974d21a92a7ef0099cf3a9725f5b0d2`.

manifest의 source file SHA·절대 경로·과거 실행 명령은 provenance다. 변경된 현재 소스의 SHA 일치를 강제하거나 과거 경로에서 시험을 실행하지 않는다.

## 포함·중복 축소

`prompts/`의13파일은 원본230,844bytes 그대로다. v1/v2/v3 요청 모델 라벨은 기존 `synthetic-baseline-model`, 구조 피드백 경로는 `$.items`이며 요청 구성 회귀만 검사한다. API-v2 archive의 mock 응답 라벨 `gpt-6.1-sol`과 구별하며 전송하지 않는다.

`archives/`는 원래96파일 중39파일·565,157bytes를 보존한다. 별도 생성 코드·변환·압축은 없다.

고정 payload 합계는52파일·796,001bytes이며 원본 manifest/CLI 증거3파일·37,533bytes와 이 README를 추가했다.

- manual failure sealed6파일: 비UTF8/NUL 실패 원출력과 실패 receipt.
- API-v2 chunk sealed19파일: 합성40,000자4block,3개 mock exchange·1문서 cycle. provider 호출0.
- handoff14파일: projection/selection과 human-review 전체10파일을 포함하고, 그 안에 manual success sealed6파일이 포함된다. 검토본·성공 부모를 다시 복사해 중복 보관하지 않는다.

각 이미지의 receipt SHA·고정 UUID/UTC 시각·모든 artifact SHA/size는 원래 manifest에서 확인한다. 원본96파일과 두 root의 독립 재생성 일치 기록은 manifest·CLI 증거에 남아 있다. portable 시험은 선택39파일을 대조하며96파일을 전부 보관했다고 주장하지 않는다.

## 실행·권한

```sh
python3.13 -B -m unittest processing.tests.test_citizen_extraction_compatibility -v
```

2026-11-18 현재 worktree 실행:8시험 통과. 고정 expected bytes와 production은 변경하지 않았다.

Git이0400/0500 권한을 보존하지 않으므로 checkout 파일은 일반 읽기/쓰기 파일이다. 시험은 임시 복사본만 파일0400·디렉터리0500으로 만들고 현재 worktree를 cwd로 실제 CLI `verify-sealed`3종·`verify-review`·`verify-handoff`를 호출한다. socket/DNS를 거부하고 키 없는 최소 환경을 사용한다. 수동 실패 exit4도 원래 기대 결과다. stdout/stderr hash·receipt 값과 검증 전후 전체 bytes/mode를 대조한다. 종료 시 임시 디렉터리 권한만 복구해 정리한다.

수동 metadata의 실제 제공 `prompt-v1` 라벨·null 모델 정보와 원출력은 그대로다. 새 템플릿 사용·실제 모델·사람 판독을 인증하지 않는다. 기대 바이트 교체가 필요하면 원인·호환 영향·이전/새 원본 증거를 먼저 검토한다.
