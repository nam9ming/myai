import 'package:material_ui/material_ui.dart';

import 'app_state.dart';
import 'shell.dart';
import '../data/models.dart';

class AppRoute {
  final Uri uri;
  const AppRoute(this.uri);
  String get path => uri.path;
  Map<String, String> get params => uri.queryParameters;
  factory AppRoute.parse(Uri input) {
    var uri = input;
    if (uri.fragment.startsWith('/')) uri = Uri.parse(uri.fragment);
    final path = uri.path.isEmpty ? '/' : uri.path;
    final params = Map<String, String>.from(uri.queryParameters);
    if (path == '/start') {
      final step = int.tryParse(params['step'] ?? '0') ?? 0;
      params['step'] = step.clamp(0, 5).toString();
    }
    if (path == '/list' || path == '/search') {
      final parsed = NoticeQuery.fromParams(params);
      params
        ..clear()
        ..addAll(parsed.params);
    }
    return AppRoute(
      Uri(path: path, queryParameters: params.isEmpty ? null : params),
    );
  }
}

class AppRouteParser extends RouteInformationParser<AppRoute> {
  @override
  Future<AppRoute> parseRouteInformation(RouteInformation information) async =>
      AppRoute.parse(information.uri);
  @override
  RouteInformation restoreRouteInformation(AppRoute configuration) =>
      RouteInformation(uri: configuration.uri);
}

class AppRouter extends RouterDelegate<AppRoute>
    with ChangeNotifier, PopNavigatorRouterDelegateMixin<AppRoute> {
  final AppState state;
  @override
  final GlobalKey<NavigatorState> navigatorKey = GlobalKey<NavigatorState>();
  AppRoute route = AppRoute(Uri(path: '/'));
  final List<AppRoute> history = [];
  final Map<String, double> scrollOffsets = {};
  AppRouter(this.state);
  @override
  AppRoute get currentConfiguration => route;
  void go(String path, [Map<String, String> params = const {}]) {
    final next = AppRoute.parse(
      Uri(path: path, queryParameters: params.isEmpty ? null : params),
    );
    if (next.uri == route.uri) return;
    if (history.isEmpty) history.add(route);
    history.add(next);
    route = next;
    notifyListeners();
  }

  void back() {
    if (history.length > 1) {
      state.browser.back();
    } else {
      go('/list');
    }
  }

  @override
  Future<void> setNewRoutePath(AppRoute configuration) async {
    if (configuration.path == '/') {
      route = AppRoute(
        Uri(path: state.settings.onboarded ? '/home' : '/start'),
      );
    } else {
      route = configuration;
    }
    final existing = history.lastIndexWhere((r) => r.uri == route.uri);
    if (existing >= 0) {
      history.removeRange(existing + 1, history.length);
    } else {
      history.add(route);
    }
  }

  @override
  Future<bool> popRoute() async {
    if (route.path == '/home' || route.path == '/start') return false;
    back();
    return true;
  }

  @override
  Widget build(BuildContext context) => Navigator(
    key: navigatorKey,
    pages: [
      MaterialPage<void>(
        key: ValueKey(route.path),
        child: AppShell(state: state, router: this, route: route),
      ),
    ],
    onDidRemovePage: (_) {},
  );
}
