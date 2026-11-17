import 'package:flutter/widgets.dart';

import 'app_state.dart';

class AppContext extends InheritedWidget {
  final AppState state;
  final void Function(String path, Map<String, String> params) navigate;
  final VoidCallback back;
  final void Function(String message) toast;
  final Future<void> Function() region;
  const AppContext({
    super.key,
    required this.state,
    required this.navigate,
    required this.back,
    required this.toast,
    required this.region,
    required super.child,
  });
  void go(String path, [Map<String, String> params = const {}]) =>
      navigate(path, params);
  static AppContext of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<AppContext>()!;
  @override
  bool updateShouldNotify(AppContext oldWidget) => true;
}
