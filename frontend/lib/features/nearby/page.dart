import 'package:material_ui/material_ui.dart';

import '../../app/app_context.dart';
import '../../core/ui.dart';
import '../../data/models.dart';
import '../../platform/nearby_map.dart';
import 'data.dart';

class NearbyPage extends StatefulWidget {
  final String? selectedId;
  const NearbyPage({super.key, this.selectedId});
  @override
  State<NearbyPage> createState() => _NearbyPageState();
}

class _NearbyPageState extends State<NearbyPage> {
  NearbyFeed? feed;
  bool busy = false, started = false;
  String? error;
  String category = 'all';
  Map<String, double>? bounds;
  int generation = 0;
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!started) {
      started = true;
      load();
    }
  }

  Future<void> load() async {
    final current = ++generation;
    final browser = AppContext.of(context).state.browser;
    setState(() {
      busy = true;
      error = null;
      feed = null;
    });
    try {
      final result = await NearbyRepository(browser).load();
      if (mounted && generation == current) setState(() => feed = result);
    } catch (_) {
      if (mounted && generation == current)
        setState(() => error = '주변 소식을 불러오지 못했어요. 연결과 자료 형식을 확인한 뒤 다시 시도해주세요.');
    } finally {
      if (mounted && generation == current) setState(() => busy = false);
    }
  }

  void select(String? id) =>
      AppContext.of(context).go('/nearby', id == null ? {} : {'id': id});
  bool visible(NearbyNotice item) =>
      bounds == null ||
      (item.lat >= bounds!['south']! &&
          item.lat <= bounds!['north']! &&
          item.lng >= bounds!['west']! &&
          item.lng <= bounds!['east']!);
  @override
  Widget build(BuildContext context) {
    final small = mobile(context);
    final items = (feed?.items ?? <NearbyNotice>[])
        .where((item) => category == 'all' || item.category == category)
        .toList();
    final shown = items.where(visible).toList();
    final selected = items
        .where((item) => item.id == widget.selectedId)
        .firstOrNull;
    final map = ClipRRect(
      borderRadius: BorderRadius.circular(18),
      child: SizedBox(
        height: small ? 350 : 540,
        child: nearbyMapView(
          notices: items.map((item) => item.marker).toList(),
          selectedId: selected?.id,
          onSelect: select,
          onBounds: (value) {
            if (mounted) setState(() => bounds = value);
          },
        ),
      ),
    );
    final list = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                '지도 안 소식 ${shown.length}건',
                style: type(18, weight: FontWeight.w600),
              ),
            ),
            UiButton(
              busy ? '조회 중' : '새로고침',
              quiet: true,
              onTap: busy ? null : load,
            ),
          ],
        ),
        if (feed != null)
          Text(
            '${feed!.demo ? '예시 소식' : '공개 소식'} · 갱신 ${feed!.updatedAt.toUtc().toIso8601String().replaceFirst('T', ' ').substring(0, 16)} UTC',
            style: type(11, color: Palette.sub),
          ),
        const SizedBox(height: 12),
        if (busy) const LinearProgressIndicator(color: Palette.orange),
        if (error != null)
          EmptyPanel('소식을 불러오지 못했어요', error!, action: '다시 조회', onTap: load),
        if (selected != null) _card(selected, expanded: true),
        if (!busy && error == null && shown.isEmpty)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 24),
            child: Text('이 지도 영역에는 소식이 없어요. 지도를 이동하거나 전체 소식을 눌러보세요.'),
          ),
        for (final item in shown.where((item) => item.id != selected?.id))
          _card(item),
      ],
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                '내 주변에서 무슨 일이?',
                style: type(
                  small ? 25 : 32,
                  weight: FontWeight.w700,
                  spacing: -1,
                ),
              ),
            ),
            if (feed?.demo == true)
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: 10,
                  vertical: 5,
                ),
                decoration: BoxDecoration(
                  color: Palette.soft,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text('예시', style: type(11, color: Palette.orange)),
              ),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          '지도를 움직여 동네 소식을 찾아보세요. 내 주변 보기를 누르면 현재 위치로 이동해요.',
          style: type(13, color: Palette.sub),
        ),
        const SizedBox(height: 20),
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: [
              for (final entry in categories.entries)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(
                      entry.value,
                      style: type(
                        12,
                        color: category == entry.key
                            ? Palette.orange
                            : Palette.sub,
                      ),
                    ),
                    selected: category == entry.key,
                    selectedColor: Palette.soft,
                    onSelected: (_) {
                      setState(() => category = entry.key);
                      if (widget.selectedId != null) select(null);
                    },
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        if (small) ...[
          map,
          const SizedBox(height: 20),
          list,
        ] else
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(flex: 3, child: map),
              const SizedBox(width: 28),
              Expanded(flex: 2, child: list),
            ],
          ),
      ],
    );
  }

  Widget _card(NearbyNotice item, {bool expanded = false}) => Container(
    margin: const EdgeInsets.only(bottom: 12),
    decoration: BoxDecoration(
      color: expanded ? Palette.soft : Colors.white,
      border: Border.all(color: expanded ? Palette.orange : Palette.line),
      borderRadius: BorderRadius.circular(14),
    ),
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  categories[item.category]!,
                  style: type(11, color: Palette.orange),
                ),
              ),
              if (item.status == 'cancelled')
                Text('취소', style: type(11, color: Palette.red)),
            ],
          ),
          const SizedBox(height: 6),
          Text(item.title, style: type(16, weight: FontWeight.w600)),
          const SizedBox(height: 7),
          Text(item.address, style: type(12, color: Palette.sub)),
          Text(
            dateRange(item.start, item.end),
            style: type(12, color: Palette.sub),
          ),
          if (expanded) ...[
            const SizedBox(height: 12),
            Text(item.description, style: type(13)),
            if (item.sourceUrl != null)
              UiButton(
                '원문 보기',
                quiet: true,
                icon: 'external',
                onTap: () {
                  if (!AppContext.of(context).state.browser
                      .open(item.sourceUrl!))
                    AppContext.of(context).toast('원문을 열지 못했어요.');
                },
              ),
          ],
          UiButton(
            expanded ? '선택 해제' : '지도에서 자세히 보기',
            quiet: true,
            icon: expanded ? 'close' : 'pin',
            onTap: () => select(expanded ? null : item.id),
          ),
        ],
      ),
    ),
  );
}
