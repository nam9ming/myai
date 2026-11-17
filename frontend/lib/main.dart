import 'dart:async';

import 'package:material_ui/material_ui.dart';
import 'package:flutter/services.dart';

import 'app/app_state.dart';
import 'app/router.dart';
import 'core/browser.dart';
import 'core/ui.dart';
import 'data/repositories.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // 본문과 SVG 포스터가 같은 글꼴 등록을 공유해 중복 해석을 피한다.
  final fontData = rootBundle.load('assets/fonts/NotoSansKR.woff2');
  final fonts = (FontLoader('sans-serif')..addFont(fontData)).load();
  final (_, prototype) = await (fonts, PrototypeData.load()).wait;
  final state = AppState(
    prototype,
    createBrowserServices(),
    mode: const String.fromEnvironment('DATA_MODE', defaultValue: 'prototype'),
    apiBaseUrl: const String.fromEnvironment(
      'API_BASE_URL',
      defaultValue: '/api/v1',
    ),
  );
  unawaited(state.reload());
  runApp(YeogiApp(state: state));
}

class YeogiApp extends StatefulWidget {
  final AppState state;
  const YeogiApp({super.key, required this.state});
  @override
  State<YeogiApp> createState() => _YeogiAppState();
}

class _YeogiAppState extends State<YeogiApp> {
  late final router = AppRouter(widget.state);
  StreamSubscription<bool>? motionSubscription;
  @override
  void initState() {
    super.initState();
    motionSubscription = widget.state.browser.reducedMotionChanges.listen((_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    unawaited(motionSubscription?.cancel());
    router.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => MaterialApp.router(
    title: '여기:it — 내 동네에 필요한 정보',
    debugShowCheckedModeBanner: false,
    theme: appTheme(),
    routerDelegate: router,
    routeInformationParser: AppRouteParser(),
    builder: (context, child) {
      final media = MediaQuery.of(context);
      return MediaQuery(
        data: media.copyWith(
          disableAnimations:
              media.disableAnimations || widget.state.browser.reducedMotion,
        ),
        child: child!,
      );
    },
  );
}
