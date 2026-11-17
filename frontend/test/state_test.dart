import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:yeogi_it/app/app_state.dart';
import 'package:yeogi_it/data/models.dart';

import 'support.dart';

void main() {
  test('설정과 저장은 재접속에 복원하고 데이터 모드별 ID를 분리한다', () async {
    final browser = FakeBrowser(), a = AppState(prototype(), FakeBrowser());
    final state = AppState(a.prototype, browser);
    await state.reload();
    state.savePreferences(
      const Preferences(onboarded: true, interests: ['education']),
    );
    state.toggleSaved(state.items.first);
    final restored = AppState(prototype(), browser);
    expect(restored.settings.onboarded, isTrue);
    expect(restored.settings.interests, ['education']);
    expect(restored.saved.keys, [state.items.first.id]);
    expect(AppState(prototype(), browser, mode: 'api').saved, isEmpty);
  });
  test('손상된 JSON·브라우저 저장 실패는 메모리 기본값으로 복구한다', () async {
    final browser = FakeBrowser()
      ..values['yeogi-settings-v2'] = '{broken'
      ..failWrites = true;
    final state = AppState(prototype(), browser);
    await state.reload();
    expect(state.storageFailed, isTrue);
    expect(state.settings.city, '안성시');
    state.toggleSaved(state.items.first);
    expect(state.saved, isNotEmpty);
    state.savePreferences(state.settings.copyWith(age: '20대'));
    expect(state.settings.age, '20대');
  });
  test('같은 origin의 v1 설정과 저장 ID를 마이그레이션한다', () {
    final browser = FakeBrowser()
      ..values['yeogi-settings-v1'] = jsonEncode({
        'onboarded': true,
        'interests': ['education', 'fake'],
      })
      ..values['yeogi-saved-v1'] = jsonEncode(['edu-pottery', 'missing-id']);
    final state = AppState(prototype(), browser);
    expect(state.settings.interests, ['education']);
    expect(state.saved.keys, ['edu-pottery']);
  });
  test('위치 요청은 명시적 호출 전 발생하지 않으며 중복을 막는다', () async {
    final browser = FakeBrowser(), state = AppState(prototype(), FakeBrowser());
    final app = AppState(state.prototype, browser);
    expect(browser.locationRequests, 0);
    final a = app.requestLocation(), b = app.requestLocation();
    expect(await a, isFalse);
    expect(await b, isFalse);
    expect(browser.locationRequests, 1);
    expect(app.locationBusy, isFalse);
  });
  test('저장본을 갱신할 때 snapshot과 revision 문맥을 보존한다', () {
    final state = AppState(prototype(), FakeBrowser(), mode: 'api');
    const n = Notice(
      id: 'event',
      category: 'event',
      title: '공개 자료',
      snapshotId: 'snapshot',
      revisionId: 'revision',
      synthetic: false,
    );
    state.refreshSaved(n);
    expect(state.saved['event'], {
      'snapshot_id': 'snapshot',
      'revision_id': 'revision',
    });
  });
  test('알 수 없는 모드는 예시로 대체하지 않는다', () async {
    final state = AppState(prototype(), FakeBrowser(), mode: 'invalid');
    await state.reload();
    expect(state.error?.code, 'INVALID_MODE');
    expect(state.items, isEmpty);
  });
}
