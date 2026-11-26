import 'dart:async';
import 'dart:js_interop';

import 'package:web/web.dart' as web;

import 'browser.dart';

class WebBrowserServices implements BrowserServices {
  @override
  String? read(String key) => web.window.localStorage.getItem(key);
  @override
  void write(String key, String value) =>
      web.window.localStorage.setItem(key, value);
  @override
  Future<HttpResult> request(
    String url, {
    String method = 'GET',
    String? body,
  }) async {
    final controller = web.AbortController();
    final timer = Timer(const Duration(seconds: 15), () => controller.abort());
    final headers = web.Headers();
    if (body != null) headers.set('Content-Type', 'application/json');
    try {
      final response = await web.window
          .fetch(
            url.toJS,
            web.RequestInit(
              method: method,
              signal: controller.signal,
              headers: headers,
              body: body?.toJS,
            ),
          )
          .toDart;
      return HttpResult(response.status, (await response.text().toDart).toDart);
    } finally {
      timer.cancel();
    }
  }

  @override
  Future<bool> requestLocation() async {
    final completer = Completer<bool>();
    web.PermissionStatus? permission;
    try {
      permission = await web.window.navigator.permissions
          .query({'name': 'geolocation'}.jsify()! as JSObject)
          .toDart
          .timeout(const Duration(seconds: 1));
      if (permission.state == 'granted') return true;
    } catch (_) {
      // Older browsers can still report the result through geolocation.
    }
    final onPermissionChange = ((web.Event _) {
      final state = permission?.state;
      if (state != 'prompt' && !completer.isCompleted) {
        completer.complete(state == 'granted');
      }
    }).toJS;
    try {
      permission?.addEventListener('change', onPermissionChange);
      web.window.navigator.geolocation.getCurrentPosition(
        ((web.GeolocationPosition _) {
          if (!completer.isCompleted) completer.complete(true);
        }).toJS,
        ((web.GeolocationPositionError _) {
          if (!completer.isCompleted) {
            completer.complete(permission?.state == 'granted');
          }
        }).toJS,
        web.PositionOptions(
          enableHighAccuracy: false,
          timeout: 8000,
          maximumAge: 60000,
        ),
      );
      return await completer.future.timeout(
        const Duration(seconds: 9),
        onTimeout: () => permission?.state == 'granted',
      );
    } catch (_) {
      return permission?.state == 'granted';
    } finally {
      permission?.removeEventListener('change', onPermissionChange);
    }
  }

  @override
  bool open(String url) {
    final uri = Uri.tryParse(url);
    if (uri == null ||
        !['http', 'https'].contains(uri.scheme) ||
        uri.host.isEmpty)
      return false;
    // 호출자는 사용자의 명시적 클릭에서만 열며 opener를 남기지 않는다.
    final anchor = web.HTMLAnchorElement()
      ..href = uri.toString()
      ..target = '_blank'
      ..rel = 'noopener noreferrer';
    anchor.click();
    return true;
  }

  @override
  void back() => web.window.history.back();
  @override
  bool get reducedMotion =>
      web.window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  @override
  Stream<bool> get reducedMotionChanges => Stream<bool>.multi((controller) {
    final query = web.window.matchMedia('(prefers-reduced-motion: reduce)');
    final callback = ((web.Event _) => controller.add(query.matches)).toJS;
    query.addEventListener('change', callback);
    controller.onCancel = () => query.removeEventListener('change', callback);
  });
}

BrowserServices createBrowserServices() => WebBrowserServices();
