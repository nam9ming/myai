import 'package:material_ui/material_ui.dart';
import 'package:flutter_svg/flutter_svg.dart';

import '../app/app_context.dart';
import '../data/models.dart';
import 'icons.dart';

abstract final class Palette {
  static const ink = Color(0xff242724),
      sub = Color(0xff747970),
      line = Color(0xffe9eae5);
  static const paper = Color(0xffffffff), background = Color(0xfffafaf7);
  static const orange = Color(0xffee663b), soft = Color(0xfffff1e9);
  static const green = Color(0xff2d6950), greenBackground = Color(0xffeaf4ec);
  static const red = Color(0xffad493b), focus = Color(0xffefab81);
}

ThemeData appTheme() => ThemeData(
  pageTransitionsTheme: PageTransitionsTheme(
    builders: {
      for (final platform in TargetPlatform.values)
        platform: const _NoPageTransitions(),
    },
  ),
  useMaterial3: false,
  fontFamily: 'NotoSansKR',
  scaffoldBackgroundColor: Palette.paper,
  colorScheme: const ColorScheme.light(
    primary: Palette.orange,
    secondary: Palette.green,
    surface: Palette.paper,
    onSurface: Palette.ink,
    error: Palette.red,
  ),
  textTheme: const TextTheme(
    bodyMedium: TextStyle(fontSize: 14, height: 1.6, color: Palette.ink),
    bodySmall: TextStyle(fontSize: 12, height: 1.7, color: Palette.sub),
  ),
  dividerColor: Palette.line,
  visualDensity: VisualDensity.standard,
  dialogTheme: const DialogThemeData(
    backgroundColor: Palette.paper,
    elevation: 0,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.all(Radius.circular(17)),
    ),
  ),
  inputDecorationTheme: InputDecorationTheme(
    contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(9),
      borderSide: const BorderSide(color: Palette.line),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(9),
      borderSide: const BorderSide(color: Palette.line),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(9),
      borderSide: const BorderSide(color: Palette.focus, width: 2),
    ),
  ),
);

class _NoPageTransitions extends PageTransitionsBuilder {
  const _NoPageTransitions();
  @override
  Widget buildTransitions<T>(
    PageRoute<T> route,
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
    Widget child,
  ) => child;
}

bool mobile(BuildContext c) => MediaQuery.sizeOf(c).width <= 760;
bool reducedMotion(BuildContext c) => MediaQuery.disableAnimationsOf(c);
TextStyle type(
  double size, {
  Color? color,
  FontWeight weight = FontWeight.w400,
  double height = 1.6,
  double spacing = 0,
}) => TextStyle(
  fontFamily: 'NotoSansKR',
  fontSize: size,
  fontWeight: weight,
  height: height,
  color: color ?? Palette.ink,
  letterSpacing: spacing,
);

class UiIcon extends StatelessWidget {
  final String name;
  final double size;
  final Color? color;
  const UiIcon(this.name, {super.key, this.size = 20, this.color});
  @override
  Widget build(BuildContext context) => ExcludeSemantics(
    child: SvgPicture.string(
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="${_hex(color ?? Palette.ink)}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${iconPaths[name] ?? iconPaths['info']}"/></svg>',
      width: size,
      height: size,
    ),
  );
  String _hex(Color value) =>
      '#${value.toARGB32().toRadixString(16).substring(2)}';
}

class Pressable extends StatefulWidget {
  final Widget child;
  final VoidCallback? onTap;
  final BorderRadius borderRadius;
  final bool? selected;
  final String? label;
  final Color? hoverColor;
  const Pressable({
    super.key,
    required this.child,
    this.onTap,
    this.selected,
    this.label,
    this.borderRadius = const BorderRadius.all(Radius.circular(9)),
    this.hoverColor,
  });
  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  final focusNode = FocusNode();
  bool focus = false, hover = false, pressed = false;
  @override
  void dispose() {
    focusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final duration = Duration(milliseconds: reducedMotion(context) ? 0 : 180);
    return Semantics(
      button: true,
      enabled: widget.onTap != null,
      selected: widget.selected,
      label: widget.label,
      child: FocusableActionDetector(
        focusNode: focusNode,
        enabled: widget.onTap != null,
        mouseCursor: widget.onTap == null
            ? SystemMouseCursors.basic
            : SystemMouseCursors.click,
        onShowFocusHighlight: (v) => setState(() => focus = v),
        onShowHoverHighlight: (v) => setState(() => hover = v),
        actions: {
          ActivateIntent: CallbackAction<ActivateIntent>(
            onInvoke: (_) {
              widget.onTap?.call();
              return null;
            },
          ),
        },
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: widget.onTap == null
              ? null
              : () {
                  focusNode.requestFocus();
                  widget.onTap!();
                },
          onTapDown: widget.onTap == null
              ? null
              : (_) => setState(() => pressed = true),
          onTapUp: (_) => setState(() => pressed = false),
          onTapCancel: () => setState(() => pressed = false),
          child: AnimatedScale(
            scale: pressed ? .97 : 1,
            duration: duration,
            child: AnimatedContainer(
              duration: duration,
              foregroundDecoration: BoxDecoration(
                borderRadius: widget.borderRadius,
                border: Border.all(
                  color: focus ? Palette.focus : Colors.transparent,
                  width: 3,
                ),
              ),
              decoration: BoxDecoration(
                borderRadius: widget.borderRadius,
                color: hover ? widget.hoverColor : null,
              ),
              child: widget.child,
            ),
          ),
        ),
      ),
    );
  }
}

class UiButton extends StatelessWidget {
  final String label;
  final VoidCallback? onTap;
  final bool primary, green, quiet, selected, leftAligned;
  final String? icon;
  const UiButton(
    this.label, {
    super.key,
    this.onTap,
    this.primary = false,
    this.green = false,
    this.quiet = false,
    this.selected = false,
    this.leftAligned = false,
    this.icon,
  });
  @override
  Widget build(BuildContext context) {
    final color = primary
        ? Colors.white
        : quiet
        ? Palette.sub
        : selected
        ? (green ? const Color(0xff435b32) : const Color(0xffbc4f27))
        : Palette.ink;
    return Pressable(
      onTap: onTap,
      hoverColor: green ? const Color(0xfff4f6ec) : Palette.soft,
      selected: selected,
      child: Container(
        constraints: const BoxConstraints(minHeight: 46),
        padding: EdgeInsets.symmetric(horizontal: quiet ? 6 : 16, vertical: 11),
        decoration: BoxDecoration(
          color: onTap == null
              ? const Color(0xffe3e3dc)
              : primary
              ? (green ? const Color(0xff3c5f42) : Palette.orange)
              : selected
              ? (green ? const Color(0xfff0f3e5) : Palette.soft)
              : null,
          borderRadius: BorderRadius.circular(9),
          border: quiet || primary
              ? null
              : Border.all(
                  color: selected
                      ? (green
                            ? const Color(0xffaab995)
                            : const Color(0xfff6b798))
                      : Palette.line,
                ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          mainAxisAlignment: leftAligned
              ? MainAxisAlignment.start
              : MainAxisAlignment.center,
          children: [
            Flexible(
              child: Text(
                label,
                style: type(
                  quiet ? 12 : 13,
                  color: color,
                  weight: primary || selected
                      ? FontWeight.w600
                      : FontWeight.w400,
                ),
                textAlign: leftAligned ? TextAlign.start : TextAlign.center,
              ),
            ),
            if (icon != null) ...[
              const SizedBox(width: 6),
              UiIcon(icon!, size: 16, color: color),
            ],
          ],
        ),
      ),
    );
  }
}

class IconAction extends StatelessWidget {
  final String icon, label;
  final VoidCallback? onTap;
  final Color? color;
  final bool selected;
  const IconAction(
    this.icon,
    this.label, {
    super.key,
    this.onTap,
    this.color,
    this.selected = false,
  });
  @override
  Widget build(BuildContext context) => Tooltip(
    message: label,
    child: Pressable(
      label: label,
      selected: selected,
      onTap: onTap,
      hoverColor: Palette.soft,
      child: SizedBox(
        width: 44,
        height: 44,
        child: Center(child: UiIcon(icon, size: 20, color: color)),
      ),
    ),
  );
}

class PageWidth extends StatelessWidget {
  final Widget child;
  final double? maxWidth;
  final EdgeInsets? padding;
  const PageWidth({
    super.key,
    required this.child,
    this.maxWidth,
    this.padding,
  });
  @override
  Widget build(BuildContext context) => Align(
    alignment: Alignment.topCenter,
    child: ConstrainedBox(
      constraints: BoxConstraints(
        maxWidth:
            maxWidth ??
            (MediaQuery.sizeOf(context).width >= 1600 ? 1260 : 1160),
      ),
      child: Padding(
        padding:
            padding ??
            EdgeInsets.symmetric(
              horizontal: mobile(context)
                  ? (MediaQuery.sizeOf(context).width <= 370 ? 17 : 22)
                  : 32,
            ),
        child: child,
      ),
    ),
  );
}

class SectionHeading extends StatelessWidget {
  final String title;
  final String? description, action;
  final VoidCallback? onTap;
  const SectionHeading(
    this.title, {
    super.key,
    this.description,
    this.action,
    this.onTap,
  });
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 18),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: type(
                  mobile(context) ? 18 : 21,
                  weight: FontWeight.w600,
                  spacing: -.7,
                ),
              ),
              if (description != null) ...[
                const SizedBox(height: 4),
                Text(description!, style: type(12, color: Palette.sub)),
              ],
            ],
          ),
        ),
        if (action != null)
          UiButton(action!, quiet: true, onTap: onTap, icon: 'chevron'),
      ],
    ),
  );
}

class EmptyPanel extends StatelessWidget {
  final String title, message, action;
  final VoidCallback? onTap;
  const EmptyPanel(
    this.title,
    this.message, {
    super.key,
    this.action = '소식 둘러보기',
    this.onTap,
  });
  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.symmetric(vertical: 48, horizontal: 20),
    decoration: BoxDecoration(
      color: Palette.background,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Column(
      children: [
        const UiIcon('info', size: 34, color: Palette.sub),
        const SizedBox(height: 16),
        Text(
          title,
          style: type(17, weight: FontWeight.w600),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 8),
        Text(
          message,
          style: type(13, color: Palette.sub),
          textAlign: TextAlign.center,
        ),
        const SizedBox(height: 20),
        if (onTap != null) UiButton(action, primary: true, onTap: onTap),
      ],
    ),
  );
}

class NoticeBadge extends StatelessWidget {
  final Notice notice;
  const NoticeBadge(this.notice, {super.key});
  @override
  Widget build(BuildContext context) {
    final day = AppContext.of(context).state.day;
    final urgent =
        (notice.daysLeft(day) ?? 100) > -1 &&
        (notice.daysLeft(day) ?? 100) <= 7;
    final color = notice.cancelled
        ? Palette.red
        : notice.uncertain || urgent
        ? Palette.orange
        : notice.isOpen(day)
        ? Palette.green
        : Palette.sub;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .08),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        notice.status(day),
        style: type(10, color: color, weight: FontWeight.w500),
      ),
    );
  }
}

class SaveButton extends StatefulWidget {
  final Notice notice;
  const SaveButton(this.notice, {super.key});
  @override
  State<SaveButton> createState() => _SaveButtonState();
}

class _SaveButtonState extends State<SaveButton>
    with SingleTickerProviderStateMixin {
  late final AnimationController controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 300),
  );
  late final Animation<double> scale = TweenSequence<double>([
    TweenSequenceItem(tween: Tween(begin: .8, end: 1.22), weight: 50),
    TweenSequenceItem(tween: Tween(begin: 1.22, end: 1.0), weight: 50),
  ]).animate(controller);
  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final env = AppContext.of(context),
        active = env.state.saved.containsKey(widget.notice.id);
    return Tooltip(
      message: active ? '관심정보에서 해제' : '관심정보에 저장',
      child: Pressable(
        label: active ? '관심정보 저장됨, 해제' : '관심정보에 저장',
        selected: active,
        onTap: () {
          final added = env.state.toggleSaved(widget.notice);
          if (added && !reducedMotion(context)) controller.forward(from: 0);
          env.toast(added ? '관심정보에 저장했어요.' : '관심정보에서 해제했어요.');
        },
        hoverColor: Palette.soft,
        borderRadius: BorderRadius.circular(30),
        child: SizedBox(
          width: 44,
          height: 44,
          child: Center(
            child: AnimatedBuilder(
              animation: controller,
              builder: (_, child) => Transform.scale(
                scale: controller.isAnimating ? scale.value : 1,
                child: child,
              ),
              child: Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: active
                      ? Palette.soft
                      : Colors.white.withValues(alpha: .94),
                  shape: BoxShape.circle,
                  border: Border.all(color: Palette.line),
                ),
                child: Center(
                  child: UiIcon(
                    'bookmark',
                    size: 16,
                    color: active ? Palette.orange : Palette.ink,
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class NoticeCard extends StatefulWidget {
  final Notice notice;
  const NoticeCard(this.notice, {super.key});
  @override
  State<NoticeCard> createState() => _NoticeCardState();
}

class _NoticeCardState extends State<NoticeCard> {
  bool hover = false;
  @override
  Widget build(BuildContext context) {
    final n = widget.notice,
        env = AppContext.of(context),
        small = mobile(context),
        hasPoster = n.poster != null;
    final open = () => env.go('/detail', {
      'id': n.id,
      if (n.snapshotId != null) 'snapshot_id': n.snapshotId!,
    });
    final copy = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '${n.agency} · ${n.district}',
          style: type(small ? 10 : 11, color: Palette.sub),
        ),
        const SizedBox(height: 6),
        Text(
          n.title,
          style: type(
            small ? 14 : 15,
            weight: FontWeight.w600,
            height: 1.55,
            spacing: -.45,
          ),
        ),
        const SizedBox(height: 9),
        if (!hasPoster) ...[
          Text(n.target, style: type(12, color: Palette.sub)),
          const SizedBox(height: 16),
        ],
        Text(
          dateRange(n.start, n.end),
          style: type(small ? 10 : 12, color: Palette.sub),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 7,
          runSpacing: 5,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [
            NoticeBadge(n),
            Text(n.costLabel, style: type(11, color: Palette.sub)),
          ],
        ),
      ],
    );
    return MouseRegion(
      onEnter: (_) => setState(() => hover = true),
      onExit: (_) => setState(() => hover = false),
      child: Pressable(
        onTap: open,
        label: '${n.title}, 상세 보기',
        child: hasPoster
            ? Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Stack(
                    children: [
                      ClipRRect(
                        borderRadius: BorderRadius.circular(small ? 9 : 12),
                        child: AspectRatio(
                          aspectRatio: 4 / 3,
                          child: AnimatedScale(
                            scale: hover && !reducedMotion(context) ? 1.035 : 1,
                            duration: Duration(
                              milliseconds: reducedMotion(context) ? 0 : 300,
                            ),
                            curve: const Cubic(.2, .8, .2, 1),
                            child: SvgPicture.asset(
                              'assets/posters/${n.poster}',
                              fit: BoxFit.cover,
                              errorBuilder: (_, __, ___) => const ColoredBox(
                                color: Palette.background,
                                child: Center(child: Text('포스터를 불러오지 못했어요.')),
                              ),
                            ),
                          ),
                        ),
                      ),
                      Positioned(top: 6, right: 6, child: SaveButton(n)),
                    ],
                  ),
                  const SizedBox(height: 13),
                  copy,
                ],
              )
            : Container(
                constraints: const BoxConstraints(minHeight: 230),
                padding: EdgeInsets.all(small ? 14 : 21),
                decoration: BoxDecoration(
                  border: Border.all(color: Palette.line),
                  borderRadius: BorderRadius.circular(small ? 9 : 12),
                ),
                child: Stack(
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(top: 32),
                      child: copy,
                    ),
                    Align(
                      alignment: Alignment.topLeft,
                      child: Padding(
                        padding: const EdgeInsets.only(right: 35),
                        child: Text(
                          categories[n.category] ?? '공개 정보',
                          style: type(11, color: Palette.sub),
                        ),
                      ),
                    ),
                    Positioned(top: -10, right: -10, child: SaveButton(n)),
                  ],
                ),
              ),
      ),
    );
  }
}

class NoticeGrid extends StatelessWidget {
  final List<Notice> notices;
  final bool home;
  const NoticeGrid(this.notices, {super.key, this.home = false});
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, c) {
      final count = mobile(context)
          ? 2
          : home
          ? 4
          : 3;
      final gap = mobile(context)
          ? (MediaQuery.sizeOf(context).width <= 370 ? 12.0 : 15.0)
          : home
          ? 20.0
          : 24.0;
      final width = (c.maxWidth - gap * (count - 1)) / count;
      return Wrap(
        spacing: gap,
        runSpacing: home ? 25 : 30,
        children: [
          for (final n in notices)
            SizedBox(
              width: width,
              child: NoticeCard(n, key: ValueKey(n.id)),
            ),
        ],
      );
    },
  );
}

class ApiErrorPanel extends StatelessWidget {
  final ApiFailure error;
  final VoidCallback? onRetry, onRefresh;
  const ApiErrorPanel(this.error, {super.key, this.onRetry, this.onRefresh});
  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(26),
    decoration: BoxDecoration(
      color: Palette.background,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          error.code == 'PUBLIC_DATA_NOT_READY'
              ? '공개 자료를 준비하고 있어요.'
              : error.code == 'SNAPSHOT_RETIRED'
              ? '새로운 공개본이 있어요.'
              : error.code.startsWith('UNSUPPORTED')
              ? '이 정보는 아직 준비 중이에요.'
              : '자료를 불러오지 못했어요.',
          style: type(20, weight: FontWeight.w600),
        ),
        const SizedBox(height: 10),
        Text(error.message, style: type(13, color: Palette.sub)),
        if (error.currentSnapshotId != null) ...[
          const SizedBox(height: 12),
          Text(
            '새 공개본: ${error.currentSnapshotId}',
            style: type(11, color: Palette.sub),
          ),
        ],
        if (error.fieldErrors.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text(
            factText(error.fieldErrors),
            style: type(12, color: Palette.red),
          ),
        ],
        if (error.requestId != null) ...[
          const SizedBox(height: 8),
          SelectableText(
            '문의 번호: ${error.requestId}',
            style: type(11, color: Palette.sub),
          ),
        ],
        if (error.code == 'SNAPSHOT_RETIRED' && onRefresh != null) ...[
          const SizedBox(height: 18),
          UiButton('새 공개본으로 다시 보기', primary: true, onTap: onRefresh),
        ],
        if (error.retryable && onRetry != null) ...[
          const SizedBox(height: 18),
          UiButton('다시 시도', primary: true, onTap: onRetry),
        ],
      ],
    ),
  );
}
