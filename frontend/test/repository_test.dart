import 'dart:convert';
import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:yeogi_it/core/browser.dart';
import 'package:yeogi_it/data/models.dart';
import 'package:yeogi_it/data/repositories.dart';

import 'support.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('실제 사실 DTO의 null·빈 배열·이모지·전체 근거를 보존한다', () {
    final j = fixture('event-facts-response.json'),
        raw = Map<String, dynamic>.from(j['data']['event']);
    final n = Notice.fromApi(raw, snapshot: j['snapshot_id'], synthetic: true);
    expect(n.title, '합성 공지 😀');
    expect(n.district, '지역 미기재');
    expect(n.start, '2026-11-03');
    expect(n.api!['exceptions'], isNull);
    expect(n.api!['relations'], isEmpty);
    expect(n.api!['field_values'], raw['field_values']);
    expect(n.api!['evidence'], raw['evidence']);
    expect(n.api!['source_refs'], raw['source_refs']);
    expect(n.api!['history'], raw['history']);
    expect(n.api!.containsKey('classification'), isFalse);
  });
  test('fixture 조회는 계약의 원래 조건과 동일 snapshot을 사용한다', () async {
    final browser = FakeBrowser(),
        repo = SpringNoticeRepository(
          FakeBrowser(),
          baseUrl: 'http://localhost:8080/api/v1',
          fixture: true,
        );
    final actual = SpringNoticeRepository(
      browser,
      baseUrl: repo.baseUrl,
      fixture: true,
    );
    final items = await actual.loadFeed();
    expect(items, hasLength(2));
    expect(
      actual.matchEnvelope!['data']['query_context'],
      fixture('matches-response.json')['data']['query_context'],
    );
    final request = browser.requests.last.body!;
    final expected = fixture('matches-request.json')
      ..['snapshot_id'] = fixture('config-response.json')['snapshot_id'];
    expect(request, expected);
    expect(request.containsKey('education'), isFalse);
    expect(request.containsKey('latitude'), isFalse);
    final detail = await actual.detail(
      items.first.id,
      snapshot: items.first.snapshotId,
    );
    expect(detail!.classification, 'candidate');
    expect(detail.synthetic, isTrue);
    expect(
      browser.requests.last.url,
      contains('snapshot_id=${items.first.snapshotId}'),
    );
  });
  test('public 모드는 지점·영업시간을 임의 생성하지 않는다', () async {
    final browser = FakeBrowser(),
        repo = SpringNoticeRepository(FakeBrowser(), baseUrl: '/api/v1');
    final actual = SpringNoticeRepository(browser, baseUrl: repo.baseUrl);
    await expectLater(
      actual.loadFeed(),
      throwsA(
        isA<ApiFailure>().having(
          (e) => e.code,
          'code',
          'UNSUPPORTED_CITIZEN_FEED',
        ),
      ),
    );
    expect(browser.requests.map((r) => r.method), ['GET']);
  });
  for (final status in [404, 409, 422, 503, 500]) {
    test('HTTP $status와 retryable·request_id·새 공개본을 보존한다', () async {
      final browser = FakeBrowser()
        ..responder = (url, method, body) async => HttpResult(
          status,
          jsonEncode({
            'error': {
              'code': status == 409 ? 'SNAPSHOT_RETIRED' : 'TEST_ERROR',
              'message': '실패',
              'retryable': status == 503,
            },
            'request_id': 'request',
            'current_snapshot_id': status == 409 ? 'new' : null,
          }),
        );
      final repo = SpringNoticeRepository(browser, baseUrl: '/api/v1');
      await expectLater(
        repo.loadFeed(),
        throwsA(
          isA<ApiFailure>()
              .having((e) => e.status, 'status', status)
              .having((e) => e.retryable, 'retryable', status == 503)
              .having((e) => e.requestId, 'requestId', 'request')
              .having(
                (e) => e.currentSnapshotId,
                'currentSnapshotId',
                status == 409 ? 'new' : null,
              ),
        ),
      );
      expect(repo.feed, isEmpty);
    });
  }
  test('혼합 snapshot 응답은 거부한다', () async {
    final browser = FakeBrowser()
      ..responder = (url, method, body) async {
        final j = fixture(
          url.endsWith('/config')
              ? 'config-response.json'
              : 'event-response.json',
        );
        return HttpResult(200, jsonEncode(j));
      };
    final repo = SpringNoticeRepository(browser, baseUrl: '/api/v1');
    await expectLater(
      repo.detail('48bb73cf-3cd9-5e4f-895e-9ba9ce62560f', snapshot: 'another'),
      throwsA(
        isA<ApiFailure>().having((e) => e.code, 'code', 'SNAPSHOT_MISMATCH'),
      ),
    );
  });
  test('늦게 도착한 설정 응답은 최신 snapshot을 덮어쓰지 않는다', () async {
    final old = Completer<HttpResult>(), latest = Completer<HttpResult>();
    var calls = 0;
    final browser = FakeBrowser()
      ..responder = (url, method, body) =>
          calls++ == 0 ? old.future : latest.future;
    final repo = SpringNoticeRepository(browser, baseUrl: '/api/v1');
    final first = expectLater(repo.loadFeed(), throwsA(isA<ApiFailure>()));
    final second = expectLater(repo.loadFeed(), throwsA(isA<ApiFailure>()));
    final newConfig = fixture('config-response.json')..['snapshot_id'] = 'new';
    latest.complete(HttpResult(200, jsonEncode(newConfig)));
    await second;
    old.complete(HttpResult(200, jsonEncode(fixture('config-response.json'))));
    await first;
    expect(repo.snapshot, 'new');
  });
}
