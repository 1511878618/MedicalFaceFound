const ids = ['cameraTab','uploadTab','cameraPane','uploadPane','cameraStage','camera','cameraPlaceholder','startCamera','capturePhoto','switchCamera','fileInput','dropZone','photoReview','photoPreview','photoMeta','retakePhoto','age','gender','heightCm','weightKg','storageConsent','modelSelect','inferenceForm','submitPhoto','formMessage','resultPanel','resultOutput','copyResult','photoStatus','photoStep','profileStep','submitStep','modelHint','resultSummary','resultTitle','checkPhoto','qualityResults','qualityNote','cropFigure','cropPreview','predictionCards','retryAnalysis','downloadReport','deleteRequest','serviceStatus','backgroundMode','researchConsent','researchControls'];
const el = Object.fromEntries(ids.map(id=>[id,document.getElementById(id)]));
let stream=null, facingMode='user', cameraRequest=0, originalFile=null, originalUrl=null;
let whiteFillMask=null;
let captureSource='upload', revision=0, quality=null, processing=false, checking=false, submitting=false;
let saved=null, report=null, requestId=null, accessToken=null, consentVersion='', catalog=[], ready=false;
let researchConsentVersion='',sessionUser=null,sessionKnown=false,sessionRevision=0,accountBusy=false;
let subjectOwner=null,subjectOptions=[],subjectRequested=new URLSearchParams(location.search).get('subject');

let failedModels=[], checkController=null, plannedModels=[], recordOwner=null, restored=false;
const RECOVERY_KEY='mff.current-measurement.v1';
function forgetRecord(){try{sessionStorage.removeItem(RECOVERY_KEY);}catch{}}
function persistRecord(){if(!saved)return;try{sessionStorage.setItem(RECOVERY_KEY,JSON.stringify({id:saved.capture_id,accessToken,owner:recordOwner,models:plannedModels,requestId}));}catch{message('本次记录已保存，但浏览器无法保留刷新恢复信息，请下载报告。');}}
function selectedModels(){return el.modelSelect.value==='all'?catalog.filter(m=>m.available).map(m=>m.id):el.modelSelect.value?[el.modelSelect.value]:[];}
function pendingModels(){return plannedModels.filter(id=>!report?.predictions.some(p=>p.model===id));}
function paintSubject(){const select=document.getElementById('captureSubject');const label=report?.subject_label||select.selectedOptions[0]?.textContent||'请选择对象';document.getElementById('currentSubjectLabel').textContent=label;document.getElementById('confirmProfileSummary').textContent=`${label} · ${el.age.value||'—'} 岁 · ${el.heightCm.value||'—'} cm · ${el.weightKg.value||'—'} kg`;}
function invalidateConfirmation(){document.getElementById('confirmProfile').checked=false;paintSubject();}
async function restoreRecord(){
 let item;try{item=JSON.parse(sessionStorage.getItem(RECOVERY_KEY)||'null');}catch{forgetRecord();return;}
 if(!item)return;if(!item.id||!item.accessToken||item.owner!==(sessionUser?.id||'guest')){forgetRecord();return;}
 saved={capture_id:item.id};accessToken=item.accessToken;requestId=item.requestId;recordOwner=item.owner;plannedModels=Array.isArray(item.models)?item.models.filter(id=>catalog.some(m=>m.id===id&&m.available)):[];
 try{await refreshReport();if(!report)return;restored=true;document.getElementById('captureSubject').value=report.subject_id;for(const [input,key] of [[el.age,'age'],[el.gender,'gender'],[el.heightCm,'height_cm'],[el.weightKg,'weight_kg']])input.value=report[key]??'';paintSubject();message('已恢复本次记录。未完成分析可手动继续，不会重新上传照片。');update();}catch(e){message('暂时无法恢复记录，请刷新重试。','error');update();}
}


const backgroundLabels={original:'原图',white:'纯白背景',clothes:'去衣物白底'};
const MAX_PHOTO_BYTES=10*1024*1024;
const labels={Age:'年龄估计',HDLC:'高密度脂蛋白胆固醇',Hb:'血红蛋白'};
const modelInfo=id=>catalog.find(model=>model.id===id)||{id,label:labels[id]||id,description:''};
const message=(text,kind='')=>{const status=document.getElementById('recordProgress');if(status){status.textContent=text;status.className=`form-message ${kind}`;}el.formMessage.textContent=text;el.formMessage.className=`form-message ${kind}`;};
const secret=()=>Array.from(crypto.getRandomValues(new Uint8Array(32)),v=>v.toString(16).padStart(2,'0')).join('');
const formatDate=value=>new Date(value).toLocaleString('zh-CN',{hour12:false});
const valueText=p=>`${Number(p.result.value).toFixed(p.model==='Age'?1:2)} ${p.model==='Age'?'岁':p.result.unit||''}`;
const escapeHtml=text=>String(text??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

const api=MFF.api;
function update() {
  const complete=[el.age,el.gender,el.heightCm,el.weightKg].every(input=>input.validity.valid);
  const busy=submitting||checking||processing||accountBusy;
  el.submitPhoto.disabled=busy||(!saved&&!ready)||(!saved&&(!originalFile||!quality?.passed||!complete||!el.storageConsent.checked||!document.getElementById('confirmProfile').checked))||Boolean(saved&&!el.modelSelect.value)||Boolean(report?.deletion_requested_at);
  el.checkPhoto.disabled=busy||!originalFile||Boolean(saved);
  el.retakePhoto.disabled=busy;
  el.fileInput.disabled=busy||Boolean(saved);
  el.cameraTab.disabled=el.uploadTab.disabled=busy||Boolean(saved);
  el.modelSelect.disabled=busy||!catalog.length;
  [el.age,el.gender,el.heightCm,el.weightKg,el.storageConsent].forEach(input=>input.disabled=submitting||Boolean(saved));
  el.retryAnalysis.disabled=el.downloadReport.disabled=busy;document.getElementById('continueAnalysis').disabled=busy;document.getElementById('confirmProfile').disabled=busy||Boolean(saved);paintSubject();
  el.deleteRequest.disabled=busy;
  el.backgroundMode.disabled=busy||Boolean(saved)||Boolean(originalFile);
  el.startCamera.disabled=processing;
  el.researchConsent.disabled=busy||Boolean(saved);
  document.getElementById('captureSubject').disabled=busy||Boolean(saved);
  el.photoStatus.textContent=processing?'正在处理照片':quality?.passed?'照片检查通过':originalFile?'待检查照片':'等待采集';
  el.photoStatus.classList.toggle('complete',Boolean(quality?.passed));
  if(!submitting) el.submitPhoto.querySelector('span').textContent=saved?(el.modelSelect.value?'分析所选指标':'资料已保存'):(el.modelSelect.value?'保存并开始分析':'保存采集资料');
  const step=!quality?.passed?0:!complete?1:2;
  [el.photoStep,el.profileStep,el.submitStep].forEach((node,i)=>{
    node.classList.toggle('complete',Boolean(saved)||i<step);
    node.classList.toggle('active',!saved&&i===step);
    if(!saved&&i===step) node.setAttribute('aria-current','step');else node.removeAttribute('aria-current');
  });
}
async function loadServiceState() {
  try{
    const state=MFF.requireCompatible(await api('/ready'));
    if(!state.subjects_enabled)throw new Error('服务正在更新成员档案功能，请稍后刷新。');
    await syncSession();
    ready=state.capture_ready&&state.quality_ready;
    consentVersion=state.consent_version;
    researchConsentVersion=state.research_consent_version;
    catalog=state.models||[];
    el.serviceStatus.className=`status ${ready?'online':'error'}`;
    el.serviceStatus.querySelector('span').textContent=ready?'服务已连接':'照片检查未就绪';
    el.modelSelect.replaceChildren(new Option('仅保存采集资料',''));
    const available=catalog.filter(m=>m.available);
    if(available.length>1) el.modelSelect.append(new Option(`全部可用指标（${available.length} 项）`,'all'));
    catalog.forEach(model=>{const option=new Option(`${model.label} · ${model.available?'可分析':'待接入'}`,model.id);option.disabled=!model.available;el.modelSelect.append(option);});
    el.modelHint.textContent=`共 ${catalog.length} 项指标，当前 ${available.length} 项可分析。待接入项目暂不提供预测。`;
    document.getElementById('catalogPreview').innerHTML=MFF.table({predictions:[],observations:[]},catalog);
    await restoreRecord();
    if(!ready) message('照片检查服务未就绪，请联系管理员。','error');
  }catch(error){ready=false;message(error.message,'error');el.serviceStatus.className='status error';el.serviceStatus.querySelector('span').textContent='服务连接失败';}
  update();
}
function stopCamera(){cameraRequest++;stream?.getTracks().forEach(track=>track.stop());stream=null;el.camera.srcObject=null;el.cameraStage.classList.remove('streaming');el.cameraPlaceholder.hidden=false;el.capturePhoto.disabled=true;el.switchCamera.disabled=true;}
function selectMode(mode){
  if(submitting||checking||processing||saved)return;
  const camera=mode==='camera';if(!camera)stopCamera();
  [el.cameraTab,el.uploadTab].forEach((button,index)=>{const active=camera===(index===0);button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;});
  el.cameraPane.classList.toggle('active',camera);el.uploadPane.classList.toggle('active',!camera);
  el.cameraPane.hidden=Boolean(originalFile)||!camera;el.uploadPane.hidden=Boolean(originalFile)||camera;
}
async function startCamera(){
  if(processing)return;
  if(!navigator.mediaDevices?.getUserMedia){message('当前浏览器无法启用相机，请使用本地上传。','error');selectMode('upload');return;}
  stopCamera();const id=++cameraRequest;
  try{
    const next=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:{ideal:facingMode},width:{ideal:1920},height:{ideal:1440}}});
    if(id!==cameraRequest){next.getTracks().forEach(track=>track.stop());return;}
    stream=next;el.camera.srcObject=stream;await el.camera.play();
    el.camera.classList.toggle('mirrored',facingMode==='user');el.cameraPlaceholder.hidden=true;el.cameraStage.classList.add('streaming');
    el.capturePhoto.disabled=false;el.switchCamera.disabled=false;
    message('请平视镜头，让额头和下巴完整入镜。');
  }catch(error){if(id!==cameraRequest)return;stopCamera();message(error.name==='NotAllowedError'?'请允许相机权限，或改用本地上传。':'相机启动失败，请检查设备。','error');}
}
const MP_BASE='/ui-assets/assets/mediapipe';
const segmenters=new Map();
const selfieClasses={background:0,faceSkin:3,clothes:4};
async function createSegmenter(mode,delegate){
  const vision=await import(`${MP_BASE}/vision_bundle.js`);
  const fileset=await vision.FilesetResolver.forVisionTasks(`${MP_BASE}/wasm`);
  const multiclass=mode==='clothes';
  const filename=multiclass?'selfie_multiclass_256x256.tflite':'selfie_segmenter.tflite';
  return vision.ImageSegmenter.createFromOptions(fileset,{
    baseOptions:{modelAssetPath:`${MP_BASE}/${filename}`,delegate},
    runningMode:'IMAGE',outputConfidenceMasks:!multiclass,outputCategoryMask:multiclass,
  });
}
function getSegmenter(mode){
  if(!segmenters.has(mode)){
    const pending=createSegmenter(mode,'GPU').catch(()=>createSegmenter(mode,'CPU'));
    segmenters.set(mode,pending);
    pending.catch(()=>segmenters.delete(mode));
  }
  return segmenters.get(mode);
}
async function whiteBackgroundPhoto(source,mode){
  const segmenter=await getSegmenter(mode);
  const multiclass=mode==='clothes';
  const result=segmenter.segment(source);
  try{
    const mask=multiclass?result.categoryMask:result.confidenceMasks?.[0];
    if(!mask)throw new Error('未获得分割结果');
    const width=source.width,height=source.height,mw=mask.width,mh=mask.height;
    const values=multiclass?mask.getAsUint8Array():mask.getAsFloat32Array();
    if(multiclass&&!values.includes(selfieClasses.faceSkin))throw new Error('未分割出面部皮肤');
    const maskCanvas=document.createElement('canvas');maskCanvas.width=mw;maskCanvas.height=mh;
    const maskContext=maskCanvas.getContext('2d');
    const maskImage=maskContext.createImageData(mw,mh);
    for(let i=0;i<values.length;i++){
      const offset=i*4,value=values[i];
      const keep=multiclass?Number(value!==selfieClasses.background&&value!==selfieClasses.clothes):Math.max(0,Math.min(1,value));
      maskImage.data[offset]=255;maskImage.data[offset+1]=255;maskImage.data[offset+2]=255;maskImage.data[offset+3]=keep*255;
    }
    maskContext.putImageData(maskImage,0,0);
    const foreground=document.createElement('canvas');foreground.width=width;foreground.height=height;
    const foregroundContext=foreground.getContext('2d');
    foregroundContext.drawImage(source,0,0,width,height);
    foregroundContext.globalCompositeOperation='destination-in';
    foregroundContext.imageSmoothingEnabled=true;
    foregroundContext.drawImage(maskCanvas,0,0,width,height);
    const output=document.createElement('canvas');output.width=width;output.height=height;
    const outputContext=output.getContext('2d');
    outputContext.fillStyle='#ffffff';outputContext.fillRect(0,0,width,height);
    outputContext.drawImage(foreground,0,0);
    const encodedMask=new Promise(resolve=>maskCanvas.toBlob(resolve,'image/png'));
    let blob=multiclass?await new Promise(resolve=>output.toBlob(resolve,'image/png')):null;
    if(!blob||blob.size>MAX_PHOTO_BYTES){
      blob=await new Promise(resolve=>output.toBlob(resolve,'image/jpeg',.92));
    }
    return {blob,fillMask:await encodedMask};
  }finally{result.close?.();}
}
async function takePhoto(){
  if(processing||!stream||!el.camera.videoWidth)return;
  const canvas=document.createElement('canvas');canvas.width=el.camera.videoWidth;canvas.height=el.camera.videoHeight;
  canvas.getContext('2d').drawImage(el.camera,0,0);
  stopCamera();
  processing=true;update();
  let blob;
  try{blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/jpeg',.94));}
  catch{return message('照片生成失败，请重新拍摄。','error');}
  finally{processing=false;update();}
  if(!blob)return message('照片生成失败，请重新拍摄。','error');
  await setPhoto(new File([blob],`original-${Date.now()}.jpg`,{type:'image/jpeg'}),'camera',canvas);
}
function resetRecord(){forgetRecord();plannedModels=[];recordOwner=null;restored=false;invalidateConfirmation();document.body.classList.remove('has-record','show-capture');document.getElementById('reviewCapture').textContent='查看照片 / 追加分析';saved=null;report=null;quality=null;requestId=crypto.randomUUID();accessToken=secret();failedModels=[];el.storageConsent.checked=false;el.researchConsent.checked=false;el.resultPanel.hidden=true;el.predictionCards.replaceChildren();el.researchControls.replaceChildren();el.resultSummary.replaceChildren();document.getElementById('measurementState').textContent='';document.getElementById('continueAnalysis').hidden=true;el.resultOutput.textContent='';el.cropFigure.hidden=true;el.qualityResults.replaceChildren();el.qualityNote.textContent='';}
async function setPhoto(file,source,frame=null){
  if(submitting||checking||processing||saved)return;
  if(!file)return;
  if(!['image/jpeg','image/png','image/webp'].includes(file.type))return message('仅支持 JPEG、PNG、WEBP 图片。','error');
  if(file.size>MAX_PHOTO_BYTES)return message('图片不能超过 10 MB。','error');
  let mode=el.backgroundMode.value,processingError='',fillMask=null;
  if(mode!=='original'){
    processing=true;update();
    message(`正在本机生成${backgroundLabels[mode]}照片…`);
    let bitmap;
    try{
      if(!frame)bitmap=await createImageBitmap(file);
      const result=await whiteBackgroundPhoto(frame||bitmap,mode);
      const {blob}=result;
      if(!blob||blob.size>MAX_PHOTO_BYTES||!result.fillMask||result.fillMask.size>MAX_PHOTO_BYTES){
        throw new Error('处理后的照片或掩码无法保存');
      }
      const extension=blob.type==='image/png'?'png':'jpg';
      file=new File([blob],`${mode}-${Date.now()}.${extension}`,{type:blob.type});
      fillMask=result.fillMask;
    }catch{
      processingError=`${backgroundLabels[mode]}处理失败，当前预览保留原图。`;
      mode='original';
      el.backgroundMode.value=mode;
    }finally{bitmap?.close();processing=false;}
  }
  revision++;checkController?.abort();resetRecord();originalFile=file;whiteFillMask=fillMask;captureSource=source;
  if(originalUrl)URL.revokeObjectURL(originalUrl);originalUrl=URL.createObjectURL(file);
  el.photoPreview.src=originalUrl;el.photoMeta.textContent=`${(file.size/1024/1024).toFixed(2)} MB · ${backgroundLabels[mode]}`;
  el.photoReview.hidden=false;el.cameraPane.hidden=el.uploadPane.hidden=true;
  if(processingError)message(processingError,'error');
  else message('请确认预览，再点击“检查照片”。这一步临时上传检查，不会保存。');
  update();
}
function clearPhoto(){
  if(submitting||checking||processing)return;
  revision++;checkController?.abort();resetRecord();originalFile=null;whiteFillMask=null;
  if(originalUrl)URL.revokeObjectURL(originalUrl);originalUrl=null;
  el.photoPreview.removeAttribute('src');el.cropPreview.removeAttribute('src');el.fileInput.value='';el.photoReview.hidden=true;el.photoMeta.textContent='—';
  selectMode(el.cameraTab.classList.contains('active')?'camera':'upload');message('拍摄或选择照片后，请先进行照片检查。');update();
}
function renderQuality(result){
  quality=result;
  el.qualityResults.replaceChildren(...result.checks.map(check=>{const li=document.createElement('li');li.className=check.passed?'passed':'needs-attention';const strong=document.createElement('strong');strong.textContent=`${check.passed?'✓':'○'} ${check.label}`;const span=document.createElement('span');span.textContent=check.message;li.append(strong,span);return li;}));
  el.qualityNote.textContent=result.note||'';
  el.cropFigure.hidden=!result.preview;
  if(result.preview)el.cropPreview.src=result.preview;
}
function photoFormData(){
  const data=new FormData();
  data.append('file',originalFile,originalFile.name);
  if(whiteFillMask)data.append('white_fill_mask',whiteFillMask,'white-fill-mask.png');
  return data;
}
async function checkPhoto(){
  if(!originalFile||submitting||checking||processing)return;
  const current=revision;checking=true;checkController=new AbortController();update();el.checkPhoto.textContent='正在检查…';
  try{
    const data=photoFormData();
    const result=await api('/v1/photos/quality',{method:'POST',body:data,signal:checkController.signal});
    if(current!==revision)return;renderQuality(result);
    message(result.passed?'照片检查通过。请确认照片和裁剪图，再完善资料。':'请按检查提示重新拍摄或选择照片。',result.passed?'success':'error');
  }catch(error){if(error.name!=='AbortError')message(error.message,'error');}
  finally{checking=false;el.checkPhoto.textContent='重新检查照片';update();}
}
function auth(){return {Authorization:`Bearer ${accessToken}`};}
async function refreshReport(){
  if(!saved)return;
  const id=saved.capture_id;
  try{
    const next=await api(`/v1/captures/${id}/report`,{headers:auth()});
    if(saved?.capture_id!==id)return;
    const changed=JSON.stringify(report)!==JSON.stringify(next);report=next;if(changed)renderReport();
  }catch(error){
    if(error.status===404&&saved?.capture_id===id&&!submitting){clearPhoto();message('这条记录已删除或访问凭证已失效，页面已清空。');return;}
    throw error;
  }
}
function renderReport(){
  const drafts=MFF.snapshotRecordDrafts(report.id);
  document.body.classList.add('has-record');paintAccount();paintSubject();
  const completed=report.predictions.filter(p=>p.status==='completed').length;
  const rows=[['测量对象',report.subject_label||'待确认'],['保存时间',formatDate(report.created_at)],['预测结果',`${completed} 项已完成`],['个人资料',`${report.age} 岁 · ${report.height_cm} cm · ${report.weight_kg} kg`]];
  el.resultSummary.replaceChildren(...rows.map(([key,value])=>{const row=document.createElement('div');row.className='result-row';const dt=document.createElement('dt');dt.textContent=key;const dd=document.createElement('dd');dd.textContent=value;row.append(dt,dd);return row;}));
  const onChange=async data=>{if(saved?.capture_id!==data.id)return;const old=el.predictionCards.querySelector('.table-scroll');const top=old?.scrollTop||0,left=old?.scrollLeft||0;report=data;renderReport();const current=el.predictionCards.querySelector('.table-scroll');if(current){current.scrollTop=top;current.scrollLeft=left;}message('已保存。','success');};
  el.predictionCards.innerHTML=MFF.table(report,catalog,{editable:true});
  MFF.bindInline(el.predictionCards,report,catalog,researchConsentVersion,auth(),onChange);
  MFF.researchPanel(el.researchControls,report,catalog,researchConsentVersion,auth(),onChange);MFF.restoreRecordDrafts(report.id,drafts);
  failedModels=report.predictions.filter(p=>p.status==='failed').map(p=>p.model);
  el.retryAnalysis.hidden=!failedModels.length||Boolean(report.deletion_requested_at);
  el.retryAnalysis.textContent='仅重试失败分析';document.getElementById('continueAnalysis').hidden=!pendingModels().length||Boolean(report.deletion_requested_at);
  const running=report.predictions.filter(p=>p.status==='running').length;document.getElementById('measurementState').textContent=running?`分析中：${running} 项` : failedModels.length?`已保存 · ${failedModels.length} 项失败` : pendingModels().length?`已保存 · ${pendingModels().length} 项待继续`:'已保存';
  el.resultOutput.textContent=JSON.stringify(report,null,2);el.resultPanel.hidden=false;
  el.resultTitle.textContent=failedModels.length?'记录已保存，部分分析待重试':'个人预测记录';
  el.deleteRequest.textContent='删除记录';
  document.getElementById('newMeasurement').disabled=submitting;
  document.getElementById('reviewCapture').disabled=submitting;
}
async function analyze(models){
 const id=saved.capture_id;
 for(const [index,model] of models.entries()){
  if(saved?.capture_id!==id) return;
  if(recordOwner!==(sessionUser?.id||'guest'))throw new Error('账号已切换，分析已停止。');
  // Reconcile before each mutation so running/completed work is never resubmitted.
  await refreshReport();
  const existing=report.predictions.find(p=>p.model===model);
  if(existing&&['completed','running'].includes(existing.status))continue;
  message(`正在分析 ${modelInfo(model).label}（${index+1}/${models.length}）…`);
  try{await api(`/v1/captures/${id}/predictions/${encodeURIComponent(model)}`,{method:'POST',headers:auth()});}
  catch(error){await refreshReport();const current=report.predictions.find(p=>p.model===model);if(current?.status==='running')message('分析仍在进行，页面会更新结果。');else if(current?.status!=='completed')message(error.message,'error');}
  await refreshReport();
 }
}
async function submit(event, retryOnly=false, continueOnly=false){
 event?.preventDefault();
 if(submitting||checking||processing||accountBusy)return;
 if(!saved&&(!quality?.passed||!originalFile||!el.storageConsent.checked||!document.getElementById('confirmProfile').checked||!el.inferenceForm.reportValidity()))return;
 submitting=true;update();el.submitPhoto.classList.add('loading');
 try{
  const expected=sessionUser?.id||'guest';const subject=document.getElementById('captureSubject').value;await syncSession();
  if(expected!==(sessionUser?.id||'guest')||(!saved&&subject!==document.getElementById('captureSubject').value))throw new Error('账号或测量对象已变化，请重新确认资料。');
  if(saved&&recordOwner!==expected){forgetRecord();throw new Error('账号已切换，请开始新测量。');}
  const models=retryOnly?failedModels.slice():continueOnly?pendingModels():selectedModels();
  if(!saved){
   const data=photoFormData();
   Object.entries({age:el.age.value,gender:el.gender.value,height_cm:el.heightCm.value,weight_kg:el.weightKg.value,capture_source:captureSource,subject_id:subject,consent:'true',consent_version:consentVersion,research_consent:String(el.researchConsent.checked),training_consent:String(el.researchConsent.checked),research_consent_version:researchConsentVersion,request_id:requestId,access_token:accessToken}).forEach(([key,value])=>data.append(key,value));
   message('正在保存照片与资料…');
   saved=await api('/v1/captures',{method:'POST',body:data});recordOwner=expected;
  }
  plannedModels=[...new Set([...plannedModels,...models])];persistRecord();
  await refreshReport();await analyze(models);await refreshReport();persistRecord();
  message(report.predictions.some(p=>p.status==='running')?'记录已保存，分析仍在进行。':failedModels.length?'记录已保存，可重试失败分析。':pendingModels().length?'记录已保存，可继续未完成分析。':'记录与分析结果已保存。','success');
  el.resultPanel.scrollIntoView({behavior:'smooth',block:'nearest'});
 }catch(error){if(error.quality)renderQuality(error.quality);message(error.message,'error');}
 finally{submitting=false;syncSession().catch(sessionError);document.getElementById('newMeasurement').disabled=false;document.getElementById('reviewCapture').disabled=false;el.submitPhoto.classList.remove('loading');update();}
}
function downloadReport(){if(report)MFF.download(report,catalog);}
el.cameraTab.addEventListener('click',()=>selectMode('camera'));el.uploadTab.addEventListener('click',()=>selectMode('upload'));
[el.cameraTab,el.uploadTab].forEach(tab=>tab.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const camera=event.key==='Home'||(event.key!=='End'&&tab===el.uploadTab);selectMode(camera?'camera':'upload');(camera?el.cameraTab:el.uploadTab).focus();}));
el.startCamera.addEventListener('click',startCamera);el.capturePhoto.addEventListener('click',takePhoto);
el.switchCamera.addEventListener('click',()=>{facingMode=facingMode==='user'?'environment':'user';startCamera();});
el.fileInput.addEventListener('change',()=>setPhoto(el.fileInput.files[0],'upload'));el.retakePhoto.addEventListener('click',()=>{if(MFF.confirmDiscardChanges())clearPhoto();});el.checkPhoto.addEventListener('click',checkPhoto);
el.backgroundMode.addEventListener('change',()=>{
  const descriptions={
    original:'照片将保留原始背景。',
    white:'拍摄或选图后，将人物以外的背景填白。',
    clothes:'拍摄或选图后，将识别到的衣物和背景填白。请在预览中确认脸部边缘。',
  };
  message(descriptions[el.backgroundMode.value]);
});
[el.age,el.gender,el.heightCm,el.weightKg,el.storageConsent,el.researchConsent].forEach(input=>input.addEventListener('input',()=>{if(!saved&&input!==el.storageConsent){requestId=crypto.randomUUID();}if([el.age,el.gender,el.heightCm,el.weightKg].includes(input))invalidateConfirmation();update();}));
document.getElementById('confirmProfile').addEventListener('change',update);document.getElementById('continueAnalysis').onclick=()=>submit(null,false,true);el.modelSelect.addEventListener('change',update);el.inferenceForm.addEventListener('submit',event=>submit(event));el.retryAnalysis.addEventListener('click',()=>submit(null,true));el.downloadReport.addEventListener('click',downloadReport);
el.copyResult.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(el.resultOutput.textContent);message('记录已复制。','success');}catch{message('复制失败，请展开完整数据后手动复制。','error');}});
el.deleteRequest.addEventListener('click',async()=>{
 if(!saved||submitting)return;
 if(!confirm('删除本条记录及关联预测和实测值？历史备份将按保留规则另行处理。'))return;
 const id=saved.capture_id;
 try{await api(`/v1/captures/${id}`,{method:'DELETE',headers:{...auth(),'Content-Type':'application/json'},body:JSON.stringify({confirmation:id})});MFF.channel?.postMessage({type:'deleted',id});clearPhoto();message('记录已删除，照片及结果已清空。','success');}
 catch(error){if(error.status===404){clearPhoto();message('记录已不存在，页面已清空。');}else message(error.message,'error');}
});
['dragenter','dragover'].forEach(name=>el.dropZone.addEventListener(name,event=>{event.preventDefault();el.dropZone.classList.add('dragging');}));
['dragleave','drop'].forEach(name=>el.dropZone.addEventListener(name,event=>{event.preventDefault();el.dropZone.classList.remove('dragging');}));
el.dropZone.addEventListener('drop',event=>setPhoto(event.dataTransfer.files[0],'upload'));
window.addEventListener('pagehide',()=>{stopCamera();checkController?.abort();if(originalUrl)URL.revokeObjectURL(originalUrl);for(const pending of segmenters.values())pending.then(segmenter=>segmenter.close?.()).catch(()=>{});segmenters.clear();});
document.querySelector('.workspace').append(el.resultPanel);
const catalogDetails=document.createElement('details');catalogDetails.className='catalog-panel';catalogDetails.innerHTML='<summary>查看全部指标与模型验证说明</summary><div id="catalogPreview"></div>';
document.querySelector('.workspace').after(catalogDetails);
MFF.channel?.addEventListener('message',event=>{if(event.data?.type==='session')syncSession().catch(sessionError);if(event.data?.type==='updated'&&saved?.capture_id===event.data.id&&!submitting)refreshReport().catch(e=>message(e.message,'error'));if(event.data?.type==='deleted'&&saved?.capture_id===event.data.id&&!submitting){clearPhoto();message('这条记录已删除，页面已同步清空。');}});

// Refresh on return to the page, and detect server-side deletions without discarding form edits.
async function verifyRecord(){if(!saved||submitting||document.hidden)return;try{await refreshReport();update();}catch(e){message('结果暂时无法更新，稍后将继续检查。','error');}}
window.addEventListener('focus',verifyRecord);setInterval(verifyRecord,5000);

loadServiceState();

document.getElementById('newMeasurement').onclick=()=>{if(submitting)return;if(!MFF.confirmDiscardChanges())return;clearPhoto();paintAccount();window.scrollTo({top:0,behavior:'smooth'});};
document.getElementById('reviewCapture').onclick=()=>{const shown=document.body.classList.toggle('show-capture');document.getElementById('reviewCapture').textContent=shown?'收起采集资料':'查看照片 / 追加分析';if(shown)document.querySelector('.workspace').scrollIntoView({behavior:'smooth'});};

function paintAccount(){
 document.getElementById('openAccount').hidden=!!sessionUser;
 document.getElementById('accountLogout').hidden=!sessionUser;
 document.getElementById('accountState').textContent=saved&&!report?.participant_id?'本次为访客记录，请下载保存；登录后新测量将加入个人历史。':sessionUser?`已登录 ${sessionUser.username} · 新测量自动保存到个人历史`:'访客模式 · 可直接测量，完成后请下载报告';
}
function sessionError(error){document.getElementById('accountNotice').textContent=error.message;document.getElementById('accountState').textContent='账号状态暂时无法确认，请刷新后重试。';}
async function syncSession(){
 const ticket=++sessionRevision;const {user}=await api('/v1/account/me');if(ticket!==sessionRevision)return;
 sessionUser=user;sessionKnown=true;
 if(saved&&recordOwner!==(user?.id||'guest')){if(submitting){forgetRecord();return;}clearPhoto();message('账号已切换，上一账号的记录已从页面清空。');}
 await syncSubjects(ticket);paintAccount();
}
document.getElementById('openAccount').onclick=()=>{document.getElementById('captureAccountPanel').hidden=false;document.getElementById('captureAccountForm').elements.username.focus();};
document.getElementById('closeAccount').onclick=()=>{document.getElementById('captureAccountPanel').hidden=true;};
document.getElementById('captureAccountForm').onsubmit=async event=>{
 event.preventDefault();if(submitting||accountBusy)return;if(!MFF.confirmDiscardChanges())return;const form=event.currentTarget;accountBusy=true;update();form.querySelectorAll('button').forEach(b=>b.disabled=true);
 try{MFF.requireCompatible(await api('/ready'));await api(`/v1/account/${event.submitter?.value||'login'}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:form.elements.username.value,password:form.elements.password.value})});form.elements.password.value='';await syncSession();document.getElementById('captureAccountPanel').hidden=true;document.getElementById('accountNotice').textContent='';MFF.channel?.postMessage({type:'session'});message('已登录，可继续本次测量。','success');}
 catch(error){document.getElementById('accountNotice').textContent=error.message;}
 finally{accountBusy=false;form.querySelectorAll('button').forEach(b=>b.disabled=false);update();}
};
document.getElementById('accountLogout').onclick=async()=>{
 if(submitting||accountBusy)return;if(!MFF.confirmDiscardChanges())return;accountBusy=true;update();try{await api('/v1/account/logout',{method:'POST'});await syncSession();MFF.channel?.postMessage({type:'session'});}catch(error){sessionError(error);}finally{accountBusy=false;update();}
};
window.addEventListener('focus',()=>syncSession().catch(sessionError));

async function syncSubjects(ticket){
 const owner=sessionUser?.id||'guest';if(subjectOwner===owner)return;const previousOwner=subjectOwner;
 const result=sessionUser?await api('/v1/me/subjects'):{items:[{id:'self',label:'本人'}]};if(ticket!==sessionRevision)return;
 subjectOptions=result.items.filter(s=>s.id!=='unknown');subjectOwner=owner;
 const select=document.getElementById('captureSubject');select.replaceChildren(...subjectOptions.map(s=>new Option(s.label,s.id)));
 if(subjectRequested&&subjectOptions.some(s=>s.id===subjectRequested)){select.value=subjectRequested;subjectRequested=null;}else select.value='self';
 document.getElementById('subjectHint').textContent=sessionUser?'不同对象的测量分别保存，不会混入本人趋势。':'登录后可创建成员档案，为其他人记录测量。';
 if(subjectRequested){select.value='';document.getElementById('subjectHint').textContent='请登录对应账号后选择测量对象。';}
 if(previousOwner!==null&&previousOwner!==owner){select.value='';[el.age,el.gender,el.heightCm,el.weightKg].forEach(input=>input.value='');el.researchConsent.checked=false;message('账号已变化，请重新选择测量对象并填写资料。');}select.required=true;invalidateConfirmation();updateSubjectConsent();update();
}
document.getElementById('captureSubject').onchange=()=>{if(saved)return;invalidateConfirmation();requestId=crypto.randomUUID();el.researchConsent.checked=false;[el.age,el.gender,el.heightCm,el.weightKg].forEach(input=>input.value='');updateSubjectConsent();message('请填写当前测量对象的基本资料。');update();};

function updateSubjectConsent(){const other=document.getElementById('captureSubject').value!=='self';el.researchConsent.closest('label').querySelector('span').textContent=other?'我确认已获得测量对象或其监护人许可，同意本条记录用于本项目研究、评估及模型开发训练（可选）':'我自愿同意将本条记录用于本项目科学研究、模型评估及模型开发与训练（可选）';}
