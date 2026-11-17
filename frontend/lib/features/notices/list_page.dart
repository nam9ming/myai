import 'package:material_ui/material_ui.dart';

import '../../app/app_context.dart';
import '../../core/ui.dart';
import '../../data/models.dart';
import '../dialogs.dart';
import '../home/page.dart';

class NoticeListPage extends StatefulWidget {
  final NoticeQuery query;
  final bool search;
  const NoticeListPage({super.key, required this.query, this.search = false});
  @override
  State<NoticeListPage> createState() => _NoticeListPageState();
}

class _NoticeListPageState extends State<NoticeListPage> {
  late final TextEditingController input = TextEditingController(
    text: widget.query.q,
  );
  @override
  void didUpdateWidget(NoticeListPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.query.q != widget.query.q) input.text = widget.query.q;
  }

  @override
  void dispose() {
    input.dispose();
    super.dispose();
  }

  void _apply(NoticeQuery query) =>
      AppContext.of(context)
          .go(widget.search ? '/search' : '/list', query.params);
  @override
  Widget build(BuildContext context) {
    final env = AppContext.of(context), app = env.state;
    final f = app.prototype.districts.contains(widget.query.district)
        ? widget.query
        : widget.query.copyWith(district: citywide);
    final items = filterNotices(app.items, f, app.settings, app.day);
    final beforeSearch =
        widget.search &&
        f.q.isEmpty &&
        !f.free &&
        !f.open &&
        f.period == 'all' &&
        f.category == 'all';
    final unsupported =
        !app.isPrototype &&
        (['education', 'support', 'life'].contains(f.category) ||
            f.free ||
            f.open ||
            f.period != 'all' ||
            f.q.isNotEmpty ||
            f.district != citywide ||
            f.sort == 'deadline');
    final chips = <(String, NoticeQuery)>[
      if (f.category != 'all')
        (categories[f.category]!, f.copyWith(category: 'all')),
      if (f.q.isNotEmpty) ('검색: ${f.q}', f.copyWith(q: '')),
      if (f.free) ('무료', f.copyWith(free: false)),
      if (f.open) ('모집 중', f.copyWith(open: false)),
      if (f.period != 'all')
        (f.period == 'week' ? '이번 주 진행' : '7일 내 마감', f.copyWith(period: 'all')),
      if (f.district != citywide) (f.district, f.copyWith(district: citywide)),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeading(
          widget.search
              ? '어떤 소식이 궁금하세요?'
              : categories[f.category] == '전체'
              ? '우리 동네 모든 소식'
              : categories[f.category]!,
          description: widget.search
              ? '지역과 관심사에 맞는 소식을 검색해보세요.'
              : '관심 있는 소식을 찾아 신청 조건과 일정을 확인해요.',
        ),
        if (widget.search || f.q.isNotEmpty) ...[
          TextField(
            controller: input,
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
              labelText: '소식 검색',
              hintText: '소식, 기관, 대상, 동네로 검색',
              prefixIcon: const Padding(
                padding: EdgeInsets.all(14),
                child: UiIcon('search'),
              ),
              suffixIcon: IconAction(
                'arrow',
                '검색 실행',
                onTap: () => _apply(f.copyWith(q: input.text.trim())),
              ),
            ),
            onSubmitted: (v) => _apply(f.copyWith(q: v.trim())),
          ),
          const SizedBox(height: 20),
        ],
        if (beforeSearch) ...[
          Text('이런 소식은 어떠세요?', style: type(14, weight: FontWeight.w600)),
          const SizedBox(height: 14),
          Wrap(
            spacing: 9,
            runSpacing: 9,
            children: [
              for (final word in ['청년', '무료', '도예', '공도읍', '공사'])
                UiButton(
                  word,
                  onTap: () => _apply(
                    word == '무료' ? f.copyWith(free: true) : f.copyWith(q: word),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 36),
        ] else ...[
          Wrap(
            spacing: 10,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              UiButton(
                '필터',
                icon: 'filter',
                onTap: () async {
                  final result = await showFilters(context, app, f);
                  if (result != null && context.mounted) _apply(result);
                },
              ),
              UiButton(
                '모집 중',
                selected: f.open,
                onTap: () => _apply(f.copyWith(open: !f.open)),
              ),
              UiButton(
                '무료',
                selected: f.free,
                onTap: () => _apply(f.copyWith(free: !f.free)),
              ),
              SizedBox(
                width: 145,
                child: DropdownButtonFormField<String>(
                  initialValue: f.sort,
                  key: ValueKey(f.sort),
                  isExpanded: true,
                  decoration: const InputDecoration(
                    labelText: '정렬',
                    contentPadding: EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 10,
                    ),
                  ),
                  items: [
                    for (final e in const {
                      'relevant': '관련순',
                      'deadline': '마감순',
                      'start': '시작일순',
                    }.entries)
                      DropdownMenuItem(
                        value: e.key,
                        child: Text(e.value, style: type(12)),
                      ),
                  ],
                  onChanged: (v) => _apply(f.copyWith(sort: v)),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          if (chips.isNotEmpty) ...[
            Wrap(
              spacing: 8,
              runSpacing: 5,
              children: [
                for (final chip in chips)
                  UiButton(
                    chip.$1,
                    quiet: true,
                    icon: 'close',
                    onTap: () => _apply(chip.$2),
                  ),
                UiButton(
                  '조건 초기화',
                  quiet: true,
                  onTap: () => _apply(f.resetConditions()),
                ),
              ],
            ),
            const SizedBox(height: 16),
          ],
          if (unsupported)
            const ApiErrorPanel(
              ApiFailure(
                'UNSUPPORTED_FILTER',
                '현재 공개 API는 이 분야·검색·신청 조건을 지원하지 않아요. 조건을 해제하거나 지원되는 공개 정보 범위를 확인해주세요.',
              ),
            )
          else
            FeedGate(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Semantics(
                    liveRegion: true,
                    child: Text(
                      app.isPrototype
                          ? '총 ${items.length}개의 소식'
                          : '현재 불러온 ${items.length}건 내 결과',
                      style: type(12, color: Palette.sub),
                    ),
                  ),
                  const SizedBox(height: 16),
                  if (items.isEmpty)
                    EmptyPanel(
                      '조건에 맞는 소식이 없어요.',
                      '검색어나 필터를 바꿔 다시 살펴보세요.',
                      action: '조건 초기화',
                      onTap: () => _apply(f.resetConditions().copyWith(q: '')),
                    )
                  else
                    NoticeGrid(items),
                ],
              ),
            ),
        ],
      ],
    );
  }
}
