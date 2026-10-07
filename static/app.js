'use strict';

const icons = {
  home:'<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z"/>',
  tasks:'<rect x="5" y="4" width="15" height="17" rx="2"/><path d="M9 3h7v4H9zM9 12l1 1 2-2M9 17l1 1 2-2M15 12h2m-2 5h2"/>',
  discover:'<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5Z"/>',
  skills:'<path d="m12 3 3 5 5 1-3 5 .5 6L12 17l-5.5 3L7 14 4 9l5-1Z"/>',
  devices:'<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4M7 8h10"/>',
  agents:'<rect x="4" y="7" width="16" height="13" rx="4"/><path d="M12 3v4m-3 6h.1m5.9 0h.1M9 17h6M1 12h3m16 0h3"/><circle cx="12" cy="3" r="1"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/>',
  arrow:'<path d="M4 12h16m-5-5 5 5-5 5"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6.1 6.1A8.3 8.3 0 0 1 20 12M4 12a8.3 8.3 0 0 0 13.9 5.9"/>',
  star:'<path d="m12 3 2.7 5.5 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1L3.2 9.4l6.1-.9Z"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  link:'<path d="m10 14 4-4m-6 5-1 1a4 4 0 0 1-5.7-5.7L6 5.7a4 4 0 0 1 5.7 0m.6 12.6a4 4 0 0 0 5.7 0l4.7-4.6a4 4 0 0 0-5.7-5.7l-1 1"/>',
  external:'<path d="M14 3h7v7m0-7L10 14M10 3H4a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-6"/>',
  file:'<path d="M14 3H5v18h14V8Zm0 0v5h5M8 12h8m-8 4h6"/>',
  news:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 8h4v4H7zM14 8h3m-3 4h3M7 16h10"/>',
  code:'<path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-14-2 18"/>',
  heart:'<path d="M20.8 4.6a5.6 5.6 0 0 0-7.9 0l-.9.9-.9-.9a5.6 5.6 0 0 0-7.9 7.9L12 21l8.8-8.5a5.6 5.6 0 0 0 0-7.9Z"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  folder:'<path d="M3 7V5h6l2 3h10v12H3Z"/>',
  copy:'<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  download:'<path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/>',
  edit:'<path d="m15 4 5 5M4 16l-1 5 5-1L21 7l-5-5Z"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/>',
  spark:'<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"/>'
};
const svg = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.file}</svg>`;
const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const list = value => Array.isArray(value) ? value : [];
const textValue = value => value == null ? '' : typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value);
const splitValues = value => String(value || '').split(/[,，\n]/).map(x => x.trim()).filter(Boolean);
const lines = value => String(value || '').split('\n').map(x => x.trim()).filter(Boolean);
const q = selector => document.querySelector(selector);
const moods = [{name:'开心',emoji:'☺️'},{name:'平静',emoji:'😌'},{name:'专注',emoji:'🧐'},{name:'疲惫',emoji:'😴'},{name:'低落',emoji:'☁️'}];
const pages = {home:['首页','TODAY & YOU'],tasks:['任务看板','ORIGINAL TASK BOARD'],discover:['发现','IDEAS & POSSIBILITIES'],skills:['Skills 库','YOUR CAPABILITIES'],devices:['设备管理','CONNECTED WORKSPACE'],agents:['AI 管理','YOUR AI TEAM']};
let S = null;
let activePage = 'home';
let modalSubmit = null;
let modalBusy = false;
let modalGeneration = 0;
let actionBusy = false;
let loadingPromise = null;
let searchTimer;
const taskBoard = {metadata:null,loadedRevision:null,loadedTask:null,busy:false,ready:false,pending:false,error:'',timer:null,request:null,generation:0,forceRequested:false};
const views = {
  discover:{query:'',kind:'news',filter:'all',visibleCount:10,modelCategory:'overall'},
  skills:{query:'',filter:'starred',category:'all'},
  devices:{filter:'active'},
  agents:{filter:'visible'}
};
const modal = q('#modal');
const taskItems = () => list(S?.tasks?.items);
const skillItems = () => list(S?.skills?.items);
const deviceItems = () => list(S?.devices?.items);
const agentItems = () => list(S?.agents?.items);
const discoverItems = () => list(S?.discover?.items);
const roleItems = () => list(S?.roles);
const relations = () => list(S?.relations);
const focusIDs = () => list(S?.daily?.focus_task_ids);
const skillName = s => s?.display_name || s?.name || '未命名 Skill';
const commonSkills = () => skillItems().filter(s=>s.starred&&!s.archived);
const skillSummary = s => list(s?.scenarios).find(value=>typeof value==='string'&&value.trim()) || s?.notes || s?.description || '查看详情，了解它适合完成什么任务。';
const skillSourceLabel = s => list(s?.locations).map(loc=>loc.label).filter(Boolean).join(' / ') || s?.source || '本地来源';
const manifestPath = value => typeof value==='string'&&value.startsWith('/')&&value.endsWith('/SKILL.md')&&!/[\x00-\x1f\x7f]/.test(value)?value:null;
const skillSharingHint = '本机 AI 可直接读取此路径；跨电脑分享请导出技能包。';
const sameNameBadge = s => Number(s?.same_name_count)>1 ? `<span class="tag ${s.same_name_different_content?'amber':'neutral'}">同名 ${e(s.same_name_count)} 包 · ${s.same_name_different_content?'内容有差异':'内容一致'}</span>` : '';
const timestamp = value => {
  if (!value) return '尚无记录';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(d);
};
const dateString = () => {
  const parts = new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const get = key => parts.find(p => p.type === key)?.value;
  return `${get('year')}-${get('month')}-${get('day')}`;
};
const shortDate = value => {
  if (!value) return '时间未提供';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'short',day:'numeric'}).format(d);
};
const statusMap = {
  progress:['进行中','green'], 'waiting-user':['等我拍板','amber'], blocked:['技术阻塞','red'], 'waiting-external':['等外部','amber'], done:['已完成','neutral'],
  online:['可达','green'], ready:['已接入','green'], available:['已接入','green'], healthy:['正常','green'], ok:['读取正常','green'], running:['进程在线','green'], paused:['已暂停','neutral'], archived:['已归档','neutral'], loading:['读取中','neutral'],
  unavailable:['暂不可达','amber'], offline:['不可达','amber'], unknown:['未知','neutral'], unconnected:['未接入','neutral'], not_connected:['未接入','neutral'], disabled:['已停用','neutral'], stale:['已过期','amber'], error:['读取异常','red'], partial:['部分可用','amber'], not_configured:['未配置','neutral'],
  valid:['检查通过','green'], warning:['检查有提醒','amber'], invalid:['检查未通过','red'], unchecked:['未检查','neutral'],
  verified:['已验证','green'], unverified:['未验证','neutral'], failed:['验证未通过','red'], outdated:['验证已过期','amber'],
  candidate:['候选','neutral'], pending:['待核实','amber'], draft:['草稿','neutral'], registered:['已登记','green'], missing:['未检测到','neutral'], detected:['已检测到','green']
};
const badge = (state, fallback) => {const [label,color] = statusMap[state] || [fallback || state || '未知','neutral'];return `<span class="tag ${color}">${e(label)}</span>`;};
const tag = value => `<span class="tag">${e(value)}</span>`;
const tags = values => `<div class="tags">${list(values).filter(Boolean).map(tag).join('')}</div>`;
const btn = (label, action, id = '', cls = 'secondary', icon = '', attrs = '') => `<button type="button" class="button ${cls}" data-action="${e(action)}" data-id="${e(id)}" ${attrs}>${icon ? svg(icon) : ''}${e(label)}</button>`;
const iconBtn = (label, action, id = '', icon = 'star', selected = false, attrs = '') => `<button type="button" class="icon-button ${icon === 'star' ? 'star-button' : ''} ${selected ? 'selected' : ''}" data-action="${e(action)}" data-id="${e(id)}" aria-label="${e(label)}" title="${e(label)}" ${attrs}>${svg(icon)}</button>`;
const empty = (title,desc,icon='folder',action='') => `<div class="empty"><span class="empty-icon">${svg(icon)}</span><h3>${e(title)}</h3><p>${e(desc)}</p>${action}</div>`;
const notice = (message,color='',extra='') => message ? `<div class="notice ${e(color)}">${svg('info')}<p>${e(message)}</p>${extra}</div>` : '';
const intro = (title,desc,actions='') => `<div class="page-intro"><div><span class="eyebrow">${e(pages[activePage]?.[1] || '')}</span><h1>${e(title)}</h1><p>${e(desc)}</p></div><div class="intro-actions">${actions}</div></div>`;
const safeURL = value => {if(typeof value!=='string'||!value.trim())return null;try {const url = new URL(value);return ['https:','http:'].includes(url.protocol) ? url.href : null;} catch {return null;}};
const external = (url,label='查看原文',cls='button secondary small') => {const safe = safeURL(url);return safe ? `<a class="${e(cls)}" href="${e(safe)}" target="_blank" rel="noopener noreferrer">${svg('external')}${e(label)}</a>` : `<span class="state-text">原文链接不可用</span>`;};
const errMessage = err => typeof err === 'string' ? err : err?.message || err?.error || err?.detail || '部分来源暂不可用';
const errorNotice = errors => list(errors).length ? notice(`${list(errors).length} 项来源需要留意：${list(errors).slice(0,2).map(errMessage).join('；')}`,'amber') : '';
const metric = (label,value,icon='tasks',unit='') => `<div class="metric-card"><div class="metric-label">${e(label)}${svg(icon)}</div><div class="metric-value">${e(value)}${unit ? `<small>${e(unit)}</small>` : ''}</div></div>`;
const search = (page,placeholder) => `<label class="search-box">${svg('search')}<span class="sr-only">${e(placeholder)}</span><input type="search" data-search="${e(page)}" value="${e(views[page].query)}" placeholder="${e(placeholder)}" autocomplete="off"></label>`;
const filter = (page,key,value,label) => `<button type="button" class="filter ${views[page][key] === value ? 'active' : ''}" data-action="filter" data-page="${e(page)}" data-key="${e(key)}" data-value="${e(value)}" aria-pressed="${views[page][key] === value}">${e(label)}</button>`;
const relationSkills = (type,id) => relations().filter(r => r.from_type === type && r.from_id === id && r.to_type === 'skill').map(r => ({...r,skill:skillItems().find(s => s.id === r.to_id)}));
function toast(message,error=false) {
  const node = document.createElement('div');node.className = `toast${error ? ' error' : ''}`;node.textContent = message;q('#toast-region').appendChild(node);
  setTimeout(() => node.remove(),error ? 8000 : 4200);
}
async function api(path,payload,method='POST') {
  const opts = {method,headers:{'X-Workbench':'1'}};
  if (payload !== undefined && method !== 'GET') {opts.headers['Content-Type']='application/json';opts.body=JSON.stringify(payload);}
  const response = await fetch(path,opts);
  let data;
  try {data=await response.json();} catch {data=null;}
  if (!response.ok) throw new Error(typeof data?.detail === 'string' ? data.detail : `请求未完成（${response.status}），请稍后重试。`);
  return data;
}
async function load({quiet=false,force=false}={}) {
  if (loadingPromise && !force) return loadingPromise;
  loadingPromise=(async()=>{
    try {
      const response = await fetch('/api/bootstrap',{cache:'no-store'});
      if (!response.ok) throw new Error('工作台暂时未能读取数据');
      const data = await response.json();S=data;
      q('#connection').classList.remove('offline');q('#connection').textContent=data.health?.local_only === false ? '已连接工作台' : '本机已连接';
      q('#sidebar-status').textContent='你的本地工作空间';
      q('#footer-updated').textContent=`最近同步 ${timestamp(data.health?.server_time || new Date().toISOString())}`;
      if (!quiet || (!modal.open && !document.activeElement?.matches('input,textarea,select'))) render();
      return data;
    } catch (err) {
      q('#connection').classList.add('offline');q('#connection').textContent='连接中断';q('#sidebar-status').textContent='连接暂时中断';
      if (!S) q('#main').innerHTML=`<div class="page-error">${svg('devices')}<h1>暂时连接不到工作台</h1><p>请确认工作台已启动。你的记录会在连接恢复后重新显示。</p>${btn('重新连接','retry','','primary','refresh')}</div>`;
      else if (!quiet) toast(err.message,true);
      if (!quiet) throw err;
      return null;
    } finally {loadingPromise=null;}
  })();
  return loadingPromise;
}
async function mutate(path,payload,options={}) {
  const result = await api(path,payload,options.method || 'POST');
  if (options.close !== false) closeModal();
  await load({force:true});
  if (options.message !== false) toast(options.message || '已保存');
  return result;
}
function navigate(page) {location.hash=page;}
function renderNavigation() {
  q('#navigation').innerHTML=Object.entries(pages).map(([key,[label]])=>`<a class="nav-item ${activePage === key ? 'active' : ''}" href="#${key}" ${activePage===key?'aria-current="page"':''}>${svg(key)}<span>${e(label)}</span>${key==='tasks' && taskItems().filter(t=>t.status==='waiting-user').length ? `<span class="nav-count">${taskItems().filter(t=>t.status==='waiting-user').length}</span>` : ''}</a>`).join('');
  q('#breadcrumb-current').textContent=pages[activePage][0];
}
function render() {
  const hash=location.hash.slice(1).split('?')[0];activePage=pages[hash]?hash:'home';renderNavigation();
  document.body.classList.toggle('task-board-page',activePage==='tasks');
  if(activePage!=='tasks')stopTaskBoard();
  if (!S) return;
  document.title=`${pages[activePage][0]} · 个人工作台`;
  if(activePage==='tasks' && q('#task-board-frame')) {
    if(taskBoard.loadedTask!==taskBoardTarget())checkTaskBoard({force:true});
    updateTaskBoardChrome();return;
  }
  q('#main').innerHTML=({home:renderHome,tasks:renderTasks,discover:renderDiscover,skills:renderSkills,devices:renderDevices,agents:renderAgents}[activePage])();
  if(activePage==='tasks')mountTaskBoard();
}
function renderHome() {
  const date=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'long'}).format(new Date());
  const hour=Number(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',hour12:false}).format(new Date()));
  const greeting=hour<11?'早上好':hour<14?'中午好':hour<18?'下午好':'晚上好';
  const focused=focusIDs().map(id=>taskItems().find(t=>t.id===id)||{id,title:S.daily?.focus_snapshots?.[id]?.title||'暂时找不到的任务',brief:'来源暂不可用，任务恢复后会重新核对。',status:'unknown'});
  const waiting=taskItems().filter(t=>t.status==='waiting-user' && !t.parent);
  const blocked=taskItems().filter(t=>['blocked','waiting-external'].includes(t.status) && !t.parent);
  const discoveries=discoverItems().slice(0,4);
  const devices=deviceItems().filter(d=>!d.archived&&d.enabled!==false&&!deviceRegisteredOnly(d));
  const connected=devices.filter(d=>['online','ready','available','healthy','ok'].includes(d.status)).length;
  const agents=agentItems().filter(a=>!a.hidden&&a.enabled!==false&&['ready','ok','available','healthy','online'].includes(a.source_state));
  const running=agents.reduce((total,a)=>total+(Number.isFinite(a.running)?a.running:0),0);
  const unread=agents.reduce((total,a)=>total+(Number.isFinite(a.completed_unread)?a.completed_unread:0),0);
  const agentEvidence=agents.some(a=>Number.isFinite(a.running)||Number.isFinite(a.completed_unread));
  const sourceWarning=S.tasks?.source_status && !['ok','ready','available','online'].includes(S.tasks.source_status) ? notice('任务来源暂未完全就绪，正在保留最近一次成功读取的记录。','amber') : '';
  return `${sourceWarning}<section class="home-hero"><div class="hero-copy"><span class="eyebrow">${e(date)} · 属于你的今天</span><h1>${greeting}<span>。</span></h1><p>把今天要推进的事，与手边可用的能力放在一起。</p><div class="hero-quote">${svg('tasks')} ${taskItems().filter(t=>!t.parent&&t.status!=='done').length} 个活跃任务 · ${commonSkills().length} 个常用 Skills</div></div><div class="hero-art" aria-hidden="true"><img class="hero-avatar user-avatar" src="/static/assets/default-avatar.svg" alt=""></div></section>
  <div class="home-grid"><div class="home-main"><section class="panel"><div class="panel-head"><div class="panel-title">${svg('tasks')}<h2>今日重点</h2><small>${focused.length} / 3</small></div>${btn('选择重点','focus-picker','','ghost small','plus')}</div>${focused.length?`<div class="focus-list">${focused.map((t,i)=>`<div class="focus-row"><span class="focus-number">0${i+1}</span><div class="focus-copy"><h3><button class="text-link" data-action="task-detail" data-id="${e(t.id)}" style="font-size:inherit;color:inherit">${e(t.title)}</button></h3><p>${e(t.next?.[0]||t.brief||'查看任务上下文，选择下一步。')}</p><div class="tags" style="margin-top:7px">${badge(t.status)}</div></div><div class="focus-controls"><button class="icon-button" data-action="focus-up" data-id="${e(t.id)}" aria-label="上移重点" ${i===0?'disabled':''}>↑</button><button class="icon-button" data-action="focus-down" data-id="${e(t.id)}" aria-label="下移重点" ${i===focused.length-1?'disabled':''}>↓</button><button class="icon-button" data-action="focus-remove" data-id="${e(t.id)}" aria-label="移除今日重点">×</button></div></div>`).join('')}</div><div class="focus-bottom">少一些同时进行，多一些真正推进。</div>`:empty('今天，先选一件重要的事','从已有任务里挑选最多 3 个重点，给今天一个清晰的方向。','tasks',btn('选择今日重点','focus-picker','','secondary small','plus'))}</section>
  <section class="panel"><div class="panel-head"><div class="panel-title">${svg('clock')}<h2>需要我处理</h2><small>${waiting.length+blocked.length}</small></div><a class="text-link" href="#tasks">打开任务看板 ${svg('arrow')}</a></div>${waiting.length+blocked.length ? `<div class="attention-list">${[...waiting,...blocked].slice(0,4).map(t=>`<div class="attention-row"><span class="attention-dot"></span><div class="attention-copy"><h3>${e(t.title)} ${badge(t.status)}</h3><p>${e(list(t.blockers)[0]||t.brief||'查看任务详情')}</p></div>${iconBtn('查看任务','task-detail',t.id,'arrow')}</div>`).join('')}</div>`:empty('目前没有待处理的拍板与卡点','可以把注意力留给今天选择的重点。','check')}</section>
  <section class="panel"><div class="panel-head"><div class="panel-title">${svg('discover')}<h2>今天发现</h2></div><a class="text-link" href="#discover">更多发现 ${svg('arrow')}</a></div>${discoveries.length?`<div class="discover-home-list">${discoveries.map(item=>`<div class="mini-article"><span class="mini-article-icon">${svg(item.kind==='project'?'code':'news')}</span><div class="mini-article-main"><h3><button class="text-link" style="font-size:inherit;color:inherit;text-align:left" data-action="discover-detail" data-id="${e(item.id)}">${e(item.title)}</button></h3><p>${e(item.reason||item.summary||'打开详情，了解它能带来什么。')}</p><div class="mini-article-meta">${tag(item.kind==='project'?'开源项目':'资讯')}<span>${e(item.source||'来源未提供')}</span><span>${e(shortDate(item.published_at))}</span></div></div>${iconBtn(item.bookmarked?'取消收藏':'收藏','discover-star',item.id,'star',item.bookmarked)}</div>`).join('')}</div>`:empty('新的可能，正在路上',S.discover?.error?'资讯来源暂时不可用。已有收藏仍可在发现里查看。':'你也可以手动添加一个感兴趣的开源项目。','discover',btn('去发现','go-discover','','secondary small','arrow'))}</section></div>
  <div class="home-aside"><section class="panel mood-panel"><div class="panel-head"><div class="panel-title">${svg('heart')}<h2>此刻的状态</h2></div><small class="muted">只记录，不评判</small></div><div class="panel-body"><div class="mood-options">${moods.map(m=>`<button class="mood-button ${S.daily?.mood===m.name?'selected':''}" data-action="mood" data-value="${e(m.name)}" aria-pressed="${S.daily?.mood===m.name}"><span>${m.emoji}</span>${m.name}</button>`).join('')}</div><div class="energy-row"><span>今日精力</span><div class="energy-bar">${[1,2,3,4,5].map(v=>`<button class="energy-button ${Number(S.daily?.energy)>=v?'selected':''}" data-action="energy" data-value="${v}" aria-label="精力 ${v} 分（共 5 分）" aria-pressed="${Number(S.daily?.energy)===v}"></button>`).join('')}</div><span>${S.daily?.energy?`${e(S.daily.energy)}/5`:'未记录'}</span></div><div class="mood-foot"><span>给自己一点觉察的时间。</span><button class="text-link" data-action="mood-clear">清空</button></div></div></section>
  <section class="panel status-panel"><div class="panel-head"><div class="panel-title">${svg('devices')}<h2>工作空间</h2></div>${tag('最近采集')}</div><div class="status-overview"><div class="status-mini"><div class="status-mini-main"><span class="soft-icon">${svg('devices')}</span><div><strong>设备连接</strong><p>${devices.length ? `${devices.length} 台已启用设备`:'还没有启用设备'}</p></div></div><a class="status-number" href="#devices">${devices.length?connected:'—'}<small>可达 / ${devices.length} 台</small></a></div><div class="status-mini"><div class="status-mini-main"><span class="soft-icon">${svg('agents')}</span><div><strong>AI 会话活动</strong><p>${agentEvidence?'按各工具的会话记录推断':'尚无可用会话证据'}</p></div></div><a class="status-number" href="#agents">${agentEvidence?running:'—'}<small>处理中</small></a></div><div class="status-mini"><div class="status-mini-main"><span class="soft-icon">${svg('check')}</span><div><strong>完成未读</strong><p>不是需要审批的任务</p></div></div><a class="status-number" href="#agents">${agentEvidence?unread:'—'}<small>条会话</small></a></div><p class="status-caption">缺少证据时显示未知，不把连接失败当作设备关机。</p></div></section>
  <section class="panel"><div class="panel-head"><div class="panel-title">${svg('skills')}<h2>常用 Skills</h2></div></div><div class="panel-body" style="padding-top:0"><div class="tags">${tag(`${commonSkills().length} 个常用`)}${tag('AI 生图')}${tag('PPT 演示')}</div><p class="task-summary" style="margin:12px 0 15px">常用的创作与办公能力，下一次工作随时找到。</p><a class="button secondary small" href="#skills">打开 Skills 库 ${svg('arrow')}</a></div></section></div></div>`;
}
function renderTasks() {
  return `<section class="task-board-view" aria-label="任务看板"><div class="task-board-toolbar"><div class="task-board-heading"><h1>任务看板</h1><p id="task-board-sync" role="status">正在读取已配置看板…</p></div><div class="task-board-actions">${btn('刷新看板','task-board-refresh','','secondary small','refresh')}<a class="button ghost small" href="/task-board/" target="_blank" rel="noopener noreferrer">${svg('external')}独立打开</a></div></div><div class="task-board-stage"><iframe id="task-board-frame" title="任务看板" sandbox="allow-scripts allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer" hidden></iframe><div class="task-board-loading" id="task-board-loading" role="status"><span class="loading-ring"></span><h2>正在打开任务看板</h2><p>沿用原有任务分区与卡片，点击任务打开独立详情页。</p></div></div></section>`;
}
function taskBoardTarget() {
  return new URLSearchParams(location.hash.split('?')[1]||'').get('task')||'';
}
function stopTaskBoard() {
  if(!taskBoard.timer&&!taskBoard.request&&!q('#task-board-frame'))return;
  clearInterval(taskBoard.timer);taskBoard.timer=null;taskBoard.request=null;taskBoard.generation++;
  taskBoard.loadedRevision=null;taskBoard.loadedTask=null;taskBoard.busy=false;taskBoard.ready=false;taskBoard.pending=false;taskBoard.forceRequested=false;
}
function mountTaskBoard() {
  taskBoard.generation++;taskBoard.loadedRevision=null;taskBoard.loadedTask=null;taskBoard.ready=false;taskBoard.busy=false;taskBoard.pending=false;taskBoard.error='';
  clearInterval(taskBoard.timer);taskBoard.timer=setInterval(()=>checkTaskBoard(),30000);
  checkTaskBoard();
}
function updateTaskBoardChrome() {
  const status=q('#task-board-sync');if(!status)return;
  const meta=taskBoard.metadata;
  if(taskBoard.error)status.textContent=taskBoard.error;
  else if(meta?.available===false)status.textContent=meta.error||'任务看板暂时不可用';
  else if(meta)status.textContent=`同步于 ${timestamp(meta.updated_at)}${taskBoard.pending?' · 已配置看板有更新，结束当前交互后同步':''}${meta.source_newer?' · 任务档案已有更新，待已配置看板生成':''}`;
  const independent=q('.task-board-actions a[href^="/task-board/"]');
  if(independent)independent.href=taskBoardTarget()?`/task-board/?task=${encodeURIComponent(taskBoardTarget())}`:'/task-board/';
}
function reloadTaskBoardFrame(meta) {
  const frame=q('#task-board-frame');if(activePage!=='tasks'||!frame||!meta?.available)return;
  const target=taskBoardTarget(),url=new URL('/task-board/',location.origin);
  url.searchParams.set('embedded','1');if(target)url.searchParams.set('task',target);
  if(meta.revision)url.searchParams.set('v',meta.revision);
  url.searchParams.set('view',Date.now().toString(36));
  taskBoard.loadedRevision=meta.revision;taskBoard.loadedTask=target;taskBoard.ready=false;taskBoard.busy=false;taskBoard.pending=false;
  frame.hidden=false;frame.src=url.pathname+url.search;
  const loading=q('#task-board-loading');loading.hidden=false;
  loading.innerHTML='<span class="loading-ring"></span><h2>正在打开任务看板</h2><p>沿用原有任务分区与卡片，点击任务打开独立详情页。</p>';
  updateTaskBoardChrome();
}
function applyTaskBoardMetadata(force=false) {
  const meta=taskBoard.metadata,frame=q('#task-board-frame');if(activePage!=='tasks'||!frame||!meta)return;
  if(!meta.available) {
    if(taskBoard.loadedTask===null) {
      frame.hidden=true;const loading=q('#task-board-loading');loading.hidden=false;
      loading.innerHTML=`${svg('info')}<h2>暂时无法打开任务看板</h2><p>${e(meta.error||'请确认任务看板文件可读取，再刷新。')}</p>${btn('重新读取','task-board-refresh','','secondary small','refresh')}`;
    }
  } else if(force||taskBoard.loadedTask===null||taskBoard.loadedRevision!==meta.revision||taskBoard.loadedTask!==taskBoardTarget()) {
    if(!force&&(taskBoard.busy||modal.open))taskBoard.pending=true;
    else reloadTaskBoardFrame(meta);
  }
  updateTaskBoardChrome();
}
async function checkTaskBoard({force=false}={}) {
  if(activePage!=='tasks'||!q('#task-board-frame'))return;
  if(force)taskBoard.forceRequested=true;
  if(taskBoard.request)return taskBoard.request;
  const generation=taskBoard.generation;
  taskBoard.request=(async()=>{
    try {
      const response=await fetch('/api/task-board',{cache:'no-store'});
      if(!response.ok)throw new Error('暂时无法检查已配置看板更新');
      const metadata=await response.json();
      if(generation!==taskBoard.generation||activePage!=='tasks')return;
      taskBoard.metadata=metadata;taskBoard.error='';
      const explicit=taskBoard.forceRequested;taskBoard.forceRequested=false;
      applyTaskBoardMetadata(explicit);
    } catch(err) {
      if(generation!==taskBoard.generation||activePage!=='tasks')return;
      taskBoard.error=`${err.message||'暂时无法检查已配置看板更新'}${taskBoard.loadedTask!==null?' · 保留当前内容':''}`;
      taskBoard.forceRequested=false;updateTaskBoardChrome();
      if(taskBoard.loadedTask===null) {
        const loading=q('#task-board-loading');loading.innerHTML=`${svg('info')}<h2>任务看板暂未连通</h2><p>${e(taskBoard.error)}</p>${btn('重新读取','task-board-refresh','','secondary small','refresh')}`;
      }
    } finally {if(generation===taskBoard.generation)taskBoard.request=null;}
  })();
  return taskBoard.request;
}
function openTaskBoard(id='') {
  if(id){window.open(`/tasks/${encodeURIComponent(id)}`,'_blank','noopener');closeModal();return;}
  closeModal();
  if(location.hash==='#tasks')checkTaskBoard({force:true});else location.hash='#tasks';
}
window.addEventListener('message',async event=>{
  const frame=q('#task-board-frame');
  if(activePage!=='tasks'||!frame||event.source!==frame.contentWindow||!event.data||typeof event.data!=='object')return;
  if(event.data.type==='task-board-copy-html'&&typeof event.data.id==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(event.data.id)) {
    const id=event.data.id;
    let copied=false;
    try {
      const target=await api(`/api/tasks/${encodeURIComponent(id)}/handoff`,{});
      if(typeof target.path!=='string'||!target.path.startsWith('/')||!target.path.endsWith('.html')||/[\x00-\x1f\x7f]/.test(target.path))throw new Error('任务 HTML 文件地址不可用');
      copied=await copyText(target.path,{manualTitle:'手动复制任务 HTML 路径',label:'本地 HTML 绝对路径',hint:'将这个完整路径发给本机 AI，即可读取任务详情。'});
    } catch(error) {toast(error.message||'复制任务 HTML 路径失败',true);}
    finally {frame.contentWindow?.postMessage({type:'task-board-copy-html-result',id,copied},'*');}
  } else if(event.data.type==='task-board-ready') {
    taskBoard.ready=true;q('#task-board-loading').hidden=true;
  } else if(event.data.type==='task-board-state'&&typeof event.data.busy==='boolean') {
    taskBoard.busy=event.data.busy;
    if(!taskBoard.busy&&taskBoard.pending&&!modal.open)applyTaskBoardMetadata();
  }
});
const modelLeaderboards = [
  {id:'overall',name:'综合榜',description:'跨场景比较模型的整体表现。'},
  {id:'coding',name:'编程榜',description:'代码生成、调试与工程开发。'},
  {id:'reasoning',name:'科研榜',description:'复杂推理与科研问题。'},
  {id:'professional',name:'专业办公榜',description:'报告、资料整理与专业工作。'},
  {id:'knowledge',name:'知识问答榜',description:'知识解释与日常问答。'}
];
const numberLabel = value => typeof value==='number'&&Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:1}).format(value):'—';
function discoverySourceNotice(source,label) {
  if(!source)return '';
  const hasItems=list(source.items).length>0||list(source.item_ids).length>0;
  if(source.stale||source.error||['unavailable','error','stale','partial','rate_limited'].includes(source.status))return notice(`${label}暂未取得最新数据${hasItems?'，正在显示最近一次成功读取的内容':''}。${source.error?` ${source.error}`:''}`,'amber');
  if(source.status==='loading')return notice(`${label}正在读取，请稍候。`);
  return '';
}
function modelPrice(value) {return value==null||value===''?'—':e(value);}
function renderModelLeaderboards() {
  const v=views.discover,category=modelLeaderboards.find(board=>board.id===v.modelCategory)||modelLeaderboards[0];
  const board=S.discover?.leaderboards?.categories?.[category.id]||{};
  const all=list(board.items),items=all.filter(item=>[item.name,item.vendor].join(' ').toLowerCase().includes(v.query.toLowerCase()));
  const sourceURL=board.source_url||'https://aihot.news/leaderboard';
  const categories=`<div class="filters model-categories" aria-label="模型榜分类">${modelLeaderboards.map(item=>filter('discover','modelCategory',item.id,item.name)).join('')}</div>`;
  const summary=[all.length?`${all.length} 个模型`:null,typeof board.evaluation_count==='number'?`${numberLabel(board.evaluation_count)} 项评测`:null,typeof board.organization_count==='number'?`${numberLabel(board.organization_count)} 个评测机构`:null].filter(Boolean).join(' · ');
  return `<section class="leaderboard-intro"><div><span class="eyebrow">AIHOT 模型排行榜</span><h2>模型表现，直接比较</h2><p>按使用场景查看名次、评测覆盖与价格。</p></div><div class="leaderboard-intro-actions">${btn('更新榜单','leaderboards-refresh','','secondary small','refresh')}${external('https://aihot.news/leaderboard/rules','排名规则','text-link')}</div></section>${categories}${discoverySourceNotice(board,'模型榜')}<div class="toolbar leaderboard-toolbar"><div><h3>${e(category.name)} <span class="count-chip">${all.length}</span></h3><p class="leaderboard-summary">${e(summary||category.description)}</p></div><div class="toolbar-actions">${search('discover','搜索模型或厂商')}</div></div>${items.length?`<section class="leaderboard-panel"><div class="leaderboard-table-scroll" tabindex="0" role="region" aria-label="${e(category.name)}，可横向滚动"><table class="leaderboard-table"><caption class="sr-only">${e(category.name)}，排名和分数来自 AIHOT；价格单位：${e(board.price_unit||'来源未提供')}</caption><thead><tr><th scope="col" class="rank-cell">排名</th><th scope="col" class="model-cell">模型 / 厂商</th><th scope="col" class="score-cell">AIHOT 分数</th><th scope="col">评测覆盖</th><th scope="col">输入价格</th><th scope="col">输出价格</th><th scope="col">缓存价格</th><th scope="col">发布日期</th></tr></thead><tbody>${items.map(item=>`<tr><td class="rank-cell"><span class="model-rank ${Number(item.rank)<=3?'leading':''}">${e(item.rank)}</span></td><th scope="row" class="model-cell"><strong>${e(item.name)}</strong><span>${e(item.vendor||'厂商未提供')}</span></th><td class="score-cell"><strong>${e(numberLabel(item.score))}</strong></td><td><span class="coverage-value">${typeof item.coverage==='number'?`${e(numberLabel(item.coverage))}%`:'—'}</span><small>${typeof item.evaluations_count==='number'?`${e(numberLabel(item.evaluations_count))} 项评测`:'评测数量未提供'}</small></td><td class="price-cell">${modelPrice(item.input_price)}</td><td class="price-cell">${modelPrice(item.output_price)}</td><td class="price-cell">${modelPrice(item.cache_price)}</td><td class="release-cell">${e(item.release_date||'—')}</td></tr>`).join('')}</tbody></table></div><div class="leaderboard-table-foot"><span>价格：${e(board.price_unit||'来源未提供单位')} · 未核验价格显示 —</span><span>AIHOT 分数为榜单评价分，并非正确率。</span></div></section>`:empty(all.length?'没有匹配的模型':'榜单正在等待真实数据',all.length?'试试其他模型名称或厂商。':board.error?'暂时无法读取官方榜单，请稍后更新。':'首次读取完成后，模型名次会直接显示在这里。','discover',!all.length?btn('读取榜单','leaderboards-refresh','','secondary small','refresh'):'')}<div class="source-stamp leaderboard-source"><span>来源：${external(sourceURL,'AIHOT 公共榜页','text-link')}</span><span>来源更新 ${e(board.source_updated_label||'未提供')}</span><span>最近核对 ${e(timestamp(board.checked_at))}</span>${board.updated_at?`<span>最近成功读取 ${e(timestamp(board.updated_at))}</span>`:''}</div>`;
}
function discoveryCard(item) {
  const project=item.kind==='project',trending=project&&item.daily_trending===true;
  return `<article class="content-card discovery-card ${trending?'trending-card':''}" data-discovery-kind="${e(item.kind)}"><div class="card-top"><span class="card-symbol">${svg(project?'code':'news')}</span>${trending&&item.trending_rank?`<span class="trending-position">GitHub 日榜 #${e(item.trending_rank)}</span>`:''}${iconBtn(item.bookmarked?'取消收藏':'收藏','discover-star',item.id,'star',item.bookmarked)}</div><div class="card-heading"><h3>${e(item.title||item.repository)}</h3></div><p class="description">${e(item.summary||'暂无摘要，可查看原始来源了解详情。')}</p>${trending?`<div class="project-growth"><div><strong>+${e(numberLabel(item.stars_today))}</strong><span>今日新增 Star</span></div><div><strong>${e(numberLabel(item.total_stars))}</strong><span>总 Star</span></div>${item.language?`<div class="project-language"><span>${e(item.language)}</span></div>`:''}</div>`:tags(list(item.tags).slice(0,3))}${item.outside_current_window?`<div class="skill-meta-line">${tag('历史收藏 / 试用记录')}</div>`:''}${!trending||item.is_relevant?`<div class="card-reason">${svg('spark')} ${e(discoveryRelevance(item))}</div>`:''}${project?`<div class="skill-meta-line">${!trending||item.license?tag(`许可：${item.license||'未知'}`):''}${tag(trialLabel(item.trial_status))}</div>`:''}<div class="card-footer"><span class="card-source" title="${e(item.source)}">${e(item.source||'手动添加')} · ${e(shortDate(item.published_at||item.fetched_at))}</span>${btn('查看详情','discover-detail',item.id,'ghost small','arrow')}</div></article>`;
}
function renderDiscover() {
  const v=views.discover,rankings=v.kind==='models',project=v.kind==='project';
  const header=intro('发现','有用的信息，新的工具，以及它们与你的关系。',rankings?'':btn('兴趣设置','interests','','secondary','discover')+btn('添加开源项目','project-add','','primary','plus'));
  const trending=S.discover?.trending||{},trendingIDs=new Set(list(trending.item_ids));
  const tabs=`<div class="tabs">${[['news','资讯'],['project','开源项目'],['models','模型榜']].map(([kind,label])=>`<button type="button" class="tab ${v.kind===kind?'active':''}" data-action="filter" data-page="discover" data-key="kind" data-value="${kind}" aria-pressed="${v.kind===kind}">${label}</button>`).join('')}</div>`;
  if(rankings)return `${header}${tabs}${renderModelLeaderboards()}`;
  const filtered=discoverItems().filter(x=>x.kind===v.kind&&(v.filter==='trending'?trendingIDs.has(x.id):v.filter==='all'?true:v.filter==='saved'?x.bookmarked:x.is_relevant===true)&&[x.title,x.repository,x.summary,x.reason,x.language,...list(x.tags)].join(' ').toLowerCase().includes(v.query.toLowerCase()));
  if(project&&v.filter==='trending')filtered.sort((a,b)=>(Number(b.stars_today)||0)-(Number(a.stars_today)||0)||(Number(a.trending_rank)||0)-(Number(b.trending_rank)||0));
  const items=filtered.slice(0,v.visibleCount);
  const source=project?`<p class="discovery-source">${external(trending.source_url||'https://github.com/trending?since=daily','GitHub 今日趋势','text-link')}<span>${e(trending.window_label||'今日新增 Star')} · 按新增 Star 排序</span></p>`:`<p class="discovery-source">资讯来源：${external(S.discover?.source_url||'https://aihot.news','AIHOT','text-link')}<span>先看 10 条，有兴趣再查看更多。</span></p>`;
  const filters=project?[['trending','今日飙升'],['all','全部项目'],['relevant','与我相关'],['saved','已收藏']]:[['all','全部'],['relevant','与我相关'],['saved','已收藏']];
  const paging=filtered.length>items.length?`<div class="discovery-pagination"><span>已展示 ${items.length} 条</span>${btn('查看更多','discover-more','','secondary','plus')}</div>`:items.length?`<p class="discovery-list-end">${project&&v.filter==='trending'?`今日飙升精选 · ${items.length} 个项目`:`已展示全部 ${items.length} 条`}</p>`:'';
  return `${header}${tabs}${project?discoverySourceNotice(trending,'开源日榜'):discoverySourceNotice(S.discover,'资讯来源')}${source}<div class="toolbar"><div class="filters">${filters.map(([val,label])=>filter('discover','filter',val,label)).join('')}</div><div class="toolbar-actions">${search('discover',project?'搜索项目与用途':'搜索资讯与关键词')}${btn(project?'更新日榜':'更新资讯',project?'trending-refresh':'discover-refresh','','subtle small','refresh')}</div></div><div class="card-grid discovery-grid">${items.length?items.map(discoveryCard).join(''):empty(v.filter==='saved'?'还没有收藏':project&&v.filter==='trending'?'暂时没有可显示的日榜项目':'暂时没有匹配的发现',v.filter==='saved'?'点击资讯或项目上的星标，有用的发现就会留在这里。':project&&v.filter==='trending'?'更新日榜以读取近期热门项目；已添加的项目可在“全部项目”中查看。':'可以调整条件，或者手动添加你感兴趣的开源项目。','discover')}</div>${paging}<p class="source-stamp">${project?`日榜最近成功读取 ${e(timestamp(trending.updated_at))} · 最近核对 ${e(timestamp(trending.checked_at))}`:`最近更新 ${e(timestamp(S.discover?.updated_at))}`}${list(S.settings?.interests||S.discover?.interests).length?` · 关注领域：${e(list(S.settings?.interests||S.discover?.interests).join('、'))}`:''} · 收藏和试用记录会保留。</p>`;
}
function trialLabel(value) {return ({saved:'已收藏',untried:'未试用',pending:'待试用',to_try:'待试用',tried:'已试用',adopted:'已采用',rejected:'暂不适用'})[value]||value||'未试用';}
function discoveryRelevance(item) {return item.is_relevant===true ? `匹配你的关注：${list(item.interest_matches).map(textValue).join('、') || '兴趣领域'}。具体用途仍需结合任务判断。` : '尚未匹配到你的关注领域，可以打开详情自行判断。';}
const skillGroups = [
  {category:'AI 生图',description:'图片生成、改图与海报创作。'},
  {category:'PPT 演示',description:'商业路演、学术汇报与可编辑演示文稿。'},
  {category:'文档与表格',description:'文档、PDF 与表格的制作和处理。'},
  {category:'效率工具',description:'任务同步与常用工作流程。'}
];
function skillCard(s) {
  return `<article class="content-card skill-card"><div class="card-top"><span class="card-symbol">${svg(s.category==='AI 生图'?'spark':s.category==='PPT 演示'?'file':'skills')}</span>${iconBtn(s.starred?'移出常用':'加入常用','skill-star',s.id,'star',s.starred)}</div><div class="card-heading"><h3>${e(skillName(s))}</h3>${s.declared_version?`<span class="skill-version">${e(s.declared_version)}</span>`:''}</div>${s.display_name&&s.display_name!==s.name?`<p class="skill-technical-name">${e(s.name)}</p>`:''}<p class="description">${e(skillSummary(s))}</p>${tags(list(s.tags).length?list(s.tags).slice(0,3):s.category?[s.category]:[])}<div class="skill-meta-line">${s.pinned?tag('核心维护'):''}${s.registered?badge('registered'):s.draft?tag('草稿'):tag('已有 Skill')}${sameNameBadge(s)}${badge(s.check_status||'unchecked')}${badge(s.validation_status||'unverified')}</div><div class="card-footer skill-card-footer"><span class="card-source">${e(skillSourceLabel(s))} ${list(s.locations).length>1?`· ${list(s.locations).length} 个入口`:''}</span><div class="skill-card-actions">${btn('复制地址','skill-copy-address',s.id,'secondary small','copy')}${btn('查看详情','skill-detail',s.id,'ghost small','arrow')}</div></div></article>`;
}
function renderSkills() {
  const v=views.skills,all=skillItems(),common=commonSkills();
  const filtered=all.filter(s=>(v.filter==='archived'?s.archived:!s.archived)&&(v.filter==='starred'?s.starred:v.filter==='draft'?s.draft&&!s.registered:v.filter==='mine'?s.draft:v.filter==='needs'?['invalid','warning'].includes(s.check_status)||!s.package_complete:v.filter==='registered'?s.registered:v.filter==='verified'?s.validation_status==='verified':true)&&(v.category==='all'||s.category===v.category)&&[s.name,s.display_name,s.description,s.category,s.notes,...list(s.tags),...list(s.scenarios)].join(' ').toLowerCase().includes(v.query.toLowerCase())).sort((a,b)=>Number(Boolean(b.pinned))-Number(Boolean(a.pinned)));
  const priority=skillGroups.map(group=>group.category);
  const categories=[...new Set(all.map(s=>s.category).filter(Boolean))].sort((a,b)=>{
    const ai=priority.indexOf(a),bi=priority.indexOf(b);
    return (ai<0?priority.length:ai)-(bi<0?priority.length:bi)||a.localeCompare(b,'zh-CN');
  });
  const groupCategories=[...priority,...new Set(filtered.map(s=>s.category||'其他技能').filter(c=>!priority.includes(c)))];
  const sections=[{category:'核心维护',description:'更新任务看板与 Skills 库，先从这里开始。',items:filtered.filter(s=>s.pinned)},...groupCategories.map(category=>({category,description:skillGroups.find(group=>group.category===category)?.description||'其他加入常用的能力。',items:filtered.filter(s=>!s.pinned&&(s.category||'其他技能')===category)}))].filter(group=>group.items.length);
  const cards=filtered.length?(v.filter==='starred'?`<div class="skill-sections">${sections.map((section,i)=>`<section class="skill-section" aria-labelledby="skill-section-${i}"><div class="skill-section-head"><h2 id="skill-section-${i}">${e(section.category)} <span class="count-chip">${section.items.length}</span></h2><p>${e(section.description)}</p></div><div class="card-grid">${section.items.map(skillCard).join('')}</div></section>`).join('')}</div>`:`<div class="card-grid">${filtered.map(skillCard).join('')}</div>`):empty('没有匹配的 Skills',v.filter==='starred'?'调整搜索或分类；也可以到全部技能中，把需要的能力加入常用。':v.filter==='draft'?'可以从任务中沉淀方法，或新建一份 Skill 草稿。':'调整筛选或搜索，也可以重新扫描已有来源。','skills');
  return `${intro('Skills 库','生图、演示与日常办公，常用能力随手可取。',btn('扫描来源','skills-scan','','secondary','refresh')+btn('新建草稿','skill-create','','primary','plus'))}${errorNotice(S.skills?.errors)}<div class="metrics-row">${metric('常用 Skills',common.length,'star')}${metric('AI 生图',common.filter(s=>s.category==='AI 生图').length,'spark')}${metric('PPT 演示',common.filter(s=>s.category==='PPT 演示').length,'file')}${metric('我的草稿',all.filter(s=>s.draft&&!s.registered&&!s.archived).length,'edit')}</div><div class="toolbar"><div class="filters">${[['starred','常用精选'],['all','全部技能'],['draft','未登记草稿'],['mine','我沉淀的'],['needs','待完善'],['registered','已登记'],['verified','已验证'],['archived','已归档']].map(([val,label])=>filter('skills','filter',val,label)).join('')}</div><div class="toolbar-actions">${search('skills',v.filter==='starred'?'搜索常用技能或使用场景':'搜索名称、用途或标签')}<select class="filter-select" data-select="skills" data-key="category" aria-label="分类筛选"><option value="all">所有分类</option>${categories.map(c=>`<option value="${e(c)}" ${v.category===c?'selected':''}>${e(c)}</option>`).join('')}</select></div></div>${cards}<p class="source-stamp">${v.filter==='all'?`全部技能保留 ${all.filter(s=>!s.archived).length} 个来源技能包 · `:''}可随时加入或移出常用 · 来源 Skill 只读 · 最近扫描 ${e(timestamp(S.skills?.scanned_at))}</p>`;
}
function resource(label,value,note='') {
  const valid=typeof value==='number'&&Number.isFinite(value);
  return `<div><div class="resource-label"><span>${e(label)}</span><strong>${valid?`${Math.round(value)}%`:'—'}</strong></div><div class="resource-track"><span style="width:${valid?Math.max(0,Math.min(100,value)):0}%"></span></div><p class="resource-note">${e(note||(!valid?'未提供指标':''))}</p></div>`;
}
function renderDevices() {
  const v=views.devices,all=deviceItems(),filtered=all.filter(d=>v.filter==='archived'?d.archived:!d.archived);
  const active=all.filter(d=>!d.archived),connected=active.filter(d=>!deviceRegisteredOnly(d)&&d.enabled!==false&&['online','ready','available','ok','healthy'].includes(d.status));
  const sections=deviceSections.map(section=>({...section,items:filtered.filter(d=>deviceSection(d)===section.id)})).filter(section=>section.items.length);
  return `${intro('设备管理','把日常电脑与服务器环境分开查看。',btn('登记设备','device-create','','primary','plus'))}<div class="metrics-row">${metric('登记设备',active.length,'devices')}${metric('可达设备',connected.length,'check')}${metric('已启用采集',active.filter(d=>!deviceRegisteredOnly(d)&&d.enabled!==false).length,'refresh')}${metric('待核验 / 暂不可达',active.filter(d=>deviceRegisteredOnly(d)||['unknown','unavailable','offline','stale','error','loading','unconnected','not_connected','not_configured',null,undefined].includes(d.status)).length,'info')}</div><div class="toolbar"><div class="filters">${filter('devices','filter','active','当前设备')}${filter('devices','filter','archived','已归档')}</div><span class="state-text">已登记不代表在线；连接失败不等于关机</span></div><div class="device-sections">${sections.length?sections.map(section=>`<section class="device-section" aria-labelledby="device-section-${e(section.id)}"><div class="device-section-head"><div><h2 id="device-section-${e(section.id)}">${e(section.title)} <span class="count-chip">${section.items.length}</span></h2><p>${e(section.description)}</p></div></div><div class="device-grid">${section.items.map(deviceCard).join('')}</div></section>`).join(''):empty(v.filter==='archived'?'没有归档设备':'还没有登记设备','先登记设备信息；没有采集来源时只显示资料与待核验状态。','devices',btn('登记设备','device-create','','secondary small','plus'))}</div><p class="source-stamp">最近采集 ${e(timestamp(S.devices?.updated_at))} · 管理操作只影响工作台的登记与采集设置。</p>`;
}
const deviceSections=[
  {id:'personal',title:'个人电脑',description:'用于日常工作的电脑与本地设备。'},
  {id:'research',title:'研发与算力',description:'研发服务器与算力设备。'},
  {id:'test',title:'测试环境',description:'测试服务的地址与环境资料。'},
  {id:'production',title:'生产环境',description:'生产服务的地址与环境资料。'},
  {id:'other',title:'其他设备',description:'其他已登记的设备。'}
];
function deviceRegisteredOnly(d) {return ['manual','none'].includes(d.source_kind);}
function deviceSection(d) {
  const context=[d.environment,d.group].filter(Boolean).join(' ');
  if(/生产/.test(context))return 'production';
  if(/测试/.test(context))return 'test';
  if(/研发|算力/.test(context))return 'research';
  if(/个人|日常|本机|办公|烧录/.test(context))return 'personal';
  return 'other';
}
function deviceBadge(d) {return deviceRegisteredOnly(d)?tag('已登记'):badge(d.enabled===false?'disabled':d.status);}
function deviceAddressRows(d) {return [['地址',d.address],['主机名',d.hostname],['域名',d.domain]].filter(([,value])=>value);}
function deviceCard(d) {
  const registered=deviceRegisteredOnly(d),m=registered?{}:d.metrics||{},addresses=deviceAddressRows(d);
  return `<article class="device-card"><div class="card-top"><div class="device-identity"><span class="card-symbol">${svg('devices')}</span><div><h3>${e(d.name)}</h3><p>${e(d.system||'系统未提供')} · ${e(d.environment||d.group||'个人设备')}</p></div></div>${deviceBadge(d)}</div><div class="tags">${tag(sourceKindLabel(d.source_kind))}${d.alias?tag(d.alias):''}${d.archived?tag('已归档'):''}</div>${addresses.length?`<dl class="device-addresses">${addresses.map(([label,value])=>`<div><dt>${e(label)}</dt><dd>${e(value)}</dd></div>`).join('')}</dl>`:''}${d.note?`<p class="device-note">${e(d.note)}</p>`:''}${registered?'<p class="device-registration">资料登记，运行状态尚未核验。</p>':''}<div class="resource-grid">${resource('CPU',m.cpu_percent)}${resource('内存',m.memory_percent,m.memory_total_gb!=null?`${m.memory_used_gb!=null?Number(m.memory_used_gb).toFixed(1):'—'} / ${Number(m.memory_total_gb).toFixed(1)} GB`:'')}${resource('磁盘',m.disk_percent,m.disk_free_gb!=null?`可用 ${Number(m.disk_free_gb).toFixed(1)} GB`:'')}</div>${!registered&&d.error?notice(d.error,'amber'):''}<div class="device-footer"><span>${registered?'仅保存设备资料':`最近成功 ${e(timestamp(d.last_success_at))}`}</span><div class="row-actions">${btn('详情','device-detail',d.id,'ghost small')}${btn('编辑','device-edit',d.id,'secondary small')}${!d.archived?btn(registered?'刷新资料':'刷新','device-refresh',d.id,'subtle small','refresh'):''}</div></div></article>`;
}
function sourceKindLabel(value) {return ({local:'本机采集',ssh:'只读连接',manual:'仅登记',none:'仅登记',candidate:'候选设备',bridge:'状态桥接'})[value]||value||'来源未配置';}
function renderAgents() {
  const v=views.agents,all=agentItems(),filtered=all.filter(a=>v.filter==='hidden'?a.hidden:!a.hidden),roles=roleItems().filter(r=>!r.archived);
  return `${intro('AI 管理','区分工具实例与角色，让 AI 的归属和能力清清楚楚。',btn('新建角色','role-create','','primary','plus'))}<div class="metrics-row">${metric('可见 AI 实例',all.filter(a=>!a.hidden).length,'agents')}${metric('角色',roles.length,'folder')}${metric('会话来源可用',all.filter(a=>!a.hidden&&['ok','ready','available','healthy','online'].includes(a.source_state)).length,'check')}${metric('已隐藏',all.filter(a=>a.hidden).length,'info')}</div>${notice('进程、来源响应与会话活动分别展示。“处理中”由会话记录推断；完成未读不等于待审批。')}<div class="toolbar"><div class="filters">${filter('agents','filter','visible','可见实例')}${filter('agents','filter','hidden','已隐藏')}</div>${btn('刷新 AI 状态','agents-refresh','','subtle small','refresh')}</div><div class="agent-grid">${filtered.length?filtered.map(a=>{const device=deviceItems().find(d=>d.id===a.device_id),ars=list(a.role_ids).map(id=>roleItems().find(r=>r.id===id)).filter(Boolean);return `<article class="agent-card"><div class="card-top"><div class="device-identity"><span class="card-symbol">${svg('agents')}</span><div><h3>${e(a.name||a.platform)}</h3><p>${e(a.platform||'来源未提供')} · ${e(device?.name||'设备归属未提供')}</p></div></div>${a.hidden?tag('已隐藏'):a.enabled===false?badge('disabled'):badge(a.source_state,'来源状态未知')}</div><div class="tags">${ars.length?ars.map(r=>tag(r.name)).join(''):tag('未绑定角色')}${a.process_state?tag(`进程：${processLabel(a.process_state)}`):tag('进程：未知')}</div><div class="agent-counts"><div class="agent-count"><strong>${Number.isFinite(a.running)?a.running:'—'}</strong><span>处理中 · 按记录推断</span></div><div class="agent-count"><strong>${Number.isFinite(a.completed_unread)?a.completed_unread:'—'}</strong><span>完成未读</span></div></div><div class="agent-activity">${e(a.activity_label||'尚无可用活动证据')}${a.source_updated_at?`<br>来源时间 ${e(timestamp(a.source_updated_at))}`:''}</div>${a.error?notice(a.error,'amber'):''}<div class="device-footer"><span>采集 ${e(timestamp(a.observed_at))}</span><div class="row-actions">${btn('详情','agent-detail',a.id,'ghost small')}${btn('绑定角色','agent-bind',a.id,'secondary small')}${btn(a.hidden?'显示':'隐藏','agent-hide',a.id,'subtle small')}</div></div></article>`;}).join(''):empty(v.filter==='hidden'?'没有隐藏的 AI 实例':'还没有可用的 AI 实例','已有工具接入后会显示在这里。角色可以先登记，实例不会用假数据填充。','agents')}</div><section class="panel roles-panel"><div class="panel-head"><div class="panel-title">${svg('folder')}<h2>我的 AI 角色</h2><small>${roles.length}</small></div>${btn('新建角色','role-create','','ghost small','plus')}</div>${roles.length?`<div class="role-grid">${roles.map(r=>`<article class="role-card"><h3>${e(r.name)}</h3><p>${e(r.description||'暂无角色说明')}</p>${tags(list(r.tags).slice(0,3))}<div class="row-actions">${btn('编辑','role-edit',r.id,'ghost small')}${btn('关联 Skill','role-skills',r.id,'secondary small')}${btn('归档','role-archive',r.id,'ghost small')}</div></article>`).join('')}</div>`:empty('先为你的 AI 团队定义角色','角色描述职责，工具实例代表实际运行来源，两者可以分别管理。','agents')}${roleItems().some(r=>r.archived)?`<div class="panel-body"><details class="raw-details"><summary>已归档角色（${roleItems().filter(r=>r.archived).length}）</summary>${roleItems().filter(r=>r.archived).map(r=>`<div class="detail-line"><span>${e(r.name)}</span>${btn('恢复','role-restore',r.id,'secondary small')}</div>`).join('')}</details></div>`:''}</section><p class="source-stamp">最近读取 ${e(timestamp(S.agents?.updated_at))} · 实例管理不启动、停止或控制原工具。</p>`;
}
function processLabel(value) {return ({running:'在线',online:'在线',stopped:'未检测到',missing:'未检测到',unknown:'未知',not_detected:'未检测到',not_running:'未检测到'})[value]||value;}

function openModal(title,html,{submit=null,label='保存',wide=false,eyebrow='我的工作台'}={}) {
  modalGeneration++;
  modalSubmit=submit;q('#modal-title').textContent=title;q('#modal-eyebrow').textContent=eyebrow;q('#modal-body').innerHTML=html;
  q('#modal-submit').textContent=label;q('#modal-submit').hidden=!submit;q('#modal-submit').disabled=false;
  q('#modal-form').reset();modal.classList.toggle('wide',wide);
  if (!modal.open) modal.showModal();document.body.classList.add('dialog-open');
}
function closeModal() {modalGeneration++;if(modal.open)modal.close();modalSubmit=null;document.body.classList.remove('dialog-open');}
function confirmAction(title,message,callback,label='确认') {openModal(title,`<p class="confirm-text">${e(message)}</p>`,{label,submit:callback});}
function field(name,label,value='',{type='text',required=false,hint='',placeholder='',full=false,rows=0,options=null,disabled=false}={}) {
  const id=`field-${name}`;
  const common=`id="${e(id)}" name="${e(name)}" ${required?'required':''} ${disabled?'disabled':''}`;
  let control;
  if(options) control=`<select ${common}>${options.map(([v,l])=>`<option value="${e(v)}" ${String(value)===String(v)?'selected':''}>${e(l)}</option>`).join('')}</select>`;
  else if(rows) control=`<textarea ${common} rows="${Number(rows)}" placeholder="${e(placeholder)}" ${name==='body'?'class="code-input" spellcheck="false"':''}>${e(value)}</textarea>`;
  else control=`<input ${common} type="${e(type)}" value="${e(value)}" placeholder="${e(placeholder)}" ${name==='name'?'maxlength="100"':''}>`;
  return `<div class="field ${full?'full':''}"><label for="${e(id)}">${e(label)}</label>${control}${hint?`<small class="field-hint">${e(hint)}</small>`:''}</div>`;
}
function detailSection(title,content) {return `<section class="detail-section"><h3>${e(title)}</h3>${content}</section>`;}
function detailList(values,ordered=false,emptyText='暂无说明') {return list(values).length?`<${ordered?'ol':'ul'}>${list(values).map(value=>`<li>${e(textValue(value))}</li>`).join('')}</${ordered?'ol':'ul'}>`:`<p>${e(emptyText)}</p>`;}
function infoGrid(entries) {return `<div class="detail-meta">${entries.map(([label,value])=>`<div><small>${e(label)}</small><span>${e(textValue(value)||'未提供')}</span></div>`).join('')}</div>`;}
function linkedSkills(type,id) {
  return linkedObjects(type,id,'skill');
}
function entityItems(type) {return ({task:taskItems,skill:skillItems,agent:agentItems,discover:discoverItems,device:deviceItems,role:roleItems}[type]||(()=>[]))();}
function entityMatches(type,item,id) {return item.id===id||(type==='discover'&&list(item.alias_ids).includes(id));}
function entityName(type,item) {return type==='skill'?skillName(item):item?.title||item?.name||'关联对象暂不可用';}
function entityLabel(type) {return ({task:'任务',skill:'Skill',agent:'AI 实例',discover:'发现',device:'设备',role:'角色'})[type]||'对象';}
function relationRows(records,contextType,contextId,inverse=false) {
  if(!records.length)return '<p class="state-text">尚无关联。</p>';
  return records.map(r=>{const type=inverse?r.from_type:r.to_type,id=inverse?r.from_id:r.to_id,item=entityItems(type).find(x=>entityMatches(type,x,id)),snapshot=inverse?r.from_snapshot:r.to_snapshot,name=item?entityName(type,item):snapshot?.title||snapshot?.name||'关联对象暂不可用';return `<div class="detail-line"><span>${e(name)}${!item?' · 来源暂不可用':''}${item?.archived?' · 已归档':''}${item?.hidden?' · 已隐藏':''}</span><div class="row-actions">${item&&['task','skill','agent','discover','device'].includes(type)?btn('查看',`${type}-detail`,item.id,'ghost small'):''}${btn('取消关联','relation-delete',r.id,'ghost small','',`data-return-type="${e(contextType)}" data-return-id="${e(contextId)}"`)}</div></div>`;}).join('');
}
function linkedObjects(type,id,target) {
  const item=entityItems(type).find(x=>entityMatches(type,x,id));
  return relationRows(relations().filter(r=>r.from_type===type&&(item?entityMatches(type,item,r.from_id):r.from_id===id)&&r.to_type===target),type,id);
}
async function reopenDetail(type,id) {
  if(type==='task')openTaskBoard(id);
  else if(type==='discover')showDiscover(id);
  else if(type==='agent')showAgent(id);
  else if(type==='device')showDevice(id);
  else if(type==='skill')await showSkill(id);
}
function showFocusPicker() {
  const items=taskItems().filter(t=>t.status!=='done').sort((a,b)=>(a.priority??9)-(b.priority??9));
  const selected=focusIDs();
  openModal('选择今日重点',`<p class="field-hint">今天最多 3 个重点。选择仅影响今天的个人安排，不改变原任务优先级。</p><div class="checkbox-list">${items.map(t=>`<label class="check-row"><input type="checkbox" name="focus" value="${e(t.id)}" ${selected.includes(t.id)?'checked':''}><span>${e(t.title)}<small>P${e(t.priority??'?')} · ${e(statusMap[t.status]?.[0]||t.status)}${t.parent?' · 子任务':''}</small></span></label>`).join('')||empty('暂无可选任务','任务来源可用后可以选择重点。','tasks')}</div>`,{label:'保存今日重点',submit:async fd=>{const chosen=fd.getAll('focus');if(chosen.length>3)throw new Error('今天最多选择 3 个重点，给自己留一点余地。');const ordered=[...selected.filter(id=>chosen.includes(id)),...chosen.filter(id=>!selected.includes(id))];await mutate('/api/daily',{focus_task_ids:ordered});}});
}
async function changeFocus(id,action) {
  const ids=[...focusIDs()];const index=ids.indexOf(id);
  if(action==='add'){if(index>=0)return;if(ids.length>=3)throw new Error('已经有 3 个今日重点，请先移除一个。');ids.push(id);}
  else if(action==='remove'){if(index>=0)ids.splice(index,1);}
  else {const other=index+(action==='up'?-1:1);if(index<0||other<0||other>=ids.length)return;[ids[index],ids[other]]=[ids[other],ids[index]];}
  await mutate('/api/daily',{focus_task_ids:ids},{close:false,message:action==='remove'?'已移除今日重点':'今日重点已更新'});
  if(modal.open && taskItems().some(t=>t.id===id))openTaskBoard(id);
}
function showRelationPicker(type,id,target='skill') {
  const context=entityItems(type).find(x=>entityMatches(type,x,id));
  const existing=relations().filter(r=>r.from_type===type&&(context?entityMatches(type,context,r.from_id):r.from_id===id)&&r.to_type===target);
  const choices=entityItems(target).filter(item=>(!item.archived&&!item.hidden)||existing.some(r=>r.to_id===item.id));
  openModal(`关联${target==='skill'?'已有 Skill':entityLabel(target)}`,`<p class="field-hint">仅保存关联关系，不派单、不执行或安装，也不修改原任务与来源文件。</p><div class="checkbox-list">${choices.map(item=>`<label class="check-row"><input type="checkbox" name="targets" value="${e(item.id)}" ${existing.some(r=>r.to_id===item.id)?'checked':''}><span>${e(entityName(target,item))}<small>${e(item.description||item.brief||item.platform||'')}${item.archived?' · 已归档':''}${item.hidden?' · 已隐藏':''}</small></span></label>`).join('')||empty(`还没有可关联的${entityLabel(target)}`,'对象接入后即可在这里建立关联。',target==='agent'?'agents':target==='task'?'tasks':'skills')}</div>`,{label:'保存关联',submit:async fd=>{
    const chosen=[...fd.getAll('targets'),...existing.filter(r=>!choices.some(item=>item.id===r.to_id)).map(r=>r.to_id)];
    for(const r of existing) if(!chosen.includes(r.to_id)) await api(`/api/relations/${encodeURIComponent(r.id)}`,undefined,'DELETE');
    for(const tid of chosen) if(!existing.some(r=>r.to_id===tid)) await api('/api/relations',{from_type:type,from_id:id,to_type:target,to_id:tid});
    closeModal();await load({force:true});toast('关联已更新');await reopenDetail(type,id);
  }});
}
function showDiscover(id) {
  const item=discoverItems().find(x=>entityMatches('discover',x,id));if(!item)return;
  id=item.id;
  const project=item.kind==='project',trending=project&&item.daily_trending===true;
  const aggregatorURL=(trending?safeURL(item.source_url):null)||safeURL(item.canonical_url)||safeURL(item.attribution?.url);
  const attribution=aggregatorURL?`<div class="discovery-attribution"><span>${trending?'榜单来源':'聚合来源'}</span>${external(aggregatorURL,trending?'GitHub 今日趋势':item.attribution?.name||'AIHOT','text-link')}</div>`:'';
  const growth=trending?detailSection('今日热度',`<div class="project-growth detail-project-growth"><div><strong>+${e(numberLabel(item.stars_today))}</strong><span>今日新增 Star</span></div><div><strong>${e(numberLabel(item.total_stars))}</strong><span>总 Star</span></div>${item.language?`<div><strong>${e(item.language)}</strong><span>主要语言</span></div>`:''}</div><p class="field-hint">GitHub 日榜提供的今日增量 · 核对时间 ${e(timestamp(item.fetched_at))}</p>`):'';
  openModal(item.title,`<div class="tags detail-tags">${tag(project?'开源项目':'资讯')}${tags(item.tags)}${item.bookmarked?tag('已收藏'):''}${item.outside_current_window?tag('历史收藏 / 试用记录'):''}</div><div class="inline-actions">${external(item.url,project?'打开官方仓库':'查看原文')}${btn(item.bookmarked?'取消收藏':'收藏','discover-star',id,'subtle small','star')}${project?btn('更新试用状态','project-trial',id,'secondary small','edit'):''}${btn('关联任务','discover-tasks',id,'secondary small','link')}${btn('关联已有 Skill','discover-skills',id,'secondary small','skills')}</div>${infoGrid([[project?'资料来源':'原文来源',item.source],['发布时间',item.published_at?timestamp(item.published_at):'未提供'],['抓取 / 核对时间',timestamp(item.fetched_at)],...(project?[['许可证',item.license||'未核实'],['我的试用状态',trialLabel(item.trial_status)]]:[])])}${attribution}${growth}${detailSection(project?'它解决什么问题':'内容摘要',`<p>${e(item.summary||'来源尚未提供摘要，可打开原始链接核对。')}</p>`)}${detailSection('与我有什么关系',`<p>${e(discoveryRelevance(item))}</p>`)}${item.reason?detailSection('来源提供的价值提要',`<p>${e(item.reason)}</p>`):''}${detailSection('关联任务',linkedObjects('discover',id,'task'))}${detailSection('关联已有 Skills',linkedObjects('discover',id,'skill'))}${project?notice('这是开源项目线索。收藏和试用记录不会安装软件，也不会自动生成 Skill。'):notice('摘要帮助快速判断；具体事实与用途请以原始来源为依据。')}`,{wide:true,eyebrow:project?'开源项目':'资讯详情'});
}
function showInterests() {
  const interests=list(S.settings?.interests||S.discover?.interests);
  openModal('我感兴趣的领域',field('interests','关注领域',interests.join('、'),{rows:3,hint:'用逗号或换行分隔，例如 AI 工具、教育、开源项目。关注领域用于匹配关联理由。',placeholder:'AI 工具\n教育\n产品设计'}),{label:'保存兴趣',submit:fd=>mutate('/api/settings',{interests:String(fd.get('interests')||'').split(/[,，、\n]/).map(x=>x.trim()).filter(Boolean)})});
}
function showProjectAdd() {
  openModal('添加开源项目',`${field('url','GitHub 仓库链接','',{type:'url',required:true,placeholder:'https://github.com/owner/repository',hint:'请输入官方仓库首页。项目会尝试读取公开资料；读取失败仍可保留链接。'})}${field('summary','为什么关注它（可选）','',{rows:3,placeholder:'它可能解决什么问题？'})}`,{label:'添加项目',submit:async fd=>{const result=await mutate('/api/discover/projects',{url:String(fd.get('url')||''),summary:String(fd.get('summary')||'')},{message:'项目已添加'});Object.assign(views.discover,{kind:'project',filter:'all',visibleCount:10,query:''});navigate('discover');render();const projectId=result?.id||result?.project?.id;if(projectId)showDiscover(projectId);}});
}
function showTrial(id) {
  const item=discoverItems().find(x=>x.id===id);if(!item)return;
  openModal('记录项目试用状态',`${field('trial_status','试用状态',item.trial_status||'untried',{options:[['untried','未试用'],['to_try','待试用'],['tried','已试用'],['adopted','已采用'],['rejected','暂不适用']]})}<p class="field-hint">这是个人记录，不会运行项目或改变仓库。</p>`,{submit:fd=>mutate(`/api/discover/${encodeURIComponent(id)}/meta`,{trial_status:fd.get('trial_status')==='untried'?null:fd.get('trial_status')})});
}
async function showSkill(id) {
  openModal('正在读取 Skill',`<div class="initial-loading" style="padding:50px 15px"><span class="loading-ring"></span><p>读取用途、文件与检查记录…</p></div>`,{wide:true});
  const generation=modalGeneration;
  const result=await api(`/api/skills/${encodeURIComponent(id)}`,undefined,'GET');
  if(!modal.open || generation!==modalGeneration)return;
  const s=result.skill||result;
  const checks=s.checks||{};
  const files=list(s.files);
  const validations=list(s.validations);
  const path=manifestPath(s.manifest_path);
  const address=`<div class="skill-address"><span class="field-label">Skill 绝对地址</span>${path?`<p class="skill-manifest-path" tabindex="0">${e(path)}</p>`:'<p class="state-text">点击“复制地址”核对本地 SKILL.md 位置。</p>'}<p class="field-hint">${e(skillSharingHint)}</p></div>`;
  openModal(skillName(s),`<div class="tags detail-tags">${s.registered?badge('registered'):s.draft?tag('草稿'):tag('来源只读')}${sameNameBadge(s)}${badge(s.check_status||checks.status||'unchecked')}${badge(s.validation_status||'unverified')}</div><p class="task-summary" style="font-size:12px;margin-bottom:17px">${e(skillSummary(s))}</p><div class="inline-actions skill-detail-actions">${btn('复制地址','skill-copy-address',id,'primary small','copy')}<a class="button secondary small" href="/api/skills/${encodeURIComponent(id)}/export">${svg('download')}导出技能包</a>${btn('生成调用说明','skill-prompt',id,'secondary small','file')}${btn(s.starred?'移出常用':'加入常用','skill-star',id,'subtle small','star')}${btn('编辑资料','skill-meta',id,'secondary small','edit')}${s.draft?btn('编辑草稿','skill-edit',id,'secondary small','edit'):''}${btn('重新检查','skill-check',id,'secondary small','shield')}${s.draft&&!s.registered?btn('登记 Skill','skill-register',id,'secondary small','check'):''}${btn('记录验证','skill-validate',id,'secondary small','plus')}${btn(s.archived?'恢复显示':'归档','skill-archive',id,'ghost small')}</div>${address}${infoGrid([['分类',s.category||'未分类'],['版本 / 修订',s.version||s.revision_id||'未提供'],['来源',skillSourceLabel(s)],['登记状态',s.registered?'已登记':'未单独登记']])}${tags(s.tags)}${Number(s.same_name_count)>1?notice(s.same_name_different_content?'检测到同名但内容不同的独立技能包。这里显示当前来源，登记与验证按各包分别记录。':'检测到多个内容一致的同名技能包，仍按真实来源分别显示。','amber'):''}${detailSection('输入与输出',`<div class="form-grid"><div>${detailSection('输入',detailList(s.inputs))}</div><div>${detailSection('输出',detailList(s.outputs))}</div></div>`)}${detailSection('依赖与运行前提',detailList(s.dependencies,false,'未提供依赖声明，请结合正文核对。'))}${detailSection('检查结果',`<div class="tags">${badge(checks.status||s.check_status||'unchecked')}${tag(checks.complete?'完整性已确认':'完整性待核实')}</div>${list(checks.issues).length?`<ul style="margin-top:10px">${list(checks.issues).map(issue=>`<li>${e(issue.message||textValue(issue))}${issue.path?`<small class="muted"> · ${e(issue.path)}</small>`:''}</li>`).join('')}</ul>`:'<p style="margin-top:8px">没有额外检查提示。</p>'}${list(checks.missing_references).length?`<p style="margin-top:8px">缺失引用：${e(checks.missing_references.map(textValue).join('、'))}</p>`:''}`)}${detailSection('验证记录',validations.length?validations.slice().reverse().map(v=>`<div class="detail-section">${infoGrid([['场景',v.scenario],['环境',v.environment],['结果',({success:'手动记录成功',failure:'手动记录失败',partial:'部分通过'})[v.result]||v.result],['记录时间',timestamp(v.at||v.created_at)],['对应版本',v.current===false?'旧版本记录，不代表当前包':v.current===true?'当前版本':'未提供']])}<p>${e(v.evidence||'未提供证据')}</p></div>`).join(''):'<p>尚未记录实际验证。检查通过不等于运行成功。</p>')}${detailSection('来源位置',list(s.locations).map(loc=>`<div class="detail-line"><span><small class="muted">${e(loc.label||'来源')} ${loc.symlink?'· 符号链接':''}</small><br>${e(loc.path||loc.real_path)}</span></div>`).join('')||'<p>位置未提供</p>')}<details class="raw-details"><summary>查看包文件（${files.length}）</summary>${files.map(f=>`<div class="detail-line"><span>${e(typeof f==='string'?f:f.path||f.name||textValue(f))}</span>${typeof f==='object'&&f.size!=null?`<small>${e(f.size)} 字节</small>`:''}</div>`).join('')||'<p>未提供文件清单</p>'}</details><details class="raw-details"><summary>查看 Skill 正文（纯文本）</summary><pre class="markdown-plain">${e(s.body||'暂无正文')}</pre></details>`,{wide:true,eyebrow:'Skill 详情'});
}
async function showSkillMeta(id) {
  const result=await api(`/api/skills/${encodeURIComponent(id)}`,undefined,'GET'),s=result.skill||result;
  openModal('编辑 Skill 资料',`${field('display_name','显示名称',s.display_name||s.name,{required:true})}<div class="form-grid">${field('category','分类',s.category||'')}${field('tags','标签',list(s.tags).join('、'),{hint:'用逗号、顿号或换行分隔。'})}</div><div class="spacer"></div><label class="inline-checkbox"><input type="checkbox" name="pinned" ${s.pinned?'checked':''}>置顶为核心维护 Skill</label><p class="field-hint">显示名称、分类和标签只保存在工作台，不修改来源包。</p>`,{submit:fd=>mutate(`/api/skills/${encodeURIComponent(id)}/meta`,{display_name:fd.get('display_name'),category:fd.get('category'),tags:String(fd.get('tags')||'').split(/[,，、\n]/).map(x=>x.trim()).filter(Boolean),pinned:fd.has('pinned')})});
}
let draftContext=null;
function resourceFields(editing=false) {
  return `<hr class="divider"><div class="detail-section"><h3>文字资源（可选）</h3><div class="form-grid">${field('resource_dir','资源目录','references',{options:[['references','references · 参考资料'],['scripts','scripts · 脚本文本'],['assets','assets · 文字素材']]})}<div class="field"><label for="field-resource_files">选择 UTF-8 文字文件</label><input type="file" id="field-resource_files" name="resource_files" multiple><small class="field-hint">单文件不超过 1 MB，总计不超过 4 MB；不支持二进制、SKILL.md 或 .env 文件。</small></div></div><p class="field-hint">${editing?'新文件合并到现有资源；同名文件替换，其他资源保留。':'文件会保存到所选目录。'} 仅保存文字，不执行脚本。</p></div>`;
}
async function readResources(fd) {
  const files=fd.getAll('resource_files').filter(file=>file instanceof File&&file.name);
  if(!files.length)return null;
  const prefix=String(fd.get('resource_dir')||'references');
  if(!['references','scripts','assets'].includes(prefix))throw new Error('请选择有效的资源目录。');
  if(files.some(file=>file.size>1024*1024))throw new Error('单个文字资源不能超过 1 MB。');
  if(files.reduce((total,file)=>total+file.size,0)>4*1024*1024)throw new Error('本次文字资源总大小不能超过 4 MB。');
  const result=[],seen=new Set();
  for(const file of files){
    if(/[\\/\x00]/.test(file.name)||/^(?:skill\.md|\.env(?:\..*)?|\.{1,2})$/i.test(file.name))throw new Error(`不能上传 ${file.name}；SKILL.md 请通过正文编辑，.env 文件不支持上传。`);
    if(seen.has(file.name))throw new Error(`本次选择中有重复文件名 ${file.name}，请分别上传或先改名。`);
    seen.add(file.name);
    let text;
    try{text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());}catch{throw new Error(`${file.name} 不是有效的 UTF-8 文字文件。`);}
    if(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(text))throw new Error(`${file.name} 包含二进制控制字符，请选择纯文字文件。`);
    result.push({filename:`${prefix}/${file.name}`,text});
  }
  return result;
}
function draftContent(s,task,mode) {
  const defaultName=task?`${String(task.id).replace(/[^a-z0-9-]/g,'-')}-method`:'';
  const workflow=typeof s?.workflow==='string'?s.workflow:list(s?.workflow).join('\n');
  return `${task?notice(`来自任务「${task.title}」。会建立一个新的方法草稿，原任务不会改变。`):''}${s?`<div class="filters" style="margin-bottom:20px"><button type="button" class="filter ${mode==='structured'?'active':''}" data-action="draft-mode" data-value="structured">结构字段</button><button type="button" class="filter ${mode==='raw'?'active':''}" data-action="draft-mode" data-value="raw">完整原文</button></div>`:''}<div class="form-grid">${field('name','技术名称',s?.name||defaultName,{required:true,hint:'小写字母、数字和连字符，最多 64 个字符。',placeholder:'my-useful-skill'})}${field('display_name','显示名称',s?.display_name||task?.title||'',{required:true,placeholder:'一个清楚的能力名称'})}</div><div class="spacer"></div>${mode==='raw'?field('body','完整 SKILL.md',s?.body||'',{rows:15,required:true,hint:'原文包含 frontmatter。以原文内容为准，保留工具专属字段。'}):`${field('description','用途与触发场景',s?.description||task?.summary||task?.brief||'',{required:true,rows:3,placeholder:'什么时候用，能解决什么问题？'})}<div class="form-grid">${field('inputs','输入',list(s?.inputs).join('\n'),{rows:3,hint:'每行一项。'})}${field('outputs','输出',list(s?.outputs).join('\n'),{rows:3,hint:'每行一项。'})}${field('workflow','执行步骤',workflow||(task?list(task.next).join('\n'):''),{rows:5,full:true,hint:'写下可以重复执行的具体步骤。'})}${field('dependencies','依赖与运行前提',list(s?.dependencies).join('\n'),{rows:3,full:true})}</div>`}${resourceFields(Boolean(s))}<p class="source-stamp">草稿保存在工作台。不会自动执行、安装或注册到其他 AI 工具。</p>`;
}
async function showDraft(id=null,taskId=null,mode='structured') {
  let s=null;
  if(id){const result=await api(`/api/skills/${encodeURIComponent(id)}`,undefined,'GET');s=result.skill||result;}
  const task=taskItems().find(t=>t.id===taskId)||null;
  draftContext={s,task,id,mode};renderDraft();
}
function renderDraft() {
  const {s,task,id,mode}=draftContext;
  openModal(id?'编辑 Skill 草稿':'新建 Skill 草稿',draftContent(s,task,mode),{wide:true,label:id?'保存草稿':'创建草稿',eyebrow:'方法沉淀',submit:async fd=>{
    const payload={name:String(fd.get('name')||'').trim(),display_name:String(fd.get('display_name')||'').trim()};
    if(mode==='raw')payload.body=String(fd.get('body')||'');
    else {payload.description=String(fd.get('description')||'');for(const key of ['inputs','outputs','workflow','dependencies'])payload[key]=lines(fd.get(key));}
    if(id&&s?.fingerprint)payload.expected_fingerprint=s.fingerprint;
    const resources=await readResources(fd);
    if(resources){payload.resources=resources;if(id)payload.resource_mode='merge';}
    if(task)payload.task_id=task.id;
    const result=await mutate(id?`/api/skills/drafts/${encodeURIComponent(id)}`:'/api/skills/drafts',payload,{method:id?'PUT':'POST',message:'草稿已保存'});
    const newId=result.id||result.skill?.id;
    if(task&&newId&&!relations().some(r=>r.from_type==='task'&&r.from_id===task.id&&r.to_type==='skill'&&r.to_id===newId)) {await api('/api/relations',{from_type:'task',from_id:task.id,to_type:'skill',to_id:newId});await load({force:true});}
    if(newId)await showSkill(newId);
  }});
}
function showSkillValidate(id) {
  openModal('记录一次实际验证',`${notice('这里保存你已经完成的验证结果，不会执行 Skill。成功记录需要写明实际产物或证据。')}<div class="form-grid">${field('scenario','验证场景','',{required:true,full:true,placeholder:'这次使用它完成了什么任务？'})}${field('environment','AI / 设备环境','',{required:true,full:true,placeholder:'例如 Codex · Mac mini'})}${field('result','验证结果','success',{options:[['success','成功'],['partial','部分通过'],['failure','失败']],full:true})}${field('evidence','实际产物或证据','',{rows:5,full:true,placeholder:'写明产物、执行情况或失败原因。请不要粘贴密钥。'})}</div>`,{label:'保存验证记录',submit:fd=>mutate(`/api/skills/${encodeURIComponent(id)}/validate`,{scenario:fd.get('scenario'),environment:fd.get('environment'),result:fd.get('result'),evidence:fd.get('evidence')})});
}
let promptText='';
function showPromptForm(id) {
  openModal('准备调用说明',`${field('task_id','关联任务（可选）','',{options:[['','不指定任务'],...taskItems().filter(t=>t.status!=='done').map(t=>[t.id,t.title])]})}${field('target','目标 AI（可选）','',{options:[['','通用调用说明'],...agentItems().filter(a=>!a.hidden).map(a=>[a.id,a.name||a.platform])]})}<p class="field-hint">生成可复制的说明，由你粘贴给目标 AI；不会发送消息或执行任务。</p>`,{label:'生成说明',submit:async fd=>{
    const params=new URLSearchParams();if(fd.get('task_id'))params.set('task_id',fd.get('task_id'));if(fd.get('target'))params.set('target',fd.get('target'));
    const result=await api(`/api/skills/${encodeURIComponent(id)}/prompt?${params}`,undefined,'GET');promptText=typeof result==='string'?result:result.prompt||result.text||'';
    if(!promptText)throw new Error('来源没有返回调用说明。');
    openModal('调用说明已准备好',`<pre class="code-block" id="prompt-text">${e(promptText)}</pre><div class="inline-actions">${btn('复制调用说明','copy-prompt','','primary','copy')}</div><p class="source-stamp">复制后自行交给目标 AI。这一步不会执行 Skill。</p>`,{wide:true});
  }});
}
async function copySkillAddress(id) {
  const target=await api(`/api/skills/${encodeURIComponent(id)}/copy-target`,undefined,'GET');
  const path=manifestPath(target.manifest_path);
  if(!path)throw new Error('没有可复制的 SKILL.md 绝对地址，请重新扫描来源。');
  await copyText(path,{manualTitle:'手动复制 Skill 地址',label:'Skill 绝对地址',hint:skillSharingHint});
}
async function copyText(value,{manualTitle='手动复制',label='待复制内容',hint='请选择下面的完整文本，手动复制。'}={}) {
  let copied=false;
  try {await navigator.clipboard.writeText(value);copied=true;}
  catch {
    const textarea=document.createElement('textarea');textarea.value=value;textarea.style.position='fixed';textarea.style.left='-9999px';
    try {(modal.open?q('#modal-body'):document.body).appendChild(textarea);textarea.focus({preventScroll:true});textarea.select();textarea.setSelectionRange(0,value.length);copied=document.execCommand('copy');}
    catch {copied=false;}
    finally {textarea.remove();}
  }
  if(copied){toast('已复制到剪贴板');return true;}
  openModal(manualTitle,`<p class="copy-fallback-message">浏览器未能自动复制，请手动选中以下文本复制。</p><div class="field"><label for="manual-copy-text">${e(label)}</label><textarea id="manual-copy-text" class="manual-copy-text" readonly rows="4" spellcheck="false">${e(value)}</textarea><small class="field-hint">${e(hint)}</small></div>`,{wide:true,eyebrow:'复制地址'});
  const manual=q('#manual-copy-text');manual.focus();manual.select();
  return false;
}
function showDeviceForm(id=null) {
  const d=deviceItems().find(x=>x.id===id)||{};
  const fixed=Boolean(id&&!deviceRegisteredOnly(d));
  openModal(id?'编辑设备资料':'登记设备',`${!id?notice('新设备先作为资料登记，运行状态显示待核验。真实采集需要可用的适配来源。'):''}<div class="form-grid">${field('name','设备名称',d.name||'',{required:true,placeholder:'我的设备'})}${field('system','系统',d.system||'',{placeholder:'macOS / Windows / Linux'})}${field('group','分组',d.group||'',{placeholder:'日常设备 / 算力设备'})}${field('environment','使用环境',d.environment||'',{placeholder:'个人 / 研发 / 测试 / 生产'})}${field('address','IP / 地址',d.address||'',{disabled:fixed,placeholder:'填写已确认的完整地址'})}${field('hostname','主机名',d.hostname||'',{disabled:fixed,placeholder:'设备主机名（可选）'})}${field('domain','域名',d.domain||'',{full:true,disabled:fixed,placeholder:'已确认的域名（可选）'})}${field('alias','连接资料 / 别名（可选）',d.alias||'',{full:true,disabled:fixed,hint:fixed?'已绑定的采集目标与连接资料保持固定。':'仅用于登记资料，不会根据输入自动建立连接。'})}${field('note','用途与备注',d.note||'',{rows:3,full:true,placeholder:'例如：Cube 烧录主机 / 地址待核对'})}</div><div class="spacer"></div>${id&&fixed?`<label class="inline-checkbox"><input type="checkbox" name="enabled" ${d.enabled!==false?'checked':''}>启用本设备的状态采集</label>`:''}${infoGrid([['采集方式',id?sourceKindLabel(d.source_kind):'仅登记'],['管理边界','不修改目标设备的服务或配置']])}`,{label:id?'保存设备':'登记设备',submit:fd=>{
    const payload={name:fd.get('name'),system:fd.get('system'),group:fd.get('group'),environment:fd.get('environment'),note:fd.get('note')};
    if(!fixed){for(const key of ['alias','address','hostname','domain'])payload[key]=fd.get(key);payload.enabled=false;}else payload.enabled=fd.has('enabled');
    if(!id)payload.source_kind='manual';
    return mutate(id?`/api/devices/${encodeURIComponent(id)}/meta`:'/api/devices',payload);
  }});
}
function showDevice(id) {
  const d=deviceItems().find(x=>x.id===id);if(!d)return;
  const registered=deviceRegisteredOnly(d),m=registered?{}:d.metrics||{},owned=agentItems().filter(a=>a.device_id===id);
  const details=[['系统',d.system],['分组',d.group],['使用环境',d.environment],['地址',d.address||'待核对'],...deviceAddressRows(d).filter(([label])=>label!=='地址'),['来源别名',d.alias||'无'],...(!registered?[['最近采集',timestamp(d.observed_at)],['最近成功',timestamp(d.last_success_at)]]:[])];
  openModal(d.name,`<div class="tags detail-tags">${deviceBadge(d)}${tag(sourceKindLabel(d.source_kind))}${d.archived?tag('已归档'):''}</div><div class="inline-actions">${btn('编辑资料','device-edit',id,'secondary small','edit')}${btn(registered?'刷新资料':'刷新状态','device-refresh',id,'subtle small','refresh')}${!registered?btn(d.enabled===false?'启用采集':'暂停采集','device-toggle',id,'secondary small'):''}${btn(d.archived?'恢复设备':'归档设备','device-archive',id,'ghost small')}</div>${registered?notice('资料登记，运行状态尚未核验。'):d.source_kind==='ssh'?notice('固定 SSH 来源，仅只读采集系统与资源指标。'):''}${infoGrid(details)}${d.note?detailSection('用途与备注',`<p>${e(d.note)}</p>`):''}${!registered&&d.error?notice(d.error,'amber'):''}<div class="resource-grid">${resource('CPU',m.cpu_percent)}${resource('内存',m.memory_percent)}${resource('磁盘',m.disk_percent)}</div>${detailSection('归属本设备的 AI 实例',owned.length?owned.map(a=>`<div class="detail-line"><span>${e(a.name||a.platform)}${a.hidden?' · 已隐藏':''}</span>${btn('查看实例','agent-detail',a.id,'ghost small')}</div>`).join(''):'<p>暂无已接入的 AI 实例。</p>')}${notice('无采样证据的指标显示“—”。管理设置仅作用于本工作台，不操作目标设备。')}`,{eyebrow:'设备详情'});
}
function showAgent(id) {
  const a=agentItems().find(x=>x.id===id);if(!a)return;
  const device=deviceItems().find(d=>d.id===a.device_id);
  const activities=list(a.activities);
  openModal(a.name||a.platform,`<div class="tags detail-tags">${badge(a.source_state)}${a.hidden?tag('已隐藏'):''}${tag(`进程：${processLabel(a.process_state||'unknown')}`)}</div><div class="inline-actions">${btn('编辑与绑定角色','agent-bind',id,'secondary small','edit')}${btn('关联 Skill','agent-skills',id,'secondary small','link')}${btn(a.enabled===false?'启用状态读取':'暂停状态读取','agent-toggle',id,'subtle small')}${btn(a.hidden?'恢复显示':'隐藏实例','agent-hide',id,'ghost small')}</div>${infoGrid([['工具平台',a.platform],['设备归属',device?.name||'未提供'],['采集时间',timestamp(a.observed_at)],['来源时间',timestamp(a.source_updated_at)]])}${detailSection('活动状态',`<p>${e(a.activity_label||'当前活动未知')}</p>`)}${a.error?notice(a.error,'amber'):''}${detailSection('来源返回的活动',activities.length?activities.map(item=>`<div class="detail-line"><span>${e(item.title||'未命名活动')}<br><small class="muted">${e(({running:'处理中（按记录推断）',completed_unread:'完成未读',unknown:'状态未知'})[item.state]||item.state||'未知')} · 活动时间 ${e(timestamp(item.last_activity_at))}</small></span></div>`).join(''):'<p>暂无可用活动记录。</p>')}${notice(a.activities_truncated?'来源列表存在截断，仅展示部分会话；上方汇总可能包含未显示的活动。':'活动列表反映来源返回的证据，不能代替工具业务健康检查。')}${detailSection('关联 Skills',linkedSkills('agent',id))}${detailSection('关联此实例的任务',relationRows(relations().filter(r=>r.from_type==='task'&&r.to_type==='agent'&&r.to_id===id),'agent',id,true))}`,{wide:true,eyebrow:'AI 实例'});
}
function showAgentBind(id) {
  const a=agentItems().find(x=>x.id===id);if(!a)return;
  const device=deviceItems().find(d=>d.id===a.device_id),roles=roleItems().filter(r=>!r.archived);
  openModal('AI 实例与角色',`${field('name','实例显示名称',a.name||a.platform,{required:true})}${infoGrid([['平台',a.platform],['实际设备归属',device?.name||'未提供']])}<p class="field-hint">设备归属来自真实采集来源，不能随意改绑。可以为一个实例关联多个角色。</p><div class="checkbox-list">${roles.map(r=>`<label class="check-row"><input type="checkbox" name="roles" value="${e(r.id)}" ${list(a.role_ids).includes(r.id)?'checked':''}><span>${e(r.name)}<small>${e(r.description||'暂无说明')}</small></span></label>`).join('')||empty('尚无可绑定的角色','先在 AI 管理页面新建角色。','agents')}</div>`,{submit:fd=>mutate(`/api/agents/${encodeURIComponent(id)}/meta`,{name:fd.get('name'),role_ids:fd.getAll('roles')})});
}
function showRoleForm(id=null) {
  const role=roleItems().find(r=>r.id===id)||{};
  openModal(id?'编辑 AI 角色':'新建 AI 角色',`${field('name','角色名称',role.name||'',{required:true,placeholder:'例如 策略规划师'})}${field('description','职责与说明',role.description||'',{rows:4,placeholder:'这个角色负责什么？'})}${field('tags','标签',list(role.tags).join('、'),{hint:'用逗号、顿号或换行分隔。'})}`,{submit:fd=>mutate(id?`/api/roles/${encodeURIComponent(id)}/meta`:'/api/roles',{name:fd.get('name'),description:fd.get('description'),tags:String(fd.get('tags')||'').split(/[,，、\n]/).map(x=>x.trim()).filter(Boolean)})});
}
function about() {
  openModal('个人工作台',`<p class="confirm-text">每天的入口，也是你的任务、发现、Skills、设备与 AI 团队的共同空间。</p>${infoGrid([['当前版本',S?.health?.version||'本地版'],['访问范围',S?.health?.local_only===false?'已配置访问':'仅本机'],['今日日期',S?.daily?.date||dateString()],['数据同步',timestamp(S?.health?.server_time)]])}<a class="button secondary" href="/api/backup">${svg('download')}下载工作台备份</a><p class="source-stamp">备份包含工作台自己的记录与草稿。原有任务与来源 Skill 保持独立。</p>`);
}

async function handleAction(button) {
  const action=button.dataset.action,id=button.dataset.id,value=button.dataset.value;
  if(action==='menu'){q('#sidebar').classList.toggle('open');return;}
  if(action==='close-modal'){closeModal();return;}
  if(action==='filter'){
    const page=button.dataset.page,key=button.dataset.key;
    views[page][key]=value;
    if(page==='discover'){
      views.discover.visibleCount=10;
      if(key==='kind'){views.discover.filter=value==='project'?'trending':'all';views.discover.query='';}
    }
    render();return;
  }
  if(action==='discover-more'){views.discover.visibleCount+=10;render();return;}
  if(action==='retry'){await load();return;}
  if(action==='about'){about();return;}
  if(action==='go-discover'){navigate('discover');return;}
  if(action==='focus-picker'){showFocusPicker();return;}
  if(action.startsWith('focus-')){await changeFocus(id,action.slice(6));return;}
  if(action==='task-detail'){openTaskBoard(id);return;}
  if(action==='task-board-refresh'){await checkTaskBoard({force:true});return;}
  if(action==='task-skills'){showRelationPicker('task',id);return;}
  if(action==='task-agents'){showRelationPicker('task',id,'agent');return;}
  if(action==='task-draft'){await showDraft(null,id);return;}
  if(action==='mood'){await mutate('/api/daily',{mood:S.daily?.mood===value?null:value},{close:false,message:'心情已记录'});return;}
  if(action==='energy'){await mutate('/api/daily',{energy:Number(value)},{close:false,message:'精力已记录'});return;}
  if(action==='mood-clear'){await mutate('/api/daily',{mood:null,energy:null},{close:false,message:'今日状态已清空'});return;}
  if(action==='refresh-all'){await mutate('/api/refresh',{},{close:false,message:'工作空间已刷新'});return;}
  if(action==='discover-refresh'){await mutate('/api/discover/refresh',{},{close:false,message:'资讯已核对，请以页面来源状态为准'});return;}
  if(action==='trending-refresh'){await mutate('/api/discover/trending/refresh',{},{close:false,message:'开源日榜已核对，请以页面来源状态为准'});return;}
  if(action==='leaderboards-refresh'){await mutate('/api/discover/leaderboards/refresh',{category:views.discover.modelCategory},{close:false,message:'模型榜已核对，请以页面来源状态为准'});return;}
  if(action==='discover-detail'){showDiscover(id);return;}
  if(action==='discover-tasks'){showRelationPicker('discover',id,'task');return;}
  if(action==='discover-skills'){showRelationPicker('discover',id,'skill');return;}
  if(action==='discover-star'){const item=discoverItems().find(x=>x.id===id);await mutate(`/api/discover/${encodeURIComponent(id)}/meta`,{bookmarked:!item.bookmarked},{close:false,message:item.bookmarked?'已取消收藏':'已收藏在发现'});if(modal.open)showDiscover(id);return;}
  if(action==='interests'){showInterests();return;}
  if(action==='project-add'){showProjectAdd();return;}
  if(action==='project-trial'){showTrial(id);return;}
  if(action==='skills-scan'){await mutate('/api/skills/scan',{},{close:false,message:'Skills 来源已重新扫描'});return;}
  if(action==='skill-detail'){await showSkill(id);return;}
  if(action==='skill-copy-address'){await copySkillAddress(id);return;}
  if(action==='skill-star'){const s=skillItems().find(x=>x.id===id);await mutate(`/api/skills/${encodeURIComponent(id)}/meta`,{starred:!s.starred},{close:false,message:s.starred?'已移出常用 Skills':'已加入常用 Skills'});if(modal.open)await showSkill(id);return;}
  if(action==='skill-meta'){await showSkillMeta(id);return;}
  if(action==='skill-create'){await showDraft();return;}
  if(action==='skill-edit'){await showDraft(id);return;}
  if(action==='draft-mode'){
    if(!draftContext)return;
    const changed=[...q('#modal-form').querySelectorAll('input,textarea,select')].some(input=>input.tagName==='SELECT'?Array.from(input.options).some(option=>option.selected!==option.defaultSelected):input.value!==input.defaultValue);
    if(changed)throw new Error('请先保存当前修改，再切换编辑方式');
    draftContext.mode=value;renderDraft();return;
  }
  if(action==='skill-check'){const generation=modalGeneration;await mutate(`/api/skills/${encodeURIComponent(id)}/check`,{},{close:false,message:'检查已完成'});if(modal.open&&generation===modalGeneration)await showSkill(id);return;}
  if(action==='skill-register'){confirmAction('登记这份 Skill','登记会将这份草稿加入工作台的可用能力。完整性检查不通过时不会登记；不修改外部工具的 Skill 来源。',async()=>{await mutate(`/api/skills/${encodeURIComponent(id)}/register`,{});await showSkill(id);},'检查并登记');return;}
  if(action==='skill-validate'){showSkillValidate(id);return;}
  if(action==='skill-prompt'){showPromptForm(id);return;}
  if(action==='copy-prompt'){await copyText(promptText);return;}
  if(action==='skill-archive'){const s=skillItems().find(x=>x.id===id);confirmAction(s.archived?'恢复 Skill':'归档 Skill',s.archived?'恢复后会在 Skills 库中重新显示。':'归档只隐藏工作台条目，不删除源包或关联记录。',()=>mutate(`/api/skills/${encodeURIComponent(id)}/meta`,{archived:!s.archived}),s.archived?'恢复':'归档');return;}
  if(action==='relation-delete'){const relation=relations().find(r=>r.id===id),returnType=button.dataset.returnType||relation?.from_type,returnId=button.dataset.returnId||relation?.from_id;confirmAction('取消关联','仅移除工作台关系，关联对象与来源文件都会保留。',async()=>{await mutate(`/api/relations/${encodeURIComponent(id)}`,undefined,{method:'DELETE'});if(returnType&&returnId)await reopenDetail(returnType,returnId);},'取消关联');return;}
  if(action==='device-create'){showDeviceForm();return;}
  if(action==='device-edit'){showDeviceForm(id);return;}
  if(action==='device-detail'){showDevice(id);return;}
  if(action==='device-refresh'){const d=deviceItems().find(x=>x.id===id);await mutate(`/api/devices/${encodeURIComponent(id)}/refresh`,{},{close:false,message:d&&deviceRegisteredOnly(d)?'设备资料已刷新，运行状态尚未核验':'设备采集已完成，请以状态说明为准'});if(modal.open)showDevice(id);return;}
  if(action==='device-toggle'){const d=deviceItems().find(x=>x.id===id);await mutate(`/api/devices/${encodeURIComponent(id)}/meta`,{enabled:d.enabled===false},{message:d.enabled===false?'已启用采集':'已暂停采集'});return;}
  if(action==='device-archive'){const d=deviceItems().find(x=>x.id===id);confirmAction(d.archived?'恢复设备':'归档设备',d.archived?'恢复登记设备，之后可按需要启用采集。':'归档隐藏工作台中的设备，不会操作目标设备。',()=>mutate(`/api/devices/${encodeURIComponent(id)}/meta`,{archived:!d.archived}),d.archived?'恢复':'归档');return;}
  if(action==='agents-refresh'){await mutate('/api/refresh',{kind:'agents'},{close:false,message:'AI 状态已刷新'});return;}
  if(action==='agent-detail'){showAgent(id);return;}
  if(action==='agent-bind'){showAgentBind(id);return;}
  if(action==='agent-skills'){showRelationPicker('agent',id);return;}
  if(action==='agent-hide'){const a=agentItems().find(x=>x.id===id);await mutate(`/api/agents/${encodeURIComponent(id)}/meta`,{hidden:!a.hidden},{message:a.hidden?'已恢复显示':'AI 实例已隐藏'});return;}
  if(action==='agent-toggle'){const a=agentItems().find(x=>x.id===id);await mutate(`/api/agents/${encodeURIComponent(id)}/meta`,{enabled:a.enabled===false},{message:a.enabled===false?'已启用状态读取':'已暂停状态读取'});return;}
  if(action==='role-create'){showRoleForm();return;}
  if(action==='role-edit'){showRoleForm(id);return;}
  if(action==='role-skills'){showRelationPicker('role',id);return;}
  if(action==='role-restore'){await mutate(`/api/roles/${encodeURIComponent(id)}/meta`,{archived:false},{message:'角色已恢复'});return;}
  if(action==='role-archive'){confirmAction('归档 AI 角色','归档后不再出现在可选角色中。原角色和关联资料保留，可以恢复。',()=>mutate(`/api/roles/${encodeURIComponent(id)}/meta`,{archived:true}),'归档角色');return;}
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-action]');if(!button||button.disabled)return;
  event.preventDefault();
  const passive=['close-modal','menu','filter','discover-more'].includes(button.dataset.action);
  if(!passive&&(actionBusy||modalBusy)){toast('上一操作正在完成，请稍候。');return;}
  const originalDisabled=button.disabled;
  if(!passive)actionBusy=true;
  q('#modal-form').setAttribute('aria-busy',String(actionBusy||modalBusy));
  try {button.disabled=true;await handleAction(button);}
  catch(err){toast(err?.message||'操作没有完成，请重试。',true);}
  finally {if(!passive)actionBusy=false;q('#modal-form').setAttribute('aria-busy',String(actionBusy||modalBusy));if(button.isConnected)button.disabled=originalDisabled;}
});
document.addEventListener('input',event=>{
  const input=event.target.closest('[data-search]');if(!input)return;
  const page=input.dataset.search;views[page].query=input.value;
  if(page==='discover')views.discover.visibleCount=10;
  clearTimeout(searchTimer);searchTimer=setTimeout(()=>{const start=input.selectionStart,end=input.selectionEnd;render();const replacement=q(`[data-search="${page}"]`);if(replacement){replacement.focus();try{replacement.setSelectionRange(start,end);}catch{}}},120);
});
document.addEventListener('change',event=>{
  const select=event.target.closest('[data-select]');if(select){views[select.dataset.select][select.dataset.key]=select.value;render();}
  if(event.target.matches('input[name="focus"]')&&q('#modal-form').querySelectorAll('input[name="focus"]:checked').length>3){event.target.checked=false;toast('今天最多选择 3 个重点。',true);}
});
q('#modal-form').addEventListener('submit',async event=>{
  event.preventDefault();if(!modalSubmit)return;if(modalBusy||actionBusy){toast('上一操作正在完成，请稍候。');return;}
  modalBusy=true;const submit=q('#modal-submit');submit.disabled=true;
  q('#modal-form').setAttribute('aria-busy','true');
  q('#modal-body .form-error')?.remove();
  try {await modalSubmit(new FormData(event.target));}
  catch(err){const error=document.createElement('div');error.className='form-error';error.setAttribute('role','alert');error.textContent=err.message||'保存未完成，请重试。';q('#modal-body').prepend(error);error.scrollIntoView({block:'nearest'});}
  finally {modalBusy=false;q('#modal-submit').disabled=false;q('#modal-form').setAttribute('aria-busy',String(actionBusy));}
});
modal.addEventListener('close',()=>{document.body.classList.remove('dialog-open');if(taskBoard.pending&&!taskBoard.busy)applyTaskBoardMetadata();});
modal.addEventListener('click',event=>{if(event.target===modal){const rect=modal.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)closeModal();}});
q('#mobile-backdrop').addEventListener('click',()=>q('#sidebar').classList.remove('open'));
window.addEventListener('hashchange',()=>{q('#sidebar').classList.remove('open');render();window.scrollTo({top:0,behavior:'instant'});});
setInterval(()=>{if(S?.daily?.date&&S.daily.date!==dateString())load({quiet:true});else if(activePage==='home'&&!modal.open&&!document.activeElement?.matches('input,textarea,select'))render();},60000);
setInterval(()=>load({quiet:true}),30000);
renderNavigation();load().catch(()=>{});
