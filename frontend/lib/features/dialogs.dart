import 'package:material_ui/material_ui.dart';

import '../app/app_state.dart';
import '../core/ui.dart';
import '../data/models.dart';

Future<Preferences?> showRegionPicker(
  BuildContext context,
  AppState state, {
  Preferences? initial,
}) => showDialog<Preferences>(
  context: context,
  builder: (_) =>
      _RegionDialog(state: state, initial: initial ?? state.settings),
);

class _RegionDialog extends StatefulWidget {
  final AppState state;
  final Preferences initial;
  const _RegionDialog({required this.state, required this.initial});
  @override
  State<_RegionDialog> createState() => _RegionDialogState();
}

class _RegionDialogState extends State<_RegionDialog> {
  late Preferences draft = widget.initial.copyWith();
  @override
  Widget build(BuildContext context) => Dialog(
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 440),
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(26),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '관심 지역 변경',
                    style: type(19, weight: FontWeight.w600),
                  ),
                ),
                IconAction('close', '닫기', onTap: () => Navigator.pop(context)),
              ],
            ),
            const SizedBox(height: 18),
            _select(
              '시·도',
              draft.province,
              widget.state.prototype.provinces,
              (v) => setState(
                () => draft = draft.copyWith(
                  province: v,
                  city: widget.state.prototype.cities[v]!.first,
                  district: citywide,
                ),
              ),
            ),
            const SizedBox(height: 18),
            _select(
              '시·군·구',
              draft.city,
              widget.state.prototype.cities[draft.province] ?? [],
              (v) => setState(
                () => draft = draft.copyWith(city: v, district: citywide),
              ),
            ),
            if (draft.city == '안성시') ...[
              const SizedBox(height: 18),
              _select(
                '동네',
                draft.district,
                widget.state.prototype.districts,
                (v) => setState(() => draft = draft.copyWith(district: v)),
              ),
            ],
            const SizedBox(height: 16),
            Text(
              '지역 목록은 일부 예시입니다. 현재 제공하는 시제품 내용은 안성시 예시예요.',
              style: type(11, color: Palette.sub),
            ),
            const SizedBox(height: 26),
            Row(
              children: [
                Expanded(
                  child: UiButton('취소', onTap: () => Navigator.pop(context)),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: UiButton(
                    '지역 적용',
                    primary: true,
                    onTap: () => Navigator.pop(context, draft),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    ),
  );
  Widget _select(
    String label,
    String value,
    List<String> values,
    ValueChanged<String> change,
  ) => DropdownButtonFormField<String>(
    initialValue: values.contains(value) ? value : null,
    key: ValueKey('$label:$value'),
    isExpanded: true,
    decoration: InputDecoration(labelText: label),
    items: [
      for (final v in values)
        DropdownMenuItem(
          value: v,
          child: Text(v, style: type(13)),
        ),
    ],
    onChanged: (v) {
      if (v != null) change(v);
    },
  );
}

Future<NoticeQuery?> showFilters(
  BuildContext context,
  AppState state,
  NoticeQuery current,
) => showDialog<NoticeQuery>(
  context: context,
  builder: (_) => _FilterDialog(state: state, initial: current),
);

class _FilterDialog extends StatefulWidget {
  final AppState state;
  final NoticeQuery initial;
  const _FilterDialog({required this.state, required this.initial});
  @override
  State<_FilterDialog> createState() => _FilterDialogState();
}

class _FilterDialogState extends State<_FilterDialog> {
  late NoticeQuery draft = widget.initial;
  @override
  Widget build(BuildContext context) => Dialog(
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 440),
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(26),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '원하는 소식 찾기',
                    style: type(19, weight: FontWeight.w600),
                  ),
                ),
                IconAction(
                  'close',
                  '필터 닫기',
                  onTap: () => Navigator.pop(context),
                ),
              ],
            ),
            const SizedBox(height: 20),
            Text('분야', style: type(13, weight: FontWeight.w600)),
            const SizedBox(height: 10),
            Wrap(
              spacing: 7,
              runSpacing: 7,
              children: [
                for (final e in categories.entries)
                  UiButton(
                    e.value,
                    selected: draft.category == e.key,
                    onTap: () =>
                        setState(() => draft = draft.copyWith(category: e.key)),
                  ),
              ],
            ),
            const SizedBox(height: 20),
            DropdownButtonFormField<String>(
              key: ValueKey(draft.district),
              initialValue:
                  widget.state.prototype.districts.contains(draft.district)
                  ? draft.district
                  : citywide,
              decoration: const InputDecoration(labelText: '동네'),
              isExpanded: true,
              items: [
                for (final v in widget.state.prototype.districts)
                  DropdownMenuItem(
                    value: v,
                    child: Text(v, style: type(13)),
                  ),
              ],
              onChanged: (v) =>
                  setState(() => draft = draft.copyWith(district: v)),
            ),
            const SizedBox(height: 20),
            Text('기간', style: type(13, weight: FontWeight.w600)),
            const SizedBox(height: 10),
            Wrap(
              spacing: 7,
              runSpacing: 7,
              children: [
                for (final e in const {
                  'all': '전체',
                  'week': '이번 주 진행',
                  'deadline': '7일 내 신청 마감',
                }.entries)
                  UiButton(
                    e.value,
                    selected: draft.period == e.key,
                    onTap: () =>
                        setState(() => draft = draft.copyWith(period: e.key)),
                  ),
              ],
            ),
            const SizedBox(height: 14),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              title: Text('모집 중', style: type(13)),
              value: draft.open,
              onChanged: (v) => setState(() => draft = draft.copyWith(open: v)),
            ),
            CheckboxListTile(
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              title: Text('무료', style: type(13)),
              value: draft.free,
              onChanged: (v) => setState(() => draft = draft.copyWith(free: v)),
            ),
            const SizedBox(height: 20),
            Row(
              children: [
                UiButton(
                  '초기화',
                  onTap: () => setState(() => draft = draft.resetConditions()),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: UiButton(
                    '조건 적용',
                    primary: true,
                    onTap: () => Navigator.pop(context, draft),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    ),
  );
}
