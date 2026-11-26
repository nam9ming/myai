import 'package:material_ui/material_ui.dart';

import '../../core/ui.dart';
import '../../data/municipality_boundaries.dart';

import 'korea_regions.dart';

const _mapInk = Color(0xff58382e);
const _mapSurface = Color(0xfffcfaf7);
const _cityNames = {
  '서울특별시',
  '부산광역시',
  '대구광역시',
  '인천광역시',
  '광주광역시',
  '대전광역시',
  '울산광역시',
  '세종특별자치시',
};

class RegionMap extends StatefulWidget {
  final List<String> regions;
  final String? province, selected;
  final ValueChanged<String> onSelected;
  final Widget? mapAction;

  const RegionMap({
    super.key,
    this.province,
    this.selected,
    required this.regions,
    required this.onSelected,
    this.mapAction,
  });

  @override
  State<RegionMap> createState() => _RegionMapState();
}

class _RegionMapState extends State<RegionMap> {
  String? hovered;
  final focused = <String>{};

  late final _regions = widget.province == null
      ? koreaRegions
      : (municipalityBoundaries[widget.province] ?? {}).map(
          (name, data) =>
              MapEntry(name, (Offset(data.$1, data.$2), regionPath(data.$3))),
        );

  late final _bounds = widget.province == null
      ? const Rect.fromLTWH(0, 0, 232, 340)
      : _regions.values
            .map((region) => region.$2.getBounds())
            .reduce((a, b) => a.expandToInclude(b));

  @override
  Widget build(BuildContext context) {
    final motion = !reducedMotion(context);
    return LayoutBuilder(
      builder: (context, constraints) {
        final width = (constraints.maxWidth - 12).clamp(0.0, 336.0);
        final unit = (width / _bounds.width).clamp(
          0.0,
          widget.province == null ? double.infinity : 365 / _bounds.height,
        );
        final paths = {
          for (final entry in _regions.entries)
            if (widget.regions.contains(entry.key))
              entry.key: entry.value.$2
                  .shift(-_bounds.topLeft)
                  .transform(Matrix4.diagonal3Values(unit, unit, 1).storage),
        };
        final highlighted = hovered ?? focused.lastOrNull ?? widget.selected;
        final mapWidth = _bounds.width * unit;
        final mapHeight = _bounds.height * unit;
        final map = SizedBox(
          width: mapWidth,
          height: mapHeight,
          child: Stack(
            children: [
              for (final entry in paths.entries)
                if (widget.province == null || entry.key != highlighted)
                  _area(entry.key, entry.value, unit, motion),
              if (widget.province != null && paths.containsKey(highlighted))
                _area(highlighted!, paths[highlighted]!, unit, motion),
              if (widget.province != null)
                ..._municipalityLabels(context, paths, unit, highlighted),
              if (widget.province != null && paths.containsKey(highlighted))
                _highlightLabel(
                  highlighted!,
                  paths[highlighted]!,
                  unit,
                  Size(mapWidth, mapHeight),
                  motion,
                ),
              if (widget.province == null)
                Positioned(
                  top: 45 * unit,
                  right: 4 * unit,
                  child: Column(
                    children: [
                      for (final island in koreaEastIslands.entries)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: Row(
                            children: [
                              CustomPaint(
                                size: const Size(15, 14),
                                painter: _RegionPaint(
                                  island.value,
                                  const Color(0xfff8d6c6),
                                ),
                              ),
                              const SizedBox(width: 4),
                              Text(island.key, style: type(10, color: _mapInk)),
                            ],
                          ),
                        ),
                    ],
                  ),
                ),
            ],
          ),
        );
        return Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(vertical: 14),
          decoration: BoxDecoration(
            color: _mapSurface,
            borderRadius: BorderRadius.circular(20),
          ),
          child: Stack(
            children: [
              Center(child: map),
              if (widget.mapAction case final action?)
                Positioned(right: 8, bottom: 0, child: action),
              Positioned(
                top: 0,
                right: 4,
                child: IconButton(
                  tooltip: '지도 출처: 통계청 SGIS (2018), 공공누리 제1유형',
                  icon: const Icon(
                    Icons.info_outline,
                    size: 16,
                    color: _mapInk,
                  ),
                  onPressed: () => showDialog<void>(
                    context: context,
                    builder: (context) => AlertDialog(
                      title: const Text('지도 출처'),
                      content: const Text(
                        '통계청 SGIS (2018) 행정구역 경계 · 공공누리 제1유형',
                      ),
                      actions: [
                        TextButton(
                          onPressed: () => Navigator.pop(context),
                          child: const Text('닫기'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  void _hover(String region) => setState(() => hovered = region);

  void _leave(String region) {
    if (hovered == region) setState(() => hovered = null);
  }

  Widget _target(String region, Widget child) => Semantics(
    label: region,
    button: true,
    selected: widget.selected == region,
    onTap: () => widget.onSelected(region),
    child: FocusableActionDetector(
      mouseCursor: SystemMouseCursors.click,
      onShowFocusHighlight: (show) => setState(() {
        show ? focused.add(region) : focused.remove(region);
      }),
      actions: {
        ActivateIntent: CallbackAction<ActivateIntent>(
          onInvoke: (_) => widget.onSelected(region),
        ),
      },
      child: MouseRegion(
        onEnter: (_) => _hover(region),
        onExit: (_) => _leave(region),
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          excludeFromSemantics: true,
          onTap: () => widget.onSelected(region),
          child: ExcludeSemantics(child: child),
        ),
      ),
    ),
  );

  Color _fill(String region) => widget.selected == region
      ? const Color(0xffec9a77)
      : hovered == region || focused.contains(region)
      ? const Color(0xfff2b69d)
      : _cityNames.contains(region)
      ? const Color(0xfff3c8b5)
      : const Color(0xfff8d6c6);

  List<Offset> _labelCandidates(Rect bounds, Offset anchor) {
    final candidates =
        [
          for (var y = 1; y < 12; y++)
            for (var x = 1; x < 12; x++)
              bounds.topLeft +
                  Offset(bounds.width * x / 12, bounds.height * y / 12),
        ]..sort(
          (a, b) => (a - anchor).distanceSquared.compareTo(
            (b - anchor).distanceSquared,
          ),
        );
    candidates.insert(0, anchor);
    return candidates;
  }

  Widget _highlightLabel(
    String region,
    Path path,
    double unit,
    Size mapSize,
    bool motion,
  ) {
    final anchor = (_regions[region]!.$1 - _bounds.topLeft) * unit;
    final center =
        _labelCandidates(
          path.getBounds(),
          anchor,
        ).where(path.contains).firstOrNull ??
        path.getBounds().center;
    final style = type(16, color: _mapInk, weight: FontWeight.w700);
    final scaler = MediaQuery.textScalerOf(context);
    final painter = TextPainter(
      text: TextSpan(text: region, style: style),
      textDirection: Directionality.of(context),
      textScaler: scaler,
      maxLines: 1,
    )..layout(maxWidth: mapSize.width);
    final size = painter.size;
    painter.dispose();
    return Positioned(
      key: ValueKey('region-highlight-$region'),
      left: (center.dx - size.width / 2).clamp(0.0, mapSize.width - size.width),
      top: (center.dy - size.height / 2).clamp(
        0.0,
        (mapSize.height - size.height).clamp(0.0, double.infinity),
      ),
      width: size.width,
      child: IgnorePointer(
        child: ExcludeSemantics(
          child: TweenAnimationBuilder<double>(
            tween: Tween(begin: motion ? 0.625 : 1.0, end: 1.0),
            duration: Duration(milliseconds: motion ? 260 : 0),
            curve: Curves.easeOutCubic,
            builder: (context, scale, child) => Transform.scale(
              key: const ValueKey('highlighted-region-scale'),
              scale: scale,
              child: child,
            ),
            child: Stack(
              children: [
                for (final outline in [true, false])
                  RichText(
                    key: outline
                        ? null
                        : const ValueKey('highlighted-region-label'),
                    textScaler: scaler,
                    maxLines: 1,
                    text: TextSpan(
                      text: region,
                      style: style.copyWith(
                        foreground: outline
                            ? (Paint()
                                ..color = _mapSurface
                                ..style = PaintingStyle.stroke
                                ..strokeWidth = 3.5
                                ..strokeJoin = StrokeJoin.round)
                            : null,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _area(String region, Path path, double unit, bool motion) {
    final bounds = path.getBounds();
    final local = path.shift(-bounds.topLeft);
    final active =
        hovered == region ||
        focused.contains(region) ||
        (widget.province != null &&
            hovered == null &&
            widget.selected == region);
    final city = _cityNames.contains(region);
    final name = city
        ? region.substring(0, 2)
        : region.replaceFirst('특별자치도', '');
    final anchor =
        (_regions[region]!.$1 - _bounds.topLeft) * unit - bounds.topLeft;
    return Positioned.fromRect(
      key: ValueKey('region-area-$region'),
      rect: bounds,
      child: Stack(
        fit: StackFit.expand,
        clipBehavior: Clip.none,
        children: [
          IgnorePointer(
            child: AnimatedScale(
              key: ValueKey(region),
              scale: active && motion
                  ? (widget.province == null ? 1.07 : 1.28)
                  : 1,
              curve: Curves.easeOutCubic,
              duration: Duration(milliseconds: motion ? 140 : 0),
              child: CustomPaint(
                painter: _RegionPaint(local, _fill(region)),
                child: widget.province == null
                    ? Stack(
                        clipBehavior: Clip.none,
                        children: [
                          Positioned(
                            left: anchor.dx - 34,
                            top: anchor.dy - 8,
                            width: 68,
                            child: Text(
                              name,
                              textAlign: TextAlign.center,
                              style: type(
                                city ? 10 : 12,
                                color: _mapInk,
                                weight: FontWeight.w600,
                              ),
                            ),
                          ),
                        ],
                      )
                    : null,
              ),
            ),
          ),
          ClipPath(
            clipper: _RegionClip(local),
            child: _target(region, const SizedBox.expand()),
          ),
        ],
      ),
    );
  }

  Iterable<Widget> _municipalityLabels(
    BuildContext context,
    Map<String, Path> paths,
    double unit,
    String? highlighted,
  ) sync* {
    final occupied = <Rect>[];
    final style = type(10, color: _mapInk, weight: FontWeight.w600);
    final names = paths.keys.toList();
    final selected = widget.selected;
    if (names.remove(selected)) names.insert(0, selected!);

    for (final name in names) {
      final path = paths[name]!;
      final bounds = path.getBounds();
      final anchor = (_regions[name]!.$1 - _bounds.topLeft) * unit;
      final candidates = _labelCandidates(bounds, anchor);
      final painter = TextPainter(
        text: TextSpan(text: name, style: style),
        textDirection: Directionality.of(context),
        textScaler: MediaQuery.textScalerOf(context),
        maxLines: 1,
      )..layout();
      final size = painter.size;
      painter.dispose();

      for (final center in candidates) {
        final rect = Rect.fromCenter(
          center: center,
          width: size.width,
          height: size.height,
        );
        final padded = rect.inflate(2);
        if (occupied.any(padded.overlaps) ||
            ![
              center,
              rect.topLeft,
              rect.topCenter,
              rect.topRight,
              rect.centerLeft,
              rect.centerRight,
              rect.bottomLeft,
              rect.bottomCenter,
              rect.bottomRight,
            ].every(path.contains)) {
          continue;
        }
        occupied.add(padded);
        yield Positioned(
          left: rect.left,
          top: rect.top,
          child: IgnorePointer(
            child: ExcludeSemantics(
              child: Opacity(
                opacity: name == highlighted ? 0 : 1,
                child: Text(
                  name,
                  key: ValueKey('region-label-$name'),
                  style: style,
                  maxLines: 1,
                ),
              ),
            ),
          ),
        );
        break;
      }
    }
  }
}

class _RegionClip extends CustomClipper<Path> {
  final Path path;
  const _RegionClip(this.path);

  @override
  Path getClip(Size size) => path;

  @override
  bool shouldReclip(_RegionClip oldClipper) => oldClipper.path != path;
}

class _RegionPaint extends CustomPainter {
  final Path path;
  final Color color;
  const _RegionPaint(this.path, this.color);

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawPath(path, Paint()..color = color);
    canvas.drawPath(
      path,
      Paint()
        ..color = const Color(0xffae7059)
        ..style = PaintingStyle.stroke
        ..strokeJoin = StrokeJoin.round
        ..strokeWidth = 0.8,
    );
  }

  @override
  bool shouldRepaint(_RegionPaint oldDelegate) =>
      oldDelegate.path != path || oldDelegate.color != color;
}
