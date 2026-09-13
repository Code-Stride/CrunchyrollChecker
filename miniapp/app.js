const tg = window.Telegram?.WebApp;
if(tg){tg.ready();tg.expand();}
const _refreshIcons = ()=>{ try{ if(window.lucide) lucide.createIcons(); }catch(e){} };

const $ = id => document.getElementById(id);
const comboInput = $('comboInput'), fileInput=$('fileInput'), fileName=$('fileName'), premiumOnly=$('premiumOnly');
const startBtn=$('startBtn'), clearBtn=$('clearBtn'), comboCount=$('comboCount');
const progressCard=$('progressCard'), barFill=$('barFill'), pctText=$('pctText'), checkedText=$('checkedText'), cpmText=$('cpmText');
const hitsText=$('hitsText'), freeText=$('freeText'), tfaText=$('2faText'), badText=$('badText'), errText=$('errText'), rateText=$('rateText');
const elapsedText=$('elapsedText'), etaText=$('etaText'), proxiesText=$('proxiesText'), ratePctText=$('ratePctText'), liveFeed=$('liveFeed');
const resultsCard=$('resultsCard'), resultsTitle=$('resultsTitle'), resultsMeta=$('resultsMeta'), hitList=$('hitList');
const exportTxt=$('exportTxt'), exportJson=$('exportJson'), exportCsv=$('exportCsv');
const poolCount=$('poolCount'), liveCount=$('liveCount'), autoCheck=$('autoCheck'), proxyInput=$('proxyInput'), addProxyBtn=$('addProxyBtn'), clearProxyBtn=$('clearProxyBtn'), refreshProxyBtn=$('refreshProxyBtn'), proxyMsg=$('proxyMsg');
const statusBox=$('statusBox'), refreshStatus=$('refreshStatus'), proxyPill=$('proxyPill'), uptimePill=$('uptimePill');

// Tabs
document.querySelectorAll('.tab').forEach(btn=>{
  btn.addEventListener('click',()=>{
    document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
    if(btn.dataset.tab==='status') loadStatus();
    if(btn.dataset.tab==='proxies') loadProxies();
    _refreshIcons();
    if(tg) tg.HapticFeedback?.impactOccurred('light');
  });
});

// Combo count
function updateCount(){
  const txt = comboInput.value;
  const lines = txt.split('\n').filter(l=>l.trim());
  // crude email:pass count
  const re = /[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}:.{3,}/g;
  const m = txt.match(re);
  const n = m? m.length : lines.length;
  comboCount.textContent = `${n} combos`;
}
comboInput.addEventListener('input', updateCount);
clearBtn.addEventListener('click',()=>{comboInput.value='';fileInput.value='';fileName.textContent='No file chosen';updateCount();hitList.innerHTML='';resultsCard.classList.add('hidden');progressCard.classList.add('hidden')});

fileInput.addEventListener('change',()=>{
  const f = fileInput.files[0];
  if(!f) return;
  fileName.textContent = `${f.name} • ${(f.size/1024/1024).toFixed(2)} MB`;
  const reader = new FileReader();
  reader.onload = e=>{ comboInput.value = e.target.result; updateCount(); };
  reader.readAsText(f);
});

// API helpers
async function api(path, opts={}){
  const url = path.startsWith('http')? path : path;
  const r = await fetch(url, {headers:{'Content-Type':'application/json', ...(opts.headers||{})}, ...opts});
  const txt = await r.text();
  try{return JSON.parse(txt)}catch{return txt}
}

// Checker — detailed
let lastResults=null;
startBtn.addEventListener('click', async ()=>{
  const text = comboInput.value.trim();
  if(!text){ alert('Paste combos first'); return; }
  startBtn.disabled=true; startBtn.innerHTML='<i data-lucide="loader-2" class="icon-sm" style="animation:spin 1s linear infinite"></i> Checking...'; _refreshIcons();;
  progressCard.classList.remove('hidden');
  resultsCard.classList.add('hidden');
  hitList.innerHTML='';
  // Reset progress
  const total = (text.match(/[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}:.{3,}/g)||[]).length || text.split('\n').filter(Boolean).length;
  updateProgress({processed:0,total,hits:[],free:[],bad:0,rate:0,err:0,twofa:0,cpm:0,elapsed:0,eta:'—',live_feed:[]});
  try{
    const res = await fetch('/api/check', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({text, premium_only: premiumOnly.checked})
    });
    const data = await res.json();
    lastResults = data;
    // Final progress
    updateProgress({...data, cpm: data.cpm||0, elapsed: data.elapsed||data.seconds||0, eta:'—'});
    showResults(data);
    if(tg) tg.HapticFeedback?.notificationOccurred('success');
  }catch(e){
    alert('Check failed: '+e);
    if(tg) tg.HapticFeedback?.notificationOccurred('error');
  }finally{
    startBtn.disabled=false; startBtn.innerHTML='<i data-lucide="rocket" class="icon-sm"></i> Start Check'; _refreshIcons();;
  }
});

function updateProgress(res){
  const total=res.total||0, processed=res.processed||0;
  const pct = total? Math.round(processed/total*100):0;
  // one decimal for <10
  const raw = total? (processed/total*100):0;
  const pctStr = raw<10 && raw!==0 ? raw.toFixed(1) : String(Math.round(raw));
  barFill.style.width = pct+'%';
  pctText.textContent = pctStr+'%';
  checkedText.textContent = `${processed}/${total}`;
  cpmText.textContent = `${res.cpm||0} cpm`;
  hitsText.textContent = res.hits? res.hits.length : 0;
  freeText.textContent = res.free? res.free.length : 0;
  tfaText.textContent = res.twofa||0;
  badText.textContent = res.bad||0;
  errText.textContent = res.err||0;
  rateText.textContent = res.rate||0;
  elapsedText.textContent = fmtDur(res.elapsed||0);
  etaText.textContent = res.eta||'—';
  proxiesText.textContent = res.proxies||0;
  const succ = processed? ((res.hits?res.hits.length:0)/processed*100).toFixed(1) : 0;
  ratePctText.textContent = succ+'%';
  // live feed
  if(res.live_feed && res.live_feed.length){
    liveFeed.innerHTML = res.live_feed.slice(-3).map(e=>`<div>${esc(e)}</div>`).join('');
    _refreshIcons();
  } else {
    liveFeed.innerHTML = '<i>—</i>';
  }
  // pills — preserve SVG, update span
  try{
    const pp = proxyPill.querySelector('span'); if(pp) pp.textContent = `${res.proxies||0} live`; else proxyPill.textContent = `${res.proxies||0} live`;
  }catch(e){ proxyPill.textContent = `${res.proxies||0} live`; }
}
function fmtDur(s){
  s=Math.round(s);
  const m=Math.floor(s/60), sec=s%60, h=Math.floor(m/60), mm=m%60;
  if(h) return `${h}h ${mm}m ${sec}s`;
  return `${m}m ${sec}s`;
}
function esc(v){return String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
function showResults(res){
  resultsCard.classList.remove('hidden');
  const hits=res.hits||[], free=res.free||[];
  resultsTitle.innerHTML = `<i data-lucide="check-circle" class="icon-sm" style="color:var(--success)"></i> Results — Hits: ${hits.length} | Free: ${free.length}`;
  resultsMeta.textContent = `Total: ${res.total} • Processed: ${res.processed} • Bad: ${res.bad} • Rate: ${res.rate} • 2FA: ${res.twofa||0} • Errors: ${res.err} • Time: ${res.seconds||0}s • CPM: ${res.cpm||0}`;
  // Detailed breakdown
  if(hits.length){
    const plans={}, ccs={};
    hits.forEach(h=>{const p=(h.data&&h.data.plan)||'Premium';plans[p]=(plans[p]||0)+1; const c=(h.data&&h.data.country_name)||(h.data&&h.data.cc)||'Unknown';ccs[c]=(ccs[c]||0)+1;});
    const planLine = Object.entries(plans).map(([k,v])=>`${k}: ${v}`).join(' • ');
    const ccLine = Object.entries(ccs).slice(0,3).map(([k,v])=>`${k}: ${v}`).join(' • ');
    resultsMeta.textContent += ` • Plans: ${planLine} • Countries: ${ccLine}`;
  }
  hitList.innerHTML='';
  _refreshIcons();
  const all = hits; // premium only already filtered if needed
  all.slice(0,50).forEach(entry=>{
    const d=entry.data||{}, cred=entry.cred||{};
    const country = [d.flag||'', d.country_name||d.cc||''].filter(Boolean).join(' ');
    const card = document.createElement('div');
    card.className='hit-card';
    card.innerHTML = `
      <div class="hit-title"><i data-lucide="star" class="icon-sm" style="color:var(--success)"></i> CRUNCHYROLL HIT!</div>
      <div><i data-lucide="mail" class="icon-xs"></i> <code>${esc(cred.value||'')}</code> • <i data-lucide="key" class="icon-xs"></i> <code>${esc(cred.password||'')}</code></div>
      <div style="margin-top:6px">
        • Plan: <code>${esc(d.plan||'Premium')}</code> • Streams: <code>${esc(d.streams||'N/A')}</code> • SKU: <code>${esc(d.sku||'N/A')}</code><br>
        • Expiry: <code>${esc(d.expiry||d.next_renewal||'N/A')}</code> • Days: <code>${esc(d.days_left||'N/A')}</code> • Renew: ${d.renew?'<i data-lucide="check-circle" class="icon-xs" style="color:var(--success)"></i>':'<i data-lucide="x-circle" class="icon-xs" style="color:var(--danger)"></i>'}<br>
        • Price: <code>${esc(d.price||'0')} ${esc(d.currency||'')}</code> • Billing: <code>${esc(d.duration||d.billing_cycle||'N/A')}</code><br>
        • Payment: <code>${esc(d.payment||d.payment_method||'N/A')}</code> • Trial: ${d.trial?'<i data-lucide="check-circle" class="icon-xs"></i>':'<i data-lucide="x-circle" class="icon-xs"></i>'}<br>
        • Verified: ${d.verified?'<i data-lucide="badge-check" class="icon-xs" style="color:var(--success)"></i>':'<i data-lucide="x-circle" class="icon-xs"></i>'} • Created: <code>${esc(d.created||d.start_date||'N/A')}</code><br>
        • Country: ${esc(country)} • CC: <code>${esc(d.cc||'N/A')}</code><br>
        ${d.account_id?`• Account: <code>${esc(d.account_id)}</code><br>`:''}
        ${d.sub_id?`• Sub: <code>${esc(d.sub_id)}</code> Status: <code>${esc(d.sub_status||'active')}</code><br>`:''}
        ${d.user?`• Profile: <code>${esc(d.user)}</code><br>`:''}
        • Checked: <code>${new Date().toLocaleString()}</code>
      </div>
      <div style="margin-top:8px;text-align:right;font-size:10px;color:#888;display:flex;align-items:center;justify-content:flex-end;gap:4px"><i data-lucide="flame" class="icon-xs"></i> BlazeNXT</div>
    `;
    hitList.appendChild(card);
    _refreshIcons();
  });
  if(hits.length>50) hitList.innerHTML+=`<div class="muted">+${hits.length-50} more in export</div>`;
}

// Exports
exportTxt.addEventListener('click',()=> doExport('txt'));
exportJson.addEventListener('click',()=> doExport('json'));
exportCsv.addEventListener('click',()=> doExport('csv'));
async function doExport(fmt){
  if(!lastResults || !lastResults.hits || !lastResults.hits.length){ alert('No hits to export'); return; }
  const toSend = lastResults.hits; // premium only already
  // Build file locally
  let content, mime, ext;
  if(fmt==='json'){
    content = JSON.stringify(toSend, null, 2);
    mime='application/json'; ext='json';
  } else if(fmt==='csv'){
    const rows=[['combo','type','status','plan','expiry','days_left','country','streams','price']];
    toSend.forEach(a=>{
      const d=a.data||{};
      rows.push([`${a.cred.value}:${a.cred.password||''}`, a.cred.type, 'HIT', d.plan||'', d.expiry||'', d.days_left||'', d.country_name||'', d.streams||'', `${d.price||''} ${d.currency||''}`.trim()]);
    });
    content = rows.map(r=>r.map(v=>`"${String(v).replaceAll('"','""')}"`).join(',')).join('\\n');
    mime='text/csv'; ext='csv';
  } else {
    content = toSend.map(a=>{
      const d=a.data||{};
      return `${a.cred.value}:${a.cred.password||''} | HIT | Plan: ${d.plan||'Premium'} | Expiry: ${d.expiry||'?'} | Days: ${d.days_left||'?'} | Country: ${d.country_name||'?'} | Streams: ${d.streams||'?'}`;
    }).join('\\n');
    mime='text/plain'; ext='txt';
  }
  const blob=new Blob([content],{type:mime});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a'); a.href=url; a.download=`blazenxt_${Date.now()}.${ext}`; a.click(); URL.revokeObjectURL(url);
}

// Proxies
async function loadProxies(){
  try{
    const d= await api('/api/proxy/status');
    poolCount.textContent = d.pool||0;
    liveCount.textContent = d.live||0;
    autoCheck.textContent = d.auto_check? 'ON':'OFF';
    const _pp2 = proxyPill.querySelector('span'); if(_pp2) _pp2.textContent = `${d.live||0} live`; else proxyPill.textContent = `${d.live||0} live`;
  }catch{}
}
addProxyBtn.addEventListener('click', async ()=>{
  const txt=proxyInput.value.trim();
  if(!txt) return;
  addProxyBtn.disabled=true;
  try{
    const r= await fetch('/api/proxy/add', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({lines: txt.split('\\n')})});
    const d= await r.json();
    proxyMsg.textContent = `Added: ${d.added} • Invalid: ${d.invalid} • Pool: ${d.pool}`;
    proxyInput.value='';
    loadProxies();
  }catch(e){ proxyMsg.textContent='Error: '+e}
  addProxyBtn.disabled=false;
});
clearProxyBtn.addEventListener('click', async ()=>{
  if(!confirm('Clear pool + live?')) return;
  await fetch('/api/proxy/clear', {method:'POST'});
  proxyMsg.textContent='Cleared';
  loadProxies();
});
refreshProxyBtn.addEventListener('click', async ()=>{
  proxyMsg.textContent='Refreshing...';
  await fetch('/api/proxy/refresh', {method:'POST'});
  proxyMsg.textContent='Refresh triggered';
  setTimeout(loadProxies,2000);
});

// Generate
document.querySelectorAll('[data-hours]').forEach(btn=>{
  btn.addEventListener('click', async ()=>{
    const h=btn.dataset.hours;
    const r=await fetch('/api/code/generate', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({hours: parseInt(h)})});
    const d=await r.json();
    if(d.code){
      const out=document.getElementById('codeOut');
      out.classList.remove('hidden');
      out.querySelector('.code').textContent=d.code;
      out.querySelector('.muted').textContent='Valid until '+d.expiry;
      if(tg) tg.HapticFeedback?.notificationOccurred('success');
    } else alert(d.error||'Failed');
  });
});

// Status
async function loadStatus(){
  try{
    const d= await api('/api/status');
    statusBox.textContent = typeof d==='string'? d : JSON.stringify(d,null,2);
    const _up2 = uptimePill.querySelector('span'); if(_up2) _up2.textContent = d.uptime||''; else uptimePill.textContent = d.uptime||'';
    const _pp3 = proxyPill.querySelector('span'); if(_pp3) _pp3.textContent = `${d.live_proxies||0} live`; else proxyPill.textContent = `${d.live_proxies||0} live`;
  }catch(e){ statusBox.textContent='Error '+e}
}
refreshStatus.addEventListener('click', loadStatus);
loadStatus(); loadProxies();
setInterval(()=>{loadStatus(); loadProxies();},15000);
// Initial icon refresh for SVG
setTimeout(_refreshIcons, 300);

// Poll for progress if backend supports job polling (optional)
// For now simple POST /api/check handles all

