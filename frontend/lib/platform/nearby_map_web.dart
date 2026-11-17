import 'dart:async';
import 'dart:convert';
import 'dart:js_interop';

import 'package:material_ui/material_ui.dart';
import 'package:web/web.dart' as web;

@JS('myaiMountMap')
external _MapHandle _mount(
  JSObject host,
  JSFunction onMove,
  JSFunction onSelect,
);

extension type _MapHandle._(JSObject _) implements JSObject {
  external void setNotices(JSString payload);
  external void dispose();
}

Future<void>? _scripts;
Future<void> _loadScripts() => _scripts ??= (() async {
  try {
    for (final name in ['map-config.js', 'kakao-map.js']) {
      final done = Completer<void>();
      final script = web.HTMLScriptElement()..src = name;
      script.onload = ((web.Event _) {
        if (!done.isCompleted) done.complete();
      }).toJS;
      script.onerror = ((web.Event _) {
        if (!done.isCompleted) done.completeError(StateError('지도 코드 로드 실패'));
      }).toJS;
      web.document.head!.append(script);
      try {
        await done.future.timeout(const Duration(seconds: 15));
      } finally {
        script.onload = null;
        script.onerror = null;
        script.remove();
      }
    }
  } catch (_) {
    _scripts = null;
    rethrow;
  }
})();
Widget nearbyMapView({
  required List<Map<String, Object>> notices,
  required String? selectedId,
  required ValueChanged<String?> onSelect,
  required ValueChanged<Map<String, double>> onBounds,
}) => _NearbyMap(
  notices: notices,
  selectedId: selectedId,
  onSelect: onSelect,
  onBounds: onBounds,
);

class _NearbyMap extends StatefulWidget {
  final List<Map<String, Object>> notices;
  final String? selectedId;
  final ValueChanged<String?> onSelect;
  final ValueChanged<Map<String, double>> onBounds;
  const _NearbyMap({
    required this.notices,
    required this.selectedId,
    required this.onSelect,
    required this.onBounds,
  });
  @override
  State<_NearbyMap> createState() => _NearbyMapState();
}

class _NearbyMapState extends State<_NearbyMap> {
  _MapHandle? handle;
  bool failed = false;
  void sync() => handle?.setNotices(
    jsonEncode({'items': widget.notices, 'selectedId': widget.selectedId}).toJS,
  );
  @override
  void didUpdateWidget(covariant _NearbyMap oldWidget) {
    super.didUpdateWidget(oldWidget);
    sync();
  }

  @override
  void dispose() {
    handle?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => failed
      ? Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text('지도를 불러오지 못했어요.'),
              TextButton(
                onPressed: () => setState(() => failed = false),
                child: const Padding(
                  padding: EdgeInsets.all(16),
                  child: Text('지도 다시 시도'),
                ),
              ),
            ],
          ),
        )
      : HtmlElementView.fromTagName(
          tagName: 'div',
          onElementCreated: (element) async {
            try {
              await _loadScripts();
              if (!mounted) return;
              handle = _mount(
                element as JSObject,
                ((JSString value) {
                  if (!mounted) return;
                  final decoded =
                      jsonDecode(value.toDart) as Map<String, dynamic>;
                  widget.onBounds(
                    decoded.map(
                      (key, value) => MapEntry(key, (value as num).toDouble()),
                    ),
                  );
                }).toJS,
                ((JSString? id) {
                  if (mounted) widget.onSelect(id?.toDart);
                }).toJS,
              );
              sync();
            } catch (_) {
              if (mounted) setState(() => failed = true);
            }
          },
        );
}

// 투명한 플랫폼 뷰로 하단 시트/상단 조작의 터치가 native 지도에 전달되지 않게 한다.
Widget mapTouchPanel({required Widget child}) => Stack(
  children: [
    Positioned.fill(
      child: HtmlElementView.fromTagName(
        tagName: 'div',
        onElementCreated: (element) {
          final host = element as web.HTMLElement;
          host.style.pointerEvents = 'auto';
          host.setAttribute('aria-hidden', 'true');
          host.setAttribute('data-map-touch-panel', '');
        },
      ),
    ),
    child,
  ],
);
