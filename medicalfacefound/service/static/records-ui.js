/* Shared public record views. Credentials stay in an HttpOnly session cookie. */
(()=>{
const D=window.MFFDrafts;
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const disclaimer='模型预测仅供科研参考，不作为临床诊断依据，不能替代实际检验。';
async function api(path,options={}){
 const response=await fetch(path,{credentials:'same-origin',...options,headers:{'X-MFF-Request':'1',...options.headers}});
 const body=await response.json();
 if(!response.ok){const d=body.detail;const e=new Error(typeof d==='string'?d:Array.isArray(d)?d.map(v=>v.msg).join('；'):d?.message||'请求失败，请重试');e.status=response.status;e.quality=d?.quality;throw e;}
 return body;
}
function requireCompatible(state){if(state.api_version!==2||state.research_consent_version!=='research-training-2026-11-12-v3'||!Array.isArray(state.models)||state.models.some(m=>typeof m.available!=='boolean'))throw new Error('页面与后端版本不兼容，请管理员重启新版服务后刷新页面；当前暂停提交。');return state;}
const date=v=>v?new Date(v).toLocaleString('zh-CN',{hour12:false}):'—';
const unit=(u,id)=>['WBC','PCT'].includes(id)?'':({'year':'岁','years':'岁','Seconds':'秒','ratio':'无量纲','\\':'无量纲','μU/ml':'μU/mL','10^9/L':'10⁹/L','10^12/L':'10¹²/L'}[u]||u||'');
const number=v=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v))?Number(v).toLocaleString('zh-CN',{maximumFractionDigits:3}):'—';
function comparison(p,o,id){
 if(!p?.result||!o||['WBC','PCT'].includes(id))return '—';
 if(!unit(p.result.unit,id)||!unit(o.unit,id))return '单位缺失，未比较';
 if(unit(p.result.unit,id).replace(/\s/g,'').toLowerCase()!==unit(o.unit,id).replace(/\s/g,'').toLowerCase())return '单位不同，未比较';
 const delta=p.result.value-o.value;
 return `${delta>0?'+':''}${number(delta)}`;
}
// Compare calendar dates in the service's display timezone, not elapsed hours.
function captureDay(value){
 if(!value||!Number.isFinite(Date.parse(value)))return '';
 return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
}
function calendarDay(value){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(value||''))return null;
 const t=Date.parse(value+'T00:00:00Z');
 return Number.isFinite(t)&&new Date(t).toISOString().slice(0,10)===value?t/86400000:null;
}
function observationTiming(record,o){
 if(!o)return '';
 if(['capture_profile','calculated_bmi'].includes(o.source))return '同次采集资料';
 const capture=calendarDay(captureDay(record.created_at)),measured=calendarDay(o.measured_on);
 if(capture===null||measured===null)return '日期不完整，无法比较时间';
 const days=measured-capture;
 return days===0?'采集同日，不代表同时点':`采集${days<0?'前':'后'} ${Math.abs(days)} 天，非同时点比较`;
}
function metric(model){
 const p=model.performance;
 return p?`${p.metric} = ${number(p.value)}${p.cohort?' · '+p.cohort:''}`:'逐项性能待补充';
}
function validation(model){
 if(!model.validation)return '';
 return `<table class="validation-table"><thead><tr><th>队列 / N</th><th>R²</th><th>MAE</th><th>Pearson r（95% CI）</th></tr></thead><tbody>${model.validation.map(v=>`<tr><td>${esc(v.cohort)}<small>N=${esc(number(v.n))}</small></td><td>${esc(number(v.r2))}</td><td>${esc(number(v.mae))}</td><td>${esc(number(v.pearson_r))}${v.pearson_ci?` (${v.pearson_ci.map(number).join(', ')})`:''}</td></tr>`).join('')}</tbody></table>`;
}
const profileModels={Age:['age','岁'],Height:['height_cm','cm'],Weight:['weight_kg','kg']};
function observations(record){
 const height=Number(record.height_cm),weight=Number(record.weight_kg);
 const hasBMI=Number.isFinite(height)&&Number.isFinite(weight)&&height>0&&weight>0;
 const saved=(record.observations||[]).filter(o=>(o.model!=='BMI'||!hasBMI)&&(!profileModels[o.model]||record[profileModels[o.model][0]]==null));
 for(const [model,[field,unit]] of Object.entries(profileModels))if(record[field]!=null)saved.push({model,value:record[field],unit,measured_on:captureDay(record.created_at),source:'capture_profile'});
 if(hasBMI)saved.push({model:'BMI',value:weight/(height/100)**2,unit:'kg/m²',measured_on:captureDay(record.created_at),source:'calculated_bmi'});
 return saved;
}
function referenceRange(model,record){
 const range=model.reference_range;
 if(!range)return '以检验报告为准';
 const hasAge=record.age!==null&&record.age!==undefined&&record.age!==''&&Number.isFinite(Number(record.age));
 if(hasAge&&Number(record.age)<18)return '未成年人请按年龄对应的检验报告参考范围';
 let text=range.text||'';
 if(range.male_text||range.female_text){
  if(record.gender==='male'&&range.male_text)text=range.male_text;
  else if(record.gender==='female'&&range.female_text)text=range.female_text;
  else text=[range.male_text?'男：'+range.male_text:'',range.female_text?'女：'+range.female_text:''].filter(Boolean).join('；');
 }
 const source=range.source;
 const url=typeof source==='string'?source:source?.url;
 const label=typeof source==='object'?(source.label||source.title||'参考来源'):'参考来源';
 const link=url&&/^https?:\/\//i.test(url)?`<a href="${esc(url)}" target="_blank" rel="noopener">${esc(label)}</a>`:'';
 return `<span>${!hasAge?'成人：':''}${esc(text||range.conditions||'以检验报告为准')}${text&&range.unit?' '+esc(unit(range.unit,'')):''}</span>${link||(text&&range.conditions)?`<details><summary>适用说明</summary>${text&&range.conditions?`<p>${esc(range.conditions)}</p>`:''}${link}</details>`:''}`;
}
const consentCurrent=(r,v)=>r.subject_id!=='unknown'&&r.research_consent&&r.training_consent&&r.research_consent_version===v&&!r.deletion_requested_at;
function inlineEditor(m,o,record){
 if(profileModels[m.id]||m.id==='BMI'||m.id==='CAD')return '';
 return `<details class="inline-observation"><summary>${o?'编辑':'填写'}</summary><form data-inline-model="${esc(m.id)}"><fieldset disabled><label>实测值<input name="value" type="number" step="any" min="0" required value="${esc(o?.value??'')}"></label><label>单位<input name="unit" maxlength="32" required value="${esc(o?.unit||unit(m.unit,m.id))}" placeholder="按报告填写"></label><label>检测日期<input name="measured_on" type="date" required max="${new Date().toLocaleDateString('en-CA')}" value="${esc(o?.measured_on||'')}"></label><label>来源<select name="source"><option value="lab_report" ${o?.source==='lab_report'?'selected':''}>检验报告</option><option value="self_report" ${o?.source==='self_report'?'selected':''}>自行填报</option></select></label><div class="inline-actions"><button type="submit" class="text-button">保存</button>${o?'<button type="button" class="text-button" data-inline-remove>移除</button>':''}</div></fieldset><small data-date-note>${esc(observationTiming(record,o))}</small><span role="status" data-inline-status></span></form></details>`;
}
function bindInline(container,record,catalog,version,headers,onChange){
 bindTable(container);
 const allowed=consentCurrent(record,version);const note=container.querySelector('[data-inline-note]');if(note)note.textContent=allowed?'填写后点击保存，未保存内容离开时会提醒。':'保存科研授权后，可在表格中补充实测结果。';
 container.querySelectorAll('[data-inline-model]').forEach(form=>{
  const dateInput=form.elements.measured_on;const updateDate=()=>{form.querySelector('[data-date-note]').textContent=dateInput.value?observationTiming(record,{measured_on:dateInput.value}):'';};dateInput.addEventListener('input',updateDate);
  const field=form.querySelector('fieldset');field.disabled=!allowed;form.closest('details').hidden=!allowed;
  const status=form.querySelector('[data-inline-status]'),key='observation:'+form.dataset.inlineModel;
  if(allowed)D.watch(form,record.id,key,status);
  const run=async(remove)=>{
   if(!allowed||!container.contains(form))return;
   if(!D.begin(form)){D.feedback(form,'其他内容正在保存，请稍候。','pending');return;}
   const formData=new FormData(form);field.disabled=true;let persisted=false;
   try{
    let options={method:'DELETE',headers},path=`/v1/captures/${record.id}/observations/${encodeURIComponent(form.dataset.inlineModel)}`;
    if(!remove){const data=Object.fromEntries(formData);data.model=form.dataset.inlineModel;data.value=Number(data.value);path=`/v1/captures/${record.id}/observations`;options={method:'PUT',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify(data)};}
    const result=await api(path,options);persisted=true;D.saved(form);
    if(container.contains(form)){const drafts=D.snapshot(record.id,form);await onChange(result);D.restore(record.id,drafts);D.showSaved(record.id,key,remove?'已移除实测值':'已保存');}
   }catch(e){if(container.contains(form))D.feedback(form,persisted?'已保存，但页面更新失败，请刷新核对。':`保存失败：${e.message}；填写内容已保留。`,'error');}
   finally{D.finish(form);if(container.contains(form))field.disabled=false;}
  };
  form.onsubmit=e=>{e.preventDefault();run(false);};const remove=form.querySelector('[data-inline-remove]');if(remove)remove.onclick=()=>{if(confirm('移除这项实测值？'))run(true);};
 });
}
function rows(record,catalog,editable=false){
 const results=new Map((record.predictions||[]).map(p=>[p.model,p]));
 const observed=new Map(observations(record).map(o=>[o.model,o]));
 const models=[...catalog];
 for(const id of results.keys())if(!models.some(m=>m.id===id))models.push({id,label:id});
 return models.map(m=>{const p=results.get(m.id),o=observed.get(m.id);const predicted=p?.status==='completed'&&p.result?.value!=null;const status=predicted?(['WBC','PCT'].includes(m.id)?'已预测 · 单位待确认':'已预测'):p?.status==='running'?'分析中':p?'分析失败':m.available?'未运行':'模型不可用';
 return `<tr data-result-row data-state="${predicted?'completed':p?.status==='running'?'running':p?'failed':m.available?'notrun':'unavailable'}" data-search="${esc([m.label,m.paper_name,m.id,m.english_name].filter(Boolean).join(' ').toLowerCase())}" data-system="${esc(m.system||'其他')}" data-predicted="${predicted?'1':'0'}" data-observed="${o?'1':'0'}"><th scope="row">${esc(m.label)}<small>${esc(m.paper_name||m.id)}</small></th><td class="prediction-value">${predicted?esc(number(p.result.value)):'—'}${predicted?` <small class="value-unit">${esc(unit(p.result.unit||m.unit,m.id))}</small>`:''}</td><td class="reference-range">${referenceRange(m,record)}</td><td>${o?`<strong>${esc(number(o.value))}</strong> <span class="value-unit">${esc(unit(o.unit,m.id))}</span><small>${esc(o.measured_on||'')}${o.source==='calculated_bmi'?' · 根据身高体重计算':o.source==='capture_profile'?' · 采集资料':''}</small>`:'<span class="missing-value">未填写</span>'}${editable?inlineEditor(m,o,record):''}</td><td class="difference-value">${esc(comparison(predicted?p:null,o,m.id))}${o?`<small class="comparison-timing">${esc(observationTiming(record,o))}</small>`:''}</td><td><details class="result-details"><summary><span class="result-badge">${esc(status)}</span> 查看</summary>${p?.error?`<p>${esc(p.error)}</p>`:''}<p>${esc(metric(m))}</p>${validation(m)}<p>${esc(m.performance_note||'验证性能待补充。')}</p>${m.source?`<a href="${esc(m.source)}" target="_blank" rel="noopener">论文来源</a>`:''}${p?`<p>模型版本：${esc(p.model_version)}<br>分析时间：${esc(date(p.updated_at))}</p>`:''}</details></td></tr>`;
 }).join('');
}
function table(record,catalog,options={}){
 const systems=[...new Set(catalog.map(m=>m.system||'其他'))];
 const systemNames={Anthropometrics:'身体测量',Cardiovascular:'心血管',Digestive:'消化系统',Electrolytes:'电解质',Endocrine:'内分泌',Hematology:'血液系统',Immune:'免疫系统',Renal:'肾功能'};
 const systemLabel=v=>v.split(', ').map(k=>systemNames[k]||k).join(' / ');
 const toolbar=options.editable?`<div class="results-toolbar"><label class="results-search">搜索指标<input type="search" data-result-search placeholder="中文名称、英文或缩写" aria-label="搜索指标"></label><label>生理系统<select data-result-system><option value="">全部系统</option>${systems.map(v=>`<option value="${esc(v)}">${esc(systemLabel(v))}</option>`).join('')}</select></label><label>显示<select data-result-filter><option value="all">全部指标</option><option value="predicted">已预测</option><option value="observed">已填实测</option><option value="running">分析中</option><option value="failed">分析失败</option><option value="notrun">未运行</option><option value="unavailable">模型不可用</option></select></label><span data-result-count role="status"></span></div><p class="field-hint" data-inline-note></p>`:'';
 return `<section class="results-browser" data-result-record="${esc(record.id||'catalog')}">${toolbar}<div class="table-scroll" tabindex="0" aria-label="指标预测与实测对比表"><table class="results-table"><thead><tr><th>指标</th><th>模型预测</th><th>参考范围</th><th>实测值</th><th>预测 − 实测</th><th>详情</th></tr></thead><tbody>${rows(record,catalog,options.editable)}</tbody></table></div><p data-result-empty hidden class="results-empty">没有匹配的指标，请调整搜索或筛选。</p><details class="table-notes"><summary>如何理解结果</summary><p>参考范围以实际检验报告为准。差值只在单位一致时显示；采集日期按北京时间计算；日期差只说明间隔，不代表数据具有临床可比性。验证性能来自研究队列，不代表本次预测准确率。</p></details></section>`;
}
const tableStates=new Map();
function bindTable(container){
 const browser=container.querySelector('.results-browser');if(!browser)return;
 const search=browser.querySelector('[data-result-search]'),system=browser.querySelector('[data-result-system]'),filter=browser.querySelector('[data-result-filter]');if(!search)return;
 const key=browser.dataset.resultRecord;const old=tableStates.get(key);if(old){search.value=old.search;system.value=old.system;filter.value=old.filter;}
 const apply=()=>{let count=0;const all=browser.querySelectorAll('[data-result-row]');const q=search.value.trim().toLowerCase();all.forEach(row=>{const show=(!q||row.dataset.search.includes(q))&&(!system.value||row.dataset.system===system.value)&&(filter.value==='all'||row.dataset[filter.value]==='1'||row.dataset.state===filter.value);row.hidden=!show;if(show)count++;});browser.querySelector('[data-result-count]').textContent=`${count} / ${all.length} 项`;browser.querySelector('[data-result-empty]').hidden=count>0;tableStates.set(key,{search:search.value,system:system.value,filter:filter.value});};
 search.oninput=apply;system.onchange=apply;filter.onchange=apply;apply();
}
function snapshotDrafts(container,exclude){const id=container.querySelector('.results-browser')?.dataset.resultRecord;return id?D.snapshot(id,exclude,container):[];}
function restoreDrafts(container,drafts,recordId){D.restore(recordId,drafts,container);}
function researchPanel(container,record,catalog,version,headers,onChange){
 container.innerHTML=`<details class="consent-details" ${consentCurrent(record,version)?'':'open'}><summary>科研参与 · ${consentCurrent(record,version)?'已同意':'自愿选择'}</summary><form data-consent><label class="consent-field"><input name="research" type="checkbox" ${record.research_consent&&record.training_consent&&record.research_consent_version===version?'checked':''}>${record.subject_id&&record.subject_id!=='self'&&record.subject_id!=='unknown'?'我确认已获得测量对象或其监护人许可，同意本条记录用于本项目研究、评估及模型开发训练。':'我自愿同意将本条记录用于本项目科学研究、模型评估及模型开发与训练，不用于其他用途'}</label>${record.research_consent&&record.research_consent_version!==version?'<p>本条记录保留此前的科研授权。请阅读上述用途并主动勾选保存，以确认本次授权。</p>':''}<button class="button secondary" type="submit">保存授权选择</button></form><p data-status role="status"></p></details><details data-observation ${consentCurrent(record,version)?'':'hidden'}><summary>补充临床信息（选填）</summary></details>`;
 const clinicalFields={medical_history:'既往病史',medications:'当前用药',family_history:'家族病史',smoking:'吸烟情况',alcohol:'饮酒情况',notes:'其他补充'};
 const clinical=document.createElement('form');clinical.className='observation-form';clinical.dataset.clinicalForm='';
 clinical.innerHTML=Object.entries(clinicalFields).map(([key,label])=>`<label>${label}<textarea name="${key}" maxlength="2000" rows="3" placeholder="选填">${esc(record.clinical_information?.[key]||'')}</textarea></label>`).join('')+'<button class="button secondary" type="submit">保存临床信息</button>';
 container.querySelector('[data-observation]').append(clinical);
 const form=container.querySelector('[data-consent]'),status=container.querySelector('[data-status]');
 const clinicalStatus=document.createElement('p');clinicalStatus.setAttribute('role','status');clinicalStatus.dataset.clinicalStatus='';clinical.append(clinicalStatus);
 if(!record.deletion_requested_at&&record.subject_id!=='unknown'){D.watch(form,record.id,'consent',status);if(consentCurrent(record,version))D.watch(clinical,record.id,'clinical',clinicalStatus);}
 const r=form.elements.research;
 if(record.subject_id==='unknown'){form.querySelectorAll('input,button').forEach(e=>e.disabled=true);status.textContent='请先在记录详情确认测量对象。';}
 const run=async(target,key,fn,withdraw=false)=>{
  if(!D.begin(target)){D.feedback(target,'其他内容正在保存，请稍候。','pending');return;}
  container.querySelectorAll('button').forEach(b=>b.disabled=true);const fields=[...target.querySelectorAll('input,select,textarea')].map(el=>[el,el.disabled]);fields.forEach(([el])=>el.disabled=true);let persisted=false;
  try{const result=await fn();persisted=true;if(withdraw)D.discard();D.saved(target);if(container.contains(form)){const drafts=D.snapshot(record.id,target);await onChange(result);D.restore(record.id,drafts);D.showSaved(record.id,key);}}
  catch(e){if(container.contains(form))D.feedback(target,persisted?'已保存，但页面更新失败，请刷新核对。':`保存失败：${e.message}；填写内容已保留。`,'error');}
  finally{D.finish(target);if(container.contains(form)){fields.forEach(([el,disabled])=>el.disabled=disabled);container.querySelectorAll('button').forEach(b=>b.disabled=false);}}
 };
 clinical.onsubmit=e=>{e.preventDefault();const body=Object.fromEntries(new FormData(clinical));run(clinical,'clinical',()=>api(`/v1/captures/${record.id}/clinical-information`,{method:'PUT',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify(body)}));};
 form.onsubmit=e=>{e.preventDefault();const chosen=r.checked;if(record.research_consent&&!chosen&&!confirm('退出科研后，将移除本条记录的实测值和临床信息，包括未保存内容。是否继续？'))return;run(form,'consent',()=>api(`/v1/captures/${record.id}/research-consent`,{method:'PUT',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({research:chosen,training:chosen,version})}),!chosen);};
 if(record.deletion_requested_at)container.querySelectorAll('input,select,textarea,button').forEach(e=>e.disabled=true);
}
function download(record,catalog){
 const html=`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>MedicalFaceFound 个人记录</title><style>body{font:15px/1.7 system-ui;margin:32px;color:#142c48}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dde3ed;padding:8px;text-align:left}small{display:block;color:#566}details p{max-width:260px}h1{font-size:24px}@media print{summary{list-style:none}}</style><h1>MedicalFaceFound 个人预测记录</h1><p><strong>${esc(disclaimer)}</strong></p><p>测量对象：${esc(record.subject_label||'待确认')}<br>采集编号：${esc(record.id)}<br>采集时间：${esc(date(record.created_at))}</p>${table(record,catalog)}<p>科研参与：${record.research_consent?'同意':'未同意'}。本报告不包含登录或记录访问凭证。</p></html>`;
 const url=URL.createObjectURL(new Blob([html],{type:'text/html;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`MedicalFaceFound-${record.id}.html`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
const channel=typeof BroadcastChannel==='function'?new BroadcastChannel('mff-record-updates'):null;
window.MFF={hasUnsavedChanges:D.hasUnsavedChanges,confirmDiscardChanges:D.confirmDiscardChanges,snapshotRecordDrafts:D.snapshot,restoreRecordDrafts:D.restore,captureDay,observationTiming,snapshotDrafts,restoreDrafts,bindTable,bindInline,referenceRange,observations,api,requireCompatible,esc,date,number,unit,table,researchPanel,download,disclaimer,channel};
})();
