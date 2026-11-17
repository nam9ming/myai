import 'dart:convert';

const categories = <String, String>{
  'all': '전체',
  'education': '교육·배움',
  'support': '지원·혜택',
  'event': '행사·문화',
  'traffic': '공사·교통',
  'life': '생활정보',
};
const ages = ['10대', '20대', '30대', '40대', '50대', '60대 이상', '선택 안 함'];
const genders = ['여성', '남성', '선택 안 함'];
const citywide = '안성시 전체';

DateTime? dateOnly(String? value) {
  if (value == null || value.length < 10) return null;
  final source = value.substring(0, 10);
  final date = DateTime.tryParse('${source}T00:00:00Z');
  return date != null && date.toIso8601String().substring(0, 10) == source
      ? date
      : null;
}

String dateLabel(String? value) {
  final d = dateOnly(value);
  return d == null
      ? '일정 확인 필요'
      : '${d.month}.${d.day.toString().padLeft(2, '0')}';
}

String dateRange(String? start, String? end) => start == null
    ? '일정 확인 필요'
    : end == null || start == end
    ? dateLabel(start)
    : '${dateLabel(start)} — ${dateLabel(end)}';

class Preferences {
  final bool onboarded, locationEnabled;
  final String province, city, district, age, gender;
  final List<String> interests;
  const Preferences({
    this.onboarded = false,
    this.province = '경기도',
    this.city = '안성시',
    this.district = citywide,
    this.age = '',
    this.gender = '',
    this.interests = const [],
    this.locationEnabled = false,
  });
  factory Preferences.fromJson(Map<String, dynamic> j) => Preferences(
    onboarded: j['onboarded'] == true,
    locationEnabled: j['locationEnabled'] == true,
    province: j['province'] is String ? j['province'] : '경기도',
    city: j['city'] is String ? j['city'] : '안성시',
    district: j['district'] is String ? j['district'] : citywide,
    age: ages.contains(j['age']) ? j['age'] : '',
    gender: genders.contains(j['gender']) ? j['gender'] : '',
    interests: (j['interests'] is List ? j['interests'] as List : [])
        .whereType<String>()
        .where((v) => categories.containsKey(v) && v != 'all')
        .toList(),
  );
  Preferences copyWith({
    bool? onboarded,
    bool? locationEnabled,
    String? province,
    String? city,
    String? district,
    String? age,
    String? gender,
    List<String>? interests,
  }) => Preferences(
    onboarded: onboarded ?? this.onboarded,
    locationEnabled: locationEnabled ?? this.locationEnabled,
    province: province ?? this.province,
    city: city ?? this.city,
    district: district ?? this.district,
    age: age ?? this.age,
    gender: gender ?? this.gender,
    interests: interests ?? List.of(this.interests),
  );
  Map<String, dynamic> toJson() => {
    'onboarded': onboarded,
    'province': province,
    'city': city,
    'district': district,
    'age': age,
    'gender': gender,
    'interests': interests,
    'locationEnabled': locationEnabled,
  };
}

class Notice {
  final String id, category, title, agency, district, target, description;
  final num? cost;
  final String? applyStart, deadline, start, end, hours, place, poster;
  final List<String> tags, age, conditions;
  final bool cancelled, uncertain, synthetic;
  final Map<String, dynamic>? change;
  final String? evidence, snapshotId, revisionId, classification;
  // 원본 DTO는 null/빈 배열·복수 근거·출처·버전 관계를 보존한다.
  final Map<String, dynamic>? api;
  const Notice({
    required this.id,
    required this.category,
    required this.title,
    this.agency = '',
    this.district = citywide,
    this.target = '대상 확인 필요',
    this.description = '',
    this.cost,
    this.applyStart,
    this.deadline,
    this.start,
    this.end,
    this.hours,
    this.place,
    this.poster,
    this.tags = const [],
    this.age = const [],
    this.conditions = const [],
    this.cancelled = false,
    this.uncertain = false,
    this.synthetic = true,
    this.change,
    this.evidence,
    this.snapshotId,
    this.revisionId,
    this.classification,
    this.api,
  });
  factory Notice.fromPrototype(Map<String, dynamic> j) => Notice(
    id: j['id'],
    category: j['cat'],
    title: j['title'],
    agency: j['agency'],
    district: j['district'],
    target: j['target'],
    description: j['description'],
    cost: j['cost'] as num?,
    applyStart: j['applyStart'],
    deadline: j['deadline'],
    start: j['start'],
    end: j['end'],
    hours: j['hours'],
    place: j['place'],
    poster: j['poster'],
    tags: List<String>.from(j['tags'] ?? []),
    age: List<String>.from(j['age'] ?? []),
    conditions: List<String>.from(j['conditions'] ?? []),
    cancelled: j['cancelled'] == true,
    uncertain: j['uncertain'] == true,
    change: j['change'],
    evidence: j['evidence'],
  );
  factory Notice.fromApi(
    Map<String, dynamic> j, {
    required String snapshot,
    required bool synthetic,
  }) {
    final types = (j['types'] as List? ?? []).whereType<String>().toList();
    final locations = j['locations'] as List? ?? [];
    final occurrences = j['occurrences'] as List? ?? [];
    final source = j['source_refs'] as List? ?? [];
    final first = occurrences.isEmpty
        ? <String, dynamic>{}
        : Map<String, dynamic>.from(occurrences.first);
    String? scalar(dynamic value) => value is String ? value : null;
    return Notice(
      id: j['event_id'] as String,
      title: j['title'] as String? ?? '제목 확인 필요',
      category: types.contains('construction') || types.contains('traffic')
          ? 'traffic'
          : types.contains('event')
          ? 'event'
          : 'unknown',
      agency: source.isEmpty
          ? '출처 확인 필요'
          : source.first['publisher'] as String? ?? '공개 자료',
      target: factText(j['applicability']),
      district: '지역 미기재',
      description: factText(j['summary'], fallback: ''),
      place: locations.isEmpty ? null : scalar(locations.first['name']),
      start: scalar(first['date_start']) ?? scalar(first['start_at']),
      end: scalar(first['date_end']) ?? scalar(first['end_at']),
      synthetic: synthetic,
      cancelled:
          j['lifecycle'] == 'cancelled' || j['classification'] == 'cancelled',
      uncertain:
          j['classification'] == 'needs_check' || j['lifecycle'] == 'uncertain',
      snapshotId: snapshot,
      revisionId: j['revision_id'],
      classification: j['classification'],
      api: jsonDecode(jsonEncode(j)) as Map<String, dynamic>,
    );
  }
  bool isOpen(DateTime day) {
    final a = dateOnly(applyStart), b = dateOnly(deadline);
    return !cancelled &&
        !uncertain &&
        a != null &&
        b != null &&
        !a.isAfter(day) &&
        !b.isBefore(day);
  }

  int? daysLeft(DateTime day) => dateOnly(deadline)?.difference(day).inDays;
  String get costLabel => cost == null
      ? '비용 확인 필요'
      : cost == 0
      ? '무료'
      : '${cost!.toInt()}원';
  String status(DateTime day) {
    if (cancelled) return '행사 취소';
    if (uncertain) return '확인 필요';
    if (deadline != null) {
      final n = daysLeft(day);
      if (n == null) return '확인 필요';
      if (n < 0) return '접수 종료';
      if (dateOnly(applyStart)?.isAfter(day) ?? false) return '접수 예정';
      if (applyStart == null) return '신청 기간 확인 필요';
      return n == 0
          ? '오늘 마감'
          : n <= 7
          ? 'D-$n'
          : '접수 중';
    }
    if (dateOnly(start)?.isAfter(day) ?? false) return '진행 예정';
    return '안내';
  }
}

String factText(dynamic value, {String fallback = '미기재 · 확인 필요'}) {
  if (value == null) return fallback;
  if (value is List)
    return value.isEmpty
        ? '없음 (명시됨)'
        : value.map((e) => factText(e)).join(' · ');
  if (value is Map) return jsonEncode(value);
  return value.toString();
}

class NoticeQuery {
  final String category, q, period, district, sort;
  final bool free, open;
  const NoticeQuery({
    this.category = 'all',
    this.q = '',
    this.period = 'all',
    this.district = citywide,
    this.sort = 'relevant',
    this.free = false,
    this.open = false,
  });
  factory NoticeQuery.fromParams(Map<String, String> p) => NoticeQuery(
    category: categories.containsKey(p['cat']) ? p['cat']! : 'all',
    q: (p['q'] ?? '').trim(),
    period: ['all', 'week', 'deadline'].contains(p['period'])
        ? p['period']!
        : 'all',
    district: p['district'] ?? citywide,
    sort: ['relevant', 'deadline', 'start'].contains(p['sort'])
        ? p['sort']!
        : 'relevant',
    free: p['free'] == '1',
    open: p['open'] == '1',
  );
  NoticeQuery copyWith({
    String? category,
    String? q,
    String? period,
    String? district,
    String? sort,
    bool? free,
    bool? open,
  }) => NoticeQuery(
    category: category ?? this.category,
    q: q ?? this.q,
    period: period ?? this.period,
    district: district ?? this.district,
    sort: sort ?? this.sort,
    free: free ?? this.free,
    open: open ?? this.open,
  );
  Map<String, String> get params => {
    if (category != 'all') 'cat': category,
    if (q.isNotEmpty) 'q': q,
    if (period != 'all') 'period': period,
    if (district != citywide) 'district': district,
    if (sort != 'relevant') 'sort': sort,
    if (free) 'free': '1',
    if (open) 'open': '1',
  };
  NoticeQuery resetConditions() => NoticeQuery(category: category, q: q);
}

List<Notice> filterNotices(
  Iterable<Notice> source,
  NoticeQuery f,
  Preferences settings,
  DateTime day,
) {
  final weekStart = day.subtract(Duration(days: day.weekday - 1));
  final weekEnd = weekStart.add(const Duration(days: 7));
  final query = f.q.toLowerCase();
  final result = source.where((n) {
    if (f.category != 'all' && n.category != f.category) return false;
    if (query.isNotEmpty &&
        ![
          n.title,
          n.agency,
          n.target,
          n.district,
          ...n.tags,
        ].join(' ').toLowerCase().contains(query))
      return false;
    if (f.free && n.cost != 0 || f.open && !n.isOpen(day)) return false;
    if (f.district != citywide &&
        n.district != citywide &&
        n.district != f.district)
      return false;
    if (f.period == 'deadline') {
      final left = n.daysLeft(day);
      if (left == null || left < 0 || left > 7) return false;
    }
    if (f.period == 'week') {
      final start = dateOnly(n.start),
          end = dateOnly(n.end) ?? dateOnly(n.start);
      if (start == null ||
          end == null ||
          !start.isBefore(weekEnd) ||
          end.isBefore(weekStart))
        return false;
    }
    return true;
  }).toList();
  int score(Notice n) =>
      (settings.interests.contains(n.category) ? 10 : 0) +
      (settings.age.isNotEmpty && n.age.contains(settings.age) ? 2 : 0) -
      (n.cancelled
          ? 100
          : n.uncertain
          ? 50
          : 0);
  result.sort((a, b) {
    if (f.sort == 'deadline') {
      final cancelled = (a.cancelled ? 1 : 0).compareTo(b.cancelled ? 1 : 0);
      if (cancelled != 0) return cancelled;
      return (a.deadline ?? '9999').compareTo(b.deadline ?? '9999');
    }
    if (f.sort == 'start')
      return (a.start ?? '9999').compareTo(b.start ?? '9999');
    return score(b).compareTo(score(a));
  });
  return result;
}

class ApiFailure implements Exception {
  final String code, message;
  final int? status;
  final bool retryable;
  final String? requestId, currentSnapshotId;
  final Map<String, dynamic> fieldErrors;
  const ApiFailure(
    this.code,
    this.message, {
    this.status,
    this.retryable = false,
    this.requestId,
    this.currentSnapshotId,
    this.fieldErrors = const {},
  });
  factory ApiFailure.fromResponse(int status, Map<String, dynamic> j) {
    final e = j['error'] as Map? ?? {};
    return ApiFailure(
      e['code'] as String? ?? 'HTTP_ERROR',
      e['message'] as String? ?? '요청을 처리하지 못했어요.',
      status: status,
      retryable: e['retryable'] == true,
      requestId: j['request_id'],
      currentSnapshotId: j['current_snapshot_id'],
      fieldErrors: e['field_errors'] is Map
          ? Map<String, dynamic>.from(e['field_errors'])
          : {},
    );
  }
  @override
  String toString() => '$code: $message';
}
