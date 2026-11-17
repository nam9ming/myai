import 'dart:convert';

import '../../core/browser.dart';
import '../../data/models.dart';

class NearbyNotice {
  final String id, category, title, address, description, status;
  final double lat, lng;
  final String? start, end, sourceUrl, summaryText;
  String get summary =>
      summaryText ??
      description.split("\n").first.replaceAll(RegExp(r"\s+"), " ");
  const NearbyNotice({
    required this.id,
    required this.category,
    required this.title,
    required this.address,
    required this.description,
    required this.status,
    required this.lat,
    required this.lng,
    this.start,
    this.end,
    this.sourceUrl,
    this.summaryText,
  });

  factory NearbyNotice.parse(Map<String, dynamic> j, {required bool live}) {
    String text(String key, int max) {
      final value = j[key];
      if (value is! String || value.trim().isEmpty || value.length > max) {
        throw const FormatException('필수 문구를 확인해주세요.');
      }
      return value.trim();
    }

    final category = text('category', 30), status = text('status', 30);
    final lat = j['lat'], lng = j['lng'];
    final source = j['source_url'];
    if (j['summary'] != null &&
        (j['summary'] is! String ||
            (j['summary'] as String).trim().isEmpty ||
            (j['summary'] as String).length > 240))
      throw const FormatException('요약을 확인해주세요.');
    final url = source is String ? Uri.tryParse(source) : null;
    if (!categories.containsKey(category) ||
        category == 'all' ||
        !['scheduled', 'ongoing', 'cancelled', 'unknown'].contains(status) ||
        lat is! num ||
        lng is! num ||
        !lat.isFinite ||
        !lng.isFinite ||
        lat.abs() > 90 ||
        lng.abs() > 180 ||
        (source != null &&
            (source is! String ||
                url == null ||
                !['https', 'http'].contains(url.scheme) ||
                url.host.isEmpty)) ||
        (live && source == null)) {
      throw const FormatException('분야·좌표·상태·원문 주소를 확인해주세요.');
    }
    for (final key in ['start', 'end']) {
      if (j[key] != null && (j[key] is! String || dateOnly(j[key]) == null)) {
        throw const FormatException('일정을 확인해주세요.');
      }
    }
    if (j['start'] != null &&
        j['end'] != null &&
        (j['start'] as String).compareTo(j['end'] as String) > 0) {
      throw const FormatException('일정 순서를 확인해주세요.');
    }
    return NearbyNotice(
      id: text('id', 120),
      category: category,
      title: text('title', 300),
      address: text('address', 500),
      description: text('description', 6000),
      status: status,
      lat: lat.toDouble(),
      lng: lng.toDouble(),
      start: j['start'],
      end: j['end'],
      sourceUrl: source as String?,
      summaryText: j['summary'],
    );
  }
  Map<String, Object> get marker => {
    'id': id,
    'type': category,
    'title': title,
    'label': title,
    'lat': lat,
    'lng': lng,
    'cancelled': status == 'cancelled',
  };
}

class NearbyFeed {
  final List<NearbyNotice> items;
  final bool demo;
  final DateTime updatedAt;
  NearbyFeed(this.items, this.demo, this.updatedAt);
  factory NearbyFeed.parse(String body) {
    final json = jsonDecode(body);
    if (json is! Map<String, dynamic> ||
        json['version'] != 1 ||
        !['demo', 'live'].contains(json['data_kind']) ||
        json['items'] is! List ||
        (json['items'] as List).length > 100 ||
        json['updated_at'] is! String) {
      throw const FormatException('지도 자료 형식이 올바르지 않아요.');
    }
    final updated = DateTime.tryParse(json['updated_at']);
    if (updated == null) throw const FormatException('갱신 시각을 확인해주세요.');
    final demo = json['data_kind'] == 'demo';
    final ids = <String>{};
    final items = <NearbyNotice>[];
    for (final row in json['items']) {
      if (row is! Map<String, dynamic>)
        throw const FormatException('소식 형식을 확인해주세요.');
      final item = NearbyNotice.parse(row, live: !demo);
      if (!ids.add(item.id)) throw const FormatException('소식 ID가 중복됐어요.');
      items.add(item);
    }
    return NearbyFeed(items, demo, updated);
  }
}

class NearbyRepository {
  static final _cache = Expando<NearbyFeed>();
  final BrowserServices browser;
  NearbyFeed? get cached => _cache[browser];
  NearbyRepository(this.browser);
  Future<NearbyFeed> load() async {
    _cache[browser] = null;
    Future<String> get(String url) async {
      final response = await browser.request(url);
      if (response.status != 200)
        throw StateError('지도 자료 응답 ${response.status}');
      if (response.body.length > 1000000)
        throw const FormatException('지도 자료가 너무 커요.');
      return response.body;
    }

    final config = jsonDecode(await get('nearby-config.json'));
    if (config is! Map || config['url'] is! String) {
      throw const FormatException('지도 자료 연결 설정을 확인해주세요.');
    }
    final source = Uri.tryParse(config['url']);
    if (source == null ||
        source.toString().isEmpty ||
        source.hasFragment ||
        (source.hasScheme && !['https', 'http'].contains(source.scheme)) ||
        (!source.hasScheme && source.hasAuthority) ||
        source.userInfo.isNotEmpty) {
      throw const FormatException('지도 자료 주소를 확인해주세요.');
    }
    final result = NearbyFeed.parse(await get(source.toString()));
    _cache[browser] = result;
    return result;
  }
}
