const $=id=>document.getElementById(id);
let token='',offset=0,activeId=null,activeRecord=null,allTags=[],images=[],adminExplanationUrls=[],detailRevision=0;
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
function clearDetail(){detailRevision++;activeId=null;activeRecord=null;images.forEach(URL.revokeObjectURL);images=[];adminExplanationUrls.forEach(URL.revokeObjectURL);adminExplanationUrls=[];$('originalImage').removeAttribute('src');$('processedImage').removeAttribute('src');$('detailPanel').hidden=true;$('recordDetails').replaceChildren();$('analysisDetails').replaceChildren();$('metadata').textContent='';$('deleteConfirm').value='';$('tagChips').replaceChildren();$('tagInput').value='';$('editAge').value='';$('editMeta').textContent='';}
function logout(){token='';clearDetail();$('workspace').hidden=true;$('loginPanel').hidden=false;$('logout').hidden=true;$('records').replaceChildren();$('adminKey').value='';$('heatmapPanel').hidden=true;$('heatmapSettings').setAttribute('aria-expanded','false');}
async function request(path,options={}){
 const response=await fetch(path,{...options,headers:{Authorization:`Bearer ${token}`,...options.headers}});
 if(!response.ok){let body;try{body=await response.json();}catch{body={};}if(response.status===401)logout();throw new Error(typeof body.detail==='string'?body.detail:'操作失败，请检查输入后重试');}
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
 renderHeatmapSettings(await (await request('/v1/admin/settings/heatmaps')).json());
}
function query(){const query=new URLSearchParams();if($('startDate').value)query.set('start',$('startDate').value);if($('endDate').value)query.set('end',$('endDate').value);query.set('status',$('statusFilter').value);if($('tagFilter').value)query.set('tag',$('tagFilter').value);return query;}
async function load(){
 const params=query();params.set('offset',offset);const data=await (await request(`/v1/admin/captures?${params}`)).json();
 $('total').textContent=`共 ${data.total} 条记录 · 第 ${Math.floor(offset/20)+1} 页`;$('previous').disabled=offset===0;$('next').disabled=offset+20>=data.total;
 $('records').innerHTML=data.items.length?data.items.map(row=>`<tr><td>${esc(row.id.slice(0,8))}…<small>${esc(date(row.created_at))}</small></td><td>${esc(row.age)} 岁 · ${esc({male:'男',female:'女',other:'其他',unspecified:'未透露'}[row.gender])}<small>${row.capture_source==='camera'?'相机拍摄':'本地上传'}</small></td><td>完成 ${row.completed} 项${row.failed?` · 失败 ${row.failed} 项`:''}</td><td>${(row.tags||[]).map(tag=>`<span class="tag">${esc(tag)}</span>`).join('')||'—'}</td><td>${row.deletion_requested_at?'待处理删除申请':'已保存'}</td><td><button data-record="${esc(row.id)}">查看记录</button></td></tr>`).join(''):'<tr><td colspan="6">暂无符合条件的采集记录。</td></tr>';
}
function renderTagChips(tags){
 $('tagChips').replaceChildren(...tags.map(tag=>{
  const chip=document.createElement('span');chip.className='tag-chip';chip.append(document.createTextNode(tag));
  const remove=document.createElement('button');remove.type='button';remove.dataset.removeTag=tag;remove.setAttribute('aria-label',`移除标签 ${tag}`);remove.textContent='×';chip.append(remove);return chip;
 }));
}
function editMeta(record){return record.updated_at?`最后人工修订：${date(record.updated_at)}`:'尚未人工修订';}
async function loadTags(){
 try{
  const data=await (await request('/v1/admin/tags')).json();
  allTags=data.items||[];
  const selected=$('tagFilter').value;
  $('tagFilter').replaceChildren(new Option('全部标签',''),...allTags.map(item=>new Option(`${item.tag}（${item.count}）`,item.tag)));
  $('tagFilter').value=selected;
  const names=[...new Set([...PRESET_TAGS,...allTags.map(item=>item.tag)])];
  $('tagOptions').replaceChildren(...names.map(name=>{const option=document.createElement('option');option.value=name;return option;}));
 }catch(error){notice(error.message,true);}
}
async function saveTags(tags){
 if(!activeId)return false;
 try{
  const record=await (await request(`/v1/admin/captures/${activeId}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({tags})})).json();
  activeRecord=record;renderTagChips(record.tags||[]);$('editMeta').textContent=editMeta(record);
  notice('标签已更新。');await load();await loadTags();return true;
 }catch(error){notice(error.message,true);return false;}
}
async function detail(id){
 clearDetail();activeId=id;const revision=detailRevision;
 const record=await (await request(`/v1/admin/captures/${id}`)).json();if(revision!==detailRevision)return;
 $('recordDetails').innerHTML=`<p><strong>${esc(record.id)}</strong><br>${esc(date(record.created_at))} · ${esc(record.age)} 岁 · ${esc(record.height_cm)} cm · ${esc(record.weight_kg)} kg${record.deletion_requested_at?'<br><strong>用户已提交删除申请，请核实处理。</strong>':''}</p>`;
 activeRecord=record;$('editAge').value=record.age;renderTagChips(record.tags||[]);$('editMeta').textContent=editMeta(record);
 $('analysisDetails').innerHTML=record.predictions.length?record.predictions.map(p=>{
  const plots=camVariants.filter(([,flag])=>p[flag]).map(([variant,,label])=>
   `<figure class="explanation"><img data-admin-explanation="${esc(p.id)}" data-variant="${variant}" alt="${label}" loading="lazy"><figcaption>${label}</figcaption></figure>`
  ).join('');
  return `<article><h3>${esc(labels[p.model]||p.model)}</h3><strong>${p.result?`${esc(Number(p.result.value).toFixed(2))} ${esc(p.model==='Age'?'岁':p.result.unit)}`:esc(p.status==='running'?'分析中':'分析失败')}</strong><p>${esc(p.error||'研究性估计，不能替代实际检验。')}</p><small>模型版本：${esc(p.model_version)}<br>更新于 ${esc(date(p.updated_at))} · 尝试 ${p.attempts} 次</small><div class="cam-comparison">${plots}</div></article>`;
 }).join(''):'<p>本条记录尚无分析结果。</p>';
 if(record.cam_comparison_available)appendCamComparison(id,revision);
 if(record.fahr_faceage_available)appendFahrComparison(id,revision);
 $('metadata').textContent=JSON.stringify({consent_version:record.consent_version,consented_at:record.consented_at,crop_box:record.crop_box,quality:record.quality_json},null,2);
 $('detailPanel').hidden=false;$('detailPanel').scrollIntoView({block:'start'});
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
$('loginForm').addEventListener('submit',async event=>{event.preventDefault();token=$('adminKey').value.trim();try{await load();await loadTags();await loadHeatmapSettings();$('adminKey').value='';$('loginPanel').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;notice('已进入内部数据管理。');}catch(error){token='';notice(error.message,true);}});
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
$('filters').addEventListener('submit',async event=>{event.preventDefault();offset=0;clearDetail();try{await load();notice('筛选结果已更新。');}catch(error){notice(error.message,true);}});
$('records').addEventListener('click',event=>{const button=event.target.closest('[data-record]');if(button)detail(button.dataset.record).catch(error=>notice(error.message,true));});
$('previous').addEventListener('click',()=>{offset=Math.max(0,offset-20);load().catch(error=>notice(error.message,true));});$('next').addEventListener('click',()=>{offset+=20;load().catch(error=>notice(error.message,true));});
$('closeDetail').addEventListener('click',clearDetail);
$('export').addEventListener('click',async()=>{try{const blob=await(await request(`/v1/admin/export?${query()}`)).blob();const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='MedicalFaceFound-采集数据.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notice('已导出符合筛选条件的资料与分析结果，文件不含照片。');}catch(error){notice(error.message,true);}});
$('backup').addEventListener('click',async()=>{try{const data=await(await request('/v1/admin/backup',{method:'POST'})).json();notice(`${data.message}：${data.filename}`);}catch(error){notice(error.message,true);}});
$('deleteRecord').addEventListener('click',async()=>{if(!activeId||$('deleteConfirm').value.trim()!==activeId){notice('请输入完整采集编号以确认。',true);return;}if(!confirm('确认永久删除当前数据库中的此记录及关联结果？历史备份不会自动删除。'))return;try{const data=await(await request(`/v1/admin/captures/${activeId}/delete`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmation:activeId})})).json();clearDetail();await load();notice(data.message);}catch(error){notice(error.message,true);}});
$('ageForm').addEventListener('submit',async event=>{
 event.preventDefault();if(!activeId)return;
 const age=Number($('editAge').value);
 if(!Number.isInteger(age)||age<0||age>120){notice('年龄需为 0–120 的整数。',true);return;}
 try{
  await (await request(`/v1/admin/captures/${activeId}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({age})})).json();
  notice(`年龄已更新为 ${age} 岁。`);await detail(activeId);await load();
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
window.addEventListener('pagehide',logout);
