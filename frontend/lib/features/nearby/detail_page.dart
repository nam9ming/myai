import 'package:material_ui/material_ui.dart';

import '../../app/app_context.dart';
import '../../core/ui.dart';
import '../../data/models.dart';
import 'data.dart';

class NearbyDetailPage extends StatefulWidget {
  final String id;
  const NearbyDetailPage({super.key, required this.id});
  @override
  State<NearbyDetailPage> createState() => _NearbyDetailPageState();
}

class _NearbyDetailPageState extends State<NearbyDetailPage> {
  Future<NearbyFeed>? pending;
  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final repo = NearbyRepository(AppContext.of(context).state.browser);
    pending ??= repo.cached == null ? repo.load() : Future.value(repo.cached!);
  }

  @override
  Widget build(BuildContext context) => FutureBuilder<NearbyFeed>(
    future: pending,
    builder: (context, snapshot) {
      final env = AppContext.of(context);
      final item = snapshot.data?.items
          .where((item) => item.id == widget.id)
          .firstOrNull;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          UiButton(
            '지도로 돌아가기',
            quiet: true,
            icon: 'left',
            onTap: () => env.go('/nearby', {'id': widget.id}),
          ),
          const SizedBox(height: 24),
          if (snapshot.connectionState != ConnectionState.done)
            const LinearProgressIndicator(color: Palette.orange)
          else if (snapshot.hasError)
            EmptyPanel(
              '소식을 불러오지 못했어요',
              '연결과 자료 형식을 확인해주세요.',
              action: '다시 조회',
              onTap: () => setState(
                () => pending = NearbyRepository(env.state.browser).load(),
              ),
            )
          else if (item == null)
            EmptyPanel(
              '소식을 찾을 수 없어요',
              '자료가 갱신되었거나 더 이상 제공되지 않는 소식이에요.',
              action: '주변 소식 보기',
              onTap: () => env.go('/nearby'),
            )
          else ...[
            Text(
              '${categories[item.category]}${snapshot.data!.demo ? " · 예시" : ""}',
              style: type(12, color: Palette.orange),
            ),
            const SizedBox(height: 10),
            Text(item.title, style: type(28, weight: FontWeight.w700)),
            const SizedBox(height: 16),
            Text(item.summary, style: type(16, color: Palette.sub)),
            const SizedBox(height: 24),
            Text('장소', style: type(14, weight: FontWeight.w600)),
            Text(item.address, style: type(14)),
            const SizedBox(height: 16),
            Text('일정', style: type(14, weight: FontWeight.w600)),
            Text(dateRange(item.start, item.end), style: type(14)),
            const SizedBox(height: 16),
            Text('진행 상태', style: type(14, weight: FontWeight.w600)),
            Text(
              const {
                'scheduled': '진행 예정',
                'ongoing': '진행 중',
                'cancelled': '취소',
                'unknown': '확인 필요',
              }[item.status]!,
              style: type(
                14,
                color: item.status == 'cancelled' ? Palette.red : Palette.ink,
              ),
            ),
            const SizedBox(height: 24),
            const Divider(),
            const SizedBox(height: 16),
            Text('소식 안내', style: type(18, weight: FontWeight.w600)),
            const SizedBox(height: 12),
            SelectableText(item.description, style: type(14, height: 1.9)),
            const SizedBox(height: 24),
            if (item.sourceUrl != null)
              UiButton(
                '원문 보기',
                primary: true,
                icon: 'external',
                onTap: () {
                  if (!env.state.browser.open(item.sourceUrl!))
                    env.toast('원문을 열지 못했어요.');
                },
              ),
            const SizedBox(height: 20),
            Text(
              '자료 갱신 ${snapshot.data!.updatedAt.toUtc().toIso8601String()} UTC',
              style: type(11, color: Palette.sub),
            ),
          ],
        ],
      );
    },
  );
}
