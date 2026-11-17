import 'browser.dart';

class MemoryBrowserServices implements BrowserServices {
  final Map<String, String> values = {};
  @override
  String? read(String key) => values[key];
  @override
  void write(String key, String value) {
    values[key] = value;
  }

  @override
  Future<HttpResult> request(
    String url, {
    String method = 'GET',
    String? body,
  }) async => throw UnsupportedError('브라우저에서 실행해주세요.');
  @override
  Future<bool> requestLocation() async => false;
  @override
  bool open(String url) => false;
  @override
  void back() {}
  @override
  bool get reducedMotion => false;
  @override
  Stream<bool> get reducedMotionChanges => const Stream.empty();
}

BrowserServices createBrowserServices() => MemoryBrowserServices();
