# G4 시민 사람 수정 원본 고정 기준본

G5 코드 작성 전에 source `16a18f0c6d1ce5b1568ce63aa95a520ee55c811a`의 기존 수동 추출/사람 수정 보관 기능으로 만든 공개 합성 bytes다. 실제 provider·사람 판독/승인·독립 평가가 아니다. 원래 `/tmp/yeogi-citizen-g4-archive-baseline/original/`76파일·360,086bytes를 `original/`에 그대로 복사했다. 미래 코드로 expected를 다시 만들지 않는다.

- `manifest.json` 원본 SHA-256: `d747977a82af2aa43a1ea635d5068589441d56e803112578ae953745420f2979`.
- `verification.json` 원본 SHA-256: `9dc66771c153d6f3ddcf715d27a8de1e02eb0292e10bb0fb12528791c9711925`.
- D05 수동 성공·비UTF8/NUL 실패 sealed2종, 성공/실패 부모의 human-review 및 title/categories 미해결 선언2종, setup source D03·실제 txt asset·prompt·metadata·전체 전후 값이 포함된다.
- 원래 두 독립 root는 모든 bytes/size/mode가 같았고 기존 CLI12회 결과도 같았다. source module SHA는 과거 provenance이며 현재 소스 SHA 일치를 요구하지 않는다.
- 실제 제공 prompt 라벨/CRLF bytes·null 모델·실패 부모 상태를 유지한다. source는 pending/unchecked다. split/D08 배정이나 공개 승인을 선언하지 않는다.

Git이0400/0500을 보존하지 않으므로 checkout은 일반 읽기/쓰기 파일이다. `test_citizen_handoff.materialize_g4(work)`가 고정 SHA/size를 검사한 임시 복사본에 manifest의 canonical0700/0600·sealed0500/0400을 재현한다. 시험이 끝나면 소유 임시 디렉터리만 쓰기 가능하게 복구해 정리한다.

`test_g4_frozen_expected_files_modes_and_original_cli_hashes_remain_unchanged`는 현재 worktree의 실제 offline verify-sealed/review CLI 결과를 저장된 stdout/stderr SHA·종료코드와 대조하고 원본 불변을 확인한다. 공개 합성 시각은 고정 clock으로 사용하며 실제 현재 시각·사람 신원 인증으로 표시하지 않는다. 기존 legacy13pin·39파일 기준본은 별도 폴더에서 계속 검증한다.
