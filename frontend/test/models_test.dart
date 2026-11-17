import 'package:flutter_test/flutter_test.dart';
import 'package:yeogi_it/data/models.dart';
import 'package:yeogi_it/app/router.dart';

import 'support.dart';

void main() {
  final data = prototype();
  List<Notice> query(NoticeQuery f) =>
      filterNotices(data.items, f, const Preferences(), data.anchor);
  test('원본 ID 16건과 예시 기준일을 보존한다', () {
    expect(dateOnly('2026-02-30'), isNull);
    expect(data.items.length, 16);
    expect(data.items.map((n) => n.id).toSet().length, 16);
    expect(data.anchor, DateTime.utc(2026, 11, 16));
    expect(data.provinces.length, 17);
  });
  test('필터 AND와 검색 기대 건수', () {
    expect(
      query(const NoticeQuery(category: 'education', free: true, open: true)),
      hasLength(2),
    );
    expect(query(const NoticeQuery(q: '도예')), hasLength(1));
    expect(query(const NoticeQuery(q: 'zz-no-such-notice-987')), isEmpty);
  });
  test('비용 미상은 무료가 아니며 취소·접수 종료는 모집 중에서 제외한다', () {
    expect(
      query(const NoticeQuery(free: true)).every((n) => n.cost == 0),
      isTrue,
    );
    expect(
      query(const NoticeQuery(open: true))
          .any((n) => ['evt-cancel', 'sup-closed'].contains(n.id)),
      isFalse,
    );
    const missingStart = Notice(
      id: 'x',
      category: 'education',
      title: '기간 미상',
      cost: null,
      deadline: '2026-11-20',
    );
    expect(missingStart.isOpen(data.anchor), isFalse);
    expect(missingStart.status(data.anchor), '신청 기간 확인 필요');
  });
  test('동네는 해당 동네와 시 전체만 포함한다', () {
    final result = query(const NoticeQuery(district: '공도읍'));
    expect(
      result.every((n) => n.district == '공도읍' || n.district == citywide),
      isTrue,
    );
    expect(result.any((n) => n.district == citywide), isTrue);
  });
  test('이번 주는 장기 행사와 월·연 경계의 진행 구간 교집합이다', () {
    const spanning = Notice(
      id: 'span',
      category: 'event',
      title: '장기 행사',
      start: '2026-12-20',
      end: '2027-01-05',
    );
    const after = Notice(
      id: 'after',
      category: 'event',
      title: '다음 주',
      start: '2027-01-04',
      end: '2027-01-05',
    );
    final result = filterNotices(
      [spanning, after],
      const NoticeQuery(period: 'week'),
      const Preferences(),
      DateTime.utc(2027, 1, 1),
    );
    expect(result.map((n) => n.id), ['span']);
  });
  test('마감순은 미상과 취소를 뒤로 둔다', () {
    final result = filterNotices(
      const [
        Notice(id: 'unknown', category: 'event', title: '미상'),
        Notice(
          id: 'cancel',
          category: 'event',
          title: '취소',
          deadline: '2026-11-17',
          cancelled: true,
        ),
        Notice(
          id: 'known',
          category: 'event',
          title: '유효',
          deadline: '2026-11-20',
        ),
      ],
      const NoticeQuery(sort: 'deadline'),
      const Preferences(),
      data.anchor,
    );
    expect(result.map((n) => n.id), ['known', 'unknown', 'cancel']);
  });
  test('칩 해제와 초기화는 다른 조건을 보존한다', () {
    const query = NoticeQuery(
      category: 'education',
      q: '도예',
      free: true,
      open: true,
      district: '공도읍',
    );
    expect(query.copyWith(free: false).open, isTrue);
    expect(query.resetConditions().params, {'cat': 'education', 'q': '도예'});
  });
  test('잘못된 쿼리와 온보딩 단계는 정규화한다', () {
    final route = AppRoute.parse(
      Uri.parse('/list?cat=invalid&sort=invalid&free=true&period=invalid'),
    );
    expect(route.params, isEmpty);
    expect(AppRoute.parse(Uri.parse('/start?step=99')).params['step'], '5');
    expect(AppRoute.parse(Uri.parse('/start?step=oops')).params['step'], '0');
    expect(
      AppRoute.parse(Uri.parse('https://example.test/#/detail?id=edu-pottery'))
          .params['id'],
      'edu-pottery',
    );
  });
}
