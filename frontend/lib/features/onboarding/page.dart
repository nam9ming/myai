import 'dart:async';
import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';

import '../../app/app_context.dart';
import '../../core/ui.dart';
import '../../data/models.dart';
import 'region_map.dart';

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

  Future<void> _confirmLocation() async {
    final env = AppContext.of(context);
    final app = env.state;
    final allowed = await app.requestLocation();
    if (!mounted) return;
    app.onboarding = app.onboarding.copyWith(locationEnabled: allowed);
    _step(6);
  }

  @override
  Widget build(BuildContext context) {
    final env = AppContext.of(context),
        app = env.state,
        draft = app.onboarding,
        step = widget.step == 2 ? 3 : widget.step.clamp(0, 7),
        small = mobile(context);
    final group = step < 2 || step == 6
        ? 1
        : step == 3
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
                      color: group >= i ? Palette.orange : Palette.soft,
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
              onTap: () => _step(switch (step) {
                3 => 1,
                6 => 0,
                7 => 6,
                _ => step - 1,
              }),
            ),
          AnimatedSwitcher(
            duration: Duration(milliseconds: reducedMotion(context) ? 0 : 320),
            switchInCurve: Curves.easeOutCubic,
            switchOutCurve: Curves.easeInCubic,
            transitionBuilder: (child, a) => FadeTransition(
              opacity: a,
              child: AnimatedBuilder(
                animation: a,
                child: child,
                builder: (_, child) => Transform.translate(
                  offset: Offset(
                    0,
                    reducedMotion(context) ? 0 : (1 - a.value) * 6,
                  ),
                  child: child,
                ),
              ),
            ),
            child: Column(
              key: ValueKey(step),
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (step == 0) ...[
                  _title('어느 지역 소식을\n만나볼까요?'),
                  _intro('자주 머무는 곳이나 관심 있는 지역을 골라주세요.'),
                  RegionMap(
                    regions: app.prototype.provinces,
                    selected: app.onboardingProvinceSelection,
                    mapAction: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        if (!app.locationBusy) const _LocationHint(),
                        Material(
                          color: app.locationBusy
                              ? Palette.sub
                              : Palette.orange,
                          shape: const CircleBorder(),
                          elevation: 2,
                          child: IconButton(
                            tooltip: app.locationBusy
                                ? '위치 권한 확인 중'
                                : '현재 위치로 찾기',
                            constraints: const BoxConstraints.tightFor(
                              width: 48,
                              height: 48,
                            ),
                            icon: app.locationBusy
                                ? const SizedBox.square(
                                    dimension: 20,
                                    child: CircularProgressIndicator(
                                      color: Colors.white,
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const UiIcon(
                                    'map',
                                    size: 23,
                                    color: Colors.white,
                                  ),
                            onPressed: app.locationBusy
                                ? null
                                : _confirmLocation,
                          ),
                        ),
                      ],
                    ),
                    onSelected: (province) => setState(() {
                      app.onboardingProvinceSelection =
                          app.onboardingProvinceSelection == province
                          ? null
                          : province;
                    }),
                  ),
                  const SizedBox(height: 12),
                  _primary(
                    '다음',
                    app.onboardingProvinceSelection == null
                        ? null
                        : () {
                            final province = app.onboardingProvinceSelection!;
                            if (province != draft.province) {
                              app.onboardingCitySelection = null;
                              app.onboarding = draft.copyWith(
                                province: province,
                                city: app.prototype.cities[province]!.first,
                                district: citywide,
                              );
                            }
                            _step(1);
                          },
                  ),
                ] else if (step == 1) ...[
                  _title('${draft.province}의\n어디가 궁금하세요?'),
                  _intro('시·군·구를 선택해주세요.\n나중에 관심 지역을 바꿀 수 있어요.'),
                  RegionMap(
                    province: draft.province,
                    regions: app.prototype.cities[draft.province] ?? [],
                    selected: app.onboardingCitySelection,
                    onSelected: (city) => setState(() {
                      app.onboardingCitySelection =
                          app.onboardingCitySelection == city ? null : city;
                    }),
                  ),
                  const SizedBox(height: 12),
                  _primary(
                    '다음',
                    app.onboardingCitySelection == null
                        ? null
                        : () {
                            app.onboarding = draft.copyWith(
                              city: app.onboardingCitySelection!,
                              district: citywide,
                            );
                            _step(3);
                          },
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
                            color: const Color(0xfffff1e9),
                            borderRadius: BorderRadius.circular(6),
                          ),
                          child: Text(
                            c,
                            style: type(11, color: const Color(0xffa54a2b)),
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
                ] else if (step == 6) ...[
                  _symbol('pin'),
                  _title('${draft.province} ${draft.city} 소식이 맞으세요?'),
                  _intro('이 지역의 소식을 보거나 지도에서 다른 지역을 고를 수 있어요.'),
                  const SizedBox(height: 16),
                  _primary('네', () => _step(7)),
                  _secondary('아니오', () => _step(0)),
                ] else ...[
                  _title('조금 더\n나에게 맞게.'),
                  _intro('선택한 정보는 추천 순서를 정하는 데 참고해요.'),
                  _label('연령대 · 선택'),
                  _choices(
                    ages,
                    draft.age,
                    (v) => setState(
                      () => app.onboarding = app.onboarding.copyWith(
                        age: v == draft.age || v == '선택 안 함' ? '' : v,
                      ),
                    ),
                  ),
                  _label('성별 · 선택'),
                  _choices(
                    genders,
                    draft.gender,
                    (v) => setState(
                      () => app.onboarding = app.onboarding.copyWith(
                        gender: v == draft.gender || v == '선택 안 함' ? '' : v,
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
                : Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
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
      color: const Color(0xfffff1e9),
      borderRadius: BorderRadius.circular(20),
    ),
    child: Center(
      child: UiIcon(icon, size: 29, color: const Color(0xffc0522c)),
    ),
  );
  Widget _primary(String label, VoidCallback? tap) => SizedBox(
    width: double.infinity,
    child: UiButton(label, primary: true, onTap: tap),
  );
  Widget _secondary(String label, VoidCallback tap) =>
      Center(child: UiButton(label, quiet: true, onTap: tap));
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
          selected: item == selected || item == '선택 안 함' && selected.isEmpty,
          onTap: () => tap(item),
        ),
    ],
  );
  Widget _story() => Container(
    constraints: const BoxConstraints(minHeight: 620),
    color: const Color(0xfffff1e9),
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
              style: type(9, color: const Color(0xffa54a2b), spacing: 1.3),
            ),
            const SizedBox(height: 22),
            Text(
              '흩어져 있던 소식이\n나에게 필요한 정보로.',
              style: type(
                28,
                color: const Color(0xff623b2a),
                weight: FontWeight.w600,
                spacing: -1.3,
              ),
            ),
            const SizedBox(height: 17),
            Text(
              '배우고 싶은 것부터 챙겨야 할 지원까지.\n여기에서, 나에게 맞는 소식을 만나요.',
              style: type(12, color: const Color(0xff886553), height: 1.9),
            ),
          ],
        ),
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 36),
          child: Wrap(
            spacing: 18,
            runSpacing: 24,
            children: [
              _StoryCard(
                'pin',
                '가까운 소식',
                '우리 동네 행사부터 생활·교통 안내까지, 선택한 지역의 소식을 한곳에서 살펴보세요.',
                Color(0xfffffdf9),
                Color(0xffa54a2b),
                -.06,
              ),
              _StoryCard(
                'leaf',
                '새로운 기회',
                '새롭게 열리는 모집과 참여 기회를 모아 보고, 관심 있는 소식을 발견해보세요.',
                Color(0xffffdfc6),
                Color(0xff9c492b),
                .06,
              ),
              _StoryCard(
                'book',
                '배우는 일상',
                '취미 수업과 교육 프로그램을 살펴보고, 일상에 더하고 싶은 배움을 찾아보세요.',
                Color(0xffeedcc6),
                Color(0xff79543b),
                -.04,
              ),
              _StoryCard(
                'gift',
                '챙기는 혜택',
                '지원사업과 생활 혜택의 대상·신청 기간을 확인하고, 필요한 정보를 챙겨보세요.',
                Color(0xfffff7ed),
                Color(0xffa54a2b),
                .05,
              ),
            ],
          ),
        ),
        Text(
          '지역과 관심사는 언제든 바꿀 수 있어요.',
          style: type(10, color: const Color(0xff886553)),
        ),
      ],
    ),
  );
}

class _StoryCard extends StatefulWidget {
  final String icon, label, description;
  final Color background, foreground;
  final double angle;
  const _StoryCard(
    this.icon,
    this.label,
    this.description,
    this.background,
    this.foreground,
    this.angle,
  );
  @override
  State<_StoryCard> createState() => _StoryCardState();
}

class _StoryCardState extends State<_StoryCard> {
  final tooltip = GlobalKey<TooltipState>();
  bool hovered = false, focused = false;
  @override
  Widget build(BuildContext context) {
    final active = hovered || focused;
    final motion = !reducedMotion(context);
    final duration = Duration(milliseconds: motion ? 180 : 0);
    return Focus(
      onFocusChange: (value) {
        setState(() => focused = value);
        if (value) {
          tooltip.currentState?.ensureTooltipVisible();
        } else {
          Tooltip.dismissAllToolTips();
        }
      },
      child: MouseRegion(
        onEnter: (_) => setState(() => hovered = true),
        onExit: (_) => setState(() => hovered = false),
        child: Tooltip(
          key: tooltip,
          message: '${widget.label}\n${widget.description}',
          waitDuration: Duration.zero,
          exitDuration: Duration.zero,
          preferBelow: false,
          verticalOffset: 18,
          constraints: const BoxConstraints(maxWidth: 240),
          padding: const EdgeInsets.all(15),
          textStyle: type(12, color: const Color(0xff654b3f), height: 1.8),
          decoration: BoxDecoration(
            color: const Color(0xfffffdfb),
            border: Border.all(color: const Color(0xffedcbb8)),
            borderRadius: BorderRadius.circular(14),
            boxShadow: const [
              BoxShadow(
                color: Color(0x1c713520),
                blurRadius: 24,
                offset: Offset(0, 8),
              ),
            ],
          ),
          child: AnimatedContainer(
            duration: duration,
            curve: Curves.easeOutCubic,
            transform: Matrix4.translationValues(
              0,
              active && motion ? -6 : 0,
              0,
            ),
            child: AnimatedScale(
              scale: active && motion ? 1.04 : 1,
              duration: duration,
              child: Transform.rotate(
                angle: widget.angle,
                child: Container(
                  width: 138,
                  padding: const EdgeInsets.symmetric(
                    vertical: 20,
                    horizontal: 8,
                  ),
                  decoration: BoxDecoration(
                    color: widget.background,
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(
                      color: focused ? Palette.focus : const Color(0x22a54a2b),
                      width: focused ? 2 : 1,
                    ),
                    boxShadow: active
                        ? const [
                            BoxShadow(
                              color: Color(0x249b4a25),
                              blurRadius: 20,
                              offset: Offset(0, 10),
                            ),
                          ]
                        : null,
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      UiIcon(
                        widget.icon,
                        size: 30,
                        color: widget.foreground,
                        strokeWidth: 1.35,
                      ),
                      const SizedBox(height: 12),
                      Text(
                        widget.label,
                        style: type(
                          12,
                          color: widget.foreground,
                          weight: FontWeight.w500,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _LocationHint extends StatefulWidget {
  const _LocationHint();

  @override
  State<_LocationHint> createState() => _LocationHintState();
}

class _LocationHintState extends State<_LocationHint> {
  Timer? _timer;
  int _bounce = 0;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (reducedMotion(context)) {
      _timer?.cancel();
      _timer = null;
    } else {
      _timer ??= Timer.periodic(const Duration(milliseconds: 1500), (_) {
        setState(() => _bounce++);
      });
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => IgnorePointer(
    child: TweenAnimationBuilder<double>(
      key: ValueKey((_bounce, reducedMotion(context))),
      tween: Tween(begin: 0, end: 1),
      duration: Duration(milliseconds: reducedMotion(context) ? 0 : 750),
      builder: (context, value, child) => Transform.translate(
        offset: Offset(0, -3 * math.sin(math.pi * value).abs()),
        child: child,
      ),
      child: Padding(
        padding: const EdgeInsets.only(bottom: 8, right: 3),
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Positioned(
              bottom: -3,
              right: 17,
              child: Transform.rotate(
                angle: math.pi / 4,
                child: const ColoredBox(
                  color: Palette.ink,
                  child: SizedBox.square(dimension: 8),
                ),
              ),
            ),
            DecoratedBox(
              decoration: BoxDecoration(
                color: Palette.ink,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
                child: Text(
                  '위치로 시작할까요?',
                  style: type(11, color: Colors.white, weight: FontWeight.w600),
                ),
              ),
            ),
          ],
        ),
      ),
    ),
  );
}
