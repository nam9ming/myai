import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:yeogi_it/core/browser.dart';
import 'package:yeogi_it/features/nearby/data.dart';

import 'support.dart';

void main() {
  final demo = File('web/nearby-feed.json').readAsStringSync();
  test('지도 예시 자료와 실제 자료가 같은 스키마로 교체된다', () async {
    final browser = FakeBrowser();
    var body = demo;
    browser.responder = (url, method, payload) async =>
        url == 'nearby-config.json'
        ? const HttpResult(200, '{"url":"nearby-feed.json"}')
        : HttpResult(200, body);
    final repository = NearbyRepository(browser);
    final initial = await repository.load();
    expect(initial.demo, true);
    expect(repository.cached, same(initial));
    expect(initial.items.every((item) => item.summary.isNotEmpty), true);
    expect(initial.items.length, 30);
    final live = jsonDecode(demo) as Map<String, dynamic>;
    live['data_kind'] = 'live';
    for (final row in live['items']) {
      row['source_url'] = 'https://www.anseong.go.kr/';
    }
    body = jsonEncode(live);
    expect((await repository.load()).demo, false);
  });
  test('좌표·중복·원문·버전 오류를 예시로 대체하지 않는다', () {
    for (final change in <void Function(Map<String, dynamic>)>[
      (j) => j['items'][0]['lat'] = 91,
      (j) => j['items'][1]['id'] = j['items'][0]['id'],
      (j) => j['items'][0]['source_url'] = 'javascript:alert(1)',
      (j) => j['data_kind'] = 'live',
      (j) => j['version'] = 2,
      (j) => j['items'][0]['summary'] = 42,
    ]) {
      final json = jsonDecode(demo) as Map<String, dynamic>;
      change(json);
      expect(() => NearbyFeed.parse(jsonEncode(json)), throwsFormatException);
    }
    expect(
      NearbyFeed.parse(
        '{"version":1,"data_kind":"live","updated_at":"2026-11-17T00:00:00Z","items":[]}',
      ).items,
      isEmpty,
    );
  });
}
