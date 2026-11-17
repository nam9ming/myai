import 'package:material_ui/material_ui.dart';

import '../../app/app_context.dart';
import '../../core/ui.dart';

class SavedPage extends StatelessWidget {
  final bool changedOnly;
  const SavedPage({super.key, this.changedOnly = false});
  @override
  Widget build(BuildContext context) {
    final env = AppContext.of(context), app = env.state;
    final known = app.items.where((n) => app.saved.containsKey(n.id)).toList();
    final shown = known
        .where(
          (n) =>
              !changedOnly ||
              n.change != null ||
              (n.api?['history'] is List &&
                  (n.api!['history'] as List).isNotEmpty),
        )
        .toList();
    final unknown = app.saved.keys
        .where((id) => !known.any((n) => n.id == id))
        .toList();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeading(
          '관심정보',
          description: app.storageFailed
              ? '다시 보고 싶은 소식을 모아두세요. 이번 방문 동안만 유지되며 새로고침하면 초기화됩니다.'
              : '다시 보고 싶은 소식을 모아두세요. 저장은 이 브라우저에서 유지됩니다.',
        ),
        Row(
          children: [
            UiButton(
              '전체 ${app.saved.length}',
              selected: !changedOnly,
              onTap: () => env.go('/saved'),
            ),
            const SizedBox(width: 12),
            UiButton(
              '변경 소식',
              selected: changedOnly,
              onTap: () => env.go('/saved', {'changed': '1'}),
            ),
          ],
        ),
        const SizedBox(height: 24),
        if (app.saved.isEmpty)
          EmptyPanel(
            '아직 저장한 소식이 없어요.',
            '소식 카드의 저장 버튼을 눌러 관심정보를 모아보세요.',
            onTap: () => env.go('/list'),
          )
        else if (shown.isEmpty && unknown.isEmpty)
          EmptyPanel(
            '달라진 소식이 아직 없어요.',
            '저장한 전체 소식도 살펴보세요.',
            action: '전체 관심정보 보기',
            onTap: () => env.go('/saved'),
          )
        else
          NoticeGrid(shown),
        if (unknown.isNotEmpty) ...[
          const SizedBox(height: 24),
          Text('저장한 공개본을 다시 확인해주세요.', style: type(16, weight: FontWeight.w600)),
          const SizedBox(height: 8),
          Text(
            '현재 불러온 자료에 없는 저장 항목입니다. 공개본 교체 또는 제공 범위 변경으로 조회되지 않을 수 있어요.',
            style: type(12, color: Palette.sub),
          ),
          for (final id in unknown)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: UiButton(
                '저장한 소식 확인',
                icon: 'chevron',
                onTap: () => env.go('/detail', {
                  'id': id,
                  if (app.saved[id]?['snapshot_id'] is String)
                    'snapshot_id': app.saved[id]!['snapshot_id'],
                }),
              ),
            ),
        ],
      ],
    );
  }
}
