import 'package:material_ui/material_ui.dart';
import 'package:flutter/gestures.dart';

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
  final sheet = DraggableScrollableController();
  @override
  void dispose() {
    sheet.dispose();
    super.dispose();
  }

  void resizeSheet(double size) {
    if (sheet.isAttached)
      sheet.animateTo(
        size,
        duration: Duration(milliseconds: reducedMotion(context) ? 1 : 220),
        curve: Curves.easeOutCubic,
      );
  }

  @override
  void didUpdateWidget(covariant NearbyPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.selectedId != widget.selectedId) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) resizeSheet(widget.selectedId == null ? .16 : .4);
      });
    }
  }

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
    final items = (feed?.items ?? <NearbyNotice>[])
        .where((item) => category == 'all' || item.category == category)
        .toList();
    final shown = items.where(visible).toList();
    final selected = items
        .where((item) => item.id == widget.selectedId)
        .firstOrNull;
    return LayoutBuilder(
      builder: (context, constraints) => Stack(
        children: [
          Positioned.fill(
            child: ListenableBuilder(
              listenable: sheet,
              builder: (context, _) => nearbyMapView(
                bottomInset:
                    constraints.maxHeight *
                    (sheet.isAttached
                        ? sheet.size
                        : (widget.selectedId == null ? .16 : .4)),
                notices: items.map((item) => item.marker).toList(),
                selectedId: selected?.id,
                onSelect: select,
                onBounds: (value) {
                  if (mounted) setState(() => bounds = value);
                },
              ),
            ),
          ),
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: SafeArea(
              bottom: false,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: mapTouchPanel(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8),
                        decoration: BoxDecoration(
                          color: Colors.white,
                          borderRadius: BorderRadius.circular(16),
                          boxShadow: const [
                            BoxShadow(color: Color(0x15000000), blurRadius: 16),
                          ],
                        ),
                        child: Row(
                          children: [
                            IconAction(
                              'left',
                              '홈으로 돌아가기',
                              onTap: () => AppContext.of(context).go('/home'),
                            ),
                            Expanded(
                              child: Text(
                                '내 주변',
                                style: type(19, weight: FontWeight.w700),
                              ),
                            ),
                            if (feed?.demo == true)
                              Text(
                                '예시',
                                style: type(11, color: Palette.orange),
                              ),
                            IconAction(
                              'clock',
                              busy ? '조회 중' : '새로고침',
                              onTap: busy ? null : load,
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 8),
                      SingleChildScrollView(
                        scrollDirection: Axis.horizontal,
                        child: Row(
                          children: [
                            for (final entry in categories.entries)
                              Padding(
                                padding: const EdgeInsets.only(right: 6),
                                child: ChoiceChip(
                                  label: Text(
                                    entry.value,
                                    style: type(
                                      12,
                                      color: category == entry.key
                                          ? Palette.orange
                                          : Palette.ink,
                                    ),
                                  ),
                                  backgroundColor: Colors.white,
                                  selectedColor: Palette.soft,
                                  selected: category == entry.key,
                                  onSelected: (_) {
                                    setState(() => category = entry.key);
                                    if (widget.selectedId != null) select(null);
                                  },
                                ),
                              ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
          DraggableScrollableSheet(
            controller: sheet,
            initialChildSize: widget.selectedId == null ? .16 : .4,
            minChildSize: .16,
            maxChildSize: .86,
            snap: true,
            snapSizes: const [.16, .4, .86],
            builder: (context, controller) => mapTouchPanel(
              child: Container(
                decoration: const BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
                  boxShadow: [
                    BoxShadow(
                      color: Color(0x22000000),
                      blurRadius: 24,
                      offset: Offset(0, -4),
                    ),
                  ],
                ),
                child: ScrollConfiguration(
                  behavior: ScrollConfiguration.of(context).copyWith(
                    dragDevices: {
                      ...ScrollConfiguration.of(context).dragDevices,
                      PointerDeviceKind.mouse,
                    },
                  ),
                  child: ListView(
                    controller: controller,
                    padding: EdgeInsets.fromLTRB(
                      20,
                      0,
                      20,
                      24 + MediaQuery.paddingOf(context).bottom,
                    ),
                    children: [
                      Center(
                        child: Container(
                          key: const ValueKey('nearby-sheet-handle'),
                          width: 44,
                          height: 5,
                          margin: const EdgeInsets.symmetric(vertical: 14),
                          decoration: BoxDecoration(
                            color: const Color(0xffd8dbd5),
                            borderRadius: BorderRadius.circular(6),
                          ),
                        ),
                      ),
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              selected == null
                                  ? '지도 안 소식 ${shown.length}건'
                                  : selected.title,
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: type(16, weight: FontWeight.w600),
                            ),
                          ),
                          if (selected != null)
                            IconAction(
                              'close',
                              '선택 해제',
                              onTap: () => select(null),
                            ),
                          UiButton(
                            '올려서 보기',
                            quiet: true,
                            onTap: () => resizeSheet(.86),
                          ),
                          UiButton(
                            '접기',
                            quiet: true,
                            onTap: () => resizeSheet(.16),
                          ),
                        ],
                      ),
                      if (busy)
                        const LinearProgressIndicator(color: Palette.orange),
                      if (error != null)
                        EmptyPanel(
                          '소식을 불러오지 못했어요',
                          error!,
                          action: '다시 조회',
                          onTap: load,
                        ),
                      if (selected != null)
                        _card(selected, expanded: true)
                      else ...[
                        Text(
                          '아이콘을 누르거나 시트를 위로 올려 소식을 확인하세요.',
                          style: type(12, color: Palette.sub),
                        ),
                        const SizedBox(height: 14),
                        if (!busy && error == null && shown.isEmpty)
                          Text(
                            '이 지도 영역에는 소식이 없어요. 지도를 이동해보세요.',
                            style: type(13, color: Palette.sub),
                          ),
                        for (final item in shown) _card(item),
                      ],
                      if (feed != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 12),
                          child: Text(
                            '${feed!.demo ? "예시 소식" : "공개 소식"} · 갱신 ${feed!.updatedAt.toUtc().toIso8601String().replaceFirst("T", " ").substring(0, 16)} UTC',
                            style: type(11, color: Palette.sub),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
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
