/* Page-memory drafts only. Never persist clinical or observation inputs to storage. */
(()=>{
 const entries=new Set(),states=new WeakMap();
 const controls=f=>[...f.querySelectorAll('input,select,textarea')].filter(e=>e.name);
 const values=f=>controls(f).map(e=>[e.name,e.value,(e.type==='checkbox'||e.type==='radio')?e.checked:null]);
 const signature=v=>JSON.stringify(v);
 function connected(s){return s.form.isConnected;}
 function prune(){for(const s of entries)if(!connected(s)&&!s.pending)entries.delete(s);}
 function dirty(s){return signature(values(s.form))!==signature(s.baseline);}
 function feedback(form,text,tone=''){const s=states.get(form);if(s?.status){s.status.textContent=text;s.status.dataset.tone=tone;}}
 function sync(form){const s=states.get(form);if(!s)return;const changed=dirty(s);form.dataset.dirty=String(changed);if(!s.pending)feedback(form,changed?'有未保存修改':'',changed?'unsaved':'');}
 function watch(form,recordId,key,status){prune();const previous=states.get(form);if(previous)entries.delete(previous);const s={form,recordId:String(recordId),key,status,baseline:values(form),pending:false};states.set(form,s);entries.add(s);form.dataset.draftKey=key;form.dataset.draftRecord=recordId;form.addEventListener('input',()=>sync(form));form.addEventListener('change',()=>sync(form));sync(form);return s;}
 function busy(recordId){return [...entries].some(s=>s.recordId===String(recordId)&&s.pending);}
 function begin(form){const s=states.get(form);if(!s||busy(s.recordId))return false;s.pending=true;feedback(form,'保存中…','pending');return true;}
 function saved(form){const s=states.get(form);if(s){s.baseline=values(form);form.dataset.dirty='false';}}
 function finish(form){const s=states.get(form);if(s)s.pending=false;prune();}
 function hasUnsavedChanges(){prune();return [...entries].some(s=>s.pending||(connected(s)&&dirty(s)));}
 function setValues(form,list){const fields=controls(form);list.forEach(([name,value,checked],i)=>{const el=fields[i]?.name===name?fields[i]:fields.find(e=>e.name===name);if(el){el.value=value;if(checked!==null)el.checked=checked;}});}
 function discard(){for(const s of entries)if(connected(s)&&!s.pending&&dirty(s)){setValues(s.form,s.baseline);sync(s.form);}}
 function confirmDiscardChanges(){
  prune();if([...entries].some(s=>s.pending)){window.alert('正在保存，请稍候再切换。');return false;}
  if(!hasUnsavedChanges())return true;
  if(!window.confirm('有未保存的修改，确定放弃并离开吗？'))return false;
  discard();return true;
 }
 function snapshot(recordId,exclude,container){prune();return [...entries].filter(s=>connected(s)&&s.recordId===String(recordId)&&s.form!==exclude&&(!container||container.contains(s.form))).map(s=>({key:s.key,values:values(s.form),baseline:s.baseline.map(v=>v.slice()),dirty:dirty(s),open:!!s.form.closest('details')?.open}));}
 function restore(recordId,drafts,container){for(const s of entries){if(!connected(s)||s.recordId!==String(recordId)||(container&&!container.contains(s.form)))continue;const draft=drafts.find(d=>d.key===s.key);if(!draft)continue;if(draft.dirty){setValues(s.form,draft.values);s.baseline=draft.baseline.map(v=>v.slice());sync(s.form);const input=s.form.querySelector('[name=measured_on]');if(input&&typeof Event!=='undefined')input.dispatchEvent(new Event('input'));}const details=s.form.closest('details');if(details)details.open=draft.open;}}
 function showSaved(recordId,key,text='已保存'){for(const s of entries)if(connected(s)&&s.recordId===String(recordId)&&s.key===key){feedback(s.form,text,'success');const details=s.form.closest('details');if(details)details.open=true;}}
 if(typeof window.addEventListener==='function')window.addEventListener('beforeunload',e=>{if(hasUnsavedChanges()){e.preventDefault();e.returnValue='';}});
 window.MFFDrafts={watch,sync,begin,saved,finish,busy,feedback,snapshot,restore,showSaved,hasUnsavedChanges,confirmDiscardChanges,discard};
})();
