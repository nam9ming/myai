import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:yeogi_it/core/browser.dart';
import 'package:yeogi_it/core/browser_stub.dart';
import 'package:yeogi_it/data/models.dart';
import 'package:yeogi_it/data/repositories.dart';

class HttpSmokeBinding extends AutomatedTestWidgetsFlutterBinding {
  @override
  bool get overrideHttpClient => false;
}

class HttpBrowser extends MemoryBrowserServices {
  final client = HttpClient();
  @override
  Future<HttpResult> request(
    String url, {
    String method = 'GET',
    String? body,
  }) async {
    final request = await client.openUrl(method, Uri.parse(url));
    request.headers.set('Origin', 'http://localhost:5173');
    if (body != null) {
      request.headers.contentType = ContentType.json;
      request.write(body);
    }
    final response = await request.close();
    return HttpResult(
      response.statusCode,
      await utf8.decoder.bind(response).join(),
    );
  }
}

void main() {
  HttpSmokeBinding();
  const base = String.fromEnvironment(
    'SMOKE_API_URL',
    defaultValue: 'http://localhost:8080/api/v1',
  );
  test('Spring 합성 config → 고정 matches → 같은 공개본 상세를 실제 HTTP로 읽는다', () async {
    final transport = HttpBrowser();
    addTearDown(() => transport.client.close(force: true));
    final repo = SpringNoticeRepository(
      transport,
      baseUrl: base,
      fixture: true,
    );
    final items = await repo.loadFeed();
    expect(items, hasLength(2));
    expect(items.every((n) => n.synthetic), isTrue);
    final detail = await repo.detail(items.first.id, snapshot: repo.snapshot);
    expect(detail, isNotNull);
    expect(detail!.snapshotId, repo.snapshot);
    expect(detail.api!['evidence'], isNotEmpty);
    expect(detail.classification, 'candidate');
    expect(sourceUrl(detail), startsWith('https://example.org/'));
  });
  test('Spring fixture의 미지원 조건은 503으로 보존한다', () async {
    final transport = HttpBrowser();
    addTearDown(() => transport.client.close(force: true));
    final request = jsonDecode(
      File('test/fixtures/matches-request.json').readAsStringSync(),
    ) as Map<String, dynamic>;
    request['weekly_hours']['monday']['intervals'][0]['start'] = '10:00';
    final response = await transport.request(
      '$base/matches',
      method: 'POST',
      body: jsonEncode(request),
    );
    expect(response.status, 503);
    final error = ApiFailure.fromResponse(
      response.status,
      jsonDecode(response.body),
    );
    expect(error.code, 'CALCULATOR_NOT_READY');
    // 기존 fixture 오류 계약은 이 503에도 retryable=true를 반환한다.
    expect(error.retryable, isTrue);
  });
  test('Spring CORS는 지정한 개발 origin과 JSON POST만 허용한다', () async {
    final client = HttpClient();
    addTearDown(() => client.close(force: true));
    final request = await client.openUrl('OPTIONS', Uri.parse('$base/matches'));
    request.headers.set('Origin', 'http://localhost:5173');
    request.headers.set('Access-Control-Request-Method', 'POST');
    request.headers.set('Access-Control-Request-Headers', 'Content-Type');
    final response = await request.close();
    expect(response.statusCode, 200);
    expect(
      response.headers.value('access-control-allow-origin'),
      'http://localhost:5173',
    );
    await response.drain<void>();
    final wrong = await client.openUrl('OPTIONS', Uri.parse('$base/matches'));
    wrong.headers.set('Origin', 'http://localhost:9999');
    wrong.headers.set('Access-Control-Request-Method', 'POST');
    final denied = await wrong.close();
    expect(denied.statusCode, 403);
    await denied.drain<void>();
  });
}

String sourceUrl(Notice n) =>
    (n.api!['source_refs'] as List).first['url'] as String;
