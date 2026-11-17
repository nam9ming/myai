const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const web=path.resolve(process.argv[2]);const base='https://cehub.hknu.ac.kr/team_asai1/app/';const output=path.resolve(process.argv[3]);
const policy="sandbox allow-scripts; base-uri 'none'; object-src 'none'; form-action 'none'; frame-src 'none'; frame-ancestors 'self'; connect-src https://cehub.hknu.ac.kr/team_asai1/";
(async()=>{fs.mkdirSync(output,{recursive:true});const browser=await chromium.launch({headless:true,args:['--no-sandbox']});try{
 for(const mode of ['compressed','apple-path','raw-fallback','raw-mode','missing-gzip']){
  const context=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true});const p=await context.newPage();const urls=[],errors=[],fontWarnings=[];
  p.on('request',r=>urls.push(r.url()));p.on('pageerror',e=>errors.push(e.message));p.on('console',m=>{if(/Failed to (parse|load) font/.test(m.text()))fontWarnings.push(m.text())});
  if(mode==='apple-path')await p.addInitScript(()=>Object.defineProperty(navigator,'vendor',{get:()=> 'Apple Computer, Inc.'}));
  if(mode==='raw-fallback')await p.addInitScript(()=>Object.defineProperty(window,'DecompressionStream',{value:undefined}));
  await p.route('**/*',async route=>{
   const url=route.request().url();if(!url.startsWith(base))return route.abort();
   const name=decodeURIComponent(new URL(url).pathname.slice(new URL(base).pathname.length))||'index.html';const file=path.resolve(web,name);
   if(!file.startsWith(web+path.sep)||!fs.existsSync(file)||(mode==='missing-gzip'&&name.endsWith('.gz')))return route.fulfill({status:404,body:'not found',headers:{'Access-Control-Allow-Origin':'*'}});
   const ext=path.extname(file);const mime={'.js':'application/javascript','.wasm':'application/wasm','.json':'application/json','.html':'text/html','.svg':'image/svg+xml','.gz':'application/gzip'}[ext]||'application/octet-stream';
   return route.fulfill({body:fs.readFileSync(file),contentType:mime,headers:{'Access-Control-Allow-Origin':'*','Cache-Control':'no-cache',...(name==='index.html'?{'Content-Security-Policy':policy}:{})}});
  });
  await p.goto(base+(mode==='raw-mode'?'?startup=raw':''),{waitUntil:'domcontentloaded'});await p.locator('#loading').waitFor({state:'detached',timeout:60000});assert.deepEqual(errors,[]);assert.deepEqual(fontWarnings,[]);
  assert.equal(urls.filter(u=>u.endsWith('NotoSansKR.woff2')).length,1,'본문 글꼴 중복 요청');
  if(mode==='compressed'||mode==='apple-path'){assert.ok(urls.some(u=>u.endsWith('main.dart.js.gz')));assert.equal(urls.filter(u=>u.endsWith('/main.dart.js')).length,0);assert.equal(urls.filter(u=>u.endsWith('.wasm')).length,0)}
  else assert.ok(urls.some(u=>u.endsWith('/main.dart.js')));
  assert.ok(await p.evaluate(()=>performance.getEntriesByName('yeogi-first-frame').length===1));await p.screenshot({path:path.join(output,mode+'.png')});fs.writeFileSync(path.join(output,mode+'.json'),JSON.stringify({urls,errors,fontWarnings},null,2));console.log('PASS',mode);await context.close();
 }
 // Flutter 초기화를 막아 로딩 화면 자체의 접근성·동작을 확인한다.
 for(const reduced of [false,true]){
  const p=await browser.newPage({viewport:{width:390,height:844},reducedMotion:reduced?'reduce':'no-preference'});await p.route('**/*',r=>r.request().url()===base?r.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(web,'index.html'))}):r.fulfill({contentType:'application/javascript',body:''}));
  await p.clock.install();await p.goto(base);await p.clock.fastForward(12001);assert.equal(await p.getByRole('button',{name:'다시 시도'}).isVisible(),true);
  const animation=await p.locator('.loading-logo span').evaluate(e=>getComputedStyle(e).animationName);assert.equal(animation==='none',reduced);await p.screenshot({path:path.join(output,reduced?'loading-reduced.png':'loading-active.png')});
  await p.evaluate(()=>window.dispatchEvent(new ErrorEvent('error',{message:'startup test'})));assert.equal(await p.locator('#loading').getAttribute('data-state'),'error');assert.equal(await p.locator('.loading-logo span').evaluate(e=>getComputedStyle(e).animationName),'none');await p.close();
 }
 console.log('PREFLIGHT COMPLETE');
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
