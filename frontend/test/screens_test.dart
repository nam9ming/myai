import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:yeogi_it/main.dart';
import 'package:yeogi_it/app/app_state.dart';
import 'package:yeogi_it/core/ui.dart';
import 'package:yeogi_it/features/notices/list_page.dart';
import 'package:yeogi_it/data/models.dart';

import 'support.dart';

Future<AppState> mount(
  WidgetTester tester,
  String path,
  double width, {
  double scale = 1,
  FakeBrowser? browser,
  String mode = 'prototype',
}) async {
  tester.view.physicalSize = Size(width, 1000);
  tester.view.devicePixelRatio = 1;
  tester.binding.platformDispatcher.defaultRouteNameTestValue = path;
  addTearDown(() {
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
    tester.binding.platformDispatcher.clearDefaultRouteNameTestValue();
  });
  final state = AppState(prototype(), browser ?? FakeBrowser(), mode: mode);
  await state.reload();
  await tester.pumpWidget(
    MediaQuery(
      data: MediaQueryData(
        textScaler: TextScaler.linear(scale),
        disableAnimations: tester
            .binding
            .platformDispatcher
            .accessibilityFeatures
            .disableAnimations,
      ),
      child: YeogiApp(state: state),
    ),
  );
  await tester.pumpAndSettle();
  return state;
}

Future<void> tapText(WidgetTester tester, String text) async {
  final finder = find.text(text).last;
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

void main() {
  final routes = [
    '/start',
    '/home',
    '/list',
    '/search',
    '/detail?id=edu-pottery',
    '/saved',
    '/settings',
  ];
  for (final width in [360.0, 390.0, 768.0, 1440.0]) {
    for (final path in routes) {
      testWidgets('$width px $path 화면에 레이아웃 오류가 없다', (tester) async {
        await mount(tester, path, width);
        expect(tester.takeException(), isNull);
        expect(find.byType(ErrorWidget), findsNothing);
      });
    }
  }
  testWidgets('위치 거부 뒤 온보딩을 선택 정보 없이 완료한다', (tester) async {
    final browser = FakeBrowser(),
        state = await mount(tester, '/start', 390, browser: FakeBrowser());
    expect(browser.locationRequests, 0);
    await tapText(tester, '경기도');
    await tapText(tester, '안성시');
    expect(state.browser, isA<FakeBrowser>());
    expect((state.browser as FakeBrowser).locationRequests, 0);
    await tapText(tester, '현재 위치로 찾기');
    expect((state.browser as FakeBrowser).locationRequests, 1);
    await tapText(tester, '지금 바로 둘러보기');
    expect(state.settings.onboarded, isTrue);
    expect(state.settings.age, isEmpty);
    expect(state.settings.gender, isEmpty);
    expect(find.text('안성시 소식을 살펴보세요.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('다른 도시에서는 안성 예시를 해당 도시 소식으로 표시하지 않는다', (tester) async {
    final state = await mount(tester, '/start', 390);
    await tapText(tester, '서울특별시');
    await tapText(tester, '종로구');
    await tapText(tester, '선택한 지역으로 둘러보기');
    await tapText(tester, '지금 바로 둘러보기');
    expect(state.settings.city, '종로구');
    expect(find.text('종로구 소식은 준비 중이에요.'), findsOneWidget);
    expect(find.text('퇴근 후, 나를 위한 생활 도예'), findsNothing);
  });
  testWidgets('필터 모달 취소와 적용을 구분한다', (tester) async {
    await mount(tester, '/list?cat=education&open=1', 390);
    await tapText(tester, '필터');
    await tester.tap(find.byType(CheckboxListTile).last);
    await tester.pumpAndSettle();
    await tester.tap(
      find.byWidgetPredicate((w) => w is IconAction && w.label == '필터 닫기'),
    );
    await tester.pumpAndSettle();
    expect(
      tester.widget<NoticeListPage>(find.byType(NoticeListPage)).query.free,
      isFalse,
    );
    await tapText(tester, '필터');
    await tester.tap(find.byType(CheckboxListTile).last);
    await tester.pumpAndSettle();
    await tapText(tester, '조건 적용');
    final q = tester.widget<NoticeListPage>(find.byType(NoticeListPage)).query;
    expect(q.free, isTrue);
    expect(q.open, isTrue);
    expect(q.category, 'education');
    expect(find.text('총 2개의 소식'), findsOneWidget);
  });
  testWidgets('검색은 1건과 0건을 구분하고 무료 추천어를 필터로 연결한다', (tester) async {
    await mount(tester, '/search', 390);
    await tester.enterText(find.byType(TextField), '도예');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pumpAndSettle();
    expect(find.text('총 1개의 소식'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'zz-no-such-notice-987');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pumpAndSettle();
    expect(find.text('총 0개의 소식'), findsOneWidget);
    expect(find.text('조건에 맞는 소식이 없어요.'), findsOneWidget);
  });
  testWidgets('카드 저장은 화면 이동 없이 즉시 동기화된다', (tester) async {
    final state = await mount(tester, '/home', 390);
    await tester.tap(find.byType(SaveButton).first);
    await tester.pumpAndSettle();
    expect(state.saved, hasLength(1));
    expect(find.text('안성시 소식을 살펴보세요.'), findsOneWidget);
    expect(AppState(prototype(), state.browser).saved.keys, state.saved.keys);
  });
  testWidgets('설정 draft는 취소하면 저장값에 반영되지 않는다', (tester) async {
    final state = await mount(tester, '/settings', 390);
    final interest = find.byWidgetPredicate(
      (w) => w is UiButton && w.label == '교육·배움',
    );
    await tester.ensureVisible(interest);
    await tester.tap(interest);
    await tester.pumpAndSettle();
    expect(state.settings.interests, isEmpty);
    await tapText(tester, '취소');
    expect(state.settings.interests, isEmpty);
  });
  testWidgets('직접 상세 진입의 목록 버튼은 앱 내부에 남는다', (tester) async {
    await mount(tester, '/detail?id=edu-pottery', 390);
    await tapText(tester, '목록으로');
    expect(find.byType(NoticeListPage), findsOneWidget);
  });
  testWidgets('없는 상세 ID는 복구 동작을 제공한다', (tester) async {
    await mount(tester, '/detail?id=missing', 390);
    expect(find.text('소식을 찾을 수 없어요.'), findsOneWidget);
  });
  testWidgets('200% 글자와 긴 제목에서도 주요 화면이 깨지지 않는다', (tester) async {
    final state = await mount(tester, '/list', 360, scale: 2);
    state.items = [
      const Notice(
        id: 'long',
        category: 'life',
        title: '아주 긴 한국어 공지 제목을 여러 줄로 읽을 때도 내용과 조작 버튼이 가려지지 않도록 확인하는 소식',
        description: '긴 본문',
      ),
    ];
    state.notifyListeners();
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
  testWidgets('키보드로 필터를 닫고 focus를 돌려준다', (tester) async {
    await mount(tester, '/list', 390);
    await tapText(tester, '필터');
    expect(find.byType(Dialog), findsOneWidget);
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
    expect(find.byType(Dialog), findsNothing);
    expect(tester.takeException(), isNull);
  });
  if (const bool.fromEnvironment('CAPTURE_QA')) {
    for (final path in ['/home', '/start', '/detail?id=edu-pottery']) {
      testWidgets('화면 제어 없이 위젯 캡처 $path', (tester) async {
        final fonts = FontLoader('NotoSansKR')
          ..addFont(rootBundle.load('assets/fonts/NotoSansKR.ttf'));
        await fonts.load();
        final svgFonts = FontLoader('sans-serif')
          ..addFont(rootBundle.load('assets/fonts/NotoSansKR.ttf'));
        await svgFonts.load();
        final serifFonts = FontLoader('serif')
          ..addFont(rootBundle.load('assets/fonts/NotoSerifKR.ttf'));
        await serifFonts.load();
        tester.view.physicalSize = const Size(390, 844);
        tester.view.devicePixelRatio = 1;
        tester.binding.platformDispatcher.defaultRouteNameTestValue = path;
        final state = AppState(prototype(), FakeBrowser());
        await state.reload();
        final key = GlobalKey();
        await tester.pumpWidget(
          RepaintBoundary(
            key: key,
            child: YeogiApp(state: state),
          ),
        );
        await tester.pumpAndSettle();
        final boundary =
            key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
        await tester.runAsync(() async {
          final image = await boundary.toImage();
          final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
          final dir = Directory('../.local/qa')..createSync(recursive: true);
          File(
            '${dir.path}/prototype-20261116-390-${path.split('?').first.substring(1)}.png',
          ).writeAsBytesSync(bytes!.buffer.asUint8List());
          image.dispose();
        });
        expect(tester.takeException(), isNull);
      });
    }
  }
}
