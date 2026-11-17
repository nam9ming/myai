// 카카오 공식 SDK. 회의용 위치는 별도 데모 JSON에서만 전달받는다.
(() => {
  let sdk;
  let viewport = {lat:37.0069, lng:127.2721, level:5};
  const initial = {...viewport};
  function loadSdk() {
    if (window.kakao?.maps?.Map) return Promise.resolve();
    if (sdk) return sdk;
    sdk = new Promise((resolve, reject) => {
      if (!/^[a-f0-9]{32}$/i.test(window.myaiMapKey || '')) {
        reject(new Error('지도 키가 설정되지 않았어요.')); return;
      }
      const script = document.createElement('script');
      let settled = false;
      const timer = setTimeout(() => finish(false), 15000);
      const finish = ok => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        script.onload = script.onerror = null;
        if (ok) resolve();
        else { script.remove(); sdk = null; reject(new Error('지도를 불러오지 못했어요. 네트워크와 지도 사용 설정을 확인해 주세요.')); }
      };
      script.src = 'https://dapi.kakao.com/v2/maps/sdk.js?autoload=false&appkey=' + encodeURIComponent(window.myaiMapKey);
      script.onerror = () => finish(false);
      script.onload = () => {
        if (!window.kakao?.maps?.load) return finish(false);
        window.kakao.maps.load(() => finish(true));
      };
      document.head.append(script);
    });
    // 설정 누락도 재시도할 수 있게 한다.
    sdk.catch(() => { sdk = null; });
    return sdk;
  }
  window.myaiMountMap = (host, onMove, onSelect = () => {}) => {
    let disposed = false, map, marker, busy = false, locationRequest = 0;
    host.setAttribute('data-myai-map', '');
    host.style.cssText = 'width:100%;height:100%;position:relative;background:#fafaf7;color:#242724;font:14px system-ui,sans-serif';
    const toolbar = document.createElement('div');
    toolbar.style.cssText = 'position:absolute;left:12px;top:116px;z-index:5;display:flex;flex-wrap:wrap;gap:5px;max-width:calc(100% - 24px);font-size:12px';
    const canvas = document.createElement('div');
    canvas.setAttribute('role','region'); canvas.setAttribute('aria-label','카카오 지도');
    canvas.tabIndex = 0;
    canvas.style.cssText = 'position:absolute;inset:0';
    const status = document.createElement('div');
    status.setAttribute('role','status'); status.setAttribute('aria-live','polite');
    status.style.cssText = 'position:absolute;left:12px;right:12px;top:170px;z-index:6;padding:8px 12px;border-radius:12px;font-size:12px;background:#fff';
    const message = value => { if (!disposed) { status.textContent = value; status.hidden = !value; } };
    function button(label, action) {
      const button = document.createElement('button');
      button.textContent = label; button.type = 'button';
      button.style.cssText = 'min-width:44px;min-height:44px;padding:8px 10px;border:1px solid #cbd6ce;border-radius:12px;background:white;color:#ee663b;font:inherit;cursor:pointer';
      button.onclick = action; toolbar.append(button); return button;
    }
    const locate = button('내 주변 보기', () => location(false));
    const zoomIn = button('확대', () => { if(map) map.setLevel(Math.max(1,map.getLevel()-1)); });
    const zoomOut = button('축소', () => { if(map) map.setLevel(Math.min(14,map.getLevel()+1)); });
    const reset = button('안성으로', () => {
      if (!map) return;
      const home = noticeData.shop || initial;
      map.setLevel(noticeData.shop ? 4 : initial.level); map.setCenter(new kakao.maps.LatLng(home.lat,home.lng));
      message('');
    });
    const allNotices = button('전체 소식', () => {
      if (!map || !noticeData.items.length) return;
      const bounds = new kakao.maps.LatLngBounds();
      if (noticeData.shop) bounds.extend(new kakao.maps.LatLng(noticeData.shop.lat,noticeData.shop.lng));
      for (const item of noticeData.items) {
        bounds.extend(new kakao.maps.LatLng(item.lat,item.lng));
        for (const point of item.route?.path || []) bounds.extend(new kakao.maps.LatLng(point.lat,point.lng));
      }
      map.setBounds(bounds,35,25,35,25); message('');
    });
    const retry = button('지도 재시도', start); retry.hidden = true;
    const style = document.createElement('style');
    style.textContent = `
      .myai-pin {position:relative;display:flex;align-items:center;justify-content:center;
        min-width:44px;min-height:44px;border:0;padding:0;border-radius:18px;background:transparent;
        color:#242724;cursor:pointer;font:600 12px system-ui,sans-serif}
      .myai-pin img {width:44px;height:44px;filter:drop-shadow(0 2px 3px #0002)}
      .myai-pin-label {position:absolute;top:100%;display:none;background:#fffdf8;border:1px solid #c4d3c9;
        border-radius:20px;padding:5px 9px;white-space:nowrap;box-shadow:0 2px 6px #0001}
      .myai-pin:hover .myai-pin-label,.myai-pin:focus-visible .myai-pin-label,
      .myai-pin[aria-pressed=true] .myai-pin-label {display:block}
      .myai-pin:focus-visible {outline:3px solid #ee663b;outline-offset:3px}
      .myai-pin[aria-pressed=true] {background:#fff1e9;border:2px solid #ee663b}
      .myai-pin[aria-pressed=true] img {width:52px;height:52px;animation:myai-greet .65s ease-out}
      [data-myai-map][data-overview=true] .myai-pin img {width:32px;height:32px}
      [data-myai-map][data-overview=true] .myai-pin[aria-pressed=true] img {width:44px;height:44px}
      [data-myai-map][data-overview=true] [data-route-endpoint] {visibility:hidden}
      @keyframes myai-greet {0%,100% {transform:scale(1)} 35% {transform:translateY(-8px) rotate(-9deg) scale(1.12)} 65% {transform:rotate(7deg)}}
      @media (prefers-reduced-motion:reduce) {.myai-pin img {animation:none!important}}
    `;
    const credit = document.createElement('div');
    credit.style.cssText = 'padding:2px 8px;text-align:right;background:#ffffff;font:10px system-ui';
    const source = document.createElement('a');
    source.href = 'https://www.openstreetmap.org/copyright';
    source.textContent = '구간 위치 © OpenStreetMap 기여자';
    source.style.color = '#56675e';credit.append(source);
    host.replaceChildren(style, toolbar, canvas, status);
    function location(automatic) {
      if (!map || busy || disposed) return;
      if (!navigator.geolocation || !window.isSecureContext) {
        message('이 브라우저에서는 현재 위치를 사용할 수 없어요. 지도를 직접 이동해 주세요.'); return;
      }
      busy = true; locate.disabled = true;
      const request = ++locationRequest;
      message('현재 위치를 확인하고 있어요.');
      const valid = () => !disposed && request === locationRequest;
      navigator.geolocation.getCurrentPosition(position => {
        if (!valid()) return;
        busy = false; locate.disabled = false;
        // 자동 요청 중 사용자가 이동했다면 화면을 다시 끌어오지 않는다.
        if (automatic && moved) { message('지도 탐색을 유지해요. 내 주변 보기를 누르면 현재 위치로 이동해요.'); return; }
        const {latitude, longitude} = position.coords;
        if (!Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude)>90 || Math.abs(longitude)>180) {
          message('현재 위치를 확인할 수 없어요. 지도를 직접 이동해 주세요.'); return;
        }
        const point = new kakao.maps.LatLng(latitude,longitude);
        map.setCenter(point); map.setLevel(4);
        if (marker) marker.setMap(null);
        const dot = document.createElement('span');
        dot.textContent = '내 위치';
        dot.style.cssText = 'display:block;background:#ee663b;color:white;border:3px solid white;border-radius:16px;padding:6px 10px;font:13px system-ui;box-shadow:0 1px 5px #555';
        marker = new kakao.maps.CustomOverlay({position:point,content:dot,yAnchor:1}); marker.setMap(map);
        message('현재 위치로 이동했어요.');
      }, error => {
        if (!valid()) return;
        busy = false; locate.disabled = false;
        message(error.code === 1
          ? '위치 권한이 없어요. 브라우저 설정을 확인하거나 지도를 직접 이동해 주세요.'
          : error.code === 3 ? '위치 확인 시간이 초과됐어요. 내 주변 보기를 다시 눌러 주세요.'
          : '현재 위치를 확인할 수 없어요. 지도를 직접 이동해 주세요.');
      }, {enableHighAccuracy:false,timeout:10000,maximumAge:60000});
    }
    let moved = false;
    const save = () => {
      host.dataset.overview = String(map.getLevel() >= 6);
      const center = map.getCenter();
      if (!noticeData.shop) viewport = {lat:center.getLat(),lng:center.getLng(),level:map.getLevel()};
      const bounds = map.getBounds();
      const sw = bounds.getSouthWest(), ne = bounds.getNorthEast();
      if (!disposed) onMove(JSON.stringify({south:sw.getLat(),west:sw.getLng(),north:ne.getLat(),east:ne.getLng()}));
    };
    const drag = () => {
      moved = true; save();
      message('');
    };
    let noticeLayers = [], shopLayer, noticeData = {items:[], selectedId:null, shop:null}, lastPayload;
    const clearSelection = () => {
      if (!disposed && noticeData.selectedId != null) onSelect(null);
    };
    function renderNotices() {
      for (const layer of noticeLayers) layer.setMap(null);
      noticeLayers = [];
      if (shopLayer) {shopLayer.setMap(null);shopLayer=null;}
      if (!map || disposed) return;
      if (noticeData.shop) {
        const shop = noticeData.shop;
        const pin = document.createElement('div');
        pin.dataset.shopPin = '';
        pin.setAttribute('role','img');pin.setAttribute('aria-label','내 가게 · '+shop.label);
        pin.textContent = '내 가게';pin.title = shop.label;
        pin.style.cssText = 'position:relative;background:#ee663b;color:white;border:3px solid white;border-radius:18px;padding:8px 12px;font:700 13px system-ui;box-shadow:0 3px 10px #0004';
        const tip = document.createElement('span');
        tip.style.cssText = 'position:absolute;top:100%;left:calc(50% - 7px);border:7px solid transparent;border-top-color:#ee663b';
        pin.append(tip);
        shopLayer = new kakao.maps.CustomOverlay({position:new kakao.maps.LatLng(shop.lat,shop.lng),content:pin,yAnchor:1.3,zIndex:10});
        shopLayer.setMap(map);
      }
      host.dataset.overview = String(map.getLevel() >= 6);
      for (const item of noticeData.items) {
        const pin = document.createElement('button');
        pin.type = 'button'; pin.dataset.noticeId = item.id; pin.className = 'myai-pin';
        pin.title = item.title;
        pin.setAttribute('aria-label', '지도 마커 · ' + item.title + (item.cancelled ? ' · 취소됨' : ''));
        const selected = item.id === noticeData.selectedId;
        pin.setAttribute('aria-pressed',String(selected));
        if (item.cancelled) pin.style.opacity = '.65';
        if (item.route) {
          const path = item.route.path.map(point => new kakao.maps.LatLng(point.lat,point.lng));
          const color = item.cancelled ? '#808a88' : item.type === 'traffic' ? '#427b9b' : '#de8945';
          const line = new kakao.maps.Polyline({map,path,strokeWeight:selected?8:5,
            strokeColor:color,strokeOpacity:selected ? .95 : .6,strokeStyle:item.cancelled?'dash':'solid',zIndex:selected?4:1});
          noticeLayers.push(line);
          if (selected) {
            for (const [index, name] of [[0,item.route.start],[path.length-1,item.route.end]]) {
              const endpoint = document.createElement('span');
              endpoint.dataset.routeEndpoint = index === 0 ? 'start' : 'end';
              endpoint.textContent = (index === 0 ? '시작 · ' : '종료 · ') + name;
              endpoint.style.cssText = 'display:block;width:max-content;max-width:130px;white-space:normal;line-height:1.4;background:#fffdf8;border:2px solid '+color+';border-radius:12px;padding:5px 8px;font:600 11px system-ui;box-shadow:0 2px 5px #0002';
              const endLayer = new kakao.maps.CustomOverlay({position:path[index],content:endpoint,yAnchor:1.5,zIndex:6});
              endLayer.setMap(map);noticeLayers.push(endLayer);
            }
          }
        }
        const art = document.createElement('img');
        art.src = new URL('assets/assets/markers/'+item.type+'.svg',document.baseURI).href;
        art.alt=''; art.width=58; art.height=58; art.draggable=false;
        const label = document.createElement('span');
        label.textContent = item.label + (item.cancelled ? ' · 취소' : '');
        label.className = 'myai-pin-label';
        pin.append(art,label);
        pin.onclick = event => {
          event.stopPropagation();
          onSelect(selected ? null : item.id);
        };
        const layer = new kakao.maps.CustomOverlay({position:new kakao.maps.LatLng(item.lat,item.lng),content:pin,clickable:true,yAnchor:.7,zIndex:selected?8:2});
        layer.setMap(map); noticeLayers.push(layer);
      }
    }
    const resize = new ResizeObserver(() => { if(map && !disposed) { const center=map.getCenter(); map.relayout(); map.setCenter(center); } });
    resize.observe(canvas);
    async function start() {
      retry.hidden = true;
      message('카카오 지도를 불러오고 있어요.');
      for (const control of [locate,zoomIn,zoomOut,reset,allNotices]) control.disabled = true;
      try {
        await loadSdk();
        // 별도 다운로드 없이 앱과 같은 한글 바이트로 등록한 native 폰트를 기다린다.

        // HtmlElementView 콜백 시점에는 DOM에 아직 붙지 않을 수 있다.
        while (!host.isConnected && !disposed) await new Promise(resolve => setTimeout(resolve,30));
        if (disposed) return;
        const home = noticeData.shop || viewport;
        map = new kakao.maps.Map(canvas,{center:new kakao.maps.LatLng(home.lat,home.lng),level:noticeData.shop ? 4 : viewport.level,scrollwheel:!noticeData.shop});
        kakao.maps.event.addListener(map,'idle',save);
        kakao.maps.event.addListener(map,'dragend',drag);
        kakao.maps.event.addListener(map,'click',clearSelection);
        canvas.onkeydown = event => {
          const delta = {ArrowLeft:[-80,0],ArrowRight:[80,0],ArrowUp:[0,-80],ArrowDown:[0,80]}[event.key];
          if (delta) {event.preventDefault();map.panBy(...delta);drag();}
        };
        renderNotices(); save();
        message('');
        for (const control of [locate,zoomIn,zoomOut,reset,allNotices]) control.disabled = false;

      } catch (error) {
        if (disposed) return;
        message(error.message); retry.hidden = false;
      }
    }
    start();
    return {
      setBottomInset(pixels) {
        if (!disposed && Number.isFinite(pixels) && pixels >= 0) canvas.style.bottom = Math.min(pixels, host.clientHeight) + 'px';
      },
      setNotices(payload) {
        if (disposed || payload === lastPayload) return;
        try {
          const data=JSON.parse(payload);
          if (!data || !Array.isArray(data.items) || data.items.length>100) throw new Error();
          if (data.shop != null && (typeof data.shop.label !== 'string' || !data.shop.label.trim() ||
              !Number.isFinite(data.shop.lat) || !Number.isFinite(data.shop.lng) ||
              Math.abs(data.shop.lat)>90 || Math.abs(data.shop.lng)>180)) throw new Error();
          const shopChanged = JSON.stringify(data.shop ?? null) !== JSON.stringify(noticeData.shop ?? null);
          const ids=new Set();
          for (const item of data.items) {
            if (!item || typeof item.id!=='string' || ids.has(item.id) ||
                !['construction','event','traffic','education','support','life'].includes(item.type) ||
                typeof item.title!=='string' || typeof item.label!=='string' ||
                typeof item.cancelled!=='boolean' || !Number.isFinite(item.lat) ||
                !Number.isFinite(item.lng) || Math.abs(item.lat)>90 || Math.abs(item.lng)>180) throw new Error();
            if (item.route != null) {
              const route = item.route;
              if (!route || typeof route.start !== 'string' || !route.start.trim() ||
                  typeof route.end !== 'string' || !route.end.trim() || !Array.isArray(route.path) ||
                  route.path.length < 2 || route.path.length > 80 || route.path.some(point =>
                    !point || !Number.isFinite(point.lat) || !Number.isFinite(point.lng) ||
                    Math.abs(point.lat)>90 || Math.abs(point.lng)>180)) throw new Error();
            }

            ids.add(item.id);
          }
          const selected = data.items.find(item => item.id === data.selectedId);
          const changed = data.selectedId !== noticeData.selectedId;
          noticeData=data;lastPayload=payload;renderNotices();
          reset.textContent = data.shop ? '내 가게로' : '안성으로';
          locate.hidden = !!data.shop;
          host.dataset.shopMap = String(!!data.shop);
          if (map && shopChanged && data.shop) {
            map.setLevel(4);map.setCenter(new kakao.maps.LatLng(data.shop.lat,data.shop.lng));
          }
          if (map && changed && selected) {
            if (selected.route) {
              const bounds = new kakao.maps.LatLngBounds();
              for (const point of selected.route.path) bounds.extend(new kakao.maps.LatLng(point.lat,point.lng));
              map.setBounds(bounds,65,65,80,65);
            } else {
              const point = new kakao.maps.LatLng(selected.lat,selected.lng);
              // 작은 지도에서는 진행 중 pan 애니메이션이 가게 복귀를 덮어쓰지 않게 한다.
              if (noticeData.shop) map.setCenter(point);
              else map.panTo(point);
            }
          }
        } catch (_) { message('지도 표시 자료를 불러오지 못했어요. 다시 열어 주세요.'); }
      },
      setEnabled(enabled) {host.style.pointerEvents=enabled?'auto':'none';host.inert=!enabled;},
      dispose() {
        disposed=true;locationRequest++;resize.disconnect();
        if(map) {save();kakao.maps.event.removeListener(map,'idle',save);kakao.maps.event.removeListener(map,'dragend',drag);kakao.maps.event.removeListener(map,'click',clearSelection);}
        if(marker)marker.setMap(null);
        if(shopLayer)shopLayer.setMap(null);
        for(const layer of noticeLayers)layer.setMap(null);
        noticeLayers=[];
        host.replaceChildren();
      },
    };
  };
})();
