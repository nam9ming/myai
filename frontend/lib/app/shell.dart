import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../core/ui.dart';
import '../data/models.dart';
import '../features/dialogs.dart';
import '../features/onboarding/page.dart';
import '../features/home/page.dart';
import '../features/notices/list_page.dart';
import '../features/notices/detail_page.dart';
import '../features/saved/page.dart';
import '../features/settings/page.dart';
import 'app_context.dart';
import 'app_state.dart';
import 'router.dart';

class AppShell extends StatefulWidget {
  final AppState state;
  final AppRouter router;
  final AppRoute route;
  const AppShell({
    super.key,
    required this.state,
    required this.router,
    required this.route,
  });
  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  late final ScrollController scroll = ScrollController(
    initialScrollOffset:
        widget.router.scrollOffsets[widget.route.uri.toString()] ?? 0,
  );
  final pageFocus = FocusNode(debugLabel: '페이지 본문');
  void _remember() => widget.router.scrollOffsets[widget.route.uri.toString()] =
      scroll.hasClients ? scroll.offset : 0;
  @override
  void initState() {
    super.initState();
    scroll.addListener(_remember);
  }

  @override
  void didUpdateWidget(AppShell oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.route.uri != widget.route.uri) {
      widget.router.scrollOffsets[oldWidget.route.uri.toString()] =
          scroll.hasClients ? scroll.offset : 0;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && scroll.hasClients)
          scroll.jumpTo(
            (widget.router.scrollOffsets[widget.route.uri.toString()] ?? 0)
                .clamp(0, scroll.position.maxScrollExtent),
          );
      });
    }
  }

  @override
  void dispose() {
    scroll.removeListener(_remember);
    scroll.dispose();
    pageFocus.dispose();
    super.dispose();
  }

  void _go(String path, Map<String, String> params) =>
      Router.navigate(context, () => widget.router.go(path, params));
  void _toast(String message) {
    final messenger = ScaffoldMessenger.of(context);
    messenger
      ..removeCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(message, style: type(12, color: Colors.white)),
          duration: const Duration(milliseconds: 3300),
          backgroundColor: const Color(0xff30372f),
          behavior: SnackBarBehavior.floating,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
        ),
      );
  }

  Future<void> _region() async {
    final result = await showRegionPicker(context, widget.state);
    if (!mounted || result == null) return;
    widget.state.savePreferences(result);
    _go('/home', {});
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.state,
    builder: (context, _) {
      final state = widget.state,
          route = widget.route,
          onboard = route.path == '/start',
          detail = route.path == '/detail',
          small = mobile(context);
      return AppContext(
        state: state,
        navigate: _go,
        back: widget.router.back,
        toast: _toast,
        region: _region,
        child: Builder(
          builder: (context) => Scaffold(
            body: Column(
              children: [
                if (!onboard && !state.isPrototype)
                  Container(
                    width: double.infinity,
                    color: const Color(0xfff4f6ed),
                    padding: const EdgeInsets.symmetric(
                      vertical: 8,
                      horizontal: 18,
                    ),
                    child: Text(
                      state.isPrototype
                          ? '예시 데이터로 구성한 시제품입니다 · 기준일 2026.11.16'
                          : state.mode == 'backend-fixture'
                          ? '백엔드 합성 자료 · 계약의 고정 예시 조건으로 조회합니다'
                          : '공개 자료 조회 · 제공 범위와 원문을 확인해주세요',
                      textAlign: TextAlign.center,
                      style: type(10, color: const Color(0xff71805d)),
                    ),
                  ),
                _header(context, onboard),
                if (!onboard) _categories(context),
                Expanded(
                  child: Focus(
                    focusNode: pageFocus,
                    child: Scrollbar(
                      controller: scroll,
                      child: SingleChildScrollView(
                        controller: scroll,
                        child: Column(
                          children: [
                            TweenAnimationBuilder<double>(
                              tween: Tween(begin: 0, end: 1),
                              duration: Duration(
                                milliseconds: reducedMotion(context) ? 0 : 300,
                              ),
                              curve: const Cubic(.22, 1, .36, 1),
                              builder: (_, v, child) => Opacity(
                                opacity: v,
                                child: Transform.translate(
                                  offset: Offset(0, (1 - v) * 14),
                                  child: child,
                                ),
                              ),
                              child: onboard
                                  ? OnboardingPage(
                                      step:
                                          int.tryParse(
                                            route.params['step'] ?? '0',
                                          ) ??
                                          0,
                                    )
                                  : PageWidth(
                                      child: Padding(
                                        padding: EdgeInsets.only(
                                          top: small ? 27 : 36,
                                          bottom: 55,
                                        ),
                                        child: _page(route),
                                      ),
                                    ),
                            ),
                            if (!onboard) _footer(context),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
            bottomNavigationBar: small && !onboard
                ? (detail
                      ? DetailActions(
                          id: route.params['id'] ?? '',
                          snapshot: route.params['snapshot_id'],
                        )
                      : _mobileNav(context))
                : null,
          ),
        ),
      );
    },
  );
  Widget _page(AppRoute route) => switch (route.path) {
    '/start' => OnboardingPage(
      step: int.tryParse(route.params['step'] ?? '0') ?? 0,
    ),
    '/home' => const HomePage(),
    '/list' => NoticeListPage(query: NoticeQuery.fromParams(route.params)),
    '/search' => NoticeListPage(
      query: NoticeQuery.fromParams(route.params),
      search: true,
    ),
    '/detail' => NoticeDetailPage(
      id: route.params['id'] ?? '',
      snapshot: route.params['snapshot_id'],
    ),
    '/saved' => SavedPage(changedOnly: route.params['changed'] == '1'),
    '/settings' => const SettingsPage(),
    _ => EmptyPanel(
      '페이지를 찾을 수 없어요.',
      '주소를 확인하거나 홈으로 이동해주세요.',
      action: '홈으로',
      onTap: () => _go('/home', {}),
    ),
  };
  Widget _header(BuildContext context, bool onboard) {
    final env = AppContext.of(context), small = mobile(context);
    return DecoratedBox(
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Palette.line)),
      ),
      child: PageWidth(
        child: SizedBox(
          height: small ? 65 : 80,
          child: Row(
            children: [
              Pressable(
                label: '여기:it 홈',
                onTap: () => env.go('/home'),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  child: Text.rich(
                    TextSpan(
                      children: [
                        const TextSpan(text: '여기'),
                        TextSpan(
                          text: ':',
                          style: TextStyle(color: Palette.orange),
                        ),
                        const TextSpan(text: 'it'),
                      ],
                    ),
                    textScaler: TextScaler.noScaling,
                    style: type(
                      small ? 27 : 30,
                      weight: FontWeight.w800,
                      spacing: -1.5,
                    ),
                  ),
                ),
              ),
              SizedBox(width: small ? 12 : 30),
              if (onboard) ...[
                Expanded(
                  child: Text(
                    '내 동네 맞춤 설정',
                    textAlign: TextAlign.end,
                    style: type(11, color: Palette.sub, height: 1.2),
                  ),
                ),
              ] else ...[
                Expanded(
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: Pressable(
                      label: '관심 지역 변경',
                      onTap: () => unawaited(env.region()),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            UiIcon(
                              'pin',
                              size: small ? 14 : 16,
                              color: Palette.sub,
                            ),
                            const SizedBox(width: 5),
                            Flexible(
                              child: Text(
                                '${env.state.settings.city} ${env.state.settings.district == citywide ? '전체' : env.state.settings.district}',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: type(small ? 11 : 12),
                              ),
                            ),
                            const SizedBox(width: 4),
                            const UiIcon('down', size: 13),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
                IconAction('search', '검색', onTap: () => env.go('/search')),
                IconAction('bookmark', '관심정보', onTap: () => env.go('/saved')),
                if (!small)
                  IconAction(
                    'settings',
                    '설정',
                    onTap: () => env.go('/settings'),
                  ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  Widget _categories(BuildContext context) {
    const icons = {
      'all': 'grid',
      'education': 'book',
      'support': 'gift',
      'event': 'ticket',
      'traffic': 'traffic',
      'life': 'home',
    };
    final env = AppContext.of(context),
        selected = widget.route.params['cat'] ?? 'all';
    return PageWidth(
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: [
            for (final e in categories.entries)
              Padding(
                padding: EdgeInsets.only(right: mobile(context) ? 23 : 31),
                child: Pressable(
                  label: '${e.value} 소식',
                  selected: selected == e.key,
                  hoverColor: Palette.soft,
                  onTap: () =>
                      env.go('/list', e.key == 'all' ? {} : {'cat': e.key}),
                  child: Container(
                    constraints: const BoxConstraints(minHeight: 62),
                    padding: const EdgeInsets.symmetric(
                      horizontal: 2,
                      vertical: 18,
                    ),
                    decoration: BoxDecoration(
                      border: Border(
                        bottom: BorderSide(
                          color: selected == e.key
                              ? Palette.orange
                              : Colors.transparent,
                          width: 2,
                        ),
                      ),
                    ),
                    child: Row(
                      children: [
                        UiIcon(
                          icons[e.key]!,
                          size: 18,
                          color: selected == e.key
                              ? Palette.orange
                              : Palette.sub,
                        ),
                        const SizedBox(width: 7),
                        Text(
                          e.value,
                          style: type(
                            13,
                            color: selected == e.key
                                ? Palette.ink
                                : Palette.sub,
                            weight: selected == e.key
                                ? FontWeight.w600
                                : FontWeight.w400,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _mobileNav(BuildContext context) {
    final env = AppContext.of(context);
    const entries = [
      ('/home', 'home', '홈'),
      ('/search', 'search', '검색'),
      ('/saved', 'bookmark', '관심정보'),
      ('/settings', 'settings', '설정'),
    ];
    return Container(
      decoration: const BoxDecoration(
        color: Colors.white,
        border: Border(top: BorderSide(color: Palette.line)),
      ),
      child: SafeArea(
        top: false,
        child: Row(
          children: [
            for (final e in entries)
              Expanded(
                child: Pressable(
                  label: e.$3,
                  selected: widget.route.path == e.$1,
                  onTap: () => env.go(e.$1),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 10),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        UiIcon(
                          e.$2,
                          color: widget.route.path == e.$1
                              ? Palette.orange
                              : Palette.sub,
                        ),
                        const SizedBox(height: 3),
                        Text(
                          e.$3,
                          style: type(
                            10,
                            color: widget.route.path == e.$1
                                ? Palette.orange
                                : Palette.sub,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _footer(BuildContext context) => Container(
    width: double.infinity,
    color: Palette.background,
    padding: const EdgeInsets.symmetric(vertical: 28),
    child: PageWidth(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('여기:it', style: type(22, weight: FontWeight.w700, spacing: -1)),
          const SizedBox(height: 13),
          Text(
            widget.state.isPrototype
                ? '안성시 지역정보 서비스 시제품 · 화면의 소식은 모두 예시입니다.'
                : '공개 자료의 제공 범위·확인 시각과 원문을 함께 확인해주세요.',
            style: type(11, color: Palette.sub),
          ),
          Text(
            widget.state.storageFailed
                ? '신청 조건과 일정은 실제 원문에서 확인해주세요. 설정과 관심정보는 이번 방문 동안만 유지됩니다.'
                : '신청 조건과 일정은 실제 원문에서 확인해야 합니다. 설정과 관심정보는 이 브라우저에 저장됩니다.',
            style: type(11, color: Palette.sub),
          ),
          UiButton(
            '안성시 홈페이지 · 개별 소식의 원문이 아닙니다',
            quiet: true,
            icon: 'external',
            onTap: () =>
                widget.state.browser.open('https://www.anseong.go.kr/'),
          ),
        ],
      ),
    ),
  );
}
