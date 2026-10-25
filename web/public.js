const isServicePage=location.pathname.startsWith('/services/');
const publicKind=location.pathname==='/candidature'?'candidature':'demande';
const publicForm=document.querySelector('#public-form');
const result=document.querySelector('#result');
const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const qs=new URLSearchParams(location.search);
let resolvedRef=publicForm?.dataset.b2cRef||qs.get('ref')||'';

if(!isServicePage){
 document.querySelector('#title').textContent=publicKind==='candidature'?'Proposer votre candidature':'Parlez-nous de votre besoin';
 document.querySelector('#intro').textContent='Renseignez un email ou un téléphone pour que notre équipe puisse vous répondre.';
}
if(publicKind==='demande'&&!isServicePage&&resolvedRef){
 fetch('/api/public/b2c?ref='+encodeURIComponent(resolvedRef)).then(r=>r.ok?r.json():{}).then(c=>{
  if(!c?.ref)return;
  resolvedRef=c.ref;
  const cityInput=publicForm.querySelector('[name="city"]'),msgInput=publicForm.querySelector('[name="message"]'),banner=document.querySelector('#b2c-banner');
  if(cityInput&&!cityInput.value)cityInput.value=c.ville;
  if(msgInput&&!msgInput.value)msgInput.value=`Bonjour, je cherche : ${c.besoin} (${c.zone}, ${c.ville}). Réf. ${c.ref}`;
  if(banner)banner.innerHTML=`<div class="notice"><strong>Demande localisée · ${safe(c.ref)}</strong><br>${safe(c.besoin)} — ${safe(c.zone)}, ${safe(c.ville)} · <a href="${safe(c.lien)}" target="_blank" rel="noopener noreferrer" style="color:#236b50;font-weight:600">Écrire plutôt sur WhatsApp ↗</a></div>`;
 }).catch(()=>{});
}
if(publicKind==='candidature'){
 fetch('/api/public/jobs').then(r=>{if(!r.ok)throw Error('Chargement impossible');return r.json()}).then(jobs=>{
  if(!jobs.length){publicForm.hidden=true;result.textContent='Aucune annonce confirmée ouverte aux candidatures pour le moment.';return}
  document.querySelector('#need-field').innerHTML=`<label>Annonce<select name="need_id" required>${jobs.map(j=>`<option value="${j.id}">${safe(j.ref)} · ${safe(j.poste)} · ${safe(j.ville)}</option>`).join('')}</select></label>`;
  document.querySelector('#jobs').innerHTML=jobs.map(j=>`<details><summary>${safe(j.ref)} · ${safe(j.poste)}</summary><article>${safe(j.annonce).replaceAll(' / ','<br>')}</article></details>`).join('');
 }).catch(()=>{publicForm.hidden=true;result.textContent='Impossible de charger les annonces. Réessayez ultérieurement.'});
}
if(publicForm){
 publicForm.addEventListener('submit',async e=>{
  e.preventDefault();const button=publicForm.querySelector('button[type="submit"]');
  let originalText='';
  if(button){
    button.disabled=true;
    button.setAttribute('aria-busy','true');
    originalText=button.textContent;
    button.textContent='Transmission en cours…';
  }
  try{
   const form=new FormData(publicForm),body=Object.fromEntries(form);
   body.kind=publicKind;
   body.acknowledge=form.get('acknowledge')==='on';
   body.source=qs.get('source')||publicForm.dataset.defaultSource||(resolvedRef?'site_formulaire:'+resolvedRef:'site_formulaire');
   if(resolvedRef)body.b2c_ref=resolvedRef;
   if(body.need_id)body.need_id=Number(body.need_id);
   const response=await fetch('/api/public/intake',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   const data=await response.json();if(!response.ok)throw Error(data.error);
   publicForm.hidden=true;result.textContent='Votre demande a été enregistrée. Référence : '+data.reference+'. Notre équipe doit encore l’examiner.';
  }catch(err){
   result.textContent=err.message;
   if(button){
     button.disabled=false;
     button.removeAttribute('aria-busy');
     button.textContent=originalText;
   }
  }
 });
}
