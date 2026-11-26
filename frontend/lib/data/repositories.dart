import 'dart:convert';

import 'package:flutter/services.dart';

import '../core/browser.dart';
import 'models.dart';
import 'municipality_boundaries.dart';

class PrototypeData {
  final List<Notice> items;
  final List<String> provinces, districts;
  final Map<String, List<String>> cities;
  final DateTime anchor;
  PrototypeData(Map<String, dynamic> json)
    : items = (json['items'] as List)
          .map((j) => Notice.fromPrototype(Map<String, dynamic>.from(j)))
          .toList(),
      provinces = List<String>.from(json['provinces']),
      districts = List<String>.from(json['districts']),
      cities = (json['cities'] as Map<String, dynamic>).map(
        (k, v) => MapEntry(k, [
          ...<String>{
            ...List<String>.from(v),
            ...?municipalityBoundaries[k]?.keys,
          },
        ]),
      ),
      anchor = dateOnly(json['anchor'])!;
  static Future<PrototypeData> load() async => PrototypeData(
    jsonDecode(await rootBundle.loadString('assets/prototype/notices.json')),
  );
}

abstract class NoticeRepository {
  Future<List<Notice>> loadFeed();
  Future<Notice?> detail(String id, {String? snapshot});
  DateTime get day;
  String? get snapshot;
}

class PrototypeFixtureRepository implements NoticeRepository {
  final PrototypeData data;
  PrototypeFixtureRepository(this.data);
  @override
  Future<List<Notice>> loadFeed() async => data.items;
  @override
  Future<Notice?> detail(String id, {String? snapshot}) async {
    for (final item in data.items) {
      if (item.id == id) return item;
    }
    return null;
  }

  @override
  DateTime get day => data.anchor;
  @override
  String? get snapshot => null;
}

class SpringNoticeRepository implements NoticeRepository {
  final BrowserServices browser;
  final String baseUrl;
  final bool fixture;
  Map<String, dynamic>? config;
  Map<String, dynamic>? matchEnvelope;
  List<Notice> feed = [];
  int _feedGeneration = 0;
  SpringNoticeRepository(
    this.browser, {
    required String baseUrl,
    this.fixture = false,
  }) : baseUrl = baseUrl.replaceFirst(RegExp(r'/$'), '');
  Future<Map<String, dynamic>> _request(
    String path, {
    Map<String, dynamic>? body,
  }) async {
    HttpResult response;
    try {
      response = await browser.request(
        '$baseUrl$path',
        method: body == null ? 'GET' : 'POST',
        body: body == null ? null : jsonEncode(body),
      );
    } catch (_) {
      throw const ApiFailure(
        'NETWORK_ERROR',
        '서버에 연결하지 못했어요. 주소와 네트워크를 확인해주세요.',
        retryable: true,
      );
    }
    Map<String, dynamic> json;
    try {
      json = jsonDecode(response.body) as Map<String, dynamic>;
    } catch (_) {
      throw ApiFailure(
        'PROTOCOL_ERROR',
        '서버 응답 형식을 확인할 수 없어요.',
        status: response.status,
      );
    }
    if (response.status < 200 || response.status >= 300)
      throw ApiFailure.fromResponse(response.status, json);
    if (json['schema_version'] != 'api-v1' ||
        json['snapshot_id'] is! String ||
        json['data'] is! Map) {
      throw const ApiFailure('PROTOCOL_ERROR', '지원하지 않는 API 형식이에요.');
    }
    return json;
  }

  @override
  Future<List<Notice>> loadFeed() async {
    final generation = ++_feedGeneration;
    final configuration = await _request('/config');
    final selectedSnapshot = configuration['snapshot_id'] as String;
    if (generation == _feedGeneration) config = configuration;
    if (!fixture)
      throw const ApiFailure(
        'UNSUPPORTED_CITIZEN_FEED',
        '현재 공개 API는 고정 지점·영업시간 조건을 사용해요. 시민용 지역 목록은 준비 중입니다.',
      );
    final request = jsonDecode(
      await rootBundle.loadString(
        'assets/prototype/backend-fixture-request.json',
      ),
    ) as Map<String, dynamic>;
    // 선택된 개발 모드에서만 계약의 고정 합성 조건을 사용한다.
    request['snapshot_id'] = selectedSnapshot;
    final result = await _request('/matches', body: request);
    if (result['snapshot_id'] != selectedSnapshot)
      throw const ApiFailure(
        'SNAPSHOT_MISMATCH',
        '목록과 설정의 공개본이 달라요. 다시 확인해주세요.',
      );
    final data = result['data'] as Map<String, dynamic>;
    final resultItems = (data['items'] as List)
        .map(
          (j) => Notice.fromApi(
            Map<String, dynamic>.from(j),
            snapshot: selectedSnapshot,
            synthetic: data['data_kind'] == 'synthetic',
          ),
        )
        .toList();
    if (generation == _feedGeneration) {
      feed = resultItems;
      matchEnvelope = result;
    }
    return resultItems;
  }

  @override
  Future<Notice?> detail(String id, {String? snapshot}) async {
    if (!RegExp(r'^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$')
        .hasMatch(id))
      return null;
    final selected = snapshot ?? this.snapshot;
    if (selected == null)
      throw const ApiFailure(
        'SNAPSHOT_REQUIRED',
        '상세를 확인할 공개본 정보가 필요해요. 목록에서 다시 열어주세요.',
      );
    final result = await _request(
      '/events/${Uri.encodeComponent(id)}?snapshot_id=${Uri.encodeQueryComponent(selected)}',
    );
    if (result['snapshot_id'] != selected)
      throw const ApiFailure('SNAPSHOT_MISMATCH', '선택한 공개본과 상세의 버전이 달라요.');
    final data = result['data'] as Map<String, dynamic>;
    final event = Map<String, dynamic>.from(data['event']);
    // 실제 상세는 사실 전용이다. 같은 공개본의 명시적 조회 결과만 결합한다.
    if (selected == this.snapshot) {
      for (final item in feed) {
        if (item.id == id && item.snapshotId == selected) {
          for (final key in [
            'classification',
            'reason_codes',
            'warnings',
            'distance_m',
            'distance_basis',
            'time_overlap_minutes',
            'matched_occurrence_ids',
          ]) {
            if (item.api!.containsKey(key)) event[key] = item.api![key];
          }
        }
      }
    }
    return Notice.fromApi(
      event,
      snapshot: selected,
      synthetic: data['data_kind'] == 'synthetic',
    );
  }

  @override
  String? get snapshot => config?['snapshot_id'];
  @override
  DateTime get day {
    final now = DateTime.tryParse(
      config?['data']?['server_now'] ?? config?['generated_at'] ?? '',
    );
    if (now == null) {
      final kst = DateTime.now().toUtc().add(const Duration(hours: 9));
      return DateTime.utc(kst.year, kst.month, kst.day);
    }
    final kst = now.toUtc().add(const Duration(hours: 9));
    return DateTime.utc(kst.year, kst.month, kst.day);
  }
}
