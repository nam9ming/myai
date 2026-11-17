import 'browser_stub.dart'
    if (dart.library.js_interop) 'browser_web.dart'
    as platform;

class HttpResult {
  final int status;
  final String body;
  const HttpResult(this.status, this.body);
}

abstract class BrowserServices {
  String? read(String key);
  void write(String key, String value);
  Future<HttpResult> request(String url, {String method = 'GET', String? body});
  Future<bool> requestLocation();
  bool open(String url);
  void back();
  bool get reducedMotion;
  Stream<bool> get reducedMotionChanges;
}

BrowserServices createBrowserServices() => platform.createBrowserServices();
