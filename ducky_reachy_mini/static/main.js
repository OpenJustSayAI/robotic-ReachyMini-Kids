'use strict';
const $ = id => document.getElementById(id);
const groups = {morning:'早上好', noon:'午间时光', night:'晚安', 'peppa-s1e1':'跳泥坑', 'peppa-s1e2':'恐龙先生', 'peppa-mini-flying':'坐飞机', tide:'月亮与大海', why:'十万个为什么', other:'其他熟悉的声音'};
const shortcuts = [['peppa_rain','☂','Rain','下雨啦'],['peppa_boots','♧','Boots','穿好雨靴'],['peppa_jump','↟','Jump','跳一下'],['peppa_love_muddy_puddles','♡','Muddy puddles!','最喜欢的小泥坑']];
let clips = [], current = {}, catalogReady = false, requestNumber = 0;
const time = seconds => `${Math.floor((seconds || 0)/60)}:${String(Math.floor((seconds || 0)%60)).padStart(2,'0')}`;
async function api(path, data) {
  const response = await fetch('/api/'+path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw Error(typeof result.detail === 'string' ? result.detail : '这次没有成功，请再试一次。');
  return result;
}
function notice(message) { $('notice').textContent = message; $('notice').hidden = !message; }
function label(clip) { return clip.label || clip.text || clip.id.replaceAll('_',' '); }
async function command(path, data = {}) {
  const number = ++requestNumber;
  try { notice(''); const state = await api(path,data); if(number === requestNumber) update(state); }
  catch(error) { notice(error.message); }
}
function update(state) {
  current = state;
  $('connection').textContent = state.ready ? 'Ducky 准备好了' : '正在准备声音';
  $('connection').classList.toggle('ready',state.ready);
  $('output').textContent = state.output || '';
  const names = {stopped:'等你来点播',loading:'正在准备',playing:'DUCKY 正在说',paused:'歇一会儿',finished:'还想再听一次吗？',error:'播放遇到问题',unavailable:'声音还没准备好'};
  $('play-state').textContent = names[state.state] || '准备中';
  const clip = clips.find(c=>c.id===state.clip_id);
  $('now-title').textContent = clip ? label(clip) : '选一句，听听 Ducky';
  $('now-text').textContent = clip ? (clip.text && clip.text !== label(clip) ? clip.text : (groups[clip.group] || 'Ducky 原声')) : '点下面的卡片开始，不会自动播放。';
  if(state.state === 'paused') $('now-text').textContent = '继续时，会从这句话的开头播放。';
  $('progress').max = Math.max(1,state.duration_seconds || 0);
  $('progress').value = state.position_seconds || 0;
  $('time').textContent = `${time(state.position_seconds)} / ${time(state.duration_seconds)}`;
  $('toggle').textContent = state.state === 'paused' ? '▶ 继续本句' : 'Ⅱ 暂停';
  $('toggle').disabled = !['playing','paused','loading'].includes(state.state);
  $('replay').disabled = !state.ready || !state.clip_id;
  $('stop').disabled = !state.ready || !['playing','paused','loading'].includes(state.state);
  $('volume').disabled = !state.ready;
  if(document.activeElement !== $('volume')) { $('volume').value = Math.round((state.volume ?? .35)*100); $('volume-value').textContent = $('volume').value+'%'; }
  document.body.classList.toggle('playing',state.state === 'playing');
  document.querySelectorAll('[data-clip]').forEach(b=>{ b.disabled = !state.ready; b.classList.toggle('active',b.dataset.clip === state.clip_id && state.state !== 'stopped'); });
  if(state.error || state.startup_error) notice(state.error || state.startup_error);
}
function textNode(tag, text, className) { const node = document.createElement(tag); node.textContent=text; if(className)node.className=className; return node; }
function playButton(clip, className) {
  const button = document.createElement('button'); button.className=className; button.dataset.clip=clip.id;
  button.setAttribute('aria-label','播放 '+label(clip));
  button.addEventListener('click',()=>command('play/'+encodeURIComponent(clip.id)));
  return button;
}
function renderList() {
  const query = $('search').value.toLocaleLowerCase().trim(), group = $('group').value;
  const filtered = clips.filter(c=>(!group || c.group===group) && [c.label,c.text,groups[c.group]].join(' ').toLocaleLowerCase().includes(query));
  $('clips').replaceChildren();
  for(const clip of filtered) {
    const button=playButton(clip,'clip'), copy=textNode('span','','copy');
    copy.append(textNode('strong',label(clip)),textNode('small',(groups[clip.group] || '其他')+' · '+(clip.language==='zh'?'中文':'English')));
    button.append(textNode('span','▶','play-mark'),copy,textNode('span',time(clip.duration_seconds),'duration')); $('clips').append(button);
  }
  $('empty').hidden = !!filtered.length; $('count').textContent = `${filtered.length} 段熟悉的声音`;
  update(current);
}
async function loadCatalog() {
  const data = await api('catalog'); clips=data.clips;
  for(const group of Object.keys(groups)) if(clips.some(c=>c.group===group)) { const option=textNode('option',groups[group]); option.value=group; $('group').append(option); }
  for(const [id,icon,en,zh] of shortcuts) {
    const clip=clips.find(c=>c.id===id); if(!clip)continue;
    const button=playButton(clip,'quick-clip'); button.append(textNode('span',icon,'icon'),textNode('strong',en),textNode('small',zh)); $('quick-clips').append(button);
  }
  catalogReady=true; renderList();
}
$('toggle').onclick=()=>command('control',{action:current.state==='paused'?'resume':'pause'});
$('replay').onclick=()=>command('control',{action:'replay'});
$('stop').onclick=()=>command('control',{action:'stop'});
$('volume').oninput=()=>{$('volume-value').textContent=$('volume').value+'%';};
$('volume').onchange=()=>command('volume',{value:Number($('volume').value)/100});
$('search').oninput=renderList; $('group').onchange=renderList;
async function refresh() {
  try { const state=await api('status'); update(state); if(!catalogReady && state.ready)await loadCatalog(); }
  catch(error) { $('connection').textContent='连接中断，正在重连'; $('connection').classList.remove('ready'); notice('暂时连不上 Ducky，请确认 App 还在运行。'); }
  finally { setTimeout(refresh,500); }
}
refresh();
