import 'package:material_ui/material_ui.dart';

import '../../app/app_context.dart';
import '../../core/ui.dart';
import '../../data/models.dart';

class OnboardingPage extends StatefulWidget {
  final int step;
  const OnboardingPage({super.key, required this.step});
  @override
  State<OnboardingPage> createState() => _OnboardingPageState();
}

class _OnboardingPageState extends State<OnboardingPage> {
  void _step(int value) =>
      AppContext.of(context).go('/start', {'step': '$value'});
  void _finish({bool skipProfile = false}) {
    final env = AppContext.of(context);
    env.state.finishOnboarding(skipProfile: skipProfile);
    env.go('/home');
    env.toast('선택한 지역의 소식부터 살펴보세요.');
  }

  @override
  Widget build(BuildContext context) {
    final env = AppContext.of(context),
        app = env.state,
        draft = app.onboarding,
        step = widget.step.clamp(0, 5),
        small = mobile(context);
    final group = step < 2
        ? 1
        : step == 2
        ? 2
        : 3;
    final form = Padding(
      padding: EdgeInsets.fromLTRB(
        small ? 6 : 31,
        small ? 7 : 30,
        small ? 6 : 31,
        25,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              for (var i = 1; i <= 3; i++)
                Expanded(
                  child: Container(
                    height: 4,
                    margin: const EdgeInsets.only(right: 6),
                    decoration: BoxDecoration(
                      color: group >= i
                          ? const Color(0xff6a8051)
                          : const Color(0xffedf0e5),
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
                ),
              Text('$group / 3', style: type(10, color: Palette.sub)),
            ],
          ),
          const SizedBox(height: 20),
          if (step > 0)
            UiButton(
              '이전',
              quiet: true,
              icon: 'left',
              onTap: () => _step(step - 1),
            ),
          AnimatedSwitcher(
            duration: Duration(milliseconds: reducedMotion(context) ? 0 : 320),
            transitionBuilder: (child, a) => FadeTransition(
              opacity: a,
              child: SlideTransition(
                position: Tween(
                  begin: const Offset(0, .03),
                  end: Offset.zero,
                ).animate(a),
                child: child,
              ),
            ),
            child: Column(
              key: ValueKey(step),
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (step == 0) ...[
                  _title('어느 지역 소식을\n만나볼까요?'),
                  _intro('자주 머무는 곳이나 관심 있는 지역을 골라주세요.'),
                  _grid(app.prototype.provinces, draft.province, (p) {
                    app.onboarding = draft.copyWith(
                      province: p,
                      city: app.prototype.cities[p]!.first,
                      district: citywide,
                    );
                    _step(1);
                  }),
                  _fine('첫 시제품은 안성시 예시 공지를 제공해요.\n다른 지역은 선택 흐름만 체험할 수 있어요.'),
                ] else if (step == 1) ...[
                  _title('${draft.province}의\n어디가 궁금하세요?'),
                  _intro('시·군·구를 선택해주세요.\n나중에 관심 지역을 바꿀 수 있어요.'),
                  _grid(
                    app.prototype.cities[draft.province] ?? [],
                    draft.city,
                    (c) {
                      app.onboarding = draft.copyWith(
                        city: c,
                        district: citywide,
                      );
                      _step(2);
                    },
                  ),
                  _fine('지역 목록은 일부 예시입니다.\n현재 공지를 볼 수 있는 예시 지역은 안성시예요.'),
                ] else if (step == 2) ...[
                  _symbol('pin'),
                  _title('내 주변 소식을\n더 가까이.'),
                  _intro(
                    '현재 위치를 사용하면 가까운 소식을 찾는 데 도움이 돼요. 시제품에서는 위치 권한 흐름만 체험할 수 있어요.',
                  ),
                  _primary(
                    app.locationBusy ? '위치 설정을 확인하고 있어요…' : '현재 위치로 찾기',
                    app.locationBusy
                        ? null
                        : () async {
                            final allowed = await app.requestLocation();
                            app.onboarding = app.onboarding.copyWith(
                              locationEnabled: allowed,
                            );
                            if (!context.mounted) return;
                            _step(3);
                            env.toast(
                              allowed
                                  ? '위치 권한을 확인했어요. 직접 선택한 지역의 예시를 보여드려요.'
                                  : '위치 없이도 괜찮아요. 선택한 지역으로 계속할게요.',
                            );
                          },
                  ),
                  _secondary('선택한 지역으로 둘러보기', () => _step(3)),
                  _fine(
                    '위치 사용은 선택이에요. 정확한 좌표는 저장하지 않으며, 허용하지 않아도 계속 이용할 수 있어요.',
                  ),
                ] else if (step == 3) ...[
                  _symbol('spark'),
                  _title('거의 다 됐어요!'),
                  _intro('관심사와 연령대를 알려주시면\n나에게 맞는 소식을 먼저 보여드릴게요.'),
                  Wrap(
                    spacing: 7,
                    runSpacing: 7,
                    children: [
                      for (final c in ['교육·배움', '지원·혜택', '행사·문화'])
                        Container(
                          padding: const EdgeInsets.symmetric(
                            vertical: 6,
                            horizontal: 9,
                          ),
                          decoration: BoxDecoration(
                            color: const Color(0xfff2f5e9),
                            borderRadius: BorderRadius.circular(6),
                          ),
                          child: Text(
                            c,
                            style: type(11, color: const Color(0xff6e7e5d)),
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 25),
                  _primary('맞춤 소식 설정하기', () => _step(4)),
                  _secondary('지금 바로 둘러보기', () => _finish()),
                  _fine('입력하지 않아도 모든 소식을 확인할 수 있어요.'),
                ] else if (step == 4) ...[
                  _title('어떤 소식에\n관심 있으세요?'),
                  _intro('원하는 만큼 골라주세요.\n아무것도 선택하지 않아도 괜찮아요.'),
                  LayoutBuilder(
                    builder: (context, c) => Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final e in categories.entries.where(
                          (e) => e.key != 'all',
                        ))
                          SizedBox(
                            width: (c.maxWidth - 8) / 2,
                            child: UiButton(
                              e.value,
                              green: true,
                              leftAligned: true,
                              selected: draft.interests.contains(e.key),
                              onTap: () => setState(() {
                                final selected = List<String>.of(
                                  app.onboarding.interests,
                                );
                                selected.contains(e.key)
                                    ? selected.remove(e.key)
                                    : selected.add(e.key);
                                app.onboarding = app.onboarding.copyWith(
                                  interests: selected,
                                );
                              }),
                            ),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 25),
                  _primary('다음', () => _step(5)),
                  _secondary('지금 바로 둘러보기', () => _finish()),
                ] else ...[
                  _title('조금 더\n나에게 맞게.'),
                  _intro('선택한 정보는 추천 순서를 정하는 데 참고해요.'),
                  _label('연령대 · 선택'),
                  _choices(
                    ages,
                    draft.age,
                    (v) => setState(
                      () => app.onboarding = app.onboarding.copyWith(
                        age: v == '선택 안 함' ? '' : v,
                      ),
                    ),
                  ),
                  _label('성별 · 선택'),
                  _choices(
                    genders,
                    draft.gender,
                    (v) => setState(
                      () => app.onboarding = app.onboarding.copyWith(
                        gender: v == '선택 안 함' ? '' : v,
                      ),
                    ),
                  ),
                  _fine('성별은 현재 추천 순서에 사용하지 않아요.\n실제 신청 자격은 상세에서 확인해주세요.'),
                  const SizedBox(height: 15),
                  _primary('여기:it 시작하기', () => _finish()),
                  _secondary('입력 없이 시작하기', () => _finish(skipProfile: true)),
                ],
              ],
            ),
          ),
        ],
      ),
    );
    return Container(
      width: double.infinity,
      color: small ? Colors.white : Palette.background,
      padding: EdgeInsets.fromLTRB(
        small ? 18 : 25,
        small ? 22 : 28,
        small ? 18 : 25,
        50,
      ),
      child: Center(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: small ? 410 : 850),
          child: Container(
            decoration: BoxDecoration(
              color: Colors.white,
              border: small ? null : Border.all(color: const Color(0xffe5e7dc)),
              borderRadius: small ? null : BorderRadius.circular(22),
            ),
            clipBehavior: Clip.antiAlias,
            child: small
                ? form
                : IntrinsicHeight(
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Expanded(child: _story()),
                        Expanded(
                          child: ConstrainedBox(
                            constraints: const BoxConstraints(minHeight: 560),
                            child: form,
                          ),
                        ),
                      ],
                    ),
                  ),
          ),
        ),
      ),
    );
  }

  Widget _title(String text) => Padding(
    padding: const EdgeInsets.only(top: 8),
    child: Text(
      text,
      style: type(
        mobile(context) ? 29 : 27,
        weight: FontWeight.w700,
        height: 1.45,
        spacing: -1.2,
      ),
    ),
  );
  Widget _intro(String text) => Padding(
    padding: const EdgeInsets.only(top: 13, bottom: 23),
    child: Text(text, style: type(12, color: Palette.sub, height: 1.9)),
  );
  Widget _fine(String text) => Padding(
    padding: const EdgeInsets.only(top: 13),
    child: Text(
      text,
      style: type(10, color: const Color(0xff8a8e80), height: 1.9),
    ),
  );
  Widget _label(String text) => Padding(
    padding: const EdgeInsets.only(top: 19, bottom: 10),
    child: Text(text, style: type(12, weight: FontWeight.w600)),
  );
  Widget _symbol(String icon) => Container(
    width: 65,
    height: 65,
    margin: const EdgeInsets.only(top: 9, bottom: 20),
    decoration: BoxDecoration(
      color: const Color(0xffedf2e5),
      borderRadius: BorderRadius.circular(20),
    ),
    child: Center(
      child: UiIcon(icon, size: 29, color: const Color(0xff627950)),
    ),
  );
  Widget _primary(String label, VoidCallback? tap) => SizedBox(
    width: double.infinity,
    child: UiButton(label, primary: true, green: true, onTap: tap),
  );
  Widget _secondary(String label, VoidCallback tap) =>
      Center(child: UiButton(label, quiet: true, onTap: tap));
  Widget _grid(List<String> items, String selected, ValueChanged<String> tap) =>
      LayoutBuilder(
        builder: (context, c) => Wrap(
          spacing: 8,
          runSpacing: 8,
          children: [
            for (final item in items)
              SizedBox(
                width: (c.maxWidth - 8) / 2,
                child: UiButton(
                  item,
                  green: true,
                  leftAligned: true,
                  selected: selected == item,
                  onTap: () => tap(item),
                ),
              ),
          ],
        ),
      );
  Widget _choices(
    List<String> items,
    String selected,
    ValueChanged<String> tap,
  ) => Wrap(
    spacing: 8,
    runSpacing: 8,
    children: [
      for (final item in items)
        UiButton(
          item,
          green: true,
          selected: item == selected || item == '선택 안 함' && selected.isEmpty,
          onTap: () => tap(item),
        ),
    ],
  );
  Widget _story() => Container(
    color: const Color(0xffedf0e2),
    padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 39),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'A LITTLE CLOSER TO YOUR NEIGHBORHOOD',
              style: type(9, color: const Color(0xff6e7958), spacing: 1.3),
            ),
            const SizedBox(height: 22),
            Text(
              '흩어져 있던 소식이\n나에게 필요한 정보로.',
              style: type(
                28,
                color: const Color(0xff33442e),
                weight: FontWeight.w600,
                spacing: -1.3,
              ),
            ),
            const SizedBox(height: 17),
            Text(
              '배우고 싶은 것부터 챙겨야 할 지원까지.\n여기에서, 나에게 맞는 소식을 만나요.',
              style: type(12, color: const Color(0xff78816b), height: 1.9),
            ),
          ],
        ),
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 40),
          child: Row(
            children: [
              for (final (i, icon, label, color, angle) in [
                (0, 'pin', '가까운 소식', const Color(0xfffafbf6), -.1),
                (1, 'leaf', '새로운 기회', const Color(0xffe1e7b7), .12),
                (2, 'book', '배우는 일상', const Color(0xffeedcc6), -.05),
              ])
                Expanded(
                  child: Transform.translate(
                    offset: Offset(0, i == 1 ? -25 : 0),
                    child: Transform.rotate(
                      angle: angle,
                      child: Container(
                        margin: const EdgeInsets.symmetric(horizontal: 4),
                        padding: const EdgeInsets.fromLTRB(6, 24, 6, 16),
                        decoration: BoxDecoration(
                          color: color,
                          borderRadius: BorderRadius.circular(16),
                        ),
                        child: Column(
                          children: [
                            UiIcon(
                              icon,
                              size: 34,
                              color: const Color(0xff526145),
                            ),
                            const SizedBox(height: 15),
                            Text(
                              label,
                              style: type(11, color: const Color(0xff526145)),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
            ],
          ),
        ),
        Text(
          '지역과 관심사는 언제든 바꿀 수 있어요.',
          style: type(10, color: const Color(0xff7a826e)),
        ),
      ],
    ),
  );
}
