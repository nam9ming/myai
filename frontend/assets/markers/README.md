# 지도 캐릭터 자산

Tabler Icons의 MIT 라이선스 아이콘을 기반으로 색상·배경 그림자·표정·좌표계를 수정했습니다. 추가 유료 사용권이나 외부 이미지 요청은 필요하지 않습니다. 원저작권과 이용 조건은 동봉한 LICENSE.txt를 따릅니다.

- 원저작자: Paweł Kuna / Tabler Icons
- 프로젝트: https://github.com/tabler/tabler-icons
- 라이선스: https://github.com/tabler/tabler-icons/blob/main/LICENSE
- 확인일: 2026-11-06
- construction.svg: icons/outline/traffic-cone.svg 기반
- event.svg: icons/outline/building-store.svg 기반
- traffic.svg: icons/outline/traffic-lights.svg 기반

검토한 대안은 OpenMoji(CC BY-SA4.0), Twemoji(CC BY4.0)입니다. 이번 배포에는 Tabler 기반 자산만 포함합니다. 원본 다운로드의 SHA-256은 다음과 같습니다.

- cone.svg: `5eb67d43cd4eb41dc0b4de07be216e7ee7e86380201999c5e3df8f453c552a8d`
- market.svg: `ecd2b1d0e458f6c5ef2db21571c8bc1d3650af4e1f505b7c43e218c9fa299be2`
- traffic.svg: `e5a7c71375ec06b4dd5ea61eaa506eba786a45a6560accfc0b42c5eeea13def5`
- tabler-license.txt: `b740a1d46122672da62833e97f7e7c8a13fa85cbc7445b584b297cc00dde93db`

2026-11-06 후속 수정: 기존 SVG에 공사콘의 곡괭이·작업 동작·눈 깜빡임, 장터의 마이크·음표·춤, 신호등의 부드러운 점등을 추가했습니다. SVG 내부 CSS를 사용하므로 GIF·추가 라이브러리·이미지 CDN이 필요하지 않습니다. 지도에서 선택하면 인사 동작을 재생합니다. `prefers-reduced-motion: reduce`에서는 내부 동작과 선택 동작을 모두 끕니다. 취소된 안내의 구간은 회색 점선입니다.

2026-11-17: 교육·지원·생활 마커는 기존 시제품 `core/icons.dart`의 책·선물·집 path를 원형 배경과 조합한 프로젝트 SVG입니다. 이 세 파일에는 위 Tabler 출처가 적용되지 않습니다.
