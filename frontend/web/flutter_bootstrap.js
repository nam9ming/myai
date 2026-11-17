{{flutter_js}}
{{flutter_build_config}}

_flutter.loader.load({
  config: {
    canvasKitBaseUrl: new URL('canvaskit/', document.baseURI).href,
  },
  onEntrypointLoaded: async function (engineInitializer) {
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
}).catch((error) => {
  console.error('Flutter loader failed', error);
  window.yeogiStartup?.fail();
});
