import 'dart:convert';

import 'package:flutter/foundation.dart';

import '../core/browser.dart';
import '../data/models.dart';
import '../data/repositories.dart';

class AppState extends ChangeNotifier {
  final BrowserServices browser;
  final PrototypeData prototype;
  final String mode;
  late final NoticeRepository repository;
  Preferences settings = const Preferences(), onboarding = const Preferences();
  Map<String, Map<String, dynamic>> saved = {};
  List<Notice> items = [];
  bool storageFailed = false, loading = true, locationBusy = false;
  ApiFailure? error;
  int _generation = 0;
  final Map<String, Future<Notice?>> _details = {};
  AppState(
    this.prototype,
    this.browser, {
    this.mode = 'prototype',
    String apiBaseUrl = '/api/v1',
  }) {
    repository = mode == 'prototype'
        ? PrototypeFixtureRepository(prototype)
        : SpringNoticeRepository(
            browser,
            baseUrl: apiBaseUrl,
            fixture: mode == 'backend-fixture',
          );
    _restore();
  }
  DateTime get day => repository.day;
  bool get isPrototype => mode == 'prototype';
  String get savedKey => 'yeogi-saved-v2-$mode';
  dynamic _read(String key) {
    try {
      final raw = browser.read(key);
      return raw == null ? null : jsonDecode(raw);
    } catch (_) {
      storageFailed = true;
      return null;
    }
  }

  void _restore() {
    final raw = _read('yeogi-settings-v2') ?? _read('yeogi-settings-v1');
    if (raw != null && raw is! Map<String, dynamic>) storageFailed = true;
    if (raw is Map<String, dynamic>)
      settings = Preferences.fromJson(
        raw['value'] is Map<String, dynamic> ? raw['value'] : raw,
      );
    if (!prototype.provinces.contains(settings.province))
      settings = settings.copyWith(province: '경기도', city: '안성시');
    if (!(prototype.cities[settings.province] ?? []).contains(settings.city))
      settings = settings.copyWith(
        city: prototype.cities[settings.province]?.first ?? '안성시',
      );
    if (!prototype.districts.contains(settings.district))
      settings = settings.copyWith(district: citywide);
    onboarding = settings.copyWith();
    final existing = _read(savedKey);
    if (existing != null &&
        (existing is! Map ||
            existing['version'] != 2 ||
            existing['items'] is! Map))
      storageFailed = true;
    if (existing is Map &&
        existing['version'] == 2 &&
        existing['items'] is Map) {
      for (final e in (existing['items'] as Map).entries) {
        if (e.key is String && e.value is Map)
          saved[e.key] = Map<String, dynamic>.from(e.value);
      }
    } else if (isPrototype) {
      final legacy = _read('yeogi-saved-v1');
      if (legacy is List)
        for (final id in legacy.whereType<String>()) {
          if (prototype.items.any((n) => n.id == id)) saved[id] = {};
        }
    }
  }

  void _write(String key, Object value) {
    try {
      browser.write(key, jsonEncode(value));
    } catch (_) {
      storageFailed = true;
    }
  }

  Future<void> reload() async {
    final generation = ++_generation;
    loading = true;
    error = null;
    if (!isPrototype) items = [];
    _details.clear();
    notifyListeners();
    try {
      if (!['prototype', 'backend-fixture', 'api'].contains(mode))
        throw const ApiFailure(
          'INVALID_MODE',
          '알 수 없는 데이터 모드입니다. 실행 설정을 확인해주세요.',
        );
      final result = await repository.loadFeed();
      if (generation != _generation) return;
      items = result;
    } on ApiFailure catch (e) {
      if (generation == _generation) error = e;
    } catch (_) {
      if (generation == _generation)
        error = const ApiFailure(
          'PROTOCOL_ERROR',
          '자료를 읽지 못했어요. 데이터 형식을 확인해주세요.',
        );
    }
    if (generation == _generation) {
      loading = false;
      notifyListeners();
    }
  }

  void savePreferences(Preferences value) {
    settings = value.copyWith();
    _write('yeogi-settings-v2', {'version': 2, 'value': settings.toJson()});
    notifyListeners();
  }

  void finishOnboarding({bool skipProfile = false}) {
    savePreferences(
      onboarding.copyWith(
        onboarded: true,
        age: skipProfile ? '' : null,
        gender: skipProfile ? '' : null,
        district: citywide,
      ),
    );
  }

  bool toggleSaved(Notice notice) {
    final adding = !saved.containsKey(notice.id);
    if (adding) {
      saved[notice.id] = {
        'snapshot_id': notice.snapshotId,
        'revision_id': notice.revisionId,
      };
    } else {
      saved.remove(notice.id);
    }
    _write(savedKey, {'version': 2, 'items': saved});
    notifyListeners();
    return adding;
  }

  Future<Notice?> detail(String id, {String? snapshot}) {
    final selected = snapshot ?? repository.snapshot;
    return _details.putIfAbsent(
      '$id:$selected',
      () => repository.detail(id, snapshot: selected),
    );
  }

  void retryDetail(String id, {String? snapshot}) {
    _details.remove('$id:${snapshot ?? repository.snapshot}');
  }

  void refreshSaved(Notice notice) {
    saved[notice.id] = {
      'snapshot_id': notice.snapshotId,
      'revision_id': notice.revisionId,
    };
    _write(savedKey, {'version': 2, 'items': saved});
    notifyListeners();
  }

  Future<bool> requestLocation() async {
    if (locationBusy) return false;
    locationBusy = true;
    notifyListeners();
    bool allowed;
    try {
      allowed = await browser.requestLocation();
    } catch (_) {
      allowed = false;
    }
    locationBusy = false;
    notifyListeners();
    return allowed;
  }
}
