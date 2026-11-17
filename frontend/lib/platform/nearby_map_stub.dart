import 'package:flutter/widgets.dart';

Widget nearbyMapView({
  double bottomInset = 0,
  required List<Map<String, Object>> notices,
  required String? selectedId,
  required ValueChanged<String?> onSelect,
  required ValueChanged<Map<String, double>> onBounds,
}) => const Center(child: Text('지도는 웹 브라우저에서 표시돼요.'));

Widget mapTouchPanel({required Widget child}) => child;
