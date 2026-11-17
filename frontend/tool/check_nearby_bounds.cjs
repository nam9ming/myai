const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync('web/kakao-map.js', 'utf8');
const context = {window: {}};
vm.runInNewContext(source, context);
for (const height of [840, 600, 140]) {
  const rect = context.nearbyQueryRect(390, height, 1000);
  assert.equal(rect.bottom - rect.top, 936);
  assert.ok(rect.top <= -48 && rect.bottom >= height + 48);
  assert.equal(rect.left, -48);
  assert.equal(rect.right, 438);
  assert.equal(rect.top - height / 2, -468);
  assert.equal(rect.bottom - height / 2, 468);
}
for (const label of ['내 주변 보기', '확대', '축소', '안성으로', '전체 소식']) {
  assert.ok(!source.includes(`button('${label}'`));
}
console.log('Nearby bounds and removed controls: PASS');
