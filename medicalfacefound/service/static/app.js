const ids = ['cameraTab','uploadTab','cameraPane','uploadPane','cameraStage','camera','cameraPlaceholder','startCamera','capturePhoto','switchCamera','fileInput','dropZone','photoReview','photoPreview','photoMeta','retakePhoto','age','gender','heightCm','weightKg','storageConsent','modelSelect','inferenceForm','submitPhoto','formMessage','resultPanel','resultOutput','copyResult','photoStatus','photoStep','profileStep','submitStep','modelHint','resultSummary','resultTitle','checkPhoto','qualityResults','qualityNote','cropFigure','cropPreview','predictionCards','retryAnalysis','downloadReport','deleteRequest','serviceStatus','backgroundMode','gradcamOption'];
const el = Object.fromEntries(ids.map(id=>[id,document.getElementById(id)]));
let stream=null, facingMode='user', cameraRequest=0, originalFile=null, originalUrl=null;
let whiteFillMask=null;
let captureSource='upload', revision=0, quality=null, processing=false, checking=false, submitting=false;
let saved=null, report=null, requestId=null, accessToken=null, consentVersion='', catalog=[], ready=false;
const blockHeatmapLabel='Grad-CAM · 最后一个 block 输出';
let ageHeatmapLabel=blockHeatmapLabel;
let failedModels=[], checkController=null;
const failedExplanations=new Set();
const backgroundLabels={original:'原图',white:'纯白背景',clothes:'去衣物白底'};
const MAX_PHOTO_BYTES=10*1024*1024;
const labels={Age:'年龄估计',HDLC:'高密度脂蛋白胆固醇',Hb:'血红蛋白'};
const modelInfo=id=>catalog.find(model=>model.id===id)||{id,label:labels[id]||id,description:''};
const message=(text,kind='')=>{el.formMessage.textContent=text;el.formMessage.className=`form-message ${kind}`;};
const secret=()=>Array.from(crypto.getRandomValues(new Uint8Array(32)),v=>v.toString(16).padStart(2,'0')).join('');
const formatDate=value=>new Date(value).toLocaleString('zh-CN',{hour12:false});
const valueText=p=>`${Number(p.result.value).toFixed(p.model==='Age'?1:2)} ${p.model==='Age'?'岁':p.result.unit||''}`;
const escapeHtml=text=>String(text??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

async function api(path,options={}) {
  const response=await fetch(path,options);
  const body=await response.json();
  if(!response.ok){
    const detail=body.detail;
    const error=new Error(typeof detail==='string'?detail:Array.isArray(detail)?detail.map(d=>d.msg).join('；'):detail?.message||'请求失败，请重试');
    error.quality=detail?.quality;
    throw error;
  }
  return body;
}
function update() {
  const complete=[el.age,el.gender,el.heightCm,el.weightKg].every(input=>input.validity.valid);
  const busy=submitting||checking||processing;
  el.submitPhoto.disabled=busy||!ready||!originalFile||!quality?.passed||!complete||!el.storageConsent.checked||Boolean(saved&&!el.modelSelect.value)||Boolean(report?.deletion_requested_at);
  el.checkPhoto.disabled=busy||!originalFile||Boolean(saved);
  el.retakePhoto.disabled=busy;
  el.fileInput.disabled=busy||Boolean(saved);
  el.cameraTab.disabled=el.uploadTab.disabled=busy||Boolean(saved);
  el.modelSelect.disabled=busy||!catalog.length;
  [el.age,el.gender,el.heightCm,el.weightKg,el.storageConsent].forEach(input=>input.disabled=submitting||Boolean(saved));
  el.retryAnalysis.disabled=el.downloadReport.disabled=busy;
  el.deleteRequest.disabled=busy||Boolean(report?.deletion_requested_at);
  el.backgroundMode.disabled=busy||Boolean(saved)||Boolean(originalFile);
  el.startCamera.disabled=processing;
  el.gradcamOption.disabled=submitting||checking||Boolean(saved);
  const model=el.modelSelect.value;
  let heatmapLabel=blockHeatmapLabel;
  if(model==='Age')heatmapLabel=ageHeatmapLabel;
  if(model==='all'&&ageHeatmapLabel!==blockHeatmapLabel){
    heatmapLabel=`年龄：${ageHeatmapLabel}；其他指标：${blockHeatmapLabel}`;
  }
  document.getElementById('gradcamHint').textContent=heatmapLabel;
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
    const state=await api('/ready');
    ready=state.capture_ready&&state.quality_ready;
    consentVersion=state.consent_version;
    ageHeatmapLabel=state.age_heatmap_label||ageHeatmapLabel;
    catalog=(state.missing_dependencies?.length?[]:state.models)||[];
    el.serviceStatus.className=`status ${ready?'online':'error'}`;
    el.serviceStatus.querySelector('span').textContent=ready?'服务已连接':'照片检查未就绪';
    el.modelSelect.replaceChildren(new Option('仅保存采集资料',''));
    if(catalog.length>1) el.modelSelect.append(new Option(`分析全部 ${catalog.length} 项指标`,'all'));
    catalog.forEach(model=>el.modelSelect.append(new Option(`${model.label} · ${model.id}`,model.id)));
    el.modelHint.textContent=catalog.length?`当前开放 ${catalog.length} 项研究指标，可按需选择。`:'暂未开放模型分析，照片检查通过后仍可保存资料。';
    if(!ready) message('照片检查服务未就绪，请联系管理员。','error');
  }catch(error){message(error.message,'error');el.serviceStatus.className='status error';el.serviceStatus.querySelector('span').textContent='服务连接失败';}
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
    message('请平视镜头，让额头、下巴完整入镜。拍照后可以查看完整照片和自动裁剪区域。');
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
function resetRecord(){saved=null;report=null;quality=null;requestId=crypto.randomUUID();accessToken=secret();failedModels=[];failedExplanations.clear();el.storageConsent.checked=false;el.resultPanel.hidden=true;el.cropFigure.hidden=true;el.qualityResults.replaceChildren();el.qualityNote.textContent='';}
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
  el.photoPreview.removeAttribute('src');el.cropPreview.removeAttribute('src');el.fileInput.value='';el.photoReview.hidden=true;
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
let explanationUrls=[];
const camVariants=[
  ['block','has_explanation',blockHeatmapLabel],
  ['hirescam','has_hirescam_explanation','HiResCAM · 第四阶段 norm1'],
  ['layercam','has_layercam_explanation','LayerCAM · 第三阶段 norm1'],
];
function clearExplanationUrls(){explanationUrls.forEach(URL.revokeObjectURL);explanationUrls=[];}
async function loadExplanations(captureId){
  for(const image of el.predictionCards.querySelectorAll('img[data-explanation]')){
    const {explanation,variant}=image.dataset;
    try{
      if(!image.isConnected)return;
      const response=await fetch(`/v1/captures/${captureId}/explanations/${explanation}?variant=${variant}`,{headers:auth()});
      if(!response.ok)continue;
      const blob=await response.blob();
      if(!image.isConnected)return;
      const url=URL.createObjectURL(blob);
      explanationUrls.push(url);image.src=url;
    }catch{}
  }
}
async function refreshReport(){report=await api(`/v1/captures/${saved.capture_id}/report`,{headers:auth()});renderReport();}
function renderReport(){
  clearExplanationUrls();
  const rows=[['采集编号',report.id],['保存时间',formatDate(report.created_at)],['原图尺寸',`${report.image_width} × ${report.image_height}`],['资料用途说明',report.consent_version||'旧记录']];
  el.resultSummary.replaceChildren(...rows.map(([key,value])=>{const row=document.createElement('div');row.className='result-row';const dt=document.createElement('dt');dt.textContent=key;const dd=document.createElement('dd');dd.textContent=value;row.append(dt,dd);return row;}));
  el.predictionCards.replaceChildren(...report.predictions.map(prediction=>{
    const card=document.createElement('article');card.className=`prediction-card ${prediction.status}`;
    const title=document.createElement('h3');title.textContent=modelInfo(prediction.model).label;
    const value=document.createElement('strong');value.textContent=prediction.status==='completed'?valueText(prediction):prediction.status==='running'?'分析中':'分析失败';
    const note=document.createElement('p');note.textContent=prediction.error||modelInfo(prediction.model).description;
    const meta=document.createElement('small');meta.textContent=`${formatDate(prediction.updated_at)} · 版本 ${prediction.model_version.slice(0,12)}`;
    card.append(title,value,note,meta);
    const plots=document.createElement('div');plots.className='cam-comparison';
    const [variant,flag,label]=camVariants.find(([name])=>name===prediction.explanation_method)||camVariants[0];
    if(prediction[flag]){
      const figure=document.createElement('figure');figure.className='explanation';
      const image=document.createElement('img');image.alt=`${modelInfo(prediction.model).label} · ${label}`;image.dataset.explanation=prediction.id;image.dataset.variant=variant;image.loading='lazy';
      const caption=document.createElement('figcaption');caption.textContent=label;
      figure.append(image,caption);plots.append(figure);
    }
    if(plots.childElementCount)card.append(plots);
    if(prediction.status==='completed'&&failedExplanations.has(prediction.model)){
      const warning=document.createElement('p');
      warning.textContent='预测结果已保存，热图生成失败，可以重试。';
      card.append(warning);
    }
    return card;
  }));
  failedModels=report.predictions.filter(p=>p.status==='failed').map(p=>p.model);
  el.retryAnalysis.hidden=!(failedModels.length||failedExplanations.size)||Boolean(report.deletion_requested_at);
  el.retryAnalysis.textContent=failedModels.length?'重试未完成的分析':'重试生成热图';
  el.resultOutput.textContent=JSON.stringify(report,null,2);el.resultPanel.hidden=false;
  el.resultTitle.textContent=failedModels.length?'资料已保存，部分分析待重试':'研究记录已保存';
  el.deleteRequest.textContent=report.deletion_requested_at?'删除申请已提交':'申请删除资料';
  if(report.deletion_requested_at)el.deleteRequest.disabled=true;
  loadExplanations(report.id);
}
async function analyze(models){
  for(const [index,model] of models.entries()){
    const explain=el.gradcamOption.checked||failedExplanations.has(model);
    message(`资料已保存，正在分析 ${modelInfo(model).label}（${index+1}/${models.length}）${explain?'，并生成热力图…':'…'}`);
    el.submitPhoto.querySelector('span').textContent=`正在分析 ${index+1}/${models.length}`;
    try{
      const result=await api(`/v1/captures/${saved.capture_id}/predictions/${encodeURIComponent(model)}${explain?'?explain=true':''}`,{method:'POST',headers:auth()});
      if(result.explanation_status==='failed')failedExplanations.add(model);
      if(result.explanation_status==='completed')failedExplanations.delete(model);
    }
    catch(error){message(error.message,'error');}
    await refreshReport();
  }
}
async function submit(event, retryOnly=false){
  event?.preventDefault();
  if(submitting||checking||processing||!quality?.passed||!originalFile||!el.inferenceForm.reportValidity())return;
  submitting=true;update();el.submitPhoto.classList.add('loading');
  try{
    if(!saved){
      const data=photoFormData();
      Object.entries({age:el.age.value,gender:el.gender.value,height_cm:el.heightCm.value,weight_kg:el.weightKg.value,capture_source:captureSource,consent:'true',consent_version:consentVersion,request_id:requestId,access_token:accessToken}).forEach(([key,value])=>data.append(key,value));
      message('正在保存已确认的原图、人脸图和基本资料…');
      saved=await api('/v1/captures',{method:'POST',body:data});
    }
    const models=retryOnly?[...new Set([...failedModels,...failedExplanations])]:el.modelSelect.value==='all'?catalog.map(m=>m.id):el.modelSelect.value?[el.modelSelect.value]:[];
    await analyze(models);await refreshReport();
    if(failedModels.length)message('资料已保存，未完成的分析可以重试。','error');
    else if(failedExplanations.size)message('预测结果已保存，部分热图生成失败，可以重试。','error');
    else message('资料与已完成的分析结果均已保存。','success');
    el.resultPanel.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'nearest'});
  }catch(error){if(error.quality)renderQuality(error.quality);message(error.message,'error');}
  finally{submitting=false;el.submitPhoto.classList.remove('loading');update();}
}
function downloadReport(){
  if(!report)return;
  const rows=report.predictions.map(p=>`<tr><td>${escapeHtml(modelInfo(p.model).label)}</td><td>${escapeHtml(p.status==='completed'?valueText(p):p.error||'未完成')}</td><td>${escapeHtml(p.model_version)}</td><td>${escapeHtml(formatDate(p.updated_at))}</td></tr>`).join('');
  const html=`<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>MedicalFaceFound 研究报告</title><style>body{font:16px/1.8 system-ui;max-width:900px;margin:48px auto;padding:24px;color:#142c48}h1{color:#2563eb}td,th{padding:12px;border-bottom:1px solid #dbe4f0;text-align:left;overflow-wrap:anywhere}table{width:100%;table-layout:fixed}small{color:#52647c}@media print{body{margin:0}}</style><h1>MedicalFaceFound 研究记录</h1><p>采集编号：${escapeHtml(report.id)}<br>保存时间：${escapeHtml(formatDate(report.created_at))}</p><p>年龄：${escapeHtml(report.age)} 岁 · 身高：${escapeHtml(report.height_cm)} cm · 体重：${escapeHtml(report.weight_kg)} kg</p><table><thead><tr><th>研究指标</th><th>模型估计</th><th>模型版本</th><th>分析时间</th></tr></thead><tbody>${rows||'<tr><td colspan="4">本次仅保存采集资料，未进行模型分析。</td></tr>'}</tbody></table><p>研究性模型估计，不用于诊断或治疗，不能替代实际检验。</p><small>资料用途说明版本：${escapeHtml(report.consent_version)}。如需申请删除，请凭采集编号联系 xutingfeng@big.ac.cn；身份核实后处理。可通过浏览器打印功能另存为 PDF。</small></html>`;
  const url=URL.createObjectURL(new Blob([html],{type:'text/html;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`MedicalFaceFound-${report.id}.html`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
el.cameraTab.addEventListener('click',()=>selectMode('camera'));el.uploadTab.addEventListener('click',()=>selectMode('upload'));
[el.cameraTab,el.uploadTab].forEach(tab=>tab.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const camera=event.key==='Home'||(event.key!=='End'&&tab===el.uploadTab);selectMode(camera?'camera':'upload');(camera?el.cameraTab:el.uploadTab).focus();}));
el.startCamera.addEventListener('click',startCamera);el.capturePhoto.addEventListener('click',takePhoto);
el.switchCamera.addEventListener('click',()=>{facingMode=facingMode==='user'?'environment':'user';startCamera();});
el.fileInput.addEventListener('change',()=>setPhoto(el.fileInput.files[0],'upload'));el.retakePhoto.addEventListener('click',clearPhoto);el.checkPhoto.addEventListener('click',checkPhoto);
el.backgroundMode.addEventListener('change',()=>{
  const descriptions={
    original:'照片将保留原始背景。',
    white:'拍摄或选图后，将人物以外的背景填白。',
    clothes:'拍摄或选图后，将识别到的衣物和背景填白。请在预览中确认脸部边缘。',
  };
  message(descriptions[el.backgroundMode.value]);
});
[el.age,el.gender,el.heightCm,el.weightKg,el.storageConsent].forEach(input=>input.addEventListener('input',()=>{if(!saved&&input!==el.storageConsent){requestId=crypto.randomUUID();}update();}));
el.modelSelect.addEventListener('change',update);el.inferenceForm.addEventListener('submit',event=>submit(event));el.retryAnalysis.addEventListener('click',()=>submit(null,true));el.downloadReport.addEventListener('click',downloadReport);
el.copyResult.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(el.resultOutput.textContent);message('研究记录已复制。','success');}catch{message('复制失败，请展开完整数据后手动复制。','error');}});
el.deleteRequest.addEventListener('click',async()=>{if(!saved||submitting||report?.deletion_requested_at)return;if(!confirm('提交删除申请后将停止该记录的新分析，管理员核实后处理。是否继续？'))return;try{await api(`/v1/captures/${saved.capture_id}/deletion-request`,{method:'POST',headers:auth()});await refreshReport();update();message('删除申请已提交，请保留采集编号。','success');}catch(error){message(error.message,'error');}});
['dragenter','dragover'].forEach(name=>el.dropZone.addEventListener(name,event=>{event.preventDefault();el.dropZone.classList.add('dragging');}));
['dragleave','drop'].forEach(name=>el.dropZone.addEventListener(name,event=>{event.preventDefault();el.dropZone.classList.remove('dragging');}));
el.dropZone.addEventListener('drop',event=>setPhoto(event.dataTransfer.files[0],'upload'));
window.addEventListener('pagehide',()=>{stopCamera();checkController?.abort();if(originalUrl)URL.revokeObjectURL(originalUrl);for(const pending of segmenters.values())pending.then(segmenter=>segmenter.close?.()).catch(()=>{});segmenters.clear();});
loadServiceState();
