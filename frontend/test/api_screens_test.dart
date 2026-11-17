import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/services.dart';
import 'package:yeogi_it/core/browser.dart';
import 'package:yeogi_it/core/ui.dart';
import 'package:yeogi_it/data/models.dart';
import 'package:yeogi_it/features/notices/detail_page.dart';
import 'package:yeogi_it/features/home/page.dart';

import 'screens_test.dart' show mount, tapText;
import 'support.dart';

void main() {
  testWidgets('주소 복사 실패도 선택 가능한 URL로 복구한다', (tester) async {
    final browser = FakeBrowser();
    await mount(tester, '/home', 390, browser: browser);
    const n = Notice(
      id: 'real',
      category: 'event',
      title: '공개 소식',
      synthetic: false,
      api: {
        'source_refs': [
          {'url': 'https://city.example.test/notice', 'is_fixture': false},
        ],
      },
    );
    unawaited(
      showSource(tester.element(find.byType(HomePage)), n, addressOnly: true),
    );
    await tester.pumpAndSettle();
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.setData')
          throw PlatformException(code: 'blocked');
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        null,
      ),
    );
    await tapText(tester, '주소 복사');
    expect(find.text('복사하지 못했어요. 표시된 주소를 선택해 복사해주세요.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('공개 준비 중 503은 0건·예시 카드와 구분한다', (tester) async {
    final browser = FakeBrowser()
      ..responder = (url, method, body) async => HttpResult(
        503,
        jsonEncode({
          'error': {
            'code': 'PUBLIC_DATA_NOT_READY',
            'message': '공개 자료 미준비',
            'retryable': false,
          },
        }),
      );
    final state = await mount(
      tester,
      '/home',
      390,
      browser: browser,
      mode: 'api',
    );
    expect(find.text('공개 자료를 준비하고 있어요.'), findsOneWidget);
    expect(state.items, isEmpty);
    expect(find.byType(NoticeCard), findsNothing);
    expect(find.text('다시 시도'), findsNothing);
  });
  testWidgets('시민용 미지원 분야를 임의 enum·matches 입력으로 보내지 않는다', (tester) async {
    final browser = FakeBrowser();
    await mount(
      tester,
      '/list?cat=education',
      390,
      browser: browser,
      mode: 'api',
    );
    expect(find.text('이 정보는 아직 준비 중이에요.'), findsOneWidget);
    expect(browser.requests.map((r) => r.method), ['GET']);
    expect(find.byType(NoticeCard), findsNothing);
  });
  testWidgets('예시 원문은 안내만 표시하고 실제 외부 탭을 열지 않는다', (tester) async {
    final browser = FakeBrowser();
    await mount(tester, '/detail?id=edu-pottery', 390, browser: browser);
    expect(browser.openedUrls, isEmpty);
    await tapText(tester, '원문 보기');
    expect(find.text('예시 소식 안내'), findsOneWidget);
    expect(browser.openedUrls, isEmpty);
  });
  testWidgets('유효한 실제 원문만 명시적 동작에서 연다', (tester) async {
    final browser = FakeBrowser();
    await mount(tester, '/home', 390, browser: browser);
    const n = Notice(
      id: 'real',
      category: 'event',
      title: '공개 소식',
      synthetic: false,
      api: {
        'source_refs': [
          {'url': 'https://city.example.test/notice', 'is_fixture': false},
        ],
      },
    );
    final context = tester.element(find.byType(HomePage));
    expect(browser.openedUrls, isEmpty);
    await showSource(context, n);
    expect(browser.openedUrls, ['https://city.example.test/notice']);
  });
  testWidgets('미상 URL이나 스크립트 주소는 원문으로 열지 않는다', (tester) async {
    final browser = FakeBrowser();
    await mount(tester, '/home', 390, browser: browser);
    const n = Notice(
      id: 'invalid',
      category: 'event',
      title: '주소 확인 필요',
      synthetic: false,
      api: {
        'source_refs': [
          {'url': 'javascript:alert(1)', 'is_fixture': false},
        ],
      },
    );
    unawaited(showSource(tester.element(find.byType(HomePage)), n));
    await tester.pumpAndSettle();
    expect(find.text('원문 미제공'), findsOneWidget);
    expect(browser.openedUrls, isEmpty);
  });
}
