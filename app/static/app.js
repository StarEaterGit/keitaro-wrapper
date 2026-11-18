'use strict';
const $=id=>document.getElementById(id);
let conf=null,current=null,draft=null;
let createBusy=false,createBlocked=false;
function notice(message,good=false){const e=$('notice');e.textContent=message;e.className='notice'+(good?' success':'');}
function clearNotice(){$('notice').className='notice hidden';}
async function api(path,options={}){
  const r=await fetch(path,{headers:{'Content-Type':'application/json'},...options});
  let body;try{body=await r.json();}catch{body={detail:'Сервер вернул не-JSON ответ'};}
  if(!r.ok){const error=new Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail||body));error.detail=body.detail;error.status=r.status;throw error;}
  return body;
}
function post(path,data){return api(path,{method:'POST',body:JSON.stringify(data)});}
function setOptions(id,items,empty='Выберите из списка'){
  $(id).replaceChildren(new Option(empty,''));
  items.forEach(x=>$(id).add(new Option(`${x.name} · ID ${x.id}`,String(x.id))));
}
const formFields = {
  country:['country','country-error'],
  offer_id:['offer-query','offer-error'],
  domain_id:['domain_id','domain-error'],
  group_id:['group_id','group-error'],
  traffic_source_id:['traffic_source_id','source-error'],
};
function clearFieldError(field){
 const elements=formFields[field]; if(!elements)return;
 const input=$(elements[0]);input.classList.remove('input-invalid');input.removeAttribute('aria-invalid');
 if(field==='offer_id')$('offer-combobox').classList.remove('input-invalid');
 const help=$(elements[1]);help.textContent='';help.classList.add('hidden');
}
function fieldError(field,message){
 const elements=formFields[field];if(!elements)return;
 const input=$(elements[0]);input.classList.add('input-invalid');input.setAttribute('aria-invalid','true');
 if(field==='offer_id')$('offer-combobox').classList.add('input-invalid');
 const help=$(elements[1]);help.textContent=message;help.classList.remove('hidden');
}
function resetPreview(){Object.keys(formFields).forEach(clearFieldError);}
function validateCampaignFields(){
 let good=syncCampaignName(true),first=good?null:'name-suffix';
 const country=$('country'),countryCode=country.value.trim().toUpperCase();
 country.value=countryCode;
 if(!/^[A-Z]{2}$/.test(countryCode)){
   fieldError('country','Введите двухбуквенный код страны, например DE.');good=false;first??='country';
 }
 const id=Number($('offer_id').value);
 if(!Number.isSafeInteger(id)||id<=0){
   fieldError('offer_id','Выберите оффер или введите его числовой ID.');good=false;first??='offer-query';
 }
 for(const [field,label] of [['domain_id','домен'],['group_id','группу кампаний'],['traffic_source_id','источник трафика']]){
   if(!(chosenId(field)??conf?.campaign_defaults?.[field])){
     fieldError(field,`Выберите ${label}.`);good=false;first??=field;
     $('advanced-settings').open=true;
   }
 }
 if(first)$(first).focus();
 return good;
}
function showPreflightError(error){
 const details=Array.isArray(error.detail)?error.detail:[];
 let matched=false;
 for(const issue of details){
   const field=String(issue.loc?.at(-1)||'');
   if(field==='name'){
     $('campaign-name-composer').classList.add('invalid');$('name-error').textContent='Проверьте название кампании.';$('name-error').classList.remove('hidden');matched=true;
   }else if(formFields[field]){fieldError(field,issue.msg||'Проверьте значение.');matched=true;}
 }
 if(!matched){
   const text=String(error.message||'');
   const field=/оффер/i.test(text)?'offer_id':/домен/i.test(text)?'domain_id':/групп/i.test(text)?'group_id':/источник/i.test(text)?'traffic_source_id':/GEO|стран/i.test(text)?'country':null;
   if(field){fieldError(field,text);matched=true;}
 }
 if(matched&&(['domain_id','group_id','traffic_source_id'].some(f=>$(formFields[f][0]).classList.contains('input-invalid'))))$('advanced-settings').open=true;
 notice(matched?'Проверьте выделенные поля.':`Не удалось проверить данные: ${error.message}`);
}

// The prefix is protected: users type only the meaningful name suffix.
// Keep the backend payload unchanged (full name), so ownership checks remain intact.
function syncCampaignName(showError=false){
  const input=$('name-suffix');
  const prefix=conf?.campaign_prefix||'test_yoursurname_';
  let suffix=input.value;
  // Pasting an entire name from README/Keitaro should not duplicate our prefix.
  if(suffix.startsWith(prefix)){
    suffix=suffix.slice(prefix.length);input.value=suffix;
  }
  const full=prefix+suffix.trim();
  $('name').value=full;
  $('name-prefix').textContent=prefix;
  $('full-name').textContent=full;
  const error=$('name-error');
  let message='';
  if(!suffix.trim())message='Введите название после префикса.';
  else if(!/^[A-Za-z0-9_]+$/.test(suffix.trim()))message='Используйте латинские буквы, цифры и подчёркивание.';
  else if(full.length>120)message='Полное название не должно превышать 120 символов.';
  else if(prefix==='test_yoursurname_')message='Укажите свою фамилию в CAMPAIGN_PREFIX в файле .env.';
  input.setCustomValidity(message);
  error.textContent=message;
  error.classList.toggle('hidden',!message||!showError);
  $('campaign-name-composer').classList.toggle('invalid',Boolean(message&&showError));
  return !message;
}
$('name-suffix').addEventListener('input',()=>{resetPreview();syncCampaignName(true);});
$('name-suffix').addEventListener('blur',()=>syncCampaignName(true));
function chosenId(id){const raw=$(id).value;return raw?Number(raw):null;}
function formData(){return {name:$('name').value.trim(),country:$('country').value.trim().toUpperCase(),offer_id:Number($('offer_id').value),domain_id:chosenId('domain_id'),group_id:chosenId('group_id'),traffic_source_id:chosenId('traffic_source_id')};}
let referenceData={domains:[],groups:[],traffic_sources:[]};
function updateSettingsStatus(){
 if(!conf)return;
 const specs=[['domain_id','Домен','domains'],['group_id','Группа','groups'],['traffic_source_id','Источник','traffic_sources']];
 const missing=[];const display=[];
 for(const [key,label,collection] of specs){
  const id=chosenId(key)??conf.campaign_defaults?.[key]??null;
  if(id===null){missing.push(label.toLowerCase());display.push(`${label}: не настроен`);continue;}
  const found=(referenceData[collection]||[]).find(x=>x.id===id);
  display.push(`${label}: ${found?found.name:'ID '+id}`);
 }
 const e=$('settings-status');
 e.textContent=missing.length?`Не выбраны: ${missing.join(', ')}. Откройте дополнительные параметры и выберите значения.`:display.join('  ·  ');
 e.className='settings-status'+(missing.length?' incomplete':'');
 if(missing.length)$('advanced-settings').open=true;
}

// Single searchable offer field: choose by name or type an exact ID.
// Input is always untrusted; backend preflight rechecks the chosen offer and all other IDs.
let availableOffers=[],offerChoices=[],offerActive=-1,offerSearchTimer=null,offerRequest=0;
const validOfferId=text=>/^\d+$/.test(text)&&Number.isSafeInteger(Number(text))&&Number(text)>0;
function offerStatus(message){$('offer-check').textContent=message;}
function hideOfferMenu(){
  $('offer-options').classList.add('hidden');
  $('offer-query').setAttribute('aria-expanded','false');
  $('offer-toggle').setAttribute('aria-expanded','false');
  $('offer-query').removeAttribute('aria-activedescendant');
  offerActive=-1;
}
function activateOffer(index){
  const nodes=[...$('offer-options').querySelectorAll('[role="option"]')];
  if(!nodes.length)return;
  offerActive=(index+nodes.length)%nodes.length;
  nodes.forEach((el,i)=>el.setAttribute('aria-selected',String(i===offerActive)));
  $('offer-query').setAttribute('aria-activedescendant',nodes[offerActive].id);
  nodes[offerActive].scrollIntoView({block:'nearest'});
}
function displayOfferMenu(items,term){
  const menu=$('offer-options');menu.replaceChildren();
  const values=items.slice(0,30).map(x=>({id:x.id,name:x.name,direct:false}));
  // Even if the offers list is truncated, an exact numeric ID can be checked separately.
  if(validOfferId(term)&&!values.some(x=>String(x.id)===term)){
    values.unshift({id:Number(term),name:`Проверить точный ID ${term} через Keitaro`,direct:true});
  }
  offerChoices=values;offerActive=-1;
  if(!values.length){
    menu.append(element('div',term?'Совпадений в доступном списке нет. Попробуйте точный ID.':'В списке пока нет офферов. Введите точный ID.','offer-empty'));
  }else{
    values.forEach((item,i)=>{
      const node=element('button',item.direct?item.name:`${item.name} · ID ${item.id}`,'offer-option');
      node.type='button';node.id=`offer-option-${i}`;node.setAttribute('role','option');node.setAttribute('aria-selected','false');
      node.addEventListener('click',()=>chooseOffer(item));
      menu.append(node);
    });
  }
  menu.classList.remove('hidden');
  $('offer-query').setAttribute('aria-expanded','true');
  $('offer-toggle').setAttribute('aria-expanded','true');
}
function chooseOffer(item){
  if(item.direct){
    const expected=$('offer-query').value.trim();
    hideOfferMenu();
    offerStatus(`Проверяем ID ${item.id} через Keitaro…`);
    api(`/api/offers/${item.id}/lookup`).then(record=>{
      if($('offer-query').value.trim()!==expected)return;
      applySelectedOffer(record);
      offerStatus(`Проверено: ${record.name} · ID ${record.id}.`);
    }).catch(err=>{
      if($('offer-query').value.trim()!==expected)return;
      $('offer_id').value='';
      offerStatus(`Не удалось проверить ID ${item.id}: ${err.message}`);
    });
    return;
  }
  applySelectedOffer(item);
  offerStatus(`Выбран: ${item.name} · ID ${item.id}. Будет проверен перед созданием.`);
}
function applySelectedOffer(item){
  $('offer_id').value=String(item.id);
  $('offer-query').value=`${item.name} · ID ${item.id}`;
  clearTimeout(offerSearchTimer);offerRequest++;
  hideOfferMenu();resetPreview();
}
function localOfferMatches(term){
  const lower=term.toLowerCase();
  return availableOffers.filter(x=>!lower||String(x.id).includes(lower)||String(x.name).toLowerCase().includes(lower)).slice(0,30);
}
function updateOfferSearch(){
  const term=$('offer-query').value.trim();
  displayOfferMenu(localOfferMatches(term),term);
  clearTimeout(offerSearchTimer);
  const request=++offerRequest;
  if(term.length<2)return;
  offerSearchTimer=setTimeout(async()=>{
    try{
      const results=await api(`/api/offers/search?q=${encodeURIComponent(term)}`);
      if(request!==offerRequest||$('offer-query').value.trim()!==term)return;
      // Keep an exact-ID suggestion even if API returns only one visible offer.
      displayOfferMenu(results,term);
    }catch{
      // Fall back to locally cached results; the precise ID is still checked before creation.
    }
  },320);
}
async function loadLookups(){
 try{
  const x=await api('/api/lookups');
  referenceData={domains:x.domains,groups:x.groups,traffic_sources:x.traffic_sources};
  for(const [key,list] of [['domain_id','domains'],['group_id','groups'],['traffic_source_id','traffic_sources']]){
    const previous=$(key).value;
    const configured=conf?.campaign_defaults?.[key];
    const found=x[list].find(v=>v.id===configured);
    const empty=configured?`По умолчанию: ${found?found.name:'ID '+configured}`:'Не задано — выберите значение';
    setOptions(key,x[list],empty);
    if(previous && x[list].some(v=>String(v.id)===previous))$(key).value=previous;
  }
  updateSettingsStatus();
  availableOffers=x.offers;
  const returned=Number.isInteger(x.offers_returned_by_api)?x.offers_returned_by_api:x.offers.length;
  $('offer-count').textContent=returned===1?'1 оффер доступен в списке. Можно указать другой ID.':'';
  notice(`Справочники загружены. Из Keitaro API получено ${returned} офферов.`,true);
  resetPreview();
 }catch(e){notice(`Справочники: ${e.message}`);}
}
$('offer-query').addEventListener('focus',()=>{
  const selected=Boolean($('offer_id').value)&&!/^\d+$/.test($('offer-query').value.trim());
  if(selected)$('offer-query').select();
  displayOfferMenu(localOfferMatches(selected?'':$('offer-query').value.trim()), selected?'':$('offer-query').value.trim());
});
$('offer-query').addEventListener('input',()=>{
  const raw=$('offer-query').value.trim();
  $('offer_id').value=validOfferId(raw)?raw:'';
  offerStatus(validOfferId(raw)?`ID ${raw} будет проверен перед созданием (или выберите «Проверить точный ID»).`:'Введите ID полностью или выберите оффер из подсказок.');
  resetPreview();updateOfferSearch();
});
$('offer-toggle').addEventListener('click',()=>{
  if(!$('offer-options').classList.contains('hidden')){hideOfferMenu();return;}
  $('offer-query').focus();
});
$('offer-query').addEventListener('keydown',event=>{
  if(event.key==='Escape'){hideOfferMenu();return;}
  if(event.key==='ArrowDown'||event.key==='ArrowUp'){
    event.preventDefault();
    if($('offer-options').classList.contains('hidden')){
      const term=$('offer-query').value.trim();displayOfferMenu(localOfferMatches(term),term);
    }
    activateOffer(event.key==='ArrowDown'?offerActive+1:offerActive-1);
  }
  if(event.key==='Enter'&&!$('offer-options').classList.contains('hidden')&&offerChoices.length){
    event.preventDefault();chooseOffer(offerChoices[offerActive<0?0:offerActive]);
  }
});
document.addEventListener('pointerdown',event=>{
  if(!$('offer-combobox').contains(event.target))hideOfferMenu();
});
async function loadOwned(){try{let rows=await api('/api/campaigns');setOptions('owned-list',rows.map(x=>({id:x.id,name:`${x.name} [${x.status}]`})),'Мои кампании');}catch(e){notice(e.message);}}
function tab(name){if(name!=='edit'&&demoMode)exitDemo();document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('hidden',x.id!==name));document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x.dataset.tab===name));$('page-title').textContent={create:'Создание кампании',edit:'Редактор потоков'}[name];clearNotice();return name==='edit'?loadOwned():Promise.resolve();}
document.querySelectorAll('.nav').forEach(n=>n.addEventListener('click',()=>tab(n.dataset.tab)));
$('campaign-form').addEventListener('input',resetPreview);
$('campaign-form').addEventListener('change',()=>{resetPreview();updateSettingsStatus();});
$('refresh-lookups').onclick=loadLookups;
// A single click performs read-only preflight, displays errors next to fields,
// then explicitly asks for confirmation before the first remote POST.
$('campaign-form').onsubmit=async event=>{
 event.preventDefault();
 if(createBusy||createBlocked)return;
 resetPreview();
 if(!validateCampaignFields())return;
 if(!conf?.write_enabled){notice('Создание кампаний выключено в настройках. Установите KEITARO_WRITE_ENABLED=true.');return;}
 const data=formData();
 createBusy=true;$('create-button').disabled=true;
 $('create-button').textContent='Проверяем данные…';
 try{
   const plan=await post('/api/preview',data);
   // Do not create an outdated campaign if the user changed any field during preflight.
   if(JSON.stringify(formData())!==JSON.stringify(data)){
     notice('Параметры изменились во время проверки. Нажмите «Создать кампанию» ещё раз.');return;
   }
   const selected=plan.selected_configuration||{};
   const answer=confirm(
     `Создать новую кампанию «${data.name}» в Keitaro?\n\n`+
     `${data.country} → Google\nОстальные → оффер #${data.offer_id}\n`+
     `Домен #${selected.domain_id}, группа #${selected.group_id}, источник #${selected.traffic_source_id}\n\n`+
     'Будут созданы новые объекты Keitaro. Существующие кампании не изменяются.'
   );
   if(!answer)return;
   // Lock duplicate writes: a timeout/error may still mean partially created objects.
   $('create-button').textContent='Создаём кампанию…';
   try{
     const result=await post('/api/campaigns',data);
     notice(`Кампания #${result.id} создана. Открываем редактор…`,true);
     await tab('edit');$('owned-list').value=String(result.id);$('lookup-id').value='';
     const opened=await showCampaign(result.id);
     if(opened)notice(`Кампания #${result.id} создана. Редактор открыт.`,true);
   }catch(error){
     createBlocked=true;
     notice(`Создание не подтверждено: ${error.message}\nНе повторяйте запрос: кампания могла создаться частично. Проверьте её состояние в Keitaro.`);
   }
 }catch(error){showPreflightError(error);}
 finally{
   createBusy=false;
   if(!createBlocked){$('create-button').disabled=false;$('create-button').textContent='Создать кампанию';}
   else{$('create-button').disabled=true;$('create-button').textContent='Проверьте состояние в Keitaro';}
 }
};
$('refresh-owned').onclick=loadOwned;
$('open-campaign').onclick=async()=>{const id=Number($('lookup-id').value||$('owned-list').value);if(!Number.isSafeInteger(id)||id<=0){notice('Выберите кампанию или введите её ID.');return;}await showCampaign(id);};
$('reload-detail').onclick=()=>{if(current)showCampaign(current.id);};
function element(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e;}
async function showCampaign(id){
 if(demoMode)exitDemo();
 try{
  current=await api(`/api/campaigns/${id}`);draft=null;
  $('campaign-detail').classList.remove('hidden');$('campaign-heading').textContent=`${current.name} · ID ${current.id}`;
  const editable=Boolean(current.can_edit);
  $('edit-status').textContent=editable?'Собственная кампания · черновик доступен':'Только чтение';$('edit-status').className='pill '+(editable?'good':'warning');
  $('fetch-streams').disabled=!current.can_edit;$('draft-editor').classList.add('hidden');
  const list=$('stream-summary');list.replaceChildren();
  for(const stream of current.streams){
    const item=element('div',undefined,'stream');const d=element('div');d.append(element('strong',`Поток #${stream.id}: ${stream.name}`));
    const count=stream.offers.length;d.append(element('small',count?`${count} офферов`:'Без офферов'));
    item.append(d);list.append(item);
  }
  if(current.can_edit){return await loadEditor(id);}else notice(current.notice||'Можно просмотреть, но нельзя менять чужую кампанию.');
  return true;
 }catch(e){current=null;draft=null;$('campaign-detail').classList.add('hidden');notice(`Открытие: ${e.message}`);return false;}
}
async function loadEditor(id){try{const result=await api(`/api/campaigns/${id}/editor`);showDraft(result);notice('Локальный черновик загружен.',true);return true;}catch(e){$('draft-editor').classList.add('hidden');notice(`Черновик: ${e.message}`);return false;}}
function showDraft(newDraft){
 draft=newDraft;$('draft-editor').classList.remove('hidden');
 const banner=$('draft-banner');
 banner.textContent=demoMode?`${newDraft.dirty?'Черновик':'Демо'} · Опубликовано: ${demoRemote.length} · В черновике: ${newDraft.rows.filter(x=>!x.removed).length}`:(newDraft.dirty?'Неопубликованные изменения':'Синхронизировано с Keitaro');
 banner.className='draft-banner '+(newDraft.dirty?'unsaved':'saved');
 const editing=Boolean(current&&current.can_edit);
 const canPublish=demoMode?editing:editing&&Boolean(conf.write_enabled);
 $('push-editor').disabled=!canPublish||!newDraft.dirty;
 $('push-editor').textContent=demoMode?'Симулировать Push':'↑ Push to KT';
 $('push-editor').title=demoMode?'Только браузер: без запросов в Keitaro':(canPublish?'Опубликовать изменения только в своём потоке':'Удалённая запись отключена в конфигурации');
 $('cancel-editor').disabled=!editing||!newDraft.dirty;$('add-offer').disabled=!editing;$('editor-offer-query').disabled=!editing;$('editor-offer-toggle').disabled=!editing;
 $('demo-alert').classList.toggle('hidden',!demoMode);
 const table=element('table');const head=element('thead');const hr=element('tr');
 ['Оффер','Доля','Действие'].forEach(h=>hr.append(element('th',h)));head.append(hr);table.append(head);
 const body=element('tbody');
 for(const item of newDraft.rows){
   const tr=element('tr');if(item.removed)tr.className='archived';
   const label=demoMode?(DEMO_CATALOG.find(x=>x.id===item.offer_id)?.name+' · '):'';
   const name=element('td',`${label}ID ${item.offer_id}${item.removed?' · removed':''}${item.state==='disabled'?' · disabled':''}`);
   const share=element('td');const val=element('strong',`${item.share}%`);share.append(val);
   if(!item.removed&&item.state==='active'){
     const pin=element('button',item.pinned?'📌 Закреплено':'📍 Закрепить','pin-button');pin.disabled=!editing;pin.title='Закрепить текущую долю, чтобы при следующих изменениях она не пересчитывалась';pin.onclick=()=>stage('pin',item.offer_id,{pinned:!item.pinned});share.append(pin);
   }
   const prior=Number($('offer-table').querySelector(`tr[data-offer-id="${item.offer_id}"]`)?.dataset.share??0);
   const meter=element('div',undefined,'share-meter');const fill=element('div',undefined,'share-meter-fill');
   fill.style.width=`${prior}%`;meter.append(fill);share.append(meter);
   requestAnimationFrame(()=>requestAnimationFrame(()=>{fill.style.width=`${item.share}%`;}));
   tr.dataset.offerId=String(item.offer_id);tr.dataset.share=String(item.share);
   tr.append(name,share);
   const act=element('td');const button=element('button',item.removed?'Bring back':'Remove','btn '+(item.removed?'secondary':'danger'));
   button.disabled=!editing;button.onclick=()=>stage(item.removed?'restore':'remove',item.offer_id);act.append(button);tr.append(act);body.append(tr);
 }
 table.append(body);$('offer-table').replaceChildren(element('div',undefined,'table-wrap'));
 $('offer-table').firstChild.append(table);
}
$('fetch-streams').onclick=async()=>{
 if(demoMode){demoFetch();return;}
 if(!current||!current.can_edit)return;
 if(draft&&draft.dirty){notice('Есть черновик. Нажмите Push или Cancel перед повторным Fetch.');return;}
 try{showDraft(await post(`/api/campaigns/${current.id}/editor/fetch`,{}));notice('Fetch завершён. Из Keitaro только прочитаны данные; удалённые офферы сохранены в архиве.',true);}catch(e){notice(`Fetch: ${e.message}`);}
};
async function stage(action,offer_id,extra={}){
 if(demoMode){demoStage(action,offer_id,extra);return;}
 if(!draft||!current||!current.can_edit)return;
 try{let result=await post(`/api/campaigns/${current.id}/editor/${action}`,{version:draft.version,offer_id,...extra});showDraft(result);if(action==='add'){$('editor-offer-query').value='';editorOfferSelectedId=null;editorHideMenu();}notice('Черновик изменён. В Keitaro ничего не отправлено. Для публикации нажмите Push to KT.',true);}catch(e){notice(`${action}: ${e.message}`);}
}
// One searchable input in the editor: browse available offers OR enter a precise ID.
// Real entries are always validated server-side before they can be staged.
let editorOfferSelectedId=null,editorOfferChoices=[],editorOfferActive=-1,editorSearchTimer=null,editorSearchVersion=0;
function editorOfferCatalog(){return demoMode?DEMO_CATALOG:availableOffers;}
function editorHideMenu(){
 $('editor-offer-options').classList.add('hidden');
 $('editor-offer-query').setAttribute('aria-expanded','false');
 editorOfferActive=-1;
}
function editorShowMenu(items,term){
 const list=$('editor-offer-options');list.replaceChildren();
 const choices=items.slice(0,30).map(x=>({id:x.id,name:x.name,direct:false}));
 if(validOfferId(term)&&!choices.some(x=>String(x.id)===term)){
  choices.unshift({id:Number(term),name:demoMode?'Такого ID нет в учебном каталоге':`Проверить ID ${term} через Keitaro`,direct:true});
 }
 editorOfferChoices=choices;editorOfferActive=-1;
 if(!choices.length){
  list.append(element('div',term?'Совпадений нет. Для поиска вне списка введите точный ID.':'Введите ID или название оффера.','offer-empty'));
 }else{
  choices.forEach((item,i)=>{
   const b=element('button',item.direct?item.name:`${item.name} · ID ${item.id}`,'offer-option');
   b.type='button';b.id=`editor-offer-option-${i}`;b.setAttribute('role','option');b.setAttribute('aria-selected','false');
   b.addEventListener('click',()=>editorChoose(item));list.append(b);
  });
 }
 list.classList.remove('hidden');$('editor-offer-query').setAttribute('aria-expanded','true');
}
function editorMatches(term){const low=term.toLowerCase();return editorOfferCatalog().filter(x=>!low||String(x.id).includes(low)||x.name.toLowerCase().includes(low)).slice(0,30);}
async function editorChoose(item){
 editorHideMenu();
 if(item.direct){
  if(demoMode){$('editor-offer-help').textContent='Учебный каталог содержит только ID 910001–910004.';return;}
  const term=$('editor-offer-query').value.trim();
  $('editor-offer-help').textContent=`Проверяем ID ${item.id} через Keitaro...`;
  try{
   const found=await api(`/api/offers/${item.id}/lookup`);
   if($('editor-offer-query').value.trim()!==term)return;
   editorSetChosen(found);
  }catch(e){if($('editor-offer-query').value.trim()===term)$('editor-offer-help').textContent=`ID ${item.id}: ${e.message}`;}
  return;
 }
 editorSetChosen(item);
}
function editorSetChosen(item){
 editorOfferSelectedId=item.id;
 $('editor-offer-query').value=`${item.name} · ID ${item.id}`;
 $('editor-offer-help').textContent=demoMode?'Учебный оффер выбран — только для демо.':`Выбран оффер #${item.id}; при добавлении Keitaro проверит доступность.`;
 clearTimeout(editorSearchTimer);editorSearchVersion++;editorHideMenu();
}
function editorQueryChanged(){
 const term=$('editor-offer-query').value.trim();
 editorOfferSelectedId=validOfferId(term)?Number(term):null;
 $('editor-offer-help').textContent=validOfferId(term)?(demoMode?'Выберите ID из учебного каталога.':'Точный ID проверится в Keitaro при добавлении.'):'Выберите результат поиска либо введите ID полностью.';
 editorShowMenu(editorMatches(term),term);
 clearTimeout(editorSearchTimer);const version=++editorSearchVersion;
 if(demoMode||!term)return;
 editorSearchTimer=setTimeout(async()=>{
   try{
     const found=await api(`/api/offers/search?q=${encodeURIComponent(term)}`);
     if(version!==editorSearchVersion||$('editor-offer-query').value.trim()!==term||demoMode)return;
     const merged=new Map([...editorMatches(term),...found].map(x=>[x.id,x]));
     editorShowMenu([...merged.values()],term);
   }catch{ /* Exact numeric ID remains usable even if the listing is restricted. */ }
 },300);
}
$('editor-offer-query').addEventListener('focus',()=>{
 if(editorOfferSelectedId && !validOfferId($('editor-offer-query').value.trim()))$('editor-offer-query').select();
 editorShowMenu(editorMatches(''),'');
});
$('editor-offer-query').addEventListener('input',editorQueryChanged);
$('editor-offer-query').addEventListener('keydown',e=>{
 if(e.key==='Escape'){editorHideMenu();return;}
 if(e.key==='ArrowDown'||e.key==='ArrowUp'){
  e.preventDefault();if($('editor-offer-options').classList.contains('hidden'))editorShowMenu(editorMatches($('editor-offer-query').value.trim()),$('editor-offer-query').value.trim());
  const nodes=[...$('editor-offer-options').querySelectorAll('[role="option"]')];if(!nodes.length)return;
  editorOfferActive=(editorOfferActive+(e.key==='ArrowDown'?1:-1)+nodes.length)%nodes.length;
  nodes.forEach((n,i)=>n.setAttribute('aria-selected',String(i===editorOfferActive)));
  nodes[editorOfferActive].scrollIntoView({block:'nearest'});
 }
 if(e.key==='Enter'&&editorOfferChoices.length&&!$('editor-offer-options').classList.contains('hidden')){
  e.preventDefault();editorChoose(editorOfferChoices[editorOfferActive<0?0:editorOfferActive]);
 }
});
$('editor-offer-toggle').onclick=()=>{
 if(!$('editor-offer-options').classList.contains('hidden')){editorHideMenu();return;}
 $('editor-offer-query').focus();
};
document.addEventListener('pointerdown',e=>{
 if(!$('editor-offer-combobox').contains(e.target))editorHideMenu();
});
$('add-offer').onclick=()=>{
 const raw=$('editor-offer-query').value.trim();
 const id=editorOfferSelectedId||(validOfferId(raw)?Number(raw):null);
 if(!id){notice('Введите точный числовой ID или выберите оффер из подсказок.');return;}
 if(demoMode&&!DEMO_CATALOG.some(x=>x.id===id)){notice('В учебном режиме доступны только офферы 910001–910004.');return;}
 stage('add',id);
};
$('cancel-editor').onclick=async()=>{
 if(demoMode){demoCancel();return;}
 if(!draft||!confirm('Отменить неопубликованные изменения черновика? Keitaro не изменится.'))return;
 try{showDraft(await post(`/api/campaigns/${current.id}/editor/cancel`,{version:draft.version}));notice('Cancel: черновик отменён. Keitaro не изменён.',true);}catch(e){notice(`Cancel: ${e.message}`);}
};
$('push-editor').onclick=async()=>{
 if(demoMode){demoPush();return;}
 if(!draft||!confirm(`Опубликовать изменения ТОЛЬКО потока #${draft.stream_id} своей кампании #${current.id} в Keitaro?`))return;
 try{showDraft(await post(`/api/campaigns/${current.id}/editor/push`,{version:draft.version}));notice('Push to KT завершён: изменения подтверждены повторным чтением Keitaro.',true);}catch(e){notice(`Push не выполнен/не подтверждён: ${e.message}`);}
};

// Isolated teaching sandbox; real client calls NEVER happen in demo mode.
// These offer IDs are fictional; they must not be used in Keitaro.
const DEMO_CATALOG=[
 {id:910001,name:'Демо-оффер A'},
 {id:910002,name:'Демо-оффер B'},
 {id:910003,name:'Демо-оффер C'},
 {id:910004,name:'Демо-оффер D (для Add)'},
];
let demoMode=false,demoPublished=[],demoRemote=[];
const demoCopy=value=>JSON.parse(JSON.stringify(value));
function demoShares(rows){
 const active=rows.filter(x=>!x.removed&&x.state==='active');
 const locked=active.filter(x=>x.pinned), free=active.filter(x=>!x.pinned);
 const remaining=100-locked.reduce((v,x)=>v+x.share,0);
 if(remaining<0||(!free.length&&active.length&&remaining!==0)|| (free.length&&remaining<free.length))throw Error('Невозможно распределить 100% с текущими закреплёнными долями.');
 if(free.length){let base=Math.floor(remaining/free.length),extra=remaining%free.length;free.forEach((x,i)=>x.share=base+(i<extra?1:0));}
 rows.filter(x=>x.removed).forEach(x=>x.share=0);
 return rows;
}
function demoRender(message){showDraft(draft);if(message)notice(message,true);}
function demoStart(){
 demoMode=true;document.body.classList.add('demo-active');
 demoPublished=DEMO_CATALOG.slice(0,3).map((x,i)=>({offer_id:x.id,share:[34,33,33][i],state:'active',removed:false,pinned:false}));
 demoRemote=demoCopy(demoPublished);
 draft={campaign_id:0,stream_id:0,version:1,dirty:false,rows:demoCopy(demoPublished)};
 current={id:0,name:'Учебная кампания',can_edit:true,streams:[]};
 $('campaign-detail').classList.remove('hidden');$('campaign-heading').textContent='Учебная кампания · без Keitaro';
 $('edit-status').textContent='ДЕМО · без запросов';$('edit-status').className='pill warning';
 $('demo-start').classList.add('hidden');$('demo-exit').classList.remove('hidden');$('demo-reset').classList.remove('hidden');$('demo-remote-remove').classList.remove('hidden');$('real-campaign-picker').classList.add('hidden');
 $('reload-detail').disabled=true;$('fetch-streams').textContent='Fetch (демо)';
 renderDemoStreams();
 $('editor-offer-query').value='';editorOfferSelectedId=null;editorHideMenu();
 demoRender('Демо запущено: 3 оффера, доли 34/33/33. Добавьте четвёртый оффер #910004.');
}
function exitDemo(){
 demoMode=false;document.body.classList.remove('demo-active');demoPublished=[];demoRemote=[];current=null;draft=null;
 $('demo-start').classList.remove('hidden');$('demo-exit').classList.add('hidden');$('demo-reset').classList.add('hidden');$('demo-remote-remove').classList.add('hidden');$('real-campaign-picker').classList.remove('hidden');
 $('campaign-detail').classList.add('hidden');$('draft-editor').classList.add('hidden');
 $('reload-detail').disabled=false;$('fetch-streams').textContent='Fetch streams from KT';
 $('push-editor').textContent='↑ Push to KT';$('editor-offer-query').value='';editorOfferSelectedId=null;editorHideMenu();
}
function demoStage(action,id,extra){
 if(!demoMode||!draft)return;
 const rows=demoCopy(draft.rows),target=rows.find(x=>x.offer_id===id);
 try{
  if(action==='add'){
   if(target)throw Error('Оффер уже есть в истории. Используйте Bring back.');
   if(!DEMO_CATALOG.some(x=>x.id===id))throw Error('Учебный оффер не найден.');
   rows.push({offer_id:id,share:0,state:'active',removed:false,pinned:false});
  }else{
   if(!target)throw Error('Оффер отсутствует.');
   if(action==='remove'){if(target.removed)throw Error('Уже удалён.');target.removed=true;target.pinned=false;}
   else if(action==='restore'){if(!target.removed)throw Error('Уже активен.');target.removed=false;target.state='active';target.pinned=false;}
   else if(action==='pin'){if(target.removed)throw Error('Удалённый оффер нельзя закрепить.');target.pinned=Boolean(extra.pinned);}
   else throw Error('Неизвестная операция.');
  }
  demoShares(rows);
  draft.rows=rows;draft.dirty=JSON.stringify(rows)!==JSON.stringify(demoPublished);draft.version++;
  demoRender('Изменён только учебный черновик. Ни один сервер не затронут.');
  if(action==='add'){$('editor-offer-query').value='';editorOfferSelectedId=null;editorHideMenu();}
 }catch(e){notice(`Демо: ${e.message}`);}
}
function demoCancel(){
 if(!draft||!draft.dirty)return;
 draft.rows=demoCopy(demoPublished);draft.dirty=false;draft.version++;
 demoRender('Cancel (демо): черновик откатан, никакие данные не отправлялись.');
}
function demoPush(){
 if(!draft||!draft.dirty)return;
 if(!draft.rows.some(x=>!x.removed&&x.state==='active')){notice('Нельзя публиковать пустой поток.');return;}
 demoPublished=demoCopy(draft.rows);demoRemote=demoCopy(draft.rows.filter(x=>!x.removed));
 draft.dirty=false;draft.version++;
 renderDemoStreams();demoRender('Push смоделирован только в браузере. Keitaro не изменён.');
}
function demoFetch(){
 if(!draft)return;
 if(draft.dirty){notice('Есть черновик. Нажмите Cancel или «Симулировать Push» перед Fetch.');return;}
 const previous=demoPublished;
 const next=demoCopy(demoRemote),ids=new Set(next.map(x=>x.offer_id));
 previous.forEach(x=>{if(!ids.has(x.offer_id))next.push({...x,removed:true,share:0,pinned:false});});
 demoPublished=next;draft.rows=demoCopy(next);draft.version++;draft.dirty=false;renderDemoStreams(true);
 demoRender('Fetch (демо): данные перечитаны из учебного состояния, пропавшие офферы сохранены серыми.');
}
// Manual demo: only the remote snapshot counts are shown in the stream summary.
function renderDemoStreams(){
 const list=$('stream-summary');list.replaceChildren();
 for(const [name,count] of [['Поток 1 · Google',0],['Поток 2 · Offers',demoRemote.length]]){
  const row=element('div',undefined,'stream');const info=element('div');
  info.append(element('strong',name),element('small',count?`${count} офферов`:'Без офферов'));
  row.append(info);list.append(row);
 }
}
$('demo-start').onclick=demoStart;
$('demo-reset').onclick=()=>{if(demoMode)demoStart();};
$('demo-exit').onclick=()=>{exitDemo();loadOwned();notice('Вернулись к собственным кампаниям.');};
$('demo-remote-remove').onclick=()=>{
 if(!demoMode)return;
 const index=demoRemote.findLastIndex(x=>!x.removed);
 if(index<0||demoRemote.filter(x=>!x.removed).length<2){notice('В учебном потоке должен остаться хотя бы один оффер.');return;}
 const id=demoRemote[index].offer_id;demoRemote.splice(index,1);demoShares(demoRemote);
 notice(`Демо: оффер #${id} «удалён на стороне Keitaro». Нажмите Fetch (демо), чтобы увидеть архив.`,true);
};

(async()=>{try{conf=await api('/api/config');syncCampaignName(true);const badge=$('write-pill');badge.textContent=conf.write_enabled?'Запись только в свои кампании':'Режим чтения Keitaro · Черновики доступны';badge.className='pill '+(conf.write_enabled?'good':'warning');await loadLookups();}catch(e){notice(e.message);}})();
