/* Local QA only; run against tests/handoff_server.py. Providers are NOT live. */
const assert = require('node:assert/strict');
const {mkdirSync, writeFileSync} = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');
const base = process.env.HANDOFF_URL || 'http://127.0.0.1:8891';
assert.match(base, /^http:\/\/(127\.0\.0\.1|localhost):\d+$/);
const out = path.resolve(process.env.HANDOFF_OUTPUT || 'test-results/handoff');
mkdirSync(out, {recursive:true});
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHROME_EXECUTABLE ? {executablePath:process.env.PLAYWRIGHT_CHROME_EXECUTABLE} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}, acceptDownloads:true, reducedMotion:'reduce'});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const req = page.request;
    async function api(method, url, data, key) {
      const r = await req.fetch(base + url, {method, data, headers:key ? {'Idempotency-Key':key} : {}});
      assert.ok(r.ok(), r.status() + ': ' + await r.text());
      return r.json();
    }
    assert.equal((await api('GET','/health/live')).status,'ok');
    assert.equal((await api('GET','/health/ready')).database,'available');
    const day = new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Amman',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    const end = new Date(day + 'T12:00:00Z'); end.setUTCDate(end.getUTCDate()+6);
    const farm = await api('POST','/api/ui/farms',{name:'QA Tomato Farm مزرعة البندورة للاختبار', location:'Isolated QA',latitude:32.19,longitude:35.62,
      area_dunum:1,planting_date:'2026-09-01',crop_stage:'mid_season',establishment_method:'transplanted',
      irrigation_efficiency:.9,effective_rain_fraction:.8,system_flow_liters_per_hour:1000});
    const root = '/api/ui/farms/' + farm.id;
    let sections = await api('GET',root+'/seasons');
    const season = sections.seasons[0];
    await api('PATCH',root+'/seasons/'+season.id,{name:'QA season',start_date:'2026-09-01',is_active:true,
      expected_harvest_kg:2000,assumed_sale_price_jod_per_kg:.6,projected_costs_jod:200,
      water_available_liters:4000,water_period_start:day,water_period_end:end.toISOString().slice(0,10)});
    await page.goto(base+'/dashboard.html');
    await page.locator('#farm-select option[value="'+farm.id+'"]').waitFor({state:'attached'});
    await page.locator('#farm-select').selectOption(farm.id);
    await page.waitForFunction(() => document.querySelector('#farm-select').value !== '');
    if (await page.locator('html').getAttribute('lang') !== 'en') await page.locator('#lang-btn').click();
    await page.locator('#btn-manage').click();
    const dialog = page.locator('.manage-dialog');
    const operation = dialog.locator('select').first();
    async function record(op, data) {
      await operation.selectOption(op);
      for (const [key,value] of Object.entries(data)) await dialog.locator('[name="'+key+'"]').fill(String(value));
      await dialog.locator('button[type=submit]').click();
      await page.waitForFunction(() => /Saved/.test(document.querySelector('.manage-output').textContent));
    }
    const before = await api('GET',root+'/financials');
    await record('expenses',{date:day,category:'labor',description:'Verified QA labor',amount_jod:'12.345'});
    const after = await api('GET',root+'/financials');
    assert.equal(after.recorded_costs_jod, before.recorded_costs_jod + 12.345);
    await record('irrigation',{date:day,volume_m3:'1.25',notes:'QA confirmed'});
    await record('harvests',{date:day,quantity_kg:'50',grade:'A'});
    await record('sales',{date:day,quantity_kg:'20',unit_price_jod:'.75',buyer:'QA buyer'});
    const stored = await api('GET',root+'/financials');
    const irrigation = await api('GET',root+'/irrigation');
    const payload = {date:day,category:'retry',description:'Retry test',amount_jod:1};
    const retryKey = 'qa-'+farm.id;
    const one = await api('POST',root+'/expenses',payload,retryKey);
    const two = await api('POST',root+'/expenses',payload,retryKey);
    assert.equal(one.id,two.id);
    assert.equal((await req.post(base+root+'/expenses',{data:{...payload,amount_jod:2},headers:{'Idempotency-Key':retryKey}})).status(),409);
    assert.equal((await req.get(base+'/api/ui/farms/not-found')).status(),404);
    await operation.selectOption('simulate');
    await dialog.locator('button[type=submit]').click();
    assert.match(await dialog.locator('.manage-output').innerText(),/at least one/);
    await dialog.locator('[name="water_available_liters"]').fill('0');
    await dialog.locator('[name="additional_costs_jod"]').fill('25');
    let count=0;
    await page.route('**/simulate',async route => {count++; await new Promise(r=>setTimeout(r,350)); await route.continue();});
    await dialog.locator('form').evaluate(form => { form.requestSubmit(); form.requestSubmit(); });
    await dialog.locator('.sim-card').first().waitFor();
    assert.equal(count,1);
    assert.equal(await dialog.locator('.sim-card').count(),7);
    assert.match(await dialog.locator('.sim-results').innerText(),/Not saved/);
    assert.match(await dialog.locator('[data-metric="water_available_liters"]').innerText(),/0 L/);
    await page.screenshot({path:path.join(out,'simulation-en.png'),fullPage:true});
    await page.unroute('**/simulate');
    const baselineAfter = await api('GET',root+'/financials');
    assert.equal(baselineAfter.projected_costs_jod, stored.projected_costs_jod + 1);
    assert.equal((await api('GET',root+'/irrigation')).records.length,irrigation.records.length);
    await page.route('**/simulate',route=>route.fulfill({status:503,contentType:'application/json',body:'{"detail":"QA failure"}'}));
    await dialog.locator('button[type=submit]').click();
    await page.waitForFunction(()=>document.querySelector('.manage-output').textContent.includes('could not'));
    assert.equal(await dialog.locator('.sim-card').count(),0);
    await page.unroute('**/simulate');
    await dialog.locator('.manage-close').click();
    await page.locator('#lang-btn').click();
    await page.locator('#btn-manage').click();
    await operation.selectOption('simulate');
    await dialog.locator('[name="water_available_liters"]').fill('7000');
    await dialog.locator('button[type=submit]').click();
    await dialog.locator('.sim-card').first().waitFor();
    assert.match(await dialog.locator('.sim-results').innerText(),/لم يتم الحفظ/);
    assert.equal(await page.locator('html').getAttribute('dir'),'rtl');
    await page.screenshot({path:path.join(out,'simulation-ar.png'),fullPage:true});
    await dialog.locator('.manage-close').click();
    for (const [language,message] of [['ar','لماذا يوجد عجز في المياه؟'],['en','How is the break-even price calculated?']]) {
      const answer = await api('POST','/api/ui/assistant/chat',{farm_id:farm.id,language,message});
      assert.equal(answer.origin,'fallback'); assert.ok(answer.sources.length); assert.ok(answer.answer);
    }
    // Use the real report button and capture its frozen dashboard snapshot.
    // The retry check above wrote through HTTP directly, so refresh the displayed snapshot.
    await page.reload();
    await page.locator('#farm-select').selectOption(farm.id);
    await page.waitForTimeout(800);
    await page.evaluate(() => {
      const download = window.SFA_REPORT.download;
      window.SFA_REPORT.download = async snap => {window.__qaSnapshot = snap; return download(snap);};
    });
    for (const lang of ['ar','en']) {
      if (await page.locator('html').getAttribute('lang') !== lang) await page.locator('#lang-btn').click();
      await page.waitForTimeout(600);
      const downloaded = page.waitForEvent('download');
      await page.locator('#btn-report').click();
      await (await downloaded).saveAs(path.join(out,'report-'+lang+'.pdf'));
      const snap = await page.evaluate(()=>window.__qaSnapshot);
      writeFileSync(path.join(out,'snapshot-'+lang+'.json'),JSON.stringify(snap,null,2));
      assert.equal(snap.sections.financials.data.projected_costs_jod,baselineAfter.projected_costs_jod);
    }
    await page.locator('#btn-recs').click();
    const player = page.locator('#dlg-recs .voice').first();
    await player.locator('.v-listen').click();
    await player.locator('.v-msg.err').waitFor();
    assert.equal(await player.locator('.v-ctr').isVisible(),false);
    await player.locator('.retry').click();
    await player.locator('.v-msg.err').waitFor();
    await page.screenshot({path:path.join(out,'voice-unconfigured.png'),fullPage:true});
    // Deterministic browser-fallback and transport control checks, not provider audio.
    const controls = await page.evaluate(async () => {
      let audio;
      class MockAudio extends EventTarget {
        constructor(){super(); audio=this; this.paused=true; this.ended=false; this.duration=60; this.currentTime=0;}
        play(){this.paused=false;this.dispatchEvent(new Event('play'));return Promise.resolve();}
        pause(){this.paused=true;this.dispatchEvent(new Event('pause'));}
        load(){} removeAttribute(){}
      }
      const originalAudio=window.Audio, originalRequest=window.SFA_API.requestVoice;
      window.Audio=MockAudio;
      window.SFA_API.requestVoice=async()=>({blob:new Blob(['mock transport'],{type:'audio/mpeg'}),text:'نص اختبار',demoMode:false});
      const rec={id:'qa-transport',topic:'data',summary:{ar:'ملخص',en:'Summary'},action:{ar:'راجع',en:'Review'},why:{ar:'سبب',en:'Reason'},limitations:[],sources:[],evidence:[]};
      const p=window.SFA_VOICE.createPlayer(rec,{lang:'en',farmId:'qa'});
      document.body.appendChild(p); p.querySelector('.v-listen').click();
      await new Promise(r=>setTimeout(r,40));
      const started=!audio.paused;
      p.querySelector('.v-ctr button').click(); const paused=audio.paused;
      p.querySelector('.v-ctr button').click(); const resumed=!audio.paused;
      const seek=p.querySelector('.v-seek');seek.value=500;seek.dispatchEvent(new Event('input'));const sought=audio.currentTime===30;
      p.querySelectorAll('.v-ctr button')[1].click(); const stopped=audio.paused && audio.currentTime===0;
      p.querySelectorAll('.v-ctr button')[2].click(); const replayed=!audio.paused;
      window.SFA_VOICE.reset();p.remove();window.Audio=originalAudio;window.SFA_API.requestVoice=originalRequest;
      return {started,paused,resumed,sought,stopped,replayed};
    });
    assert.ok(Object.values(controls).every(Boolean));
    const fallback = await page.evaluate(async () => {
      const originalRequest = window.SFA_API.requestVoice;
      const descriptor = Object.getOwnPropertyDescriptor(window, 'speechSynthesis');
      const originalUtterance=window.SpeechSynthesisUtterance;
      window.SpeechSynthesisUtterance=class {constructor(text){this.text=text;}};
      let voices=[], utterance, calls=0;
      Object.defineProperty(window, 'speechSynthesis', {configurable:true,value:{cancel(){},getVoices(){return voices;},speak(u){calls++;utterance=u;}}});
      window.SFA_API.requestVoice=async()=>{throw Object.assign(new Error('offline'),{code:'UNAVAILABLE'});};
      const rec={id:'qa-fallback',topic:'data',summary:{ar:'ملخص',en:'Summary'},action:{ar:'راجع',en:'Review'},why:{ar:'سبب',en:'Reason'},limitations:[],sources:[],evidence:[]};
      const p=window.SFA_VOICE.createPlayer(rec,{lang:'en',farmId:'qa'});document.body.append(p);
      p.querySelector('.v-listen').click();await new Promise(r=>setTimeout(r,30));
      p.querySelector('.v-alt').click();const noVoice=calls===0 && p.querySelector('.v-msg').classList.contains('err');
      voices=[{lang:'ar-JO',name:'QA mock'}];p.querySelector('.v-alt').click();
      const started=calls===1 && utterance.lang==='ar-JO';utterance.onerror();
      const failed=p.querySelector('.v-msg').classList.contains('err') && p.querySelector('.v-ctr').hidden;
      window.SFA_VOICE.reset();p.remove();window.SFA_API.requestVoice=originalRequest;
      window.SpeechSynthesisUtterance=originalUtterance;
      if(descriptor) Object.defineProperty(window,'speechSynthesis',descriptor);else delete window.speechSynthesis;
      return {noVoice,started,failed};
    });
    assert.ok(Object.values(fallback).every(Boolean));
    await page.setViewportSize({width:390,height:844});
    await page.locator('#dlg-recs [data-close]').click();
    await page.locator('#btn-manage').click();
    await operation.selectOption('simulate');
    await dialog.locator('[name="water_available_liters"]').fill('0');
    await dialog.locator('button[type=submit]').click();
    await dialog.locator('.sim-card').first().waitFor();
    assert.equal(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1),true);
    await page.screenshot({path:path.join(out,'simulation-mobile.png'),fullPage:true});
    assert.deepEqual(errors,[]);
    const result={farmId:farm.id,health:true,records:true,idempotentRetry:true,simulationCards:7,
      simulationNoWrites:true,simulationLoadingDedup:true,simulationErrorRecovery:true,arabicRtl:true,
      pdfDownloads:['report-en.pdf','report-ar.pdf'],voiceUnavailable:true,voiceControlsMocked:controls,
      voiceBrowserFallbackMocked:fallback,liveProviders:false,browserErrors:errors};
    writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});

