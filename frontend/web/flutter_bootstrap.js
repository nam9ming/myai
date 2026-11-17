{{flutter_js}}
{{flutter_build_config}}

(async () => {
  const canvasKitBaseUrl = new URL('canvaskit/', document.baseURI).href;
  let entrypointBlob;

  // 지원 브라우저에서만 압축 자산을 사용하며, 실패하면 원본 로더로 복귀한다.
  if (new URL(location.href).searchParams.get('startup') !== 'raw' &&
      typeof DecompressionStream !== 'undefined' &&
      _flutter.buildConfig.builds.some((build) => build.compileTarget === 'dart2js')) {
    try {
      const unpack = async (path) => {
        const response = await fetch(new URL(path, document.baseURI));
        if (!response.ok) throw new Error(`Startup asset ${response.status}: ${path}`);
        return new Response(response.body.pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
      };
      const chromium = (navigator.vendor === 'Google Inc.' || navigator.userAgent.includes('Edg/')) &&
        typeof ImageDecoder !== 'undefined' && typeof Intl.v8BreakIterator !== 'undefined' &&
        typeof Intl.Segmenter !== 'undefined';
      const variant = chromium ? 'chromium/' : '';
      const [javascript, wasm, canvasKitModule] = await Promise.all([
        unpack('main.dart.js.gz'),
        unpack(`canvaskit/${variant}canvaskit.wasm.gz`).then(WebAssembly.compile),
        import(`${canvasKitBaseUrl}${variant}canvaskit.js`),
      ]);
      // 고정 SDK의 CanvasKit 초기화 훅에 컴파일한 모듈을 전달한다.
      window.flutterCanvasKit = await canvasKitModule.default({
        instantiateWasm(imports, receiveInstance) {
          const instance = new WebAssembly.Instance(wasm, imports);
          receiveInstance(instance, wasm);
          return instance.exports;
        },
      });
      entrypointBlob = URL.createObjectURL(new Blob([javascript], { type: 'application/javascript' }));
      for (const build of _flutter.buildConfig.builds) {
        if (build.compileTarget === 'dart2js') build.mainJsPath = entrypointBlob;
      }
    } catch (error) {
      console.warn('Compressed startup unavailable; using original assets', error);
    }
  }

  await _flutter.loader.load({
    config: { canvasKitBaseUrl },
    onEntrypointLoaded: async function (engineInitializer) {
      if (entrypointBlob) URL.revokeObjectURL(entrypointBlob);
      try {
        window.yeogiStartup?.phase('화면 구성 요소를 준비하고 있어요…');
        const appRunner = await engineInitializer.initializeEngine();
        window.yeogiStartup?.phase('동네 소식을 불러오고 있어요…');
        await appRunner.runApp();
      } catch (error) {
        console.error('Flutter startup failed', error);
        window.yeogiStartup?.fail();
      }
    },
  });
})().catch((error) => {
  console.error('Flutter loader failed', error);
  window.yeogiStartup?.fail();
});
