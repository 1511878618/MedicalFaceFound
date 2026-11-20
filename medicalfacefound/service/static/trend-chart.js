(()=>{
const {esc,number,unit}=MFF;
function collect(records,id,days){
 const cutoff=days?Date.now()-days*86400000:-Infinity,points=[],excluded=[];
 const add=(value,u,time,series,version,timing)=>{const t=Date.parse(time);if(value==null||value===''||!Number.isFinite(Number(value))||!Number.isFinite(t)||t<cutoff)return;const normalized=unit(u,'');if(!normalized){excluded.push(`${series}：缺少单位`);return;}points.push({value:Number(value),unit:normalized,t,time,series,version,timing});};
 for(const r of records){const p=r.predictions?.filter(p=>p.model===id&&p.status==='completed').at(-1),o=MFF.observations(r).find(o=>o.model===id);if(p?.result){if(['WBC','PCT'].includes(id))excluded.push('预测单位尚未确认，未绘制预测点');else add(p.result.value,p.result.unit,r.created_at,'预测',p.model_version||'未提供版本');}if(o)add(o.value,o.unit,['capture_profile','calculated_bmi'].includes(o.source)?r.created_at:o.measured_on,'实测','',MFF.observationTiming(r,o));}
 return {points:points.sort((a,b)=>a.t-b.t),excluded:[...new Set(excluded)]};
}
function ageGap(records,days){
 const cutoff=days?Date.now()-days*86400000:-Infinity;
 const r=records.filter(r=>Date.parse(r.created_at)>=cutoff&&r.predictions?.some(p=>p.model==='Age'&&p.status==='completed')).sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at))[0];
 if(!r)return null;
 const p=r.predictions.filter(p=>p.model==='Age'&&p.status==='completed').at(-1),value=p?.result?.value;
 if(r.age==null||r.age===''||value==null||value===''||!Number.isFinite(Number(r.age))||!Number.isFinite(Number(value))||unit(p.result.unit,'')!=='岁')return null;
 return {actual:Number(r.age),predicted:Number(value),gap:Math.round((Number(value)-Number(r.age))*10)/10,time:r.created_at};
}
function timestamp(time){return /^\d{4}-\d{2}-\d{2}$/.test(time)?`${time}（未记录时刻）`:new Date(time).toLocaleString('zh-CN',{year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false});}
function gapCard(records,days){
 const a=ageGap(records,days);if(!a)return '<div class="age-gap-card"><h3>Age Gap · 预测年龄差</h3><p>同次测量具备预测年龄和填写年龄后，即可查看年龄差。</p></div>';
 const direction=a.gap<0?'低':a.gap>0?'高':'';
 return `<section class="age-gap-card" aria-label="Age Gap 预测年龄差"><div><span class="eyebrow">AGE GAP · 年龄对照</span><h3>预测年龄差</h3><p>${direction?`比填写年龄${direction} ${number(Math.abs(a.gap))} 岁`:'与填写年龄一致'}</p><small>最近一次年龄预测 · ${esc(timestamp(a.time))}</small></div><div class="age-gap-value">${a.gap>0?'+':''}${number(a.gap)}<span>岁</span></div><dl><div><dt>预测年龄</dt><dd>${number(a.predicted)} 岁</dd></div><div><dt>填写年龄</dt><dd>${number(a.actual)} 岁</dd></div></dl><p class="age-gap-note">Age Gap = 预测年龄 − 同次填写年龄，仅表示本模型的年龄差。</p></section>`;
}
function render(container,records,id,days){
 const {points,excluded}=collect(records,id,days);container.replaceChildren();
 if(!points.length){container.innerHTML=`<p class="empty-state">所选时间内没有可绘制的数据。</p>${excluded.map(t=>`<p class="field-hint">${esc(t)}</p>`).join('')}`;return;}
 const units=[...new Set(points.map(p=>p.unit))];
 container.innerHTML=`${id==='Age'?gapCard(records,days):''}<div class="chart-legend"><span class="prediction-dot">模型预测</span><span class="observation-dot">实测 / 采集资料</span><small>点击或聚焦数据点查看详情</small></div>${units.length>1?'<p class="field-hint">单位不同的结果分别绘制，不进行换算。</p>':''}`;
 for(const u of units){const data=points.filter(p=>p.unit===u),section=document.createElement('section');section.className='trend-plot';const W=Math.max(280,Math.min(760,container.clientWidth||760)),H=260,L=48,R=16,T=25,B=42;let xmin=Math.min(...data.map(p=>p.t)),xmax=Math.max(...data.map(p=>p.t)),lo=Math.min(...data.map(p=>p.value)),hi=Math.max(...data.map(p=>p.value));const single=xmin===xmax;const pad=(hi-lo)*.15||Math.max(Math.abs(lo)*.05,1);lo-=pad;hi+=pad;const x=t=>single?(L+W-R)/2:L+(t-xmin)/(xmax-xmin)*(W-L-R),y=v=>T+(hi-v)/(hi-lo)*(H-T-B);let svg='';for(let i=0;i<5;i++){let v=lo+(hi-lo)*i/4;svg+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="#e8eef6"/><text x="${L-10}" y="${y(v)+4}" text-anchor="end">${esc(number(v))}</text>`;}
 for(const series of ['预测','实测']){const stream=data.filter(p=>p.series===series);let segment=[];const flush=()=>{if(segment.length>1)svg+=`<polyline points="${segment.map(p=>`${x(p.t)},${y(p.value)}`).join(' ')}" fill="none" stroke="${series==='预测'?'#3478df':'#159b9d'}" stroke-width="2"/>`;segment=[];};for(const p of stream){if(segment.length&&segment.at(-1).version!==p.version)flush();segment.push(p);}flush();}
 for(let i=0;i<data.length;i++){const p=data[i],label=`${p.series} · ${timestamp(p.time)} · ${number(p.value)} ${u}${p.version?' · '+p.version:''}${p.timing?' · '+p.timing:''}`;svg+=`<circle data-point="${i}" tabindex="0" role="button" aria-label="${esc(label)}" cx="${x(p.t)}" cy="${y(p.value)}" r="5" fill="${p.series==='预测'?'#3478df':'#159b9d'}" stroke="white" stroke-width="2"><title>${esc(label)}</title></circle>`;}
 const short=xmax-xmin<=48*3600000,hasTime=data.some(p=>!/^\d{4}-\d{2}-\d{2}$/.test(p.time));
 for(const t of single?[xmin]:W<480?[xmin,xmax]:[xmin,(xmin+xmax)/2,xmax]){const label=new Date(t).toLocaleString('zh-CN',{month:'numeric',day:'numeric',...(short&&hasTime?{hour:'2-digit',minute:'2-digit',hour12:false}:{})});svg+=`<text class="time-tick" x="${x(t)}" y="${H-13}" text-anchor="${single?'middle':t===xmin?'start':t===xmax?'end':'middle'}">${esc(label)}</text>`;}
 section.innerHTML=`<h4>${esc(u)}</h4><svg viewBox="0 0 ${W} ${H}" role="group" aria-label="${esc(id)} 趋势 ${esc(u)}">${svg}</svg><p class="chart-tooltip" role="status">${single?'已记录本次测量，后续测量将连成趋势。':'选择数据点查看时间、数值和模型版本。'}</p>`;
 const show=e=>{const p=data[Number(e.currentTarget.dataset.point)];section.querySelector('.chart-tooltip').textContent=`${p.series} · ${timestamp(p.time)} · ${number(p.value)} ${u}${p.version?' · 模型 '+p.version:''}${p.timing?' · '+p.timing:''}`;};section.querySelectorAll('[data-point]').forEach(point=>{point.addEventListener('focus',show);point.addEventListener('click',show);point.addEventListener('mouseenter',show);point.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show(e);}});});container.append(section);
 }
 if(excluded.length){const note=document.createElement('p');note.className='field-hint';note.textContent=excluded.join('；');container.append(note);}
}
window.MFFTrend={render,collect,ageGap};
})();
