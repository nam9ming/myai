import 'dart:convert';
import 'dart:io';

import 'package:yeogi_it/core/browser.dart';
import 'package:yeogi_it/core/browser_stub.dart';
import 'package:yeogi_it/data/repositories.dart';

Map<String, dynamic> fixture(String name) =>
    jsonDecode(File('test/fixtures/$name').readAsStringSync())
        as Map<String, dynamic>;
PrototypeData prototype() => PrototypeData(
  jsonDecode(File('assets/prototype/notices.json').readAsStringSync()),
);

class FakeBrowser extends MemoryBrowserServices {
  final List<String> openedUrls = [];
  @override
  bool open(String url) {
    openedUrls.add(url);
    return true;
  }

  void Function()? onBack;
  @override
  void back() => onBack?.call();
  final List<({String url, String method, Map<String, dynamic>? body})>
  requests = [];
  Future<HttpResult> Function(String url, String method, String? body)?
  responder;
  bool failWrites = false;
  bool locationAllowed = false;
  int locationRequests = 0;
  @override
  void write(String key, String value) {
    if (failWrites) throw StateError('blocked');
    super.write(key, value);
  }

  @override
  Future<bool> requestLocation() async {
    locationRequests++;
    return locationAllowed;
  }

  @override
  Future<HttpResult> request(
    String url, {
    String method = 'GET',
    String? body,
  }) async {
    requests.add((
      url: url,
      method: method,
      body: body == null ? null : jsonDecode(body),
    ));
    if (responder != null) return responder!(url, method, body);
    if (url.endsWith('/config'))
      return HttpResult(200, jsonEncode(fixture('config-response.json')));
    if (url.endsWith('/matches'))
      return HttpResult(200, jsonEncode(fixture('matches-response.json')));
    return HttpResult(200, jsonEncode(fixture('event-response.json')));
  }
}
