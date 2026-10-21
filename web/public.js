const publicKind=location.pathname==='/candidature'?'candidature':'demande';
const publicForm=document.querySelector('#public-form');
const result=document.querySelector('#result');
const safe=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
document.querySelector('#title').textContent=publicKind==='candidature'?'Proposer votre candidature':'Parlez-nous de votre besoin';
document.querySelector('#intro').textContent='Renseignez un email ou un téléphone pour que notre équipe puisse vous répondre.';
if(publicKind==='candidature'){
 fetch('/api/public/jobs').then(r=>{if(!r.ok)throw Error('Chargement impossible');return r.json()}).then(jobs=>{
  if(!jobs.length){publicForm.hidden=true;result.textContent='Aucune annonce confirmée ouverte aux candidatures pour le moment.';return}
  document.querySelector('#need-field').innerHTML=`<label>Annonce<select name="need_id" required>${jobs.map(j=>`<option value="${j.id}">${safe(j.ref)} · ${safe(j.poste)} · ${safe(j.ville)}</option>`).join('')}</select></label>`;
  document.querySelector('#jobs').innerHTML=jobs.map(j=>`<details><summary>${safe(j.ref)} · ${safe(j.poste)}</summary><article>${safe(j.annonce).replaceAll(' / ','<br>')}</article></details>`).join('');
 }).catch(()=>{publicForm.hidden=true;result.textContent='Impossible de charger les annonces. Réessayez ultérieurement.'});
}
publicForm.addEventListener('submit',async e=>{
 e.preventDefault();const button=publicForm.querySelector('button');button.disabled=true;
 try{
  const form=new FormData(publicForm),body=Object.fromEntries(form);body.kind=publicKind;body.acknowledge=form.get('acknowledge')==='on';body.source=new URLSearchParams(location.search).get('source')||'formulaire_public';if(body.need_id)body.need_id=Number(body.need_id);
  const response=await fetch('/api/public/intake',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(data.error);
  publicForm.hidden=true;result.textContent='Votre demande a été enregistrée. Référence : '+data.reference+'. Notre équipe doit encore l’examiner.';
 }catch(err){result.textContent=err.message;button.disabled=false}
});