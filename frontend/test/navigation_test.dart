import 'dart:async';

import 'package:flutter/services.dart';

import 'dart:ui' show PointerDeviceKind;

import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:yeogi_it/core/ui.dart';
import 'package:yeogi_it/features/notices/list_page.dart';

import 'screens_test.dart' show mount, tapText;
import 'support.dart';

Finder verticalScrollable() => find.byWidgetPredicate(
  (w) => w is Scrollable && w.axisDirection == AxisDirection.down,
);

void main() {
  testWidgets('PC 상세 요약은 재배치와 스크롤 중에도 표시된다', (tester) async {
    final state = await mount(tester, '/detail?id=edu-pottery', 1440);
    for (final width in [390.0, 1440.0, 850.0, 1440.0]) {
      tester.view.physicalSize = Size(width, 1000);
      state.notifyListeners();
      await tester.pump();
      await tester.pumpAndSettle();
      final position = tester
          .state<ScrollableState>(verticalScrollable().first)
          .position;
      position.jumpTo(position.maxScrollExtent.clamp(0, 160).toDouble());
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    }
    expect(find.text('퇴근 후, 나를 위한 생활 도예'), findsOneWidget);
    expect(find.byType(SaveButton), findsWidgets);
  });
  testWidgets('온보딩 카드는 호버와 초점에서 설명을 표시한다', (tester) async {
    await mount(tester, '/start', 1440);
    for (final label in ['가까운 소식', '새로운 기회', '배우는 일상', '챙기는 혜택']) {
      expect(find.text(label), findsOneWidget);
    }
    final card = find.text('챙기는 혜택');
    final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await mouse.addPointer(location: Offset.zero);
    addTearDown(mouse.removePointer);
    await mouse.moveTo(tester.getCenter(card));
    await tester.pumpAndSettle();
    expect(find.textContaining('지원사업과 생활 혜택의 대상·신청 기간'), findsOneWidget);
    expect(
      tester
          .widgetList<AnimatedScale>(find.byType(AnimatedScale))
          .any((w) => w.scale == 1.04),
      isTrue,
    );
    await mouse.moveTo(Offset.zero);
    await tester.pumpAndSettle();
    expect(find.textContaining('지원사업과 생활 혜택의 대상·신청 기간'), findsNothing);
    final tooltip = find
        .ancestor(of: card, matching: find.byType(Tooltip))
        .first;
    final focus = find
        .ancestor(of: tooltip, matching: find.byType(Focus))
        .first;
    Focus.of(tester.element(tooltip)).requestFocus();
    await tester.pumpAndSettle();
    expect(find.textContaining('지원사업과 생활 혜택의 대상·신청 기간'), findsOneWidget);
    expect(focus, findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('온보딩 이전 단계로 돌아가도 지역 선택을 보존한다', (tester) async {
    final state = await mount(tester, '/start', 390);
    await tapText(tester, '경기도');
    await tapText(tester, '안성시');
    await tapText(tester, '이전');
    expect(state.onboarding.province, '경기도');
    expect(state.onboarding.city, '안성시');
    expect(find.text('경기도의\n어디가 궁금하세요?'), findsOneWidget);
  });
  testWidgets('포스터 hover는 내부 이미지만 확대한다', (tester) async {
    await mount(tester, '/home', 1440);
    final card = find.byType(NoticeCard).first,
        before = tester.getSize(find.byType(NoticeCard).first);
    final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await mouse.addPointer(location: Offset.zero);
    addTearDown(mouse.removePointer);
    await mouse.moveTo(tester.getCenter(card));
    await tester.pumpAndSettle();
    final scales = tester.widgetList<AnimatedScale>(
      find.descendant(of: card, matching: find.byType(AnimatedScale)),
    );
    expect(scales.any((w) => w.scale == 1.035), isTrue);
    expect(tester.getSize(card), before);
  });
  testWidgets('필터 토글은 화면 진입 fade를 재시작하지 않는다', (tester) async {
    await mount(tester, '/list', 390);
    final finder = find.byType(TweenAnimationBuilder<double>),
        before = tester.stateList(finder).toList();
    await tester.tap(
      find.byWidgetPredicate((w) => w is UiButton && w.label == '무료'),
    );
    await tester.pumpAndSettle();
    expect(
      tester.widget<NoticeListPage>(find.byType(NoticeListPage)).query.free,
      isTrue,
    );
    expect(tester.stateList(finder).toList(), before);
  });
  for (final path in [
    '/start?step=5',
    '/home',
    '/detail?id=edu-pottery',
    '/saved',
    '/settings',
  ]) {
    testWidgets('200% 확대 $path 에서 가림·overflow가 없다', (tester) async {
      await mount(tester, path, 360, scale: 2);
      expect(tester.takeException(), isNull);
    });
  }
  for (final width in [369.0, 370.0, 760.0, 761.0]) {
    testWidgets('$width 반응형 경계 홈·상세 전환', (tester) async {
      await mount(tester, '/home', width);
      await tester.tap(find.byType(NoticeCard).first);
      await tester.pumpAndSettle();
      expect(find.text('목록으로'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
  testWidgets('목록→상세→브라우저 뒤로에서 조건과 스크롤을 복원한다', (tester) async {
    final browser = FakeBrowser();
    final state = await mount(tester, '/list?free=1', 390, browser: browser);
    await tester.drag(verticalScrollable(), const Offset(0, -350));
    await tester.pumpAndSettle();
    final before = tester
        .state<ScrollableState>(verticalScrollable())
        .position
        .pixels;
    expect(before, greaterThan(100));
    final card = find.byType(NoticeCard).hitTestable().first;
    await tester.tap(card);
    await tester.pumpAndSettle();
    final router = tester
        .widgetList<Router<dynamic>>(
          find.byWidgetPredicate((w) => w is Router<dynamic>),
        )
        .first;
    final provider =
        router.routeInformationProvider! as PlatformRouteInformationProvider;
    browser.onBack = () => unawaited(
      provider
          .didPushRouteInformation(
            RouteInformation(uri: Uri.parse('/list?free=1')),
          )
          .then((_) {}),
    );
    await tapText(tester, '목록으로');
    expect(
      tester.widget<NoticeListPage>(find.byType(NoticeListPage)).query.free,
      isTrue,
    );
    final restored = tester
        .state<ScrollableState>(verticalScrollable())
        .position
        .pixels;
    expect(restored, closeTo(before, 1));
    expect(state.items, isNotEmpty);
  });
  testWidgets('저장 토글은 스크롤을 이동시키지 않는다', (tester) async {
    final state = await mount(tester, '/list', 390);
    await tester.drag(verticalScrollable(), const Offset(0, -350));
    await tester.pumpAndSettle();
    final before = tester
        .state<ScrollableState>(verticalScrollable())
        .position
        .pixels;
    await tester.tap(find.byType(SaveButton).hitTestable().first);
    await tester.pumpAndSettle();
    expect(state.saved, hasLength(1));
    expect(
      tester.state<ScrollableState>(verticalScrollable()).position.pixels,
      closeTo(before, 1),
    );
  });
  testWidgets('모달 Escape 후 트리거 버튼으로 키보드 focus가 돌아온다', (tester) async {
    await mount(tester, '/list', 390);
    await tapText(tester, '필터');
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
    final focus = FocusManager.instance.primaryFocus;
    expect(focus, isNotNull);
    expect(
      focus!.context!.findAncestorWidgetOfExactType<Pressable>(),
      isNotNull,
    );
    await tester.sendKeyEvent(LogicalKeyboardKey.enter);
    await tester.pumpAndSettle();
    expect(find.byType(Dialog), findsOneWidget);
  });
  testWidgets('홈 재방문은 완료한 온보딩을 강제하지 않는다', (tester) async {
    final browser = FakeBrowser();
    final stored = prototype();
    browser.write(
      'yeogi-settings-v2',
      '{"version":2,"value":{"onboarded":true}}',
    );
    await mount(tester, '/', 390, browser: browser);
    expect(stored.items, hasLength(16));
    expect(find.text('안성시 소식을 살펴보세요.'), findsOneWidget);
  });
  testWidgets('모션 감소를 켜면 이동·확대 애니메이션을 사용하지 않는다', (tester) async {
    tester.binding.platformDispatcher.accessibilityFeaturesTestValue =
        const FakeAccessibilityFeatures(disableAnimations: true);
    addTearDown(
      tester.binding.platformDispatcher.clearAccessibilityFeaturesTestValue,
    );
    await mount(tester, '/home', 390);
    final animations = tester.widgetList<TweenAnimationBuilder<double>>(
      find.byType(TweenAnimationBuilder<double>),
    );
    expect(animations.every((w) => w.duration == Duration.zero), isTrue);
  });
}
