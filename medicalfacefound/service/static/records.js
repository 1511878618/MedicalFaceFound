(()=>{
const $=id=>document.getElementById(id),{api,esc,date,number}=MFF;
let user=null,catalog=[],consentVersion='',offset=0,items=[],active=null,revision=0,loadRevision=0,trendItems=[],subjects=[],subjectId='self';
let retryingId=null;
function notice(text,error=false){$('notice').textContent=text;$('notice').className=`history-notice${error?' error':''}`;}
function clearDetail(){revision++;active=null;$('detailPanel').hidden=true;$('recordTable').replaceChildren();$('researchControls').replaceChildren();$('recordMeta').textContent='';}
function clearHistory(){items=[];trendItems=[];offset=0;clearDetail();$('historyRows').replaceChildren();$('trend').replaceChildren();$('trendChart').replaceChildren();$('total').textContent='';$('userLabel').textContent='';for(const id of ['statTotal','statLatest','statCompleted'])$(id).textContent='—';$('latestProfile').replaceChildren();$('recentRecords').replaceChildren();$('profileDate').textContent='';}
function signedOut(){loadRevision++;closeMember();user=null;document.querySelectorAll('a[href^="/ui-assets/capture.html"]').forEach(a=>a.href='/ui-assets/capture.html');subjectId='self';subjects=[];$('subjectSelect').replaceChildren();clearHistory();$('historyRows').replaceChildren();$('trend').replaceChildren();$('historyPanel').hidden=true;$('loginPanel').hidden=false;showSession();}
function showSession(){ $('loginPanel').hidden=!!user;$('historyPanel').hidden=!user;$('topUsername').textContent=user?.username||'访客';$('avatar').textContent=(user?.username||'访').slice(0,1).toUpperCase();$('welcomeTitle').textContent=user?`${user.username}，欢迎回来`:'我的测量记录';if(user)$('userLabel').textContent=user.username; }
function renderOverview(total){
 const latest=subjectId==='unknown'?null:trendItems[0];$('statTotal').textContent=String(total);$('statLatest').textContent=latest?date(latest.created_at).split(' ')[0]:'暂无';$('statCompleted').textContent=latest?String(latest.predictions.filter(p=>p.status==='completed').length):'—';$('profileDate').textContent=latest?date(latest.created_at):'';
 if(!latest){$('latestProfile').innerHTML='<p class="empty-state">暂无测量资料。</p>';$('recentRecords').innerHTML='<p class="empty-state">还没有测量记录。</p>';return;}
 const h=Number(latest.height_cm),w=Number(latest.weight_kg),bmi=h>0&&w>0?(w/(h/100)**2).toFixed(1):'—';
 const fields=[['年龄',latest.age!=null?`${latest.age} 岁`:'—'],['性别',({male:'男',female:'女',other:'其他',unspecified:'未提供'})[latest.gender]||'—'],['身高',latest.height_cm!=null?`${latest.height_cm} cm`:'—'],['体重',latest.weight_kg!=null?`${latest.weight_kg} kg`:'—'],['BMI',bmi]];
 $('latestProfile').innerHTML=fields.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
 $('recentRecords').innerHTML=trendItems.slice(0,3).map(r=>`<button class="recent-record" data-record="${esc(r.id)}"><span><strong>${esc(date(r.created_at))}</strong><small>完成 ${r.predictions.filter(p=>p.status==='completed').length} 项指标</small></span><span aria-hidden="true">↗</span></button>`).join('');
}

async function load(){
 const ticket=++loadRevision;
 const {user:current}=await api('/v1/account/me');if(ticket!==loadRevision)return;if(!current){signedOut();return;}
 if(user?.id!==current.id){closeMember();subjectId='self';subjects=[];clearHistory();}
 user=current;showSession();
 const subjectData=await api('/v1/me/subjects');if(ticket!==loadRevision)return;subjects=subjectData.items;if(!subjects.some(s=>s.id===subjectId))subjectId='self';renderSubjects();
 const data=await api(`/v1/me/captures?subject_id=${encodeURIComponent(subjectId)}&offset=${offset}&limit=20`);
 if(ticket!==loadRevision)return;
 if(offset&&offset>=data.total){offset=Math.max(0,Math.floor((data.total-1)/20)*20);return load();}
 items=data.items;$('total').textContent=`共 ${data.total} 次测量 · 第 ${Math.floor(offset/20)+1} 页`;
 $('previous').disabled=offset===0;$('next').disabled=offset+20>=data.total;
 $('historyRows').innerHTML=items.length?items.map(r=>`<tr><td>${esc(date(r.created_at))}</td><td>${esc(r.id.slice(0,8))}…</td><td>完成 ${r.predictions.filter(p=>p.status==='completed').length} 项${r.predictions.some(p=>p.status==='running')?' · 分析中 '+r.predictions.filter(p=>p.status==='running').length+' 项':''}${r.predictions.some(p=>p.status==='failed')?' · 失败 '+r.predictions.filter(p=>p.status==='failed').length+' 项':''}${r.deletion_requested_at?' · 已申请删除':''}</td><td>${r.research_consent?'已同意':'未参与'}</td><td><button class="text-button" data-record="${esc(r.id)}">查看 / 补充实测</button><button class="text-button record-delete" data-delete="${esc(r.id)}">删除</button></td></tr>`).join(''):'<tr><td colspan="5">暂无记录，完成测量后会显示在这里。</td></tr>';
 trendItems=[];$('trend').textContent='正在加载历史记录…';
 for(let start=0;start<data.total;start+=100){const page=await api(`/v1/me/captures?subject_id=${encodeURIComponent(subjectId)}&offset=${start}&limit=100`);if(ticket!==loadRevision)return;trendItems.push(...page.items);if(!page.items.length)break;}
 renderTrend();renderOverview(data.total);
 if(active){const id=active.id;try{const result=await api(`/v1/captures/${id}/report`);if(ticket===loadRevision&&active?.id===id)renderDetail(result,Boolean(retryingId));}catch(e){if(ticket!==loadRevision)return;if(e.status===404)clearDetail();else throw e;}}
}
function renderTrend(){
 const id=$('trendModel').value;if(subjectId==='unknown'){$('trendChart').innerHTML='<p class="empty-state">请先确认每条记录的归属，再查看对应对象的趋势。</p>';$('trend').replaceChildren();return;}MFFTrend.render($('trendChart'),trendItems,id,Number($('trendPeriod').value));
 const rows=trendItems.slice().reverse().map(r=>{const p=r.predictions.filter(p=>p.model===id&&p.status==='completed').at(-1),o=MFF.observations(r).find(o=>o.model===id);if(!p&&!o)return '';return `<tr><td>${esc(date(r.created_at))}</td><td>${p?`${esc(number(p.result.value))} ${esc(MFF.unit(p.result.unit,id))}`:'—'}</td><td>${o?`${esc(number(o.value))} ${esc(MFF.unit(o.unit,id))}（${esc(o.measured_on)}）<small>${esc(MFF.observationTiming(r,o))}</small>`:'—'}</td><td>${p?esc(p.model_version):'—'}</td></tr>`;}).join('');
 $('trend').innerHTML=`<div class="table-scroll"><table class="history-table"><thead><tr><th>采集时间</th><th>模型预测</th><th>实测值</th><th>模型版本</th></tr></thead><tbody>${rows||'<tr><td colspan="4">没有该指标的测量结果。</td></tr>'}</tbody></table></div>`;
}
function renderDetail(r,preserveDrafts=false){const drafts=active?.id===r.id?MFF.snapshotRecordDrafts(r.id):[];active=r;$('recordSubject').replaceChildren(...subjects.map(s=>new Option(s.label,s.id)));$('recordSubject').value=r.subject_id||'unknown';$('detailPanel').hidden=false;$('recordMeta').textContent=`${r.id} · ${date(r.created_at)}`;const changed=async result=>{if(!user||active?.id!==r.id)return;renderDetail(result);await load();notice('记录已更新。');};$('recordTable').innerHTML=MFF.table(r,catalog,{editable:true});MFF.bindInline($('recordTable'),r,catalog,consentVersion,{},changed);MFF.researchPanel($('researchControls'),r,catalog,consentVersion,{},changed);MFF.restoreRecordDrafts(r.id,drafts);renderRecovery(r);}
function failedModels(r){return [...new Set((r.predictions||[]).filter(p=>p.status==='failed'&&catalog.some(m=>m.id===p.model&&m.available)).map(p=>p.model))];}
function renderRecovery(r){
 let panel=$('measurementRecovery');if(!panel){panel=document.createElement('div');panel.id='measurementRecovery';panel.className='measurement-recovery';$('recordTable').before(panel);}
 const completed=r.predictions.filter(p=>p.status==='completed').length,running=r.predictions.filter(p=>p.status==='running').length,failed=r.predictions.filter(p=>p.status==='failed').length;
 panel.replaceChildren();const status=document.createElement('p');status.setAttribute('role','status');status.textContent=`资料已保存 · 已完成 ${completed} 项${running?' · 分析中 '+running+' 项':''}${failed?' · 失败 '+failed+' 项':''}`;panel.append(status);
 const refresh=document.createElement('button');refresh.className='button secondary';refresh.textContent='刷新状态';refresh.disabled=retryingId===r.id;refresh.onclick=async()=>{refresh.disabled=true;try{const result=await api(`/v1/captures/${r.id}/report`);if(active?.id===r.id)renderDetail(result,true);}catch(e){notice(e.message,true);}finally{refresh.disabled=false;}};panel.append(refresh);
 if(failedModels(r).length&&!r.deletion_requested_at){const retry=document.createElement('button');retry.className='button secondary';retry.textContent=retryingId===r.id?'重试中…':'仅重试失败项';retry.disabled=retryingId!==null;retry.onclick=()=>retryFailed(r.id);panel.append(retry);}
}
async function retryFailed(id){
 if(retryingId||!user||active?.id!==id)return;
 const owner=user.id;retryingId=id;renderRecovery(active);
 let failedRequests=0;
 try{
  let current=await api(`/v1/captures/${id}/report`);
  for(const model of failedModels(current)){
   if(user?.id!==owner||active?.id!==id)break;
   // Recheck before every request: another tab may have completed the model.
   current=await api(`/v1/captures/${id}/report`);
   if(current.deletion_requested_at)break;
   if(!current.predictions.some(p=>p.model===model&&p.status==='failed'))continue;
   try{await api(`/v1/captures/${id}/predictions/${encodeURIComponent(model)}`,{method:'POST'});}catch(e){if(e.status!==409)failedRequests++;}
   if(user?.id===owner&&active?.id===id){current=await api(`/v1/captures/${id}/report`);renderDetail(current,true);}
  }
  if(user?.id===owner&&active?.id===id){await load();notice(failedRequests?'部分分析未完成，请查看状态后重试。':'状态已更新，已完成项未重复运行。',failedRequests>0);MFF.channel?.postMessage({type:'updated',id});}
 }catch(e){if(user?.id===owner){if(e.status===404)clearDetail();notice(e.message,true);}}
 finally{retryingId=null;if(active?.id===id)renderRecovery(active);}
}
async function detail(id){if(active?.id===id){$('detailPanel').scrollIntoView({block:'start',behavior:'smooth'});return;}if(!MFF.confirmDiscardChanges())return;clearDetail();const ticket=revision;try{const r=await api(`/v1/captures/${id}/report`);if(ticket!==revision)return;renderDetail(r);$('detailPanel').scrollIntoView({block:'start',behavior:'smooth'});}catch(e){if(ticket!==revision)return;if(e.status===404){clearDetail();await load();}notice(e.message,true);}}
$('loginForm').onsubmit=async e=>{e.preventDefault();const form=e.currentTarget;const action=e.submitter?.value||'login';form.querySelectorAll('button').forEach(b=>b.disabled=true);try{MFF.requireCompatible(await api('/ready'));const data=await api(`/v1/account/${action}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('username').value,password:$('password').value})});subjectId='self';subjects=[];clearHistory();user=data.user;$('password').value='';await load();notice('已登录。');MFF.channel?.postMessage({type:'session'});}catch(error){notice(error.message,true);}finally{form.querySelectorAll('button').forEach(b=>b.disabled=false);}};
$('logout').onclick=async()=>{if(!MFF.confirmDiscardChanges())return;try{await api('/v1/account/logout',{method:'POST'});signedOut();notice('已退出，个人记录已从页面清空。');MFF.channel?.postMessage({type:'session'});}catch(e){notice(e.message,true);}};
$('reload').onclick=()=>load().catch(e=>notice(e.message,true));
$('recentRecords').onclick=e=>{const b=e.target.closest('[data-record]');if(b)detail(b.dataset.record);};
$('historyRows').onclick=e=>{const del=e.target.closest('[data-delete]');if(del){deleteRecord(del.dataset.delete,del);return;}const b=e.target.closest('[data-record]');if(b)detail(b.dataset.record);};
$('previous').onclick=()=>{if(!MFF.confirmDiscardChanges())return;offset=Math.max(0,offset-20);load().catch(e=>notice(e.message,true));};
$('next').onclick=()=>{if(!MFF.confirmDiscardChanges())return;offset+=20;load().catch(e=>notice(e.message,true));};
$('trendModel').onchange=renderTrend;$('trendPeriod').onchange=renderTrend;
$('download').onclick=()=>{if(active)MFF.download(active,catalog);};
async function deleteRecord(id,button){const record=items.find(r=>r.id===id)||active;const label=subjects.find(s=>s.id===(record?.subject_id||subjectId))?.label||'当前对象';if(!confirm(`删除 ${label} 在 ${date(record?.created_at)} 的测量及关联结果？历史备份将另行处理。`))return;button.disabled=true;try{await api(`/v1/captures/${id}`,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation:id})});if(active?.id===id)clearDetail();await load();MFF.channel?.postMessage({type:'deleted',id});notice('记录已删除。');}catch(e){if(e.status===404){if(active?.id===id)clearDetail();await load();}notice(e.message,true);}finally{button.disabled=false;}}
$('delete').onclick=()=>{if(active)deleteRecord(active.id,$('delete'));};
function renderSubjects(){ $('subjectSelect').replaceChildren(...subjects.map(s=>new Option(`${s.label}${Number.isInteger(s.record_count)?'（'+s.record_count+'）':''}`,s.id)));$('subjectSelect').value=subjectId;const unknownCount=subjects.find(s=>s.id==='unknown')?.record_count||0;$('subjectNote').textContent=subjectId==='unknown'?'旧记录归属待确认，请逐条指定对象。':unknownCount?`${unknownCount} 条旧记录待确认，切换“待确认”后指定对象。`:'概览、记录和趋势仅包含当前对象。';document.querySelectorAll('a[href^="/ui-assets/capture.html"]').forEach(a=>a.href='/ui-assets/capture.html?subject='+encodeURIComponent(subjectId==='unknown'?'self':subjectId));}
$('subjectSelect').onchange=()=>{if(!MFF.confirmDiscardChanges()){$('subjectSelect').value=subjectId;return;}subjectId=$('subjectSelect').value;clearHistory();load().catch(e=>notice(e.message,true));};
function closeMember(){ $('memberForm').hidden=true;$('addSubject').setAttribute('aria-expanded','false');$('memberLabel').value='';$('memberStatus').textContent='';}
$('addSubject').onclick=()=>{$('memberForm').hidden=false;$('addSubject').setAttribute('aria-expanded','true');$('memberLabel').focus();};
$('cancelMember').onclick=closeMember;
$('memberForm').onsubmit=async e=>{e.preventDefault();const label=$('memberLabel').value.trim();if(!label||!user)return;if(!MFF.confirmDiscardChanges())return;const accountId=user.id,ticket=loadRevision,button=e.currentTarget.querySelector('[type=submit]');button.disabled=true;$('memberStatus').textContent='创建中…';try{const member=await api('/v1/me/subjects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label})});if(user?.id!==accountId||loadRevision!==ticket)return;closeMember();subjectId=member.id;clearHistory();await load();notice('成员已添加。');}catch(e){if(user?.id===accountId&&loadRevision===ticket)$('memberStatus').textContent=e.message;}finally{button.disabled=false;}};

$('subjectForm').onsubmit=async e=>{e.preventDefault();if(!active)return;const id=active.id,target=$('recordSubject').value;if(target===(active.subject_id||'unknown'))return;if(!confirm('更改归属将清除本条记录的科研授权，测量记录保留。继续？'))return;if(!MFF.confirmDiscardChanges())return;try{await api(`/v1/captures/${id}/subject`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({subject_id:target})});if(active?.id===id)clearDetail();await load();MFF.channel?.postMessage({type:'updated',id});notice('归属已更新，请在对应对象下查看。');}catch(e){notice(e.message,true);}};

MFF.channel?.addEventListener('message',event=>{if(event.data?.type==='deleted'){if(active?.id===event.data.id)clearDetail();load().catch(e=>notice(e.message,true));}if(event.data?.type==='updated'){load().catch(e=>notice(e.message,true));}if(event.data?.type==='session'){signedOut();load().catch(e=>notice(e.message,true));}});
document.querySelectorAll('[data-section]').forEach(link=>link.addEventListener('click',()=>{document.querySelectorAll('.portal-sidebar [data-section]').forEach(a=>a.removeAttribute('aria-current'));document.querySelector(`.portal-sidebar [data-section="${link.dataset.section}"]`)?.setAttribute('aria-current','page');$('sectionLabel').textContent=({overview:'概览',measurements:'测量记录',trends:'趋势比较',account:'我的账户'})[link.dataset.section];if(!user)$('loginPanel').scrollIntoView({behavior:'smooth'});}));
window.addEventListener('focus',()=>{if(user)load().catch(e=>notice(e.message,true));});
(async()=>{try{const state=MFF.requireCompatible(await api('/ready'));if(!state.subjects_enabled)throw new Error('请更新后端服务后使用对象档案。');catalog=state.models;consentVersion=state.research_consent_version;$('trendModel').replaceChildren(...catalog.map(m=>new Option(m.label,m.id)));$('trendModel').value='Age';await load();}catch(e){notice(e.message,true);}})();
})();
