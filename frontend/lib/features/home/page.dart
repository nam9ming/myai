import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../../app/app_context.dart';
import '../../core/ui.dart';
import '../../data/models.dart';

class UnsupportedRegion extends StatelessWidget {
  const UnsupportedRegion({super.key});
  @override
  Widget build(BuildContext context) {
    final env = AppContext.of(context);
    return EmptyPanel(
      '${env.state.settings.city} 소식은 준비 중이에요.',
      '현재 시제품은 안성시 예시 정보를 제공합니다. 다른 지역의 실제 소식으로 표시하지 않아요.',
      action: '안성시 예시 둘러보기',
      onTap: () {
        env.state.savePreferences(
          env.state.settings.copyWith(
            province: '경기도',
            city: '안성시',
            district: citywide,
          ),
        );
        env.go('/home');
      },
    );
  }
}

class FeedGate extends StatelessWidget {
  final Widget child;
  const FeedGate({super.key, required this.child});
  @override
  Widget build(BuildContext context) {
    final app = AppContext.of(context).state;
    if (app.settings.city != '안성시') return const UnsupportedRegion();
    if (app.loading)
      return const Padding(
        padding: EdgeInsets.all(50),
        child: Center(
          child: CircularProgressIndicator(semanticsLabel: '소식을 불러오는 중'),
        ),
      );
    if (app.error != null)
      return ApiErrorPanel(
        app.error!,
        onRetry: () => unawaited(app.reload()),
        onRefresh: () => unawaited(app.reload()),
      );
    return child;
  }
}

class HomePage extends StatelessWidget {
  const HomePage({super.key});
  @override
  Widget build(BuildContext context) {
    final env = AppContext.of(context), app = env.state;
    final local = filterNotices(
      app.items,
      app.isPrototype
          ? NoticeQuery(district: app.settings.district)
          : const NoticeQuery(),
      app.settings,
      app.day,
    );
    final features = local
        .where((n) => n.poster != null && !n.cancelled && !n.uncertain)
        .take(4)
        .toList();
    final support = filterNotices(
      local,
      const NoticeQuery(category: 'support', open: true, sort: 'deadline'),
      app.settings,
      app.day,
    ).take(3).toList();
    final changes = local
        .where((n) => n.change != null && !n.cancelled)
        .take(mobile(context) ? 2 : 3)
        .toList();
    final traffic = local
        .where((n) => n.category == 'traffic')
        .take(2)
        .toList();
    return FeedGate(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '우리 동네, 필요한 소식부터',
                      style: type(11, color: Palette.sub),
                    ),
                    const SizedBox(height: 7),
                    Text(
                      '${app.settings.city} 소식을 살펴보세요.',
                      style: type(
                        mobile(context) ? 23 : 27,
                        weight: FontWeight.w600,
                        spacing: -1,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      app.settings.interests.isEmpty
                          ? '배우고 싶은 것부터 챙겨야 할 지원까지, 한곳에서 확인해요.'
                          : '${app.settings.interests.map((c) => categories[c]).join(' · ')}에 관심 있으시군요. 관련 소식부터 모았어요.',
                      style: type(12, color: Palette.sub),
                    ),
                  ],
                ),
              ),
              if (!mobile(context))
                UiButton(
                  '관심 분야 바꾸기',
                  quiet: true,
                  icon: 'chevron',
                  onTap: () => env.go('/settings'),
                ),
            ],
          ),
          const SizedBox(height: 25),
          Container(
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
            decoration: BoxDecoration(
              color: const Color(0xfff8f8f4),
              borderRadius: BorderRadius.circular(9),
            ),
            child: Row(
              children: [
                const UiIcon('calendar', size: 17, color: Palette.sub),
                const SizedBox(width: 9),
                Expanded(
                  child: Text(
                    '신청 마감과 진행 일정을 나눠서 확인하세요.',
                    style: type(11, color: Palette.sub),
                  ),
                ),
                UiButton(
                  '7일 내 마감',
                  quiet: true,
                  icon: 'chevron',
                  onTap: () => env.go('/list', {
                    'period': 'deadline',
                    'open': '1',
                    'sort': 'deadline',
                  }),
                ),
              ],
            ),
          ),
          const SizedBox(height: 32),
          if (app.isPrototype) ...[
            SectionHeading(
              '가까운 곳에서 배우고, 즐겨요',
              description: '교육과 행사에서 새로운 일상을 발견해보세요.',
              action: '전체 보기',
              onTap: () => env.go('/list'),
            ),
            if (features.isNotEmpty)
              NoticeGrid(features, home: true)
            else
              EmptyPanel(
                '선택한 지역의 예시 소식이 없어요.',
                '지역을 안성시 전체로 바꿔보세요.',
                action: '지역 변경',
                onTap: () => unawaited(env.region()),
              ),
            const SizedBox(height: 42),
            LayoutBuilder(
              builder: (context, c) {
                final left = Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SectionHeading(
                      '신청 전에 챙겨보세요',
                      description: '대상과 접수 조건을 먼저 확인해요.',
                      action: '더보기',
                      onTap: () => env.go('/list', {
                        'cat': 'support',
                        'open': '1',
                        'sort': 'deadline',
                      }),
                    ),
                    if (support.isEmpty)
                      Text(
                        '현재 조건의 지원사업 예시가 없습니다.',
                        style: type(12, color: Palette.sub),
                      ),
                    for (final n in support) SupportRow(n),
                  ],
                );
                final right = Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(20),
                      decoration: BoxDecoration(
                        color: const Color(0xfff7f7f0),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              const UiIcon(
                                'bell',
                                size: 17,
                                color: Palette.green,
                              ),
                              const SizedBox(width: 8),
                              Text(
                                '달라진 소식',
                                style: type(16, weight: FontWeight.w600),
                              ),
                            ],
                          ),
                          const SizedBox(height: 12),
                          if (mobile(context))
                            Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                for (final n in changes)
                                  Expanded(child: _change(context, n)),
                              ],
                            )
                          else
                            for (final n in changes) _change(context, n),
                        ],
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      '신청 자격과 세부 사항은 원문 확인이 필요해요.\n맞춤 정렬이 신청 자격을 보장하지는 않아요.',
                      style: type(11, color: Palette.sub),
                    ),
                  ],
                );
                return mobile(context)
                    ? Column(
                        children: [left, const SizedBox(height: 28), right],
                      )
                    : Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Expanded(child: left),
                          SizedBox(
                            width: MediaQuery.sizeOf(context).width <= 1020
                                ? 24
                                : 40,
                          ),
                          SizedBox(
                            width: MediaQuery.sizeOf(context).width <= 1020
                                ? 270
                                : 310,
                            child: right,
                          ),
                        ],
                      );
              },
            ),
            const SizedBox(height: 40),
            SectionHeading(
              '이동 전에 확인해요',
              description: '공사 구간과 교통 변경 안내',
              action: '더보기',
              onTap: () => env.go('/list', {'cat': 'traffic'}),
            ),
            LayoutBuilder(
              builder: (context, c) => Wrap(
                spacing: 18,
                runSpacing: 12,
                children: [
                  for (final n in traffic)
                    SizedBox(
                      width: mobile(context)
                          ? c.maxWidth
                          : (c.maxWidth - 18) / 2,
                      child: SupportRow(n, traffic: true),
                    ),
                ],
              ),
            ),
          ] else ...[
            const SectionHeading(
              '공개 조회 결과',
              description: '고정 예시 조건의 후보 결과입니다. 시민 전체 목록과 구분해주세요.',
            ),
            NoticeGrid(local),
          ],
        ],
      ),
    );
  }

  Widget _change(BuildContext context, Notice n) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 3),
    child: Pressable(
      onTap: () => AppContext.of(context).go('/detail', {'id': n.id}),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${n.change!['kind']} · 예시',
            style: type(10, color: Palette.green),
          ),
          const SizedBox(height: 5),
          Text(n.title, style: type(12, weight: FontWeight.w600)),
          const SizedBox(height: 5),
          Text(
            n.change!['before'],
            style: type(
              11,
              color: Palette.sub,
            ).copyWith(decoration: TextDecoration.lineThrough),
          ),
          Text(n.change!['after'], style: type(11, weight: FontWeight.w500)),
        ],
      ),
    ),
  );
}

class SupportRow extends StatelessWidget {
  final Notice notice;
  final bool traffic;
  const SupportRow(this.notice, {super.key, this.traffic = false});
  @override
  Widget build(BuildContext context) {
    final env = AppContext.of(context);
    return Container(
      decoration: BoxDecoration(
        border: traffic
            ? Border.all(color: Palette.line)
            : const Border(bottom: BorderSide(color: Palette.line)),
        borderRadius: traffic ? BorderRadius.circular(10) : null,
      ),
      child: Pressable(
        onTap: () => env.go('/detail', {
          'id': notice.id,
          if (notice.snapshotId != null) 'snapshot_id': notice.snapshotId!,
        }),
        child: Padding(
          padding: EdgeInsets.symmetric(
            vertical: 18,
            horizontal: traffic ? 18 : 0,
          ),
          child: Row(
            children: [
              if (traffic || !mobile(context)) ...[
                UiIcon(
                  traffic ? 'traffic' : 'gift',
                  size: 24,
                  color: Palette.green,
                ),
                const SizedBox(width: 15),
              ],
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      notice.title,
                      style: type(14, weight: FontWeight.w600),
                    ),
                    const SizedBox(height: 5),
                    Text(
                      '${notice.district} · ${traffic ? dateRange(notice.start, notice.end) : notice.target}',
                      style: type(11, color: Palette.sub),
                    ),
                    if (traffic && notice.hours != null)
                      Text(notice.hours!, style: type(11, color: Palette.sub)),
                  ],
                ),
              ),
              if (!traffic) ...[
                const SizedBox(width: 10),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    NoticeBadge(notice),
                    if (notice.deadline != null) ...[
                      const SizedBox(height: 4),
                      Text(
                        '${dateLabel(notice.deadline)} 마감',
                        style: type(11, color: Palette.sub),
                      ),
                    ],
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
