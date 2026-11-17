import 'package:material_ui/material_ui.dart';

import '../../app/app_context.dart';
import '../../core/ui.dart';
import '../../data/models.dart';
import '../dialogs.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});
  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  Preferences? draft;
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    draft ??= AppContext.of(context).state.settings.copyWith();
  }

  @override
  Widget build(BuildContext context) {
    final env = AppContext.of(context), app = env.state, d = draft!;
    return Align(
      alignment: Alignment.topLeft,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 700),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const SectionHeading(
              '내 동네 맞춤 설정',
              description:
                  '입력한 정보는 추천 순서를 정하는 데 참고해요.\n선택하지 않아도 모든 소식을 볼 수 있어요.',
            ),
            _section(
              '관심 지역',
              '사는 곳이나 자주 머무는 지역을 선택해주세요.',
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${d.province} ${d.city} · ${d.district}',
                    style: type(13),
                  ),
                  const SizedBox(height: 10),
                  UiButton(
                    '지역 변경',
                    onTap: () async {
                      final result = await showRegionPicker(
                        context,
                        app,
                        initial: d,
                      );
                      if (result != null && mounted)
                        setState(() => draft = result);
                    },
                  ),
                ],
              ),
            ),
            _section(
              '관심 분야',
              '원하는 만큼 골라주세요. 관련 소식을 먼저 보여드려요.',
              Wrap(
                spacing: 9,
                runSpacing: 9,
                children: [
                  for (final e in categories.entries.where(
                    (e) => e.key != 'all',
                  ))
                    UiButton(
                      e.value,
                      selected: d.interests.contains(e.key),
                      onTap: () => setState(() {
                        final selected = List<String>.of(d.interests);
                        selected.contains(e.key)
                            ? selected.remove(e.key)
                            : selected.add(e.key);
                        draft = d.copyWith(interests: selected);
                      }),
                    ),
                ],
              ),
            ),
            _section(
              '연령대 · 선택',
              '세부 자격을 확정하는 기준이 아닌 추천 참고 정보예요.',
              _choices(
                ages,
                d.age,
                (v) => setState(
                  () => draft = d.copyWith(age: v == '선택 안 함' ? '' : v),
                ),
              ),
            ),
            _section(
              '성별 · 선택',
              '성별은 현재 추천 순서나 신청 자격 판정에 사용하지 않아요.',
              _choices(
                genders,
                d.gender,
                (v) => setState(
                  () => draft = d.copyWith(gender: v == '선택 안 함' ? '' : v),
                ),
              ),
            ),
            _section(
              '위치 사용',
              '위치 권한은 선택 사항이에요. 시제품에서는 지역을 자동 판별하거나 거리순으로 계산하지 않습니다. 정확한 좌표는 저장하지 않아요.',
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    d.locationEnabled ? '위치 사용 설정됨' : '직접 선택한 지역 사용 중',
                    style: type(13),
                  ),
                  const SizedBox(height: 10),
                  UiButton(
                    app.locationBusy
                        ? '위치를 확인하고 있어요…'
                        : d.locationEnabled
                        ? '위치 사용 해제'
                        : '위치 사용해보기',
                    onTap: app.locationBusy
                        ? null
                        : () async {
                            if (d.locationEnabled) {
                              setState(
                                () =>
                                    draft = d.copyWith(locationEnabled: false),
                              );
                              env.toast(
                                '앱의 위치 사용을 해제했어요. 브라우저 권한은 브라우저 설정에서 변경할 수 있어요.',
                              );
                              return;
                            }
                            final allowed = await app.requestLocation();
                            if (!mounted) return;
                            setState(
                              () => draft = draft!.copyWith(
                                locationEnabled: allowed,
                              ),
                            );
                            env.toast(
                              allowed
                                  ? '위치 권한을 확인했어요. 선택한 지역의 예시를 보여드려요.'
                                  : '위치 없이도 선택한 지역으로 이용할 수 있어요.',
                            );
                          },
                  ),
                ],
              ),
            ),
            if (app.storageFailed)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Text(
                  '설정과 관심정보는 이번 방문 동안만 유지되며 새로고침하면 초기화됩니다.',
                  style: type(11, color: Palette.sub),
                ),
              ),
            const SizedBox(height: 24),
            Wrap(
              spacing: 12,
              runSpacing: 10,
              children: [
                UiButton(
                  '취소',
                  onTap: () {
                    draft = app.settings.copyWith();
                    env.go('/home');
                  },
                ),
                UiButton(
                  '설정 저장하기',
                  primary: true,
                  icon: 'check',
                  onTap: () {
                    app.savePreferences(d);
                    env.toast('맞춤 설정을 저장했어요.');
                    env.go('/home');
                  },
                ),
                UiButton(
                  '첫 방문 설정 다시 보기',
                  quiet: true,
                  onTap: () {
                    app.onboarding = app.settings.copyWith();
                    env.go('/start', {'step': '0'});
                  },
                ),
              ],
            ),
            const SizedBox(height: 14),
            Text(
              '설정과 관심정보는 이 브라우저에 저장됩니다. 브라우저 데이터를 삭제하면 함께 지워질 수 있어요.',
              style: type(11, color: Palette.sub),
            ),
          ],
        ),
      ),
    );
  }

  Widget _choices(
    List<String> values,
    String selected,
    ValueChanged<String> change,
  ) => Wrap(
    spacing: 9,
    runSpacing: 9,
    children: [
      for (final value in values)
        UiButton(
          value,
          selected: selected == value || selected.isEmpty && value == '선택 안 함',
          onTap: () => change(value),
        ),
    ],
  );
  Widget _section(String title, String help, Widget child) => Container(
    width: double.infinity,
    padding: const EdgeInsets.symmetric(vertical: 26),
    decoration: const BoxDecoration(
      border: Border(bottom: BorderSide(color: Palette.line)),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: type(16, weight: FontWeight.w600, spacing: -.6)),
        const SizedBox(height: 7),
        Text(help, style: type(12, color: Palette.sub)),
        const SizedBox(height: 17),
        child,
      ],
    ),
  );
}
