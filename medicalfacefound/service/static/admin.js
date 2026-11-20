const $=id=>document.getElementById(id);
let modelCatalog=[],token='',offset=0,activeId=null,activeRecord=null,allTags=[],images=[],adminExplanationUrls=[],detailRevision=0;
let trendRevision=0,trendRecords=[];let listRevision=0,participantRevision=0,scopeRevision=0,participantOffset=0,selectedParticipant=null,selectedSubject='',scopeMode='all',currentConsentVersion='';
const UI_STATE_KEY='mff.admin.filters.v1';
let participantAppliedQuery='';let appliedFields={start:'',end:'',status:'all',tag:''},scopeValid=true,pendingUIState=null,listRows=[],listTotal=0,listReturn=null,detailOrder=[],detailNavigationRevision=0;
try{pendingUIState=JSON.parse(sessionStorage.getItem(UI_STATE_KEY)||'null');}catch{}
function readDraft(){return {start:$('startDate').value,end:$('endDate').value,status:$('statusFilter').value,tag:$('tagFilter').value};}
function paintDraft(){const changed=JSON.stringify(readDraft())!==JSON.stringify(appliedFields);$('filterDraftNotice').textContent=changed?' 筛选已修改，点击“查询”后生效。':'';}
function setDraft(fields){for(const [id,key] of [['startDate','start'],['endDate','end'],['statusFilter','status'],['tagFilter','tag']]){if(id==='tagFilter'&&fields[key]&&!Array.from($(id).options).some(o=>o.value===fields[key]))$(id).add(new Option(fields[key],fields[key]));$(id).value=fields[key]|| (key==='status'?'all':'');}paintDraft();}
function saveUIState(){if(!token)return;try{sessionStorage.setItem(UI_STATE_KEY,JSON.stringify({v:1,applied:appliedFields,draft:readDraft(),scopeMode,participant:selectedParticipant,subject:selectedSubject,offset,participantOffset,participantQuery:$('participantQuery').value,participantAppliedQuery,windowX:listReturn?.x??window.scrollX,windowY:listReturn?.y??window.scrollY,tableX:listReturn?.tableX??$('recordListScroll').scrollLeft}));}catch{}}
function safeFields(value){return {start:/^\d{4}-\d{2}-\d{2}$/.test(value?.start||'')?value.start:'',end:/^\d{4}-\d{2}-\d{2}$/.test(value?.end||'')?value.end:'',status:['all','failed','deletion'].includes(value?.status)?value.status:'all',tag:typeof value?.tag==='string'?value.tag.slice(0,100):''};}
function renderMembers(items){$('memberChoices').innerHTML='<button data-subject="" aria-pressed="'+String(!selectedSubject)+'">全部成员</button>'+items.map(m=>`<button data-subject="${esc(m.id)}" aria-pressed="${selectedSubject===m.id}">${esc(m.label)}（${m.record_count}）</button>`).join('');}
async function restoreUIState(){
 try{pendingUIState=JSON.parse(sessionStorage.getItem(UI_STATE_KEY)||'null');}catch{}const state=pendingUIState;if(!state||state.v!==1)return true;
 appliedFields=safeFields(state.applied);setDraft(safeFields(state.draft||state.applied));offset=Math.max(0,Math.floor(Number(state.offset)||0)/20|0)*20;participantOffset=Math.max(0,Math.floor(Number(state.participantOffset)||0)/20|0)*20;$('participantQuery').value=String(state.participantQuery||'').slice(0,100);participantAppliedQuery=String(state.participantAppliedQuery??state.participantQuery??'').slice(0,100);
 scopeMode=state.scopeMode;selectedParticipant=state.participant&&typeof state.participant.id==='string'?{id:state.participant.id,username:String(state.participant.username||'已选账号')}:null;selectedSubject=typeof state.subject==='string'?state.subject:'';
 try{
  if(!['all','account','guest','unknown'].includes(scopeMode))throw new Error('保存的记录范围无效');
  if(selectedParticipant){const data=await(await request(`/v1/admin/participants/${encodeURIComponent(selectedParticipant.id)}/subjects`)).json();if(selectedSubject&&!data.items.some(m=>m.id===selectedSubject))throw new Error('保存的成员已不存在');renderMembers(data.items);}
  else if(selectedSubject&&selectedSubject!=='unknown')throw new Error('成员缺少账号范围，请重新选择');
  scopeValid=true;paintScope();return true;
 }catch(e){scopeValid=false;paintScope();$('records').innerHTML='<tr><td colspan="7">保存的账号或成员范围不可用，请重新选择范围。</td></tr>';$('total').textContent='范围待确认';notice('保存的筛选范围无法恢复，请重新选择账号、成员或记录范围。',true);return false;}
}
function restoreListScroll(){const state=pendingUIState;pendingUIState=null;if(!state)return;$('recordListScroll').scrollLeft=Number(state.tableX)||0;window.scrollTo(Number(state.windowX)||0,Number(state.windowY)||0);}
function updateDetailNavigation(busy=false){const index=detailOrder.indexOf(activeId);$('detailPosition').textContent=index>=0?`第 ${index+1} 条，共 ${detailOrder.length} 条`:'当前记录不在已查询列表中';$('detailPrevious').disabled=busy||index<=0;$('detailNext').disabled=busy||index<0||index>=detailOrder.length-1;}
async function orderedIds(ticket){
 const params=query(),ids=[];let page=0,total=null;
 do{params.set('offset',page);params.set('limit',100);const data=await(await request(`/v1/admin/captures?${params}`)).json();if(ticket!==detailNavigationRevision||!token)return null;if(total!==null&&total!==data.total)throw new Error('列表已变化，请返回列表重新选择记录。');total=data.total;if(!data.items.length&&page<total)throw new Error('列表已变化，请重新查询。');ids.push(...data.items.map(r=>r.id));page+=data.items.length;}while(page<total);
 if(new Set(ids).size!==ids.length)throw new Error('列表已变化，请重新查询。');return ids;
}
async function openDetail(id,direction=0){
 const ticket=++detailNavigationRevision;detailRevision++;updateDetailNavigation(true);
 try{const ids=await orderedIds(ticket);if(!ids||ticket!==detailNavigationRevision)return;const index=ids.indexOf(id);if(index<0)throw new Error('记录已删除或不再符合筛选，请返回列表刷新。');const target=ids[index+direction];detailOrder=ids;if(!target){updateDetailNavigation();return;}await detail(target);if(ticket!==detailNavigationRevision)return;updateDetailNavigation();}
 catch(e){if(ticket===detailNavigationRevision){notice(e.message,true);updateDetailNavigation();}}
}
async function returnToList(){
 const context=listReturn;detailNavigationRevision++;clearDetail();if(!context)return;
 const ticket=detailNavigationRevision;offset=context.offset;
 try{await load();if(ticket!==detailNavigationRevision||!token)return;$('recordListScroll').scrollLeft=context.tableX;const button=$('records').querySelector(`[data-record="${CSS.escape(context.id)}"]`);(button||$('recordListScroll')).focus({preventScroll:true});window.scrollTo(context.x,context.y);}catch(e){notice(e.message,true);}
 listReturn=null;
}
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=value=>new Date(value).toLocaleString('zh-CN',{hour12:false});
const labels={Age:'年龄估计',HDLC:'高密度脂蛋白胆固醇',Hb:'血红蛋白'};
const camVariants=[
 ['block','has_explanation','Grad-CAM · 最后一个 block 输出'],
 ['norm1','has_norm1_explanation','Grad-CAM · 最后一个 block 的 norm1'],
 ['hirescam','has_hirescam_explanation','HiResCAM · 第四阶段 norm1'],
 ['layercam','has_layercam_explanation','LayerCAM · 第三阶段 norm1'],
];
const PRESET_TAGS=['已复核','需复查','数据异常','排除','随访'];
function notice(text,error=false){$('adminMessage').textContent=text;$('adminMessage').className=error?'error':'';}
function clearDetail(){detailRevision++;$('authorizationDetails').replaceChildren();$('clinicalDetails').replaceChildren();activeId=null;activeRecord=null;images.forEach(URL.revokeObjectURL);images=[];adminExplanationUrls.forEach(URL.revokeObjectURL);adminExplanationUrls=[];$('originalImage').removeAttribute('src');$('processedImage').removeAttribute('src');$('detailPanel').hidden=true;$('recordDetails').replaceChildren();$('analysisDetails').replaceChildren();$('metadata').textContent='';$('deleteConfirm').value='';$('tagChips').replaceChildren();$('tagInput').value='';$('editAge').value='';$('editMeta').textContent='';}
function logout(clearStored=true){participantAppliedQuery='';if(clearStored){pendingUIState=null;try{sessionStorage.removeItem(UI_STATE_KEY);}catch{}}detailNavigationRevision++;detailOrder=[];listRows=[];listTotal=0;listReturn=null;appliedFields={start:'',end:'',status:'all',tag:''};scopeValid=true;token='';trendRevision++;trendRecords=[];$('memberTrendPanel').hidden=true;$('memberTrendChart').replaceChildren();$('memberTrendStatus').textContent='';$('memberTrendModel').replaceChildren();listRevision++;participantRevision++;scopeRevision++;participantOffset=0;offset=0;selectedParticipant=null;selectedSubject='';scopeMode='all';modelCatalog=[];allTags=[];$('participantRows').replaceChildren();$('participantTotal').textContent='';$('participantQuery').value='';$('memberChoices').replaceChildren();$('total').textContent='';$('tagFilter').replaceChildren(new Option('全部标签',''));$('tagOptions').replaceChildren();$('startDate').value='';$('endDate').value='';$('statusFilter').value='all';paintScope();clearDetail();$('workspace').hidden=true;$('loginPanel').hidden=false;$('logout').hidden=true;$('records').replaceChildren();$('adminKey').value='';$('heatmapPanel').hidden=true;$('heatmapSettings').setAttribute('aria-expanded','false');}
async function request(path,options={}){
 const credential=token;const response=await fetch(path,{...options,headers:{Authorization:`Bearer ${credential}`,...options.headers}});if(!credential||credential!==token)throw new Error('管理会话已结束');
 if(!response.ok){let body;try{body=await response.json();}catch{body={};}if(response.status===401){if(!$('workspace').hidden)saveUIState();logout(false);}throw new Error(typeof body.detail==='string'?body.detail:'操作失败，请检查输入后重试');}
 return response;
}
function renderHeatmapSettings(data){
 $('ageHeatmapMethod').replaceChildren(...data.options.map(option=>{
  const entry=new Option(option.label,option.id);
  entry.disabled=!option.available;
  return entry;
 }));
 $('ageHeatmapMethod').value=data.age_method;
 $('heatmapCurrent').textContent=`当前年龄热图：${data.options.find(option=>option.id===data.age_method)?.label||data.age_method}`;
}
async function loadHeatmapSettings(){
 const credential=token;const data=await(await request('/v1/admin/settings/heatmaps')).json();if(token===credential&&token)renderHeatmapSettings(data);
}
function clearTrend(){trendRevision++;trendRecords=[];$('memberTrendChart').replaceChildren();$('memberTrendStatus').textContent='';$('memberTrendPanel').hidden=!(selectedParticipant&&selectedSubject&&selectedSubject!=='unknown');$('loadMemberTrend').disabled=false;}
function paintScope(){
 if(!scopeValid){$('scopeLabel').textContent='当前范围：保存的范围待重新确认';$('scopeNavigation').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed','false'));return;}
 const names={all:'全站记录',account:'登录账号记录',guest:'访客记录',unknown:'待确认归属'};
 $('scopeLabel').textContent=`当前范围：${selectedParticipant?`账号 ${selectedParticipant.username} / ${selectedSubject?$('memberChoices').querySelector(`[data-subject="${CSS.escape(selectedSubject)}"]`)?.textContent||selectedSubject:'全部成员'}`:names[scopeMode]}`;
 $('scopeNavigation').querySelectorAll('[data-scope]').forEach(b=>b.setAttribute('aria-pressed',String(!selectedParticipant&&b.dataset.scope===scopeMode)));
}
function query(){if(!scopeValid)throw new Error('请先重新确认记录范围');const params=new URLSearchParams();for(const [key,value] of Object.entries(appliedFields))if(value)params.set(key,value);params.set('ownership',selectedParticipant?'account':scopeMode==='unknown'?'all':scopeMode);if(selectedParticipant)params.set('participant_id',selectedParticipant.id);if(selectedSubject)params.set('subject_id',selectedSubject);else if(scopeMode==='unknown')params.set('subject_id','unknown');return params;}
async function loadParticipants(){
 const revision=++participantRevision;const params=new URLSearchParams({q:participantAppliedQuery,limit:20,offset:participantOffset});
 const data=await(await request(`/v1/admin/participants?${params}`)).json();if(revision!==participantRevision||!token)return;
 $('participantTotal').textContent=`共 ${data.total} 个账号`;$('participantPrevious').disabled=participantOffset===0;$('participantNext').disabled=participantOffset+20>=data.total;
 $('participantRows').innerHTML=data.items.map(p=>`<button class="participant-card" data-participant="${esc(p.id)}" data-username="${esc(p.username)}" aria-pressed="${selectedParticipant?.id===p.id}"><strong>${esc(p.username)}</strong><span>${p.capture_count} 条测量 · ${p.subject_count} 个对象分组</span><small>最近测量：${p.last_capture_at?esc(date(p.last_capture_at)):'暂无'}</small></button>`).join('')||'<p class="muted">未找到账号。</p>';
}
async function chooseParticipant(id,username){
 detailNavigationRevision++;listReturn=null;const revision=++scopeRevision;scopeValid=true;selectedParticipant={id,username};selectedSubject='';scopeMode='account';offset=0;listRevision++;clearTrend();clearDetail();$('total').textContent='正在加载成员…';$('records').replaceChildren();$('memberChoices').textContent='正在加载成员…';paintScope();
 try{const data=await(await request(`/v1/admin/participants/${encodeURIComponent(id)}/subjects`)).json();if(revision!==scopeRevision||!token)return;
 renderMembers(data.items);paintScope();await load();loadParticipants().catch(e=>notice(e.message,true));
 }catch(e){if(revision===scopeRevision){scopeValid=false;paintScope();$('memberChoices').textContent='成员加载失败，请重新选择账号。';notice(e.message,true);}}
}
async function load(){
 clearTrend();const revision=++listRevision;$('records').innerHTML='<tr><td colspan="7">正在加载当前范围…</td></tr>';$('total').textContent='正在加载…';const params=query();params.set('offset',offset);params.set('limit',20);let data;try{data=await(await request(`/v1/admin/captures?${params}`)).json();}catch(e){if(revision===listRevision&&token){$('records').innerHTML='<tr><td colspan="7">当前范围加载失败，请重新查询。</td></tr>';$('total').textContent='加载失败';}throw e;}if(revision!==listRevision||!token)return;
 if(data.total===0&&offset!==0){offset=0;return load();}if(data.total>0&&offset>=data.total){offset=Math.floor((data.total-1)/20)*20;return load();}listRows=data.items;listTotal=data.total;saveUIState();
 $('total').textContent=`共 ${data.total} 条记录 · 第 ${Math.floor(offset/20)+1} 页`;$('previous').disabled=offset===0;$('next').disabled=offset+20>=data.total;
 $('records').innerHTML=data.items.length?data.items.map(row=>`<tr><td>${esc(row.id.slice(0,8))}…<small>${esc(date(row.created_at))}</small></td><td>${esc(row.username||'访客')}<small>${esc(row.subject_label||'待确认')}</small></td><td>${esc(row.age)} 岁 · ${esc({male:'男',female:'女',other:'其他',unspecified:'未透露'}[row.gender])}<small>${row.capture_source==='camera'?'相机拍摄':'本地上传'}</small></td><td>完成 ${row.completed} 项${row.running?` · 进行中 ${row.running} 项`:''}${row.failed?` · 失败 ${row.failed} 项`:''}<small>实测 ${row.observation_count||0} 项</small></td><td>${row.research_consent&&row.training_consent&&row.research_consent_version===currentConsentVersion?'已授权':row.research_consent?'历史授权 / 待确认':'未参与'}</td><td>${(row.tags||[]).map(tag=>`<span class="tag">${esc(tag)}</span>`).join('')||'—'}<small>${row.deletion_requested_at?'待处理删除申请':'已保存'}</small></td><td><button data-record="${esc(row.id)}">查看记录</button></td></tr>`).join(''):'<tr><td colspan="7">当前范围内暂无符合条件的记录。</td></tr>';
}
function renderTagChips(tags){
 $('tagChips').replaceChildren(...tags.map(tag=>{
  const chip=document.createElement('span');chip.className='tag-chip';chip.append(document.createTextNode(tag));
  const remove=document.createElement('button');remove.type='button';remove.dataset.removeTag=tag;remove.setAttribute('aria-label',`移除标签 ${tag}`);remove.textContent='×';chip.append(remove);return chip;
 }));
}
function editMeta(record){return record.updated_at?`最后人工修订：${date(record.updated_at)}`:'尚未人工修订';}
async function loadTags(){
 const credential=token;try{
  const data=await (await request('/v1/admin/tags')).json();
  if(!token||token!==credential)return;allTags=data.items||[];
  const selected=$('tagFilter').value;
  $('tagFilter').replaceChildren(new Option('全部标签',''),...allTags.map(item=>new Option(`${item.tag}（${item.count}）`,item.tag)));
  if(selected&&!Array.from($('tagFilter').options).some(o=>o.value===selected))$('tagFilter').add(new Option(selected,selected));$('tagFilter').value=selected;paintDraft();
  const names=[...new Set([...PRESET_TAGS,...allTags.map(item=>item.tag)])];
  $('tagOptions').replaceChildren(...names.map(name=>{const option=document.createElement('option');option.value=name;return option;}));
 }catch(error){notice(error.message,true);}
}
async function saveTags(tags){
 if(!activeId)return false;
 try{
  const identity=activeId,revision=detailRevision;const record=await (await request(`/v1/admin/captures/${identity}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({tags})})).json();
  if(revision!==detailRevision||activeId!==identity)return false;activeRecord=record;renderTagChips(record.tags||[]);$('editMeta').textContent=editMeta(record);
  notice('标签已更新。');await load();await loadTags();await syncDetailPosition();return true;
 }catch(error){notice(error.message,true);return false;}
}
async function detail(id){
 clearDetail();activeId=id;const revision=detailRevision;
 const record=await (await request(`/v1/admin/captures/${id}`)).json();if(revision!==detailRevision)return;
 $('recordDetails').innerHTML=`<p><strong>${esc(record.id)}</strong><br>${esc(date(record.created_at))}<br>账号：${esc(record.username||'访客')} · 成员：${esc(record.subject_label||'待确认')} · ${esc(record.age)} 岁 · ${esc(record.height_cm)} cm · ${esc(record.weight_kg)} kg${record.deletion_requested_at?'<br><strong>用户已提交删除申请，请核实处理。</strong>':''}</p>`;
 activeRecord=record;$('editAge').value=record.age;renderTagChips(record.tags||[]);$('editMeta').textContent=editMeta(record);
 if(!modelCatalog.length){const state=await (await request('/ready')).json();if(revision!==detailRevision)return;modelCatalog=state.models||[];currentConsentVersion=state.research_consent_version;}
 const observed=new Map(MFF.observations(record).map(o=>[o.model,o]));
 const tasks=[...record.predictions,...[...observed.keys()].filter(id=>!record.predictions.some(p=>p.model===id)).map(model=>({model,status:'observation_only'}))];
 $('authorizationDetails').innerHTML=`<h3>科研授权</h3><p>${record.research_consent&&record.training_consent&&record.research_consent_version===currentConsentVersion?'当前用途已授权':record.research_consent?'保留历史授权，当前用途待确认':'未参与科研'} · 科研 ${record.research_consent?'同意':'未同意'} / 训练 ${record.training_consent?'同意':'未同意'}</p><p class="muted">每条记录独立授权；实测与临床信息为用户填报，未经核实。</p>`;
 const clinicalLabels={medical_history:'既往病史',medications:'当前用药',family_history:'家族病史',smoking:'吸烟情况',alcohol:'饮酒情况',notes:'其他补充'};
 $('clinicalDetails').innerHTML='<h3>临床信息</h3><dl class="clinical-grid">'+Object.entries(clinicalLabels).map(([key,label])=>`<div><dt>${label}</dt><dd>${esc(record.clinical_information?.[key]||'未填写')}</dd></div>`).join('')+'</dl>';
 $('analysisDetails').innerHTML=tasks.length?`<div class="prediction-table-scroll" tabindex="0"><table class="prediction-table"><thead><tr><th>指标</th><th>模型预测</th><th>参考范围</th><th>实测值</th><th>状态</th><th>详情</th></tr></thead><tbody>${tasks.map(p=>{
  const m=modelCatalog.find(m=>m.id===p.model)||{id:p.model,label:labels[p.model]||p.model},o=observed.get(p.model);
  const plots=camVariants.filter(([,flag])=>p[flag]).map(([variant,,label])=>`<figure class="explanation"><img data-admin-explanation="${esc(p.id)}" data-variant="${variant}" alt="${esc(label)}" loading="lazy"><figcaption>${esc(label)}</figcaption></figure>`).join('');
  const status={completed:'已完成',running:'分析中',failed:'失败',observation_only:'仅实测'}[p.status]||p.status;
  return `<tr><th scope="row">${esc(m.label)}<small>${esc(p.model)}</small></th><td>${p.result?`${esc(MFF.number(p.result.value))} ${esc(MFF.unit(p.result.unit,p.model))}`:'—'}</td><td>${MFF.referenceRange(m,record)}</td><td>${o?`${esc(MFF.number(o.value))} ${esc(o.unit)}<small>日期：${esc(o.measured_on||'未填写')}<br>${esc(MFF.observationTiming(record,o))}<br>${esc({capture_profile:'采集资料',calculated_bmi:'身高体重计算',lab_report:'检验报告',self_report:'自行填报'}[o.source]||o.source||'')}</small>`:'—'}</td><td>${esc(status)}${p.error?`<small>${esc(p.error)}</small>`:''}</td><td><details><summary>查看</summary>${p.id?`<small>更新：${esc(date(p.updated_at))}<br>版本：${esc(p.model_version)}<br>尝试：${esc(p.attempts)}</small>`:'<small>尚无模型预测</small>'}<div class="cam-comparison">${plots}</div></details></td></tr>`;
 }).join('')}</tbody></table></div>`:'<p>暂无预测结果</p>';
 if(record.cam_comparison_available)appendCamComparison(id,revision);
 if(record.fahr_faceage_available)appendFahrComparison(id,revision);
 $('metadata').textContent=JSON.stringify({research_consent:record.research_consent,training_consent:record.training_consent,research_consent_version:record.research_consent_version,observations:record.observations,clinical_information:record.clinical_information,consent_version:record.consent_version,consented_at:record.consented_at,crop_box:record.crop_box,quality:record.quality_json},null,2);
 $('detailPanel').hidden=false;updateDetailNavigation();$('detailPanel').scrollIntoView({block:'start'});
 for(const [kind,img] of [['original','originalImage'],['processed','processedImage']]){
  try{const blob=await (await request(`/v1/admin/captures/${id}/image/${kind}`)).blob();if(revision!==detailRevision)return;const url=URL.createObjectURL(blob);images.push(url);$(img).src=url;}catch(error){if(revision===detailRevision)notice(error.message,true);}
 }
 loadAdminExplanations(record,revision);
}
function appendCamComparison(id,revision){
 const card=document.createElement('article');
 card.innerHTML=`<h3>MedicalFaceFound 年龄热图 · 临时对照</h3>
  <p>使用当前 Age 权重和本记录的裁剪图。结果仅在当前详情显示。</p>
  <div class="actions cam-controls"><button type="button">运行热图对照</button>
  <label><input type="checkbox"> 同时测量 ROAD 遮挡前后的年龄变化</label></div>
  <p role="status"></p><div class="cam-comparison"></div><div class="cam-road"></div>`;
 const button=card.querySelector('button');
 const evaluate=card.querySelector('input');
 const status=card.querySelector('[role="status"]');
 const plots=card.querySelector('.cam-comparison');
 const metrics=card.querySelector('.cam-road');
 const methods=[
  ['hirescam','HiResCAM · 第四阶段 norm1（8×8）'],
  ['layercam','LayerCAM · 第三阶段 norm1（16×16）'],
 ];
 $('analysisDetails').append(card);
 button.addEventListener('click',async()=>{
  button.disabled=evaluate.disabled=true;
  status.textContent='正在生成对照…';
  status.className='';
  try{
   const path=`/v1/admin/captures/${encodeURIComponent(id)}/cam-comparison?evaluate=${evaluate.checked}`;
   const data=await (await request(path,{method:'POST'})).json();
   if(revision!==detailRevision)return;
   plots.replaceChildren(...methods.map(([key,label])=>{
    const figure=document.createElement('figure');
    figure.className='explanation';
    const image=document.createElement('img');
    image.alt=label;
    image.src=data.overlays[key];
    const caption=document.createElement('figcaption');
    caption.textContent=label;
    figure.append(image,caption);
    return figure;
   }));
   metrics.replaceChildren();
   if(data.road){
    const heading=document.createElement('p');
    heading.textContent='ROAD · 分别替换最高分与最低分的 25% 像素，显示预测年龄的变化。同分像素按固定次序选取。';
    const changes=document.createElement('ul');
    const years=value=>`${value>=0?'+':''}${value.toFixed(2)} 岁`;
    for(const [key,label] of [...methods,['gradcam_norm1','Grad-CAM · 第四阶段 norm1（参照）']]){
     const row=document.createElement('li');
     const change=data.road[key];
     row.textContent=change
      ?`${label}：高分区 ${years(change.high_delta_years)} · 低分区 ${years(change.low_delta_years)}`
      :`${label}：热图没有空间差异`;
     changes.append(row);
    }
    metrics.append(heading,changes);
   }
   status.textContent='对照已生成。';
  }catch(error){
   if(revision!==detailRevision)return;
   status.textContent=error.message;
   status.className='error';
  }finally{
   if(revision===detailRevision)button.disabled=evaluate.disabled=false;
  }
 });
}
function appendFahrComparison(id,revision){
 const card=document.createElement('article');
 const title=document.createElement('h3');
 title.textContent='FAHR-FaceAge · 临时对照';
 const button=document.createElement('button');
 button.type='button';
 button.textContent='运行年龄预测与热图';
 const status=document.createElement('p');
 status.setAttribute('role','status');
 status.textContent='使用本记录的人脸裁剪图，结果仅在当前详情显示。';
 const output=document.createElement('div');
 card.append(title,button,status,output);
 $('analysisDetails').append(card);
 button.addEventListener('click',async()=>{
  button.disabled=true;
  status.textContent='正在运行 FAHR-FaceAge…';
  status.className='';
  try{
   const path=`/v1/admin/captures/${encodeURIComponent(id)}/fahr-faceage`;
   const data=await (await request(path,{method:'POST'})).json();
   if(revision!==detailRevision)return;
   const value=document.createElement('strong');
   value.textContent=`${data.result.value.toFixed(2)} 岁`;
   const plots=document.createElement('div');
   plots.className='actions';
   const heatmaps=[
    ['论文方法的单图注意力 · 最后一层 CLS → 图像块',data.attention?.overlay],
    ['Grad-CAM · 年龄输出的梯度归因',data.explanation],
   ];
   for(const [label,source] of heatmaps){
    if(!source)continue;
    const figure=document.createElement('figure');
    figure.className='explanation';
    const image=document.createElement('img');
    image.alt=label;
    image.src=source;
    const caption=document.createElement('figcaption');
    caption.textContent=label;
    figure.append(image,caption);
    plots.append(figure);
   }
   output.replaceChildren(value,plots);
   status.textContent='模型输入为共用裁剪图缩放至 112×112。';
  }catch(error){
   if(revision!==detailRevision)return;
   status.textContent=error.message;
   status.className='error';
  }finally{
   if(revision===detailRevision)button.disabled=false;
  }
 });
}
async function loadAdminExplanations(record,revision){
 adminExplanationUrls.forEach(URL.revokeObjectURL);adminExplanationUrls=[];
 for(const image of $('analysisDetails').querySelectorAll('img[data-admin-explanation]')){
  const {adminExplanation,variant}=image.dataset;
  try{const blob=await (await request(`/v1/admin/captures/${record.id}/explanations/${adminExplanation}?variant=${variant}`)).blob();if(revision!==detailRevision)return;const url=URL.createObjectURL(blob);adminExplanationUrls.push(url);image.src=url;}catch(error){if(revision===detailRevision)notice(error.message,true);}
 }
}
$('loginForm').addEventListener('submit',async event=>{event.preventDefault();token=$('adminKey').value.trim();try{const state=await(await request('/ready')).json();modelCatalog=state.models||[];currentConsentVersion=state.research_consent_version;$('memberTrendModel').replaceChildren(...modelCatalog.map(m=>new Option(m.label,m.id)));await loadTags();const restored=await restoreUIState();if(restored)await load();await loadParticipants();await loadHeatmapSettings();$('adminKey').value='';$('loginPanel').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;if(scopeValid)notice('已进入内部数据管理。');restoreListScroll();}catch(error){logout(false);notice(error.message,true);}});
$('heatmapSettings').addEventListener('click',async()=>{
 const panel=$('heatmapPanel');
 if(panel.hidden){
  try{await loadHeatmapSettings();}catch(error){notice(error.message,true);return;}
 }
 panel.hidden=!panel.hidden;
 $('heatmapSettings').setAttribute('aria-expanded',String(!panel.hidden));
});
$('heatmapForm').addEventListener('submit',async event=>{
 event.preventDefault();
 const button=event.submitter;
 if(button)button.disabled=true;
 try{
  const response=await request('/v1/admin/settings/heatmaps',{
   method:'PUT',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({age_method:$('ageHeatmapMethod').value}),
  });
  renderHeatmapSettings(await response.json());
  notice('年龄热图设置已保存，采集页的新分析将使用此方法。');
 }catch(error){notice(error.message,true);}
 finally{if(button)button.disabled=false;}
});
$('logout').addEventListener('click',()=>{logout();notice('已退出登录。');});
$('filters').addEventListener('submit',async event=>{event.preventDefault();detailNavigationRevision++;listReturn=null;appliedFields=readDraft();paintDraft();offset=0;clearDetail();try{await load();notice('筛选结果已更新。');}catch(error){notice(error.message,true);}});
$('records').addEventListener('click',event=>{const button=event.target.closest('[data-record]');if(button){listReturn={id:button.dataset.record,x:window.scrollX,y:window.scrollY,tableX:$('recordListScroll').scrollLeft,offset};openDetail(button.dataset.record);}});
$('previous').addEventListener('click',()=>{detailNavigationRevision++;listReturn=null;clearDetail();offset=Math.max(0,offset-20);load().catch(error=>notice(error.message,true));});$('next').addEventListener('click',()=>{detailNavigationRevision++;listReturn=null;clearDetail();offset+=20;load().catch(error=>notice(error.message,true));});
$('closeDetail').addEventListener('click',returnToList);$('detailPrevious').onclick=()=>activeId&&openDetail(activeId,-1);$('detailNext').onclick=()=>activeId&&openDetail(activeId,1);for(const id of ['startDate','endDate','statusFilter','tagFilter'])$(id).addEventListener('input',paintDraft);
$('export').addEventListener('click',async()=>{try{const blob=await(await request(`/v1/admin/export?${query()}`)).blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='MedicalFaceFound-采集数据.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notice('已导出符合筛选条件的资料与分析结果，文件不含照片。');}catch(error){notice(error.message,true);}});
$('backup').addEventListener('click',async()=>{try{const data=await(await request('/v1/admin/backup',{method:'POST'})).json();notice(`${data.message}：${data.filename}`);}catch(error){notice(error.message,true);}});
$('deleteRecord').addEventListener('click',async()=>{
 const identity=activeId,revision=detailRevision;if(!identity||$('deleteConfirm').value.trim()!==identity){notice('请输入完整采集编号以确认。',true);return;}
 if(!confirm('确认永久删除当前数据库中的此记录及关联结果？历史备份不会自动删除。'))return;
 try{const data=await(await request(`/v1/admin/captures/${identity}/delete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation:identity})})).json();
 const updates=new BroadcastChannel('mff-record-updates');updates.postMessage({type:'deleted',id:identity});updates.close();if(revision!==detailRevision)return;clearDetail();await load();await loadTags();await loadParticipants();await refreshMemberCounts();await returnToList();notice(data.message);
 }catch(error){if(revision===detailRevision)notice(error.message,true);}
});
$('ageForm').addEventListener('submit',async event=>{
 event.preventDefault();if(!activeId)return;
 const identity=activeId,revision=detailRevision;const age=Number($('editAge').value);
 if(!Number.isInteger(age)||age<0||age>120){notice('年龄需为 0–120 的整数。',true);return;}
 try{
  await (await request(`/v1/admin/captures/${identity}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({age})})).json();
  if(revision!==detailRevision||activeId!==identity)return;notice(`年龄已更新为 ${age} 岁。`);await detail(identity);await load();await syncDetailPosition();
 }catch(error){notice(error.message,true);}
});
$('tagForm').addEventListener('submit',async event=>{
 event.preventDefault();if(!activeRecord)return;
 const tag=$('tagInput').value.trim().replace(/\s+/g,' ');
 if(!tag)return;
 if(tag.length>32){notice('标签不能超过 32 个字符。',true);return;}
 if((activeRecord.tags||[]).includes(tag)){notice('该标签已存在。');$('tagInput').value='';return;}
 if(await saveTags([...(activeRecord.tags||[]),tag]))$('tagInput').value='';
});
$('tagChips').addEventListener('click',event=>{
 const button=event.target.closest('[data-remove-tag]');if(!button||!activeRecord)return;
 saveTags((activeRecord.tags||[]).filter(tag=>tag!==button.dataset.removeTag));
});
window.addEventListener('pagehide',()=>{if(!$('workspace').hidden)saveUIState();logout(false);});

for(const purpose of ['evaluation','training']){const button=document.createElement('button');button.type='button';button.textContent=purpose==='training'?'导出已授权训练数据':'导出已授权科研数据';$('export').after(button);button.onclick=async()=>{try{const exportParams=query();exportParams.set('purpose',purpose);const state=await (await request('/ready')).json();if(state.api_version!==2)throw new Error('页面与后端版本不兼容，请重启新版服务后导出');const blob=await(await request(`/v1/admin/research-export?${exportParams}`)).blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`MedicalFaceFound-${purpose}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notice('已导出当前筛选范围内具有有效授权的记录，实测值未经核实。');}catch(error){notice(error.message,true);}};}

$('participantSearch').onsubmit=e=>{e.preventDefault();participantAppliedQuery=$('participantQuery').value.trim();participantOffset=0;loadParticipants().catch(e=>notice(e.message,true));};
$('participantPrevious').onclick=()=>{participantOffset=Math.max(0,participantOffset-20);loadParticipants().catch(e=>notice(e.message,true));};
$('participantNext').onclick=()=>{participantOffset+=20;loadParticipants().catch(e=>notice(e.message,true));};
$('participantRows').onclick=e=>{const b=e.target.closest('[data-participant]');if(b)chooseParticipant(b.dataset.participant,b.dataset.username);};
$('scopeNavigation').onclick=e=>{const b=e.target.closest('[data-scope]');if(!b)return;detailNavigationRevision++;listReturn=null;scopeValid=true;scopeRevision++;selectedParticipant=null;selectedSubject='';scopeMode=b.dataset.scope;offset=0;clearDetail();$('memberChoices').replaceChildren();paintScope();load().catch(e=>notice(e.message,true));loadParticipants().catch(e=>notice(e.message,true));};
$('memberChoices').onclick=e=>{const b=e.target.closest('[data-subject]');if(!b||!selectedParticipant)return;detailNavigationRevision++;listReturn=null;scopeValid=true;selectedSubject=b.dataset.subject;offset=0;clearDetail();$('memberChoices').querySelectorAll('button').forEach(button=>button.setAttribute('aria-pressed',String(button===b)));paintScope();load().catch(e=>notice(e.message,true));};

$('loadMemberTrend').onclick=async()=>{
 if(!selectedParticipant||!selectedSubject||selectedSubject==='unknown')return;
 const participant=selectedParticipant.id,subject=selectedSubject,ticket=++trendRevision,params=query();trendRecords=[];$('memberTrendChart').replaceChildren();$('loadMemberTrend').disabled=true;
 try{
  const records=[];let page=0,total=0;
  do{params.set('offset',page);params.set('limit',20);const data=await(await request(`/v1/admin/captures?${params}`)).json();if(ticket!==trendRevision||!token)return;total=data.total;
   if(!data.items.length&&page<total)throw new Error('记录分页已变化，请重新加载趋势。');
   for(const row of data.items){if(row.participant_id!==participant||row.subject_id!==subject)throw new Error('记录范围不一致，请重新选择成员。');const r=await(await request(`/v1/admin/captures/${encodeURIComponent(row.id)}`)).json();if(ticket!==trendRevision||!token)return;if(r.participant_id!==participant||r.subject_id!==subject)throw new Error('记录归属已变化，请重新加载。');records.push(r);$('memberTrendStatus').textContent=`已加载 ${records.length} / ${total} 条`;}
   page+=data.items.length;
  }while(page<total);
  if(ticket!==trendRevision)return;trendRecords=records;MFFTrend.render($('memberTrendChart'),trendRecords,$('memberTrendModel').value,0);$('memberTrendStatus').textContent=`已加载当前筛选范围全部 ${records.length} 条记录。`;
 }catch(e){if(ticket===trendRevision){trendRecords=[];$('memberTrendChart').replaceChildren();$('memberTrendStatus').textContent=e.message;}}
 finally{if(ticket===trendRevision)$('loadMemberTrend').disabled=false;}
};
$('memberTrendModel').onchange=()=>{if(trendRecords.length)MFFTrend.render($('memberTrendChart'),trendRecords,$('memberTrendModel').value,0);};

async function refreshMemberCounts(){
 if(!selectedParticipant)return;const identity=selectedParticipant.id,ticket=scopeRevision;
 const data=await(await request(`/v1/admin/participants/${encodeURIComponent(identity)}/subjects`)).json();if(ticket!==scopeRevision||selectedParticipant?.id!==identity||!token)return;
 for(const m of data.items){const button=$('memberChoices').querySelector(`[data-subject="${CSS.escape(m.id)}"]`);if(button)button.textContent=`${m.label}（${m.record_count}）`;}
 paintScope();
}

async function syncDetailPosition(){if(!activeId)return;const ticket=++detailNavigationRevision;try{const ids=await orderedIds(ticket);if(ticket!==detailNavigationRevision||!ids)return;detailOrder=ids;updateDetailNavigation();}catch(e){if(ticket===detailNavigationRevision){detailOrder=[];updateDetailNavigation();notice(e.message,true);}}}
