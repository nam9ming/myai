import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../../app/app_context.dart';
import '../../core/ui.dart';
import '../../data/models.dart';

String kstText(dynamic value) {
  if (value is! String) return '미기재';
  final d = DateTime.tryParse(value);
  if (d == null) return '미기재';
  if (value.length == 10) return value.replaceAll('-', '.');
  final kst = d.toUtc().add(const Duration(hours: 9));
  return '${kst.year}.${kst.month.toString().padLeft(2, '0')}.${kst.day.toString().padLeft(2, '0')} ${kst.hour.toString().padLeft(2, '0')}:${kst.minute.toString().padLeft(2, '0')} KST';
}

const _fieldLabels = {
  'title': '제목',
  'lifecycle': '공개 상태',
  'applicability': '적용 대상',
  'exceptions': '예외',
  'route_names': '노선',
  'stop_names': '정류장',
  'directions': '방향',
  'occurrences': '진행 일정',
  'locations': '장소',
  'date_start': '시작일',
  'date_end': '종료일',
  'time_start': '시작 시각',
  'time_end': '종료 시각',
  'name': '이름',
  'address': '주소',
};
String humanFact(dynamic value) {
  if (value == null) return '미기재 · 확인 필요';
  if (value is List)
    return value.isEmpty ? '없음 (명시됨)' : value.map(humanFact).join('\n');
  if (value is Map) {
    if (value.containsKey('value')) return humanFact(value['value']);
    final known = value.entries.where((e) => _fieldLabels.containsKey(e.key));
    return known.isEmpty
        ? '세부 변경 내용은 근거와 원문을 확인해주세요.'
        : known
              .map((e) => '${_fieldLabels[e.key]}: ${humanFact(e.value)}')
              .join('\n');
  }
  return switch (value.toString()) {
    'active' => '유효',
    'cancelled' => '취소',
    'uncertain' => '확인 필요',
    _ => value.toString(),
  };
}

List<Map<String, dynamic>> sourceRefs(Notice n) =>
    ((n.api?['source_refs'] as List?) ?? [])
        .map((j) => Map<String, dynamic>.from(j))
        .toList();
bool fixtureSource(Notice n, Map<String, dynamic> source) {
  final host = Uri.tryParse(source['url'] as String? ?? '')?.host ?? '';
  return n.synthetic ||
      source['is_fixture'] == true ||
      host == 'example.org' ||
      host.endsWith('.example.org');
}

Future<void> showSource(
  BuildContext context,
  Notice n, {
  Map<String, dynamic>? source,
  bool addressOnly = false,
}) async {
  final env = AppContext.of(context), refs = sourceRefs(n);
  final chosen = source ?? (refs.isEmpty ? <String, dynamic>{} : refs.first);
  final fixture = fixtureSource(n, chosen),
      raw = chosen['url'] as String?,
      uri = Uri.tryParse(raw ?? '');
  final valid =
      uri != null &&
      ['http', 'https'].contains(uri.scheme) &&
      uri.host.isNotEmpty;
  if (!fixture && valid && !addressOnly) {
    env.state.browser.open(raw!);
    env.toast('원문을 새 탭에서 열었어요. 열리지 않으면 원문 주소 확인·복사를 이용해주세요.');
    return;
  }
  await showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text(
        fixture
            ? '예시 소식 안내'
            : valid
            ? '원문 주소 확인'
            : '원문 미제공',
        style: type(19, weight: FontWeight.w600),
      ),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              fixture
                  ? '이 소식은 화면 체험을 위한 예시입니다. 실제 신청 원문을 제공하지 않아요.'
                  : valid
                  ? '원문은 외부 사이트에서 열립니다. 열리지 않으면 주소를 복사해 확인해주세요.'
                  : '공개된 원문 주소가 없습니다. 제공 기관과 확인 상태를 살펴주세요.',
              style: type(13, color: Palette.sub),
            ),
            if (!fixture && valid) ...[
              const SizedBox(height: 16),
              SelectableText(raw!, style: type(12)),
            ],
          ],
        ),
      ),
      actions: [
        if (!fixture && valid) ...[
          TextButton(
            onPressed: () async {
              try {
                await Clipboard.setData(ClipboardData(text: raw!));
                if (context.mounted) env.toast('원문 주소를 복사했어요.');
              } catch (_) {
                if (context.mounted)
                  env.toast('복사하지 못했어요. 표시된 주소를 선택해 복사해주세요.');
              }
            },
            child: const Text('주소 복사'),
          ),
          TextButton(
            onPressed: () => env.state.browser.open(raw!),
            child: const Text('새 탭에서 열기'),
          ),
        ],
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('닫기'),
        ),
      ],
    ),
  );
}

class NoticeDetailPage extends StatefulWidget {
  final String id;
  final String? snapshot;
  const NoticeDetailPage({super.key, required this.id, this.snapshot});
  @override
  State<NoticeDetailPage> createState() => _NoticeDetailPageState();
}

class _NoticeDetailPageState extends State<NoticeDetailPage> {
  Future<Notice?>? pending;
  final contentKey = GlobalKey(), summaryKey = GlobalKey();
  RenderBox? contentBox, summaryBox;
  @override
  void didUpdateWidget(NoticeDetailPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.id != oldWidget.id || widget.snapshot != oldWidget.snapshot)
      pending = null;
  }

  @override
  Widget build(BuildContext context) {
    final env = AppContext.of(context), app = env.state;
    if (!app.isPrototype && app.loading && widget.snapshot == null)
      return const Center(child: CircularProgressIndicator());
    pending ??= app.detail(widget.id, snapshot: widget.snapshot);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        UiButton('목록으로', quiet: true, icon: 'left', onTap: env.back),
        const SizedBox(height: 18),
        FutureBuilder<Notice?>(
          future: pending,
          builder: (context, result) {
            if (result.connectionState != ConnectionState.done)
              return const Padding(
                padding: EdgeInsets.all(60),
                child: Center(
                  child: CircularProgressIndicator(
                    semanticsLabel: '상세를 불러오는 중',
                  ),
                ),
              );
            if (result.hasError) {
              final error = result.error is ApiFailure
                  ? result.error as ApiFailure
                  : const ApiFailure('PROTOCOL_ERROR', '상세 응답을 읽지 못했어요.');
              return ApiErrorPanel(
                error,
                onRetry: () {
                  app.retryDetail(widget.id, snapshot: widget.snapshot);
                  setState(() => pending = null);
                },
                onRefresh: () async {
                  await app.reload();
                  if (context.mounted)
                    env.go('/detail', {
                      'id': widget.id,
                      if (error.currentSnapshotId != null)
                        'snapshot_id': error.currentSnapshotId!,
                    });
                },
              );
            }
            final n = result.data;
            if (n == null)
              return EmptyPanel(
                '소식을 찾을 수 없어요.',
                '주소가 잘못되었거나 공개되지 않은 소식이에요.',
                action: '목록으로',
                onTap: () => env.go('/list'),
              );
            final summary = KeyedSubtree(
              key: summaryKey,
              child: _summary(context, n),
            );
            final body = KeyedSubtree(
              key: contentKey,
              child: _body(context, n),
            );
            if (mobile(context))
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [summary, const SizedBox(height: 20), body],
              );
            // 재배치 중 비활성화된 요소를 읽지 않도록 레이아웃 이후 참조한다.
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (!mounted) return;
              final left = contentKey.currentContext?.findRenderObject();
              final right = summaryKey.currentContext?.findRenderObject();
              contentBox = left is RenderBox ? left : null;
              summaryBox = right is RenderBox ? right : null;
            });
            final position = Scrollable.of(context).position;
            return Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(child: body),
                SizedBox(
                  width: MediaQuery.sizeOf(context).width <= 1020 ? 28 : 48,
                ),
                SizedBox(
                  width: MediaQuery.sizeOf(context).width <= 1020 ? 300 : 360,
                  child: ListenableBuilder(
                    listenable: position,
                    builder: (_, child) {
                      final leftBox = contentBox, rightBox = summaryBox;
                      final left =
                              leftBox != null &&
                                  leftBox.attached &&
                                  leftBox.hasSize
                              ? leftBox.size.height
                              : 0.0,
                          right =
                              rightBox != null &&
                                  rightBox.attached &&
                                  rightBox.hasSize
                              ? rightBox.size.height
                              : 0.0;
                      final offset = (position.pixels - 60).clamp(
                        0.0,
                        math.max(0, left - right),
                      );
                      return Transform.translate(
                        offset: Offset(0, offset.toDouble()),
                        child: child,
                      );
                    },
                    child: summary,
                  ),
                ),
              ],
            );
          },
        ),
      ],
    );
  }

  Widget _summary(BuildContext context, Notice n) {
    final env = AppContext.of(context), saved = env.state.saved[n.id];
    final outdated =
        saved != null &&
        n.snapshotId != null &&
        saved['snapshot_id'] != n.snapshotId;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: 8,
          runSpacing: 6,
          children: [
            Text(
              categories[n.category] ?? '공개 소식',
              style: type(12, color: Palette.green, weight: FontWeight.w500),
            ),
            NoticeBadge(n),
            if (n.synthetic) Text('예시 자료', style: type(11, color: Palette.sub)),
          ],
        ),
        const SizedBox(height: 14),
        Text(
          n.title,
          style: type(
            mobile(context) ? 24 : 27,
            weight: FontWeight.w600,
            height: 1.5,
            spacing: -1.1,
          ),
        ),
        const SizedBox(height: 12),
        Text(
          '${n.agency} · ${n.district}',
          style: type(12, color: Palette.sub),
        ),
        const SizedBox(height: 20),
        _fact(
          '신청 기간',
          n.applyStart == null && n.deadline == null
              ? '신청 기간 미기재'
              : dateRange(n.applyStart, n.deadline),
        ),
        _fact('진행 기간', dateRange(n.start, n.end)),
        if (n.hours != null) _fact('진행 시간', n.hours!),
        _fact('장소', n.place ?? '장소 확인 필요'),
        _fact('대상', n.target),
        _fact('비용', n.costLabel),
        if (n.classification != null)
          _fact('조건 조회', switch (n.classification) {
            'candidate' => '시간·거리 조건이 맞는 후보',
            'needs_check' => '추가 확인 필요',
            'cancelled' => '취소',
            _ => '계산 결과 확인 필요',
          }),
        if (n.api != null) ...[
          _fact(
            '거리',
            n.api!['distance_m'] == null
                ? '계산 결과 미제공'
                : '${n.api!['distance_m']}m · 기준: ${_distanceBasis(n.api!['distance_basis'])}',
          ),
          _fact(
            '시간 중첩',
            n.api!['time_overlap_minutes'] == null
                ? '계산 결과 미제공'
                : '${n.api!['time_overlap_minutes']}분',
          ),
        ],
        if (outdated)
          Container(
            padding: const EdgeInsets.all(12),
            color: Palette.soft,
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '저장한 뒤 공개본이 바뀌었어요. 현재 내용을 확인한 뒤 저장 정보를 갱신할 수 있어요.',
                  style: type(12),
                ),
                UiButton(
                  '저장 정보 갱신',
                  quiet: true,
                  onTap: () {
                    env.state.refreshSaved(n);
                    env.toast('현재 공개본으로 저장 정보를 갱신했어요.');
                  },
                ),
              ],
            ),
          ),
        if (!mobile(context)) ...[
          const SizedBox(height: 15),
          _actions(context, n),
        ],
        const SizedBox(height: 13),
        Text(
          n.synthetic ? '실제 신청 원문이 없는 예시 정보입니다.' : '신청 자격과 최신 일정은 원문에서 확인해주세요.',
          style: type(11, color: Palette.sub),
        ),
        if (sourceRefs(n).any((s) => !fixtureSource(n, s)))
          UiButton(
            '원문 주소 확인·복사',
            quiet: true,
            icon: 'external',
            onTap: () => unawaited(showSource(context, n, addressOnly: true)),
          ),
      ],
    );
  }

  String _distanceBasis(dynamic v) => switch (v) {
    'point' => '기준 지점',
    'straight_line' => '직선 거리',
    null => '서버 제공 기준',
    _ => '서버 제공 기준',
  };
  Widget _fact(String label, String value) => Padding(
    padding: const EdgeInsets.only(bottom: 13),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 74,
          child: Text(label, style: type(12, color: Palette.sub)),
        ),
        Expanded(child: Text(value, style: type(13))),
      ],
    ),
  );
  Widget _heading(String text) => Padding(
    padding: const EdgeInsets.only(top: 28, bottom: 13),
    child: Text(text, style: type(18, weight: FontWeight.w600, spacing: -.5)),
  );
  Widget _body(BuildContext context, Notice n) {
    final raw = n.api;
    final occurrences = (raw?['occurrences'] as List?) ?? [];
    final locations = (raw?['locations'] as List?) ?? [];
    final history = (raw?['history'] as List?) ?? [];
    final fields = (raw?['field_values'] as Map?) ?? {};
    final refs = sourceRefs(n);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (n.poster != null)
          ClipRRect(
            borderRadius: BorderRadius.circular(13),
            child: AspectRatio(
              aspectRatio: 4 / 3,
              child: SvgPicture.asset(
                'assets/posters/${n.poster}',
                fit: BoxFit.contain,
                errorBuilder: (_, __, ___) =>
                    const Center(child: Text('포스터를 불러오지 못했어요.')),
              ),
            ),
          ),
        _heading('소식 안내'),
        SelectableText(
          n.description.isEmpty
              ? '공개된 일정과 대상·예외, 근거를 함께 확인해주세요.'
              : n.description,
          style: type(14, color: const Color(0xff50584a), height: 1.95),
        ),
        if (n.synthetic)
          Padding(
            padding: const EdgeInsets.only(top: 18),
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(17),
              decoration: const BoxDecoration(
                color: Color(0xfffaf7f0),
                border: Border(
                  left: BorderSide(color: Color(0xffe9cba7), width: 3),
                ),
              ),
              child: Text(
                '이 화면은 예시 자료입니다. 실제 사업·일정·신청 가능 여부를 보장하지 않습니다.',
                style: type(12, color: const Color(0xff70644f), height: 1.9),
              ),
            ),
          ),
        _heading(raw == null ? '신청 전에 확인해주세요' : '적용 대상과 예외'),
        if (raw == null)
          for (final text in n.conditions)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                '• $text',
                style: type(14, color: const Color(0xff50584a)),
              ),
            ),
        if (raw != null) ...[
          for (final key in [
            'applicability',
            'exceptions',
            'route_names',
            'stop_names',
            'directions',
          ])
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _fact(_fieldLabels[key]!, humanFact(raw[key])),
                if (fields[key] is Map &&
                    (fields[key] as Map)['reason'] != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: Text(
                      (fields[key] as Map)['reason'].toString(),
                      style: type(11, color: Palette.sub),
                    ),
                  ),
              ],
            ),
          _heading('공개된 진행 일정'),
          if (occurrences.isEmpty)
            Text('진행 일정 미기재', style: type(13, color: Palette.sub)),
          for (final o in occurrences)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(
                '${dateRange(o['date_start'], o['date_end'])}\n${o['time_start'] ?? '시각 미기재'} — ${o['time_end'] ?? '시각 미기재'}${o['end_day_offset'] == 1 ? ' (다음 날 종료)' : ''}',
                style: type(13),
              ),
            ),
          _heading('장소'),
          if (locations.isEmpty)
            Text('장소 정보 미기재', style: type(13, color: Palette.sub)),
          for (final l in locations)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(
                '${l['name'] ?? '장소명 미기재'}\n${l['address'] ?? '주소 미기재'}',
                style: type(13),
              ),
            ),
          if (raw['warnings'] != null &&
              raw['warnings'] is List &&
              (raw['warnings'] as List).isNotEmpty) ...[
            _heading('추가로 확인할 사항'),
            Text(
              humanFact(raw['warnings']),
              style: type(13, color: Palette.red),
            ),
          ],
        ],
        if (refs.isNotEmpty) ...[
          _heading('출처와 확인 시각'),
          for (final s in refs)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.only(bottom: 14),
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                border: Border.all(color: Palette.line),
                borderRadius: BorderRadius.circular(9),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    s['title'] as String? ?? '공개 원문',
                    style: type(14, weight: FontWeight.w500),
                  ),
                  Text(
                    s['publisher'] as String? ?? '기관 미기재',
                    style: type(12, color: Palette.sub),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    '게시일 ${kstText(s['published_date'])}\n원문 확인 ${kstText(s['last_verified_at'])}\n최근 확인 시도 ${kstText(s['latest_check_attempt_at'])}',
                    style: type(11, color: Palette.sub),
                  ),
                  Text(
                    s['check_result'] == 'verified'
                        ? '공개본에 기록된 원문 확인 상태: 확인됨'
                        : '공개본에 기록된 원문 확인 상태: 추가 확인 필요',
                    style: type(11, color: Palette.sub),
                  ),
                  if (s['current_last_verified_at'] != null)
                    Text(
                      '공개본 생성 시 확보한 확인 시각 ${kstText(s['current_last_verified_at'])}',
                      style: type(11, color: Palette.sub),
                    ),
                  UiButton(
                    fixtureSource(n, s) ? '예시 출처 안내' : '원문 보기',
                    quiet: true,
                    icon: 'external',
                    onTap: () => unawaited(showSource(context, n, source: s)),
                  ),
                ],
              ),
            ),
        ],
        if (n.change != null || history.isNotEmpty) ...[
          _heading('달라진 내용'),
          if (n.change != null)
            _history(
              n.change!['before'],
              n.change!['after'],
              dateLabel(n.change!['date']),
            ),
          for (final h in history) ...[
            Text(
              '${kstText(h['published_at'])} · ${h['action'] == 'rollback' ? '공개본 복구' : '공개 내용 변경'}',
              style: type(12, color: Palette.sub),
            ),
            for (final c in (h['changes'] as List? ?? []))
              _history(
                humanFact(c['before']),
                humanFact(c['after']),
                _fieldLabels[c['field']] ?? '공개 정보',
              ),
            for (final old in (h['before_source_refs'] as List? ?? []))
              UiButton(
                '이전 근거 출처',
                quiet: true,
                icon: 'external',
                onTap: () => unawaited(
                  showSource(
                    context,
                    n,
                    source: Map<String, dynamic>.from(old),
                  ),
                ),
              ),
            for (final e in (h['before_evidence'] as List? ?? []))
              SelectableText(
                '이전 근거: ${e['quote'] ?? '미기재'}',
                style: type(12, color: Palette.sub),
              ),
            for (final e in (h['evidence'] as List? ?? []))
              SelectableText(
                '변경 근거: ${e['quote'] ?? '미기재'}',
                style: type(12, color: Palette.sub),
              ),
            for (final s in (h['source_refs'] as List? ?? []))
              UiButton(
                '변경 근거 출처',
                quiet: true,
                icon: 'external',
                onTap: () => unawaited(
                  showSource(context, n, source: Map<String, dynamic>.from(s)),
                ),
              ),
          ],
        ],
      ],
    );
  }

  Widget _history(String before, String after, String label) => Container(
    width: double.infinity,
    margin: const EdgeInsets.only(bottom: 12),
    padding: const EdgeInsets.all(17),
    decoration: BoxDecoration(
      color: const Color(0xfff6f7f1),
      borderRadius: BorderRadius.circular(9),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: type(11, color: Palette.sub)),
        Text(
          before,
          style: type(
            13,
            color: Palette.sub,
          ).copyWith(decoration: TextDecoration.lineThrough),
        ),
        Text(after, style: type(13, weight: FontWeight.w500)),
      ],
    ),
  );
}

Widget _actions(BuildContext context, Notice n) => Row(
  children: [
    SaveButton(n),
    const SizedBox(width: 9),
    Expanded(
      child: UiButton(
        n.api != null && sourceRefs(n).isEmpty ? '원문 미제공' : '원문 보기',
        primary: true,
        icon: 'external',
        onTap: () => unawaited(showSource(context, n)),
      ),
    ),
  ],
);

class DetailActions extends StatelessWidget {
  final String id;
  final String? snapshot;
  const DetailActions({super.key, required this.id, this.snapshot});
  @override
  Widget build(BuildContext context) {
    final app = AppContext.of(context).state;
    if (!app.isPrototype && app.loading && snapshot == null)
      return const SizedBox.shrink();
    return FutureBuilder<Notice?>(
      future: app.detail(id, snapshot: snapshot),
      builder: (context, result) {
        if (result.data == null) return const SizedBox.shrink();
        return Container(
          decoration: const BoxDecoration(
            color: Colors.white,
            border: Border(top: BorderSide(color: Palette.line)),
          ),
          child: SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
              child: _actions(context, result.data!),
            ),
          ),
        );
      },
    );
  }
}
