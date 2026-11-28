// Interface Acquisition autonome, Demandes Clients B2C, Prospection B2B & File d'envoi
(function () {
  const AUTONOME_PAGES = ['acquisition', 'demandes', 'prospection', 'file_envoi'];

  const PIPELINE_FAMILLES_LABELS = {
    demande_recue: 'Demande reçue',
    qualifiee: 'Qualifiée',
    rdv_programme: 'RDV / appel programmé',
    besoin_confirme: 'Besoin confirmé',
    candidats_proposes: 'Candidats proposés',
    mission_confirmee: 'Mission confirmée',
    gagnee: 'Gagnée',
    perdue: 'Perdue',
  };

  const PIPELINE_PRO_LABELS = {
    prospect_identifie: 'Prospect identifié',
    contact_valide: 'Contact validé',
    message_envoye: 'Message envoyé',
    reponse_recue: 'Réponse reçue',
    rdv_programme: 'RDV programmé',
    besoin_confirme: 'Besoin confirmé',
    proposition_envoyee: 'Proposition envoyée',
    gagne: 'Gagné',
    perdu: 'Perdu',
  };

  const VALIDATION_LABELS = {
    en_attente_validation: 'À valider',
    valide: 'Validé',
    rejete: 'Rejeté',
    bloque: 'Bloqué définitivement',
    exclu: 'Exclu',
    verification_demandee: 'Vérification demandée',
    programme: 'Envoi programmé',
    envoye: 'Envoyé',
  };

  const B2C_SOURCES = [
    ['formulaire_prestation', 'Formulaire demande de prestation (site)'],
    ['formulaire_contact', 'Formulaire de contact (site)'],
    ['whatsapp_bouton', 'Bouton WhatsApp prérempli (site)'],
    ['whatsapp_entrant', 'Message WhatsApp Business reçu'],
    ['email_officiel', 'Email reçu sur adresse officielle'],
    ['appel_entrant', 'Appel téléphonique entrant'],
    ['social_entrant', 'Message volontaire FB / IG / TikTok / GBP'],
    ['campagne_formulaire', 'Formulaire publicitaire (Meta / Google Ads)'],
    ['recommandation_client', 'Recommandation client avec accord'],
    ['partenaire_local', 'Partenaire local avec accord client'],
  ];

  const B2B_SOURCES = [
    ['google_maps_places', 'Google Maps / Google Places'],
    ['site_web_officiel', 'Site officiel d’entreprise'],
    ['annonce_emploi_publique', 'Offre d’emploi publique'],
    ['reseau_pro_public', 'Réseau professionnel public'],
    ['annuaire_registre_public', 'Annuaire / registre public'],
    ['formulaire_entrant_b2b', 'Formulaire entrant entreprise'],
    ['recommandation_partenaire_b2b', 'Recommandation partenaire autorisée'],
  ];

  let filterDemandeStage = '';
  let filterDemandeClass = '';
  let filterProspectStage = '';
  let filterProspectClass = '';

  function autoData() {
    return (typeof ops !== 'undefined' && ops && ops.autonome) ? ops.autonome : {};
  }

  function isAdmin() {
    return (typeof data !== 'undefined' && data && data.user && data.user.role === 'admin') || !(typeof data !== 'undefined' && data && data.user);
  }

  function classBadge(cls, score) {
    const label = `${cls || '—'}${score !== undefined && score !== null ? ' · ' + score + '/100' : ''}`;
    const tone = cls === 'A' ? '' : cls === 'B' ? 'warn' : 'gray';
    return `<span class="badge ${tone}">${esc(label)}</span>`;
  }

  function valBadge(st) {
    const label = VALIDATION_LABELS[st] || st || '—';
    const tone = st === 'valide' || st === 'envoye' ? '' : (st === 'verification_demandee' || st === 'programme' || st === 'en_attente_validation') ? 'warn' : 'gray';
    return `<span class="badge ${tone}">${esc(label)}</span>`;
  }

  async function postJson(url, payload) {
    const r = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Yallah-Token': data.token },
      body: JSON.stringify(payload),
    });
    const res = await r.json();
    if (!r.ok) throw Error(res.error || 'Erreur serveur');
    await load();
    return res;
  }

  // =========================================================================
  // Page 1 : Acquisition autonome (Dashboard KPI + Digest + Auto-pilot + Audit)
  // =========================================================================
  function renderAcquisition() {
    const a = autoData();
    const k = a.kpis || {};
    const ap = a.autopilot || {};
    const digest = a.latest_digest || null;
    const alerts = a.alertes_conformite || [];
    const connectors = a.connectors || {};
    const topSources = a.top_sources || [];
    const roiSources = a.roi_sources || [];
    const admin = isAdmin();

    const kpiCards = [
      ['Demandes clients (aujourd’hui)', k.demandes_aujourdhui ?? 0, '⌂', `Total : ${(a.demandes_clients || []).length}`],
      ['Qualifiées A · B2C', k.demandes_qualifiees_a ?? 0, '★', 'Familles prioritaires'],
      ['Qualifiés A · B2B', k.prospects_pro_qualifies_a ?? 0, '◈', 'Pros ≥ 75/100'],
      ['Messages prêts à valider', k.messages_prets ?? 0, '✉', 'Validation humaine'],
      ['Messages envoyés', k.messages_envoyes ?? 0, '⇪', `Quota jour : ${k.first_contacts_today ?? 0}/${k.max_first_contacts_per_day ?? 15}`],
      ['Réponses reçues', k.reponses_recues ?? 0, '☷', `Taux : ${k.taux_reponse ?? 0} %`],
      ['RDV obtenus', k.rdv_obtenus ?? 0, '✓', 'Familles & Pros'],
      ['Missions confirmées', k.missions_confirmees ?? 0, '▤', 'Gagnées / confirmées'],
      ['Contacts bloqués / STOP', k.contacts_bloques ?? 0, '⊘', `Doublons évités : ${k.doublons_evites ?? 0}`],
      ['Temps économisé (est.)', `${k.temps_economise_minutes ?? 0} min`, '◷', `${k.temps_economise_heures ?? 0} h gagnées`],
    ];

    const alertsHtml = alerts.length
      ? alerts.map(al => `<div class="note ${al.niveau === 'critique' ? 'alert-crit' : ''}"><strong>${esc(String(al.niveau || 'info').toUpperCase())}</strong> · ${esc(al.message)}</div>`).join('')
      : '<div class="note">Aucune alerte de conformité active. Loi 09-08, STOP et plafonds quotidiens respectés.</div>';

    const digestSection = digest
      ? `<div class="card">
          <div class="card-head">
            <div><h2>Daily Prospect Digest · ${esc(digest.digest_date)}</h2><p class="sub">Synthèse quotidienne Email + WhatsApp (jamais de coordonnées sensibles exposées sur WhatsApp)</p></div>
            <div class="actions">
              <button type="button" class="primary" data-auto-digest="generate">↻ Régénérer</button>
              <button type="button" data-auto-digest="send">Envoyer le digest</button>
            </div>
          </div>
          <div class="stats">
            <div class="stat"><label>Nouvelles demandes</label><b>${digest.kpis?.nouvelles_demandes ?? 0}</b></div>
            <div class="stat"><label>Qualifiées A B2C</label><b>${digest.kpis?.demandes_qualifiees_a ?? 0}</b></div>
            <div class="stat"><label>Qualifiés A B2B</label><b>${digest.kpis?.prospects_pro_qualifies_a ?? 0}</b></div>
            <div class="stat"><label>Doublons évités</label><b>${digest.kpis?.doublons_evites ?? 0}</b></div>
            <div class="stat"><label>Invalides / rejetés</label><b>${digest.kpis?.contacts_rejetes ?? 0}</b></div>
            <div class="stat"><label>STOP / retraits</label><b>${digest.kpis?.demandes_stop ?? 0}</b></div>
          </div>
          <h3>Top priorités du jour (${(digest.items || []).length})</h3>
          ${(digest.items || []).length ? `<div class="table-wrap"><table><thead><tr><th>Nom / Type</th><th>Zone</th><th>Score</th><th>Besoin / Source</th><th>Actions</th></tr></thead><tbody>${digest.items.map(it => `<tr><td><strong>${esc(it.nom)}</strong><small>${esc(it.type_label)} · ${esc(it.reference)}</small></td><td>${esc(it.quartier_ville)}</td><td>${classBadge(it.classification, it.score)}</td><td>${esc(it.besoin)}<small>${esc(it.source)} · ${esc(it.canal)}</small></td><td><button type="button" class="text-link" data-open-fiche="${esc(it.entity_type)}" data-fiche-id="${it.entity_id}">Ouvrir &amp; valider ↗</button></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">Aucune fiche prioritaire en attente pour le moment.</div>'}
          <details style="margin-top:12px"><summary>Aperçu WhatsApp (masquage automatique des coordonnées sensibles)</summary><pre class="message">${esc(digest.whatsapp_text || '')}</pre></details>
        </div>`
      : `<div class="card"><div class="card-head"><div><h2>Daily Prospect Digest</h2><p class="sub">Aucun digest généré aujourd’hui.</p></div><button type="button" class="primary" data-auto-digest="generate">Générer le digest du matin</button></div></div>`;

    const autopilotSection = `<div class="card">
      <div class="card-head">
        <div>
          <h2>Mode Auto-pilot (optionnel · Admin uniquement)</h2>
          <p class="sub">Désactivé par défaut. Envoie uniquement aux fiches de niveau A avec consentement valide par canal. Jamais de prospection froide B2C.</p>
        </div>
        ${badge(ap.enabled ? 'ACTIF' : 'DÉSACTIVÉ (par défaut)')}
      </div>
      ${ap.circuit_breaker_reason ? `<div class="note alert-crit"><strong>Coupe-circuit actif :</strong> ${esc(ap.circuit_breaker_reason)}</div>` : ''}
      <p><small>Plafond quotidien : <strong>${ap.max_first_contacts_per_day ?? 15}</strong> contacts/jour · Max relances : <strong>${ap.max_followups ?? 3}</strong> (J+3, J+7, J+14) · Jamais 2 messages le même jour · Seuil rebond : <strong>${ap.bounce_threshold_pct ?? 10}%</strong></small></p>
      ${admin ? `
        <form id="autopilot-form" class="form-grid" style="margin-top:12px">
          <label class="field">Plafond contacts / jour (1–50)<input type="number" name="max_first_contacts_per_day" min="1" max="50" value="${ap.max_first_contacts_per_day ?? 15}"></label>
          <label class="field">Max relances par contact (0–3)<input type="number" name="max_followups" min="0" max="3" value="${ap.max_followups ?? 3}"></label>
          <label class="field">Seuil arrêt rebonds (%)<input type="number" name="bounce_threshold_pct" min="1" max="50" value="${ap.bounce_threshold_pct ?? 10}"></label>
          <label class="field">Heure Daily Digest (HH:MM)<input type="text" name="digest_hour" value="${esc(ap.digest_hour || '08:00')}"></label>
          <label class="field full"><input type="checkbox" name="enabled" ${ap.enabled ? 'checked' : ''}> Activer le mode Auto-pilot (niveau A uniquement, règles Loi 09-08 &amp; WhatsApp strictement appliquées)</label>
          <div class="actions full">
            <button type="submit" class="primary">Enregistrer la configuration</button>
            <button type="button" data-autopilot-run="sim">Tester un cycle (dry-run)</button>
            <button type="button" data-autopilot-run="live" ${ap.enabled ? '' : 'disabled'}>Exécuter un cycle réel</button>
            <button type="button" class="danger" data-autopilot-kill>⛔ Arrêt Auto-pilot en un clic</button>
          </div>
        </form>
      ` : '<div class="note">Seul un administrateur peut activer le mode Auto-pilot ou modifier les plafonds.</div>'}
    </div>`;

    const connCards = `<div class="card">
      <h2>Connecteurs techniques &amp; sécurité</h2>
      <div class="grid">
        <div>
          <strong>Email (${esc(connectors.email?.provider || 'non configuré')})</strong><br>
          ${badge(connectors.email?.ready ? 'PRET — configuré' : 'Simulation / à configurer')}
          <p class="sub">IMAP réponses : ${connectors.email?.imap_configured ? 'Configuré' : 'Non configuré'} · Tracking : désactivé par défaut</p>
        </div>
        <div>
          <strong>WhatsApp Business Cloud API</strong><br>
          ${badge(connectors.whatsapp?.ready ? 'PRET — configuré' : 'Simulation / à configurer')}
          <p class="sub">Opt-in obligatoire · Templates approuvés requis</p>
        </div>
      </div>
      <p class="sub" style="margin-top:8px">Découverte Web publique : robots.txt respecté, limitation de débit activée, réseaux privés bloqués automatiquement.</p>
      ${admin ? `<div class="actions"><a class="button" href="/api/audit/export?format=csv" download="audit_yallah.csv">↓ Exporter le journal d’audit (CSV)</a><a class="button" href="/api/audit/export?format=json" download="audit_yallah.json">↓ Exporter l’audit (JSON)</a></div>` : ''}
    </div>`;

    const sourcesHtml = `<div class="card">
      <h2>Meilleures sources &amp; ROI réel (MAD / heure)</h2>
      <div class="grid">
        <div>
          <h3>Sources d’acquisition</h3>
          ${topSources.length ? `<table><thead><tr><th>Source</th><th>Type</th><th>Total</th><th>Niveau A</th></tr></thead><tbody>${topSources.map(s => `<tr><td>${esc(s.source)}</td><td>${esc(s.type || '')}</td><td>${s.total}</td><td>${s.qualifies_a}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">Aucune source enregistrée.</div>'}
        </div>
        <div>
          <h3>ROI encaissé par source (MAD/h)</h3>
          ${roiSources.length ? `<table><thead><tr><th>Source</th><th>Encaissé</th><th>Temps</th><th>MAD/h</th></tr></thead><tbody>${roiSources.slice(0, 8).map(r => `<tr><td>${esc(r.source)}</td><td>${esc(r.ca_encaisse_mad)} MAD</td><td>${esc(r.heures)} h</td><td><strong>${r.roi_mad_heure != null ? esc(r.roi_mad_heure) + ' MAD/h' : '—'}</strong></td></tr>`).join('')}</tbody></table>` : '<div class="empty">Saisissez vos encaissements dans le grand livre pour calculer le ROI réel.</div>'}
        </div>
      </div>
    </div>`;

    $('#content').innerHTML =
      heading(
        'ACQUISITION AUTONOME · CASABLANCA',
        'Centre de pilotage commercial & conformité.',
        'Capture B2C, prospection pro publique, scoring 0–100, validation humaine, Daily Digest et Auto-pilot sécurisé.',
        `<div class="actions"><button type="button" class="primary" data-new-demande>+ Nouvelle demande B2C</button><button type="button" data-new-pro>+ Nouveau prospect pro</button></div>`
      ) +
      `<div class="stats">${kpiCards.map(([t, n, i, s]) => `<div class="stat"><span class="icon">${i}</span><label>${t}</label><b>${esc(n)}</b><small>${esc(s)}</small></div>`).join('')}</div>` +
      `<div class="card"><h2>Alertes de conformité</h2>${alertsHtml}</div>` +
      digestSection +
      autopilotSection +
      sourcesHtml +
      connCards;
  }

  // =========================================================================
  // Page 2 : Demandes Clients (B2C) — Pipeline Familles (8 étapes)
  // =========================================================================
  function renderDemandes() {
    const a = autoData();
    const demandes = a.demandes_clients || [];
    const counts = {};
    demandes.forEach(d => { counts[d.pipeline_stage] = (counts[d.pipeline_stage] || 0) + 1; });

    const filtered = demandes.filter(d =>
      (!filterDemandeStage || d.pipeline_stage === filterDemandeStage) &&
      (!filterDemandeClass || d.classification === filterDemandeClass)
    );

    const pipeHtml = `<div class="pipeline-strip">${Object.entries(PIPELINE_FAMILLES_LABELS).map(([k, lbl]) =>
      `<button type="button" class="pipe-pill ${filterDemandeStage === k ? 'active' : ''}" data-filter-demande-stage="${k}"><strong>${counts[k] || 0}</strong><span>${esc(lbl)}</span></button>`
    ).join('')}<button type="button" class="pipe-pill ${!filterDemandeStage ? 'active' : ''}" data-filter-demande-stage=""><strong>${demandes.length}</strong><span>Toutes</span></button></div>`;

    const rowsHtml = filtered.length
      ? `<table><thead><tr><th>Réf. / Client</th><th>Zone &amp; Besoin</th><th>Score Besoin</th><th>Consentement</th><th>Validation &amp; Pipeline</th><th></th></tr></thead><tbody>${filtered.map(d => `<tr>
          <td><strong>${esc(d.nom)}</strong><small>${esc(d.reference)} · ${esc(d.source || '')}</small></td>
          <td>${esc(d.ville || '—')}${d.quartier ? ' · ' + esc(d.quartier) : ''}<small>${esc(d.type_besoin || 'À préciser')}${d.frequence ? ' · ' + esc(d.frequence) : ''}</small></td>
          <td>${classBadge(d.classification, d.score)}<small>Langue : ${esc(d.langue_preferee || 'fr')} · Canal : ${esc(d.message_canal || '—')}</small></td>
          <td>${d.workflow_status === 'bloque' ? '<span class="badge gray">STOP / Bloqué</span>' : `${d.consentement_recontact ? '<span class="badge">Recontact OK</span>' : '<span class="badge warn">Recontact à vérifier</span>'} ${d.consentement_whatsapp ? '<span class="badge">WA OK</span>' : ''}`}</td>
          <td>${valBadge(d.workflow_status)}<small>${esc(PIPELINE_FAMILLES_LABELS[d.pipeline_stage] || d.pipeline_stage)}</small></td>
          <td><button type="button" class="primary" data-open-fiche="demande_b2c" data-fiche-id="${d.id}">Valider / Fiche ↗</button></td>
        </tr>`).join('')}</tbody></table>`
      : '<div class="empty">Aucune demande client dans cette sélection. Partagez <a href="/demande" target="_blank">/demande</a> ou saisissez une demande entrante.</div>';

    $('#content').innerHTML =
      heading(
        'DEMANDES CLIENTS (B2C · FAMILLES)',
        'Capture entrante, analyse FR/Darija/Arabe et scoring 0–100.',
        'Zéro prospection froide B2C : uniquement des demandes volontaires avec consentement explicite.',
        `<div class="actions"><button type="button" class="primary" data-new-demande>+ Enregistrer une demande entrante</button><a class="button" href="/demande" target="_blank" rel="noopener noreferrer">Formulaire public /demande ↗</a></div>`
      ) +
      `<div class="card"><h2>Pipeline Familles (8 étapes)</h2>${pipeHtml}<div class="actions" style="margin-top:10px">${['', 'A', 'B', 'C', 'Exclu'].map(c => `<button type="button" class="${filterDemandeClass === c ? 'primary' : ''}" data-filter-demande-class="${c}">${c ? 'Classe ' + c : 'Toutes classes'}</button>`).join('')}</div></div>` +
      `<div class="card table-wrap">${rowsHtml}</div>`;
  }

  // =========================================================================
  // Page 3 : Prospection B2B — Pipeline Professionnels (9 étapes)
  // =========================================================================
  function renderProspection() {
    const a = autoData();
    const prospects = a.prospects || [];
    const counts = {};
    prospects.forEach(p => { counts[p.pipeline_stage] = (counts[p.pipeline_stage] || 0) + 1; });

    const filtered = prospects.filter(p =>
      (!filterProspectStage || p.pipeline_stage === filterProspectStage) &&
      (!filterProspectClass || p.classification === filterProspectClass)
    );

    const pipeHtml = `<div class="pipeline-strip">${Object.entries(PIPELINE_PRO_LABELS).map(([k, lbl]) =>
      `<button type="button" class="pipe-pill ${filterProspectStage === k ? 'active' : ''}" data-filter-pro-stage="${k}"><strong>${counts[k] || 0}</strong><span>${esc(lbl)}</span></button>`
    ).join('')}<button type="button" class="pipe-pill ${!filterProspectStage ? 'active' : ''}" data-filter-pro-stage=""><strong>${prospects.length}</strong><span>Tous</span></button></div>`;

    const rowsHtml = filtered.length
      ? `<table><thead><tr><th>Établissement</th><th>Segment &amp; Zone</th><th>Prospect Pro Score</th><th>Source &amp; Canal</th><th>Validation &amp; Pipeline</th><th></th></tr></thead><tbody>${filtered.map(p => `<tr>
          <td><strong>${esc(p.nom_entreprise)}</strong><small>${esc(p.reference)} · ${esc(p.besoin_probable || 'Besoin à confirmer')}</small></td>
          <td>${esc(p.type_etablissement || 'entreprise')}<small>${esc(p.ville || 'Casablanca')}${p.quartier ? ' · ' + esc(p.quartier) : ''}</small></td>
          <td>${classBadge(p.classification, p.score)}</td>
          <td><small>${esc(p.source_nom || '—')}<br>${esc(p.message_canal || '—')}${p.email_pro ? ' · ' + esc(p.email_pro) : ''}</small></td>
          <td>${valBadge(p.workflow_status)}<small>${esc(PIPELINE_PRO_LABELS[p.pipeline_stage] || p.pipeline_stage)}</small></td>
          <td><button type="button" class="primary" data-open-fiche="prospect_pro" data-fiche-id="${p.id}">Valider / Fiche ↗</button></td>
        </tr>`).join('')}</tbody></table>`
      : '<div class="empty">Aucun prospect professionnel dans cette sélection.</div>';

    $('#content').innerHTML =
      heading(
        'PROSPECTION B2B (SOURCES PUBLIQUES)',
        'Hôtels, restaurants, traiteurs, événementiel, conciergeries et entreprises.',
        'Collecte strictement publique (robots.txt respecté, zéro scraping privé) et scoring Prospect Pro 0–100.',
        `<div class="actions"><button type="button" class="primary" data-new-pro>+ Nouveau prospect pro</button><button type="button" data-discover-pro>⌕ Découvrir une URL publique</button></div>`
      ) +
      `<div class="card"><h2>Pipeline Professionnels (9 étapes)</h2>${pipeHtml}<div class="actions" style="margin-top:10px">${['', 'A', 'B', 'C', 'Exclu'].map(c => `<button type="button" class="${filterProspectClass === c ? 'primary' : ''}" data-filter-pro-class="${c}">${c ? 'Classe ' + c : 'Toutes classes'}</button>`).join('')}</div></div>` +
      `<div class="card table-wrap">${rowsHtml}</div>`;
  }

  // =========================================================================
  // Page 4 : File d'envoi, Relances J+3/J+7/J+14, Réponses & Blocages STOP
  // =========================================================================
  function renderFileEnvoi() {
    const a = autoData();
    const envois = a.envois || [];
    const relances = a.relances || [];
    const blocages = a.blocages || [];
    const reponses = a.reponses || [];
    const consentements = a.consentements || [];

    $('#content').innerHTML =
      heading(
        'FILE D’ENVOI, RELANCES & CONFORMITÉ',
        'Suivi complet des envois, relances J+3/J+7/J+14, réponses et STOP.',
        'Chaque envoi conserve la preuve de consentement, la date prévue, l’historique et le résultat.',
        `<button type="button" class="primary" data-new-reponse>+ Enregistrer une réponse / STOP</button>`
      ) +
      `<div class="card table-wrap"><h2>File d’envoi (${envois.length})</h2>${envois.length ? `<table><thead><tr><th>Prospect / Demande</th><th>Canal &amp; Destination</th><th>Date prévue</th><th>Statut</th><th>Preuve de consentement</th><th>Résultat</th></tr></thead><tbody>${envois.map(e => `<tr><td><strong>${esc(e.entity_nom || e.entity_type + ' #' + e.entity_id)}</strong><small>${esc((e.message_final || '').slice(0, 90))}…</small></td><td>${esc(e.canal)}<small>${esc(e.destination)}</small></td><td>${esc((e.scheduled_at || e.created_at || '').replace('T', ' ').slice(0, 16))}</td><td>${valBadge(e.statut)}</td><td><small>${esc(e.consentement_preuve || '—')}</small></td><td><small>${esc(e.resultat || e.error_detail || '—')}</small></td></tr>`).join('')}</tbody></table>` : '<div class="empty">Aucun envoi dans la file pour le moment. Validez une fiche puis cliquez sur Envoyer maintenant ou Programmer l’envoi.</div>'}</div>` +
      `<div class="card table-wrap"><h2>Relances planifiées J+3 / J+7 / J+14 (${relances.length})</h2>${relances.length ? `<table><thead><tr><th>Étape</th><th>Cible</th><th>Canal</th><th>Prévue le</th><th>Statut</th></tr></thead><tbody>${relances.map(r => `<tr><td><strong>J+${r.delai_jours} (Relance ${r.etape}/3)</strong></td><td>${esc(r.entity_type)} #${r.entity_id}</td><td>${esc(r.canal)}</td><td>${esc((r.scheduled_for || '').slice(0, 10))}</td><td>${badge(r.statut)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">Les relances J+3, J+7 et J+14 sont planifiées automatiquement après un premier envoi et annulées dès la première réponse ou STOP.</div>'}</div>` +
      `<div class="grid">
        <div class="card table-wrap"><h2>Réponses entrantes (${reponses.length})</h2>${reponses.length ? `<table><thead><tr><th>Canal / Expéditeur</th><th>STOP</th><th>Message</th></tr></thead><tbody>${reponses.map(rp => `<tr><td><strong>${esc(rp.canal)}</strong><small>${esc(rp.expediteur)}</small></td><td>${rp.stop_detecte ? '<span class="badge gray">STOP (' + esc(rp.stop_mot_cle) + ')</span>' : '<span class="badge">Réponse</span>'}</td><td><small>${esc((rp.contenu || '').slice(0, 140))}</small></td></tr>`).join('')}</tbody></table>` : '<div class="empty">Aucune réponse enregistrée.</div>'}</div>
        <div class="card table-wrap"><h2>Registre des blocages définitifs / STOP (${blocages.length})</h2>${blocages.length ? `<table><thead><tr><th>Clé bloquée</th><th>Canal</th><th>Mot-clé / Motif</th><th>Date</th></tr></thead><tbody>${blocages.map(b => `<tr><td><code>${esc(b.contact_key)}</code></td><td>${esc(b.canal)}</td><td><strong>${esc(b.mot_cle || 'STOP')}</strong><small>${esc(b.motif)}</small></td><td><small>${esc((b.created_at || '').slice(0, 16).replace('T', ' '))}</small></td></tr>`).join('')}</tbody></table>` : '<div class="empty">Aucun contact bloqué.</div>'}</div>
      </div>` +
      `<div class="card table-wrap"><h2>Preuves de consentement (${consentements.length})</h2>${consentements.length ? `<table><thead><tr><th>Canal</th><th>Accord</th><th>Preuve</th><th>Date</th></tr></thead><tbody>${consentements.slice(0, 30).map(c => `<tr><td>${esc(c.canal)}</td><td>${c.consenti ? '<span class="badge">Accordé</span>' : '<span class="badge gray">Non accordé / Retiré</span>'}</td><td><small>${esc(c.preuve)}</small></td><td><small>${esc((c.created_at || '').slice(0, 16).replace('T', ' '))}</small></td></tr>`).join('')}</tbody></table>` : '<div class="empty">Aucun consentement journalisé.</div>'}</div>`;
  }

  // =========================================================================
  // Modale Fiche détaillée + 9 boutons obligatoires de validation
  // =========================================================================
  async function openFiche(entityType, entityId) {
    const r = await fetch(`/api/autonome/fiche?type=${encodeURIComponent(entityType)}&id=${encodeURIComponent(entityId)}`);
    const f = await r.json();
    if (!r.ok) { toast(f.error || 'Fiche introuvable'); return; }
    const item = f.item;
    const normType = f.entity_type || entityType;
    const isDem = normType === 'demande_b2c';
    const breakdown = f.score_details || {};
    const analyse = f.analyse || {};
    const draft = (f.messages && f.messages[0]) || null;
    const msgBody = draft ? draft.corps : '';
    const msgCanal = draft ? draft.canal : (isDem ? (item.canal_prefere || 'email') : (item.email_pro ? 'email' : 'appel'));
    const pipeLabels = isDem ? PIPELINE_FAMILLES_LABELS : PIPELINE_PRO_LABELS;
    const titleName = isDem ? item.nom : item.nom_entreprise;

    const breakdownHtml = Object.entries(breakdown).map(([k, v]) =>
      `<span class="badge gray">${esc(k)} : ${esc(v)}</span>`
    ).join(' ');

    const waRaw = isDem ? (item.whatsapp || item.tel) : (item.whatsapp_pro || item.tel_pro);
    const telRaw = isDem ? (item.tel || item.whatsapp) : (item.tel_pro || item.whatsapp_pro);
    const waLink = waRaw ? `https://wa.me/${esc(String(waRaw).replace(/\D+/g, ''))}?text=${encodeURIComponent(msgBody)}` : '';
    const telLink = telRaw ? `tel:${esc(telRaw)}` : '';

    modal(
      modalHead(`${item.reference} · ${titleName}`) +
      `<p>${classBadge(item.classification, item.score)} ${valBadge(item.workflow_status)} ${f.bloque ? '<span class="badge gray">⛔ CONTACT BLOQUÉ / STOP</span>' : ''}</p>` +
      `<p class="sub">${esc(item.ville || '—')}${item.quartier ? ' · ' + esc(item.quartier) : ''} · Canal préparé : <strong>${esc(msgCanal)}</strong></p>` +
      `<div class="note"><strong>Détail du score :</strong> ${breakdownHtml || '—'}</div>` +
      (isDem
        ? `<div class="card"><h3>Demande originale &amp; analyse sans invention</h3>
            <p>${esc(item.message_brut)}</p>
            <small>Besoin détecté : <strong>${esc(item.type_besoin || 'non précisé')}</strong> · Fréquence : <strong>${esc(item.frequence || 'non précisée')}</strong> · Urgence : <strong>${esc(item.urgence || 'non précisée')}</strong> · Langue : <strong>${esc(item.langue_preferee || 'fr')}</strong></small>
            ${analyse.contraintes_volontaires && analyse.contraintes_volontaires.length ? `<br><small>Contraintes exprimées : ${esc(analyse.contraintes_volontaires.join(', '))}</small>` : ''}
            <br><small>Consentement recontact : <strong>${item.consentement_recontact ? 'Oui' : 'Non'}</strong> · Consentement WhatsApp : <strong>${item.consentement_whatsapp ? 'Oui' : 'Non'}</strong></small>
          </div>`
        : `<div class="card"><h3>Source publique &amp; signaux B2B</h3>
            <p><strong>Segment :</strong> ${esc(item.type_etablissement)} · <strong>Besoin probable :</strong> ${esc(item.besoin_probable || 'À confirmer')}</p>
            <p><strong>Preuve / extrait :</strong> ${esc(item.preuve_extrait || '—')}</p>
            <p><small>Source : ${esc(item.source_nom)} ${item.source_url ? `· <a href="${safeUrl(item.source_url)}" target="_blank" rel="noopener noreferrer">${esc(item.source_url)} ↗</a>` : ''} · Consultée le ${esc(item.date_consultation || '')}</small></p>
            <p><small>Contact : ${esc([item.email_pro, item.tel_pro, item.whatsapp_pro].filter(Boolean).join(' · ') || 'Aucun contact direct')}</small></p>
          </div>`) +
      `<div class="card">
        <h3>Étape 4 &amp; 5 — Message recommandé &amp; Validation humaine</h3>
        <label class="field">Message final (modifiable avant validation ou envoi)
          <textarea id="fiche-msg-body" rows="6">${esc(msgBody)}</textarea>
        </label>
        <div class="form-grid">
          <label class="field">Canal d’envoi
            <select id="fiche-channel">
              <option value="email" ${msgCanal === 'email' ? 'selected' : ''}>Email</option>
              <option value="whatsapp" ${msgCanal === 'whatsapp' ? 'selected' : ''}>WhatsApp Business</option>
              <option value="appel" ${msgCanal === 'appel' ? 'selected' : ''}>Téléphone / Appel</option>
            </select>
          </label>
          <label class="field">Date / heure programmée (pour « Programmer l’envoi »)
            <input id="fiche-schedule" type="datetime-local">
          </label>
        </div>
        <label class="field">Note / motif (facultatif)<input id="fiche-note" placeholder="Précision interne, motif de rejet ou vérification…"></label>
        <div class="actions" style="margin-top:12px">
          <button type="button" class="primary" data-val-action="valider" data-etype="${normType}" data-eid="${entityId}">✓ Valider</button>
          <button type="button" data-val-action="modifier_message" data-etype="${normType}" data-eid="${entityId}">✎ Modifier le message</button>
          <button type="button" data-val-action="rejeter" data-etype="${normType}" data-eid="${entityId}">✕ Rejeter</button>
          <button type="button" class="danger" data-val-action="bloquer" data-etype="${normType}" data-eid="${entityId}">⊘ Bloquer définitivement</button>
          <button type="button" data-val-action="demander_verification" data-etype="${normType}" data-eid="${entityId}">? Demander une vérification</button>
          <button type="button" data-val-action="appeler" data-etype="${normType}" data-eid="${entityId}" data-tel-link="${telLink}">☎ Appeler</button>
          <button type="button" data-val-action="repondre_whatsapp" data-etype="${normType}" data-eid="${entityId}" data-wa-link="${waLink}">💬 Répondre sur WhatsApp</button>
          <button type="button" class="primary" data-val-action="envoyer_maintenant" data-etype="${normType}" data-eid="${entityId}">⇪ Envoyer maintenant</button>
          <button type="button" data-val-action="programmer_envoi" data-etype="${normType}" data-eid="${entityId}">◷ Programmer l’envoi</button>
        </div>
      </div>` +
      `<div class="card">
        <h3>Pipeline CRM (${isDem ? 'Familles' : 'Professionnels'})</h3>
        <form id="fiche-pipeline-form" data-etype="${normType}" data-eid="${entityId}" class="form-grid">
          <label class="field">Étape actuelle
            <select name="pipeline_stage">${Object.entries(pipeLabels).map(([k, lbl]) => `<option value="${k}" ${item.pipeline_stage === k ? 'selected' : ''}>${esc(lbl)}</option>`).join('')}</select>
          </label>
          <label class="field">Motif de perte (obligatoire si Perdu/Perdue)
            <input name="loss_reason" value="${esc(item.loss_reason || '')}" placeholder="Budget, délai, concurrent…">
          </label>
          <label class="field full">Note de suivi<input name="notes" value="${esc(item.notes || '')}" placeholder="Résumé d’échange ou prochaine étape…"></label>
          <div class="actions full"><button type="submit">Mettre à jour le pipeline</button></div>
        </form>
      </div>` +
      `<div class="card"><h3>Historique des envois (${(f.envois || []).length}) &amp; consentements (${(f.consentements || []).length})</h3>
        ${(f.envois || []).length ? (f.envois || []).map(e => `<div class="event"><strong>${esc(e.canal)} · ${esc(e.statut)}</strong> — ${esc(e.resultat || e.error_detail || '')}<br><small>${esc((e.created_at || '').replace('T', ' '))}</small></div>`).join('') : '<small>Aucun envoi enregistré.</small>'}
      </div>`
    );
  }

  // =========================================================================
  // Modales de création (Demande B2C, Prospect Pro, Découverte URL, Réponse/STOP)
  // =========================================================================
  function openNewDemandeModal() {
    modal(
      modalHead('Enregistrer une demande client (B2C)') +
      `<form id="auto-demande-form">
        <div class="form-grid">
          <label class="field">Nom du client<input name="nom" required maxlength="150"></label>
          <label class="field">Source entrante autorisée
            <select name="source">${B2C_SOURCES.map(([k, lbl]) => `<option value="${k}">${esc(lbl)}</option>`).join('')}</select>
          </label>
          <label class="field">Ville<input name="ville" placeholder="Casablanca"></label>
          <label class="field">Quartier / secteur<input name="quartier" placeholder="Anfa, Maârif, Californie, Bouskoura…"></label>
          <label class="field">Email<input name="email" type="email"></label>
          <label class="field">Téléphone<input name="tel" placeholder="+212 6…"></label>
          <label class="field">WhatsApp<input name="whatsapp" placeholder="+212 6…"></label>
          <label class="field">Canal préféré<select name="canal_prefere"><option value="">Auto</option><option value="email">Email</option><option value="whatsapp">WhatsApp</option><option value="appel">Téléphone</option></select></label>
        </div>
        <label class="field">Message exact du client (FR, Darija ou Arabe)<textarea name="message_brut" required rows="4" placeholder="Collez exactement la demande du client sans rien inventer…"></textarea></label>
        <div class="note">
          <label style="display:block;margin:6px 0"><input type="checkbox" name="consentement_recontact"> J’accepte que Yallah Services me recontacte au sujet de ma demande.</label>
          <label style="display:block;margin:6px 0"><input type="checkbox" name="consentement_whatsapp"> J’accepte de recevoir des messages de Yallah Services sur WhatsApp.</label>
          <small>Cases décochées par défaut. Ne cochez que si le client a explicitement consenti.</small>
        </div>
        <div class="error" id="auto-form-error"></div>
        <div class="actions"><button type="submit" class="primary">Analyser, scorer &amp; enregistrer</button></div>
      </form>`
    );
  }

  function openNewProModal() {
    modal(
      modalHead('Enregistrer un prospect professionnel (B2B)') +
      `<form id="auto-pro-form">
        <div class="form-grid">
          <label class="field">Nom de l’établissement<input name="nom_entreprise" required maxlength="160"></label>
          <label class="field">Segment
            <select name="type_etablissement">
              <option value="hotel">Hôtel / Hôtellerie</option>
              <option value="restaurant">Restaurant / Café</option>
              <option value="traiteur">Traiteur</option>
              <option value="evenementiel">Agence événementielle</option>
              <option value="residence">Résidence / Conciergerie</option>
              <option value="entreprise">Entreprise / Bureau</option>
              <option value="autre">Autre professionnel</option>
            </select>
          </label>
          <label class="field">Source publique autorisée
            <select name="source_nom">${B2B_SOURCES.map(([k, lbl]) => `<option value="${k}">${esc(lbl)}</option>`).join('')}</select>
          </label>
          <label class="field">URL de la source publique<input name="source_url" type="url" required placeholder="https://…"></label>
          <label class="field">Ville<input name="ville" value="Casablanca"></label>
          <label class="field">Quartier / zone<input name="quartier" placeholder="Anfa, Corniche, Sidi Maarouf…"></label>
          <label class="field">Email professionnel<input name="email_pro" type="email"></label>
          <label class="field">Téléphone<input name="tel_pro"></label>
          <label class="field">WhatsApp pro<input name="whatsapp_pro"></label>
          <label class="field">Niveau vérification<select name="niveau"><option value="A">A (vérifié)</option><option value="B">B (partiel)</option></select></label>
        </div>
        <label class="field">Besoin probable observé<input name="besoin_probable" placeholder="Ex : renfort serveurs, personnel de ménage, cuisine…"></label>
        <label class="field">Extrait / preuve publique<textarea name="preuve_extrait" rows="3" placeholder="Offre publiée, mention recrutement ou page contact officielle…"></textarea></label>
        <div class="error" id="auto-form-error"></div>
        <div class="actions"><button type="submit" class="primary">Scorer &amp; enregistrer</button></div>
      </form>`
    );
  }

  function openDiscoverProModal() {
    modal(
      modalHead('Découverte publique B2B (URL ou HTML)') +
      `<form id="auto-discover-form">
        <p class="sub">Respecte robots.txt et la limitation de débit. Les réseaux privés (Facebook, Instagram, TikTok, LinkedIn, groupes WhatsApp) sont automatiquement bloqués.</p>
        <label class="field">URL publique de l’établissement<input name="url" type="url" required placeholder="https://exemple-hotel-casablanca.ma/contact"></label>
        <label class="field">HTML public collé (facultatif — mode hors ligne)<textarea name="raw_html" rows="4" placeholder="Facultatif : collez l’extrait HTML d’une page publique si le réseau externe est restreint…"></textarea></label>
        <div class="error" id="auto-form-error"></div>
        <div class="actions"><button type="submit" class="primary">Extraire, scorer &amp; enregistrer</button></div>
      </form>`
    );
  }

  function openNewReponseModal() {
    modal(
      modalHead('Enregistrer une réponse entrante / STOP') +
      `<form id="auto-reponse-form">
        <p class="sub">Si le message contient STOP, STOP SMS, désinscription, ne plus me contacter, retirez-moi ou arrêtez, le contact est bloqué immédiatement et toutes ses relances sont annulées.</p>
        <div class="form-grid">
          <label class="field">Canal<select name="canal"><option value="email">Email</option><option value="whatsapp">WhatsApp</option><option value="appel">Téléphone</option></select></label>
          <label class="field">Expéditeur (email ou téléphone)<input name="expediteur" required placeholder="client@exemple.ma ou +2126…"></label>
        </div>
        <label class="field">Contenu du message<textarea name="contenu" required rows="4" placeholder="Ex : Bonjour, oui nous pouvons échanger demain / STOP"></textarea></label>
        <div class="error" id="auto-form-error"></div>
        <div class="actions"><button type="submit" class="primary">Traiter la réponse</button></div>
      </form>`
    );
  }

  // =========================================================================
  // Événements globaux (clics & formulaires)
  // =========================================================================
  document.addEventListener('click', async e => {
    const b = e.target.closest('button,a');
    if (!b) return;
    try {
      if (b.dataset.filterDemandeStage !== undefined) { filterDemandeStage = b.dataset.filterDemandeStage; render(); return; }
      if (b.dataset.filterDemandeClass !== undefined) { filterDemandeClass = b.dataset.filterDemandeClass; render(); return; }
      if (b.dataset.filterProStage !== undefined) { filterProspectStage = b.dataset.filterProStage; render(); return; }
      if (b.dataset.filterProClass !== undefined) { filterProspectClass = b.dataset.filterProClass; render(); return; }
      if (b.hasAttribute('data-new-demande')) { openNewDemandeModal(); return; }
      if (b.hasAttribute('data-new-pro')) { openNewProModal(); return; }
      if (b.hasAttribute('data-discover-pro')) { openDiscoverProModal(); return; }
      if (b.hasAttribute('data-new-reponse')) { openNewReponseModal(); return; }
      if (b.dataset.openFiche) { await openFiche(b.dataset.openFiche, Number(b.dataset.ficheId)); return; }

      if (b.dataset.autoDigest) {
        if (b.dataset.autoDigest === 'generate') {
          await postJson('/api/autonome/digest', {});
          toast('Daily Prospect Digest généré');
        } else {
          if (!confirm('Confirmer l’envoi du Daily Prospect Digest aux destinataires configurés ?')) return;
          const res = await postJson('/api/autonome/digest', { send: true });
          toast(`Daily Digest : email=${res.email_status}, whatsapp=${res.whatsapp_status}`);
        }
        return;
      }

      if (b.hasAttribute('data-autopilot-kill')) {
        if (!confirm('Désactiver immédiatement le mode Auto-pilot ?')) return;
        await postJson('/api/autonome/autopilot', { action: 'kill_switch', motif: 'Arrêt en un clic opérateur' });
        toast('Auto-pilot désactivé immédiatement');
        return;
      }

      if (b.dataset.autopilotRun) {
        const live = b.dataset.autopilotRun === 'live';
        if (live && !confirm('Confirmer l’exécution d’un cycle Auto-pilot réel ? Seuls les contacts niveau A conformes seront traités.')) return;
        const res = await postJson('/api/autonome/autopilot', { action: 'run', dry_run: !live });
        toast(res.ran ? `Cycle Auto-pilot : ${res.sent} traité(s), ${(res.skipped || []).length} ignoré(s)` : (res.reason || 'Auto-pilot inactif'));
        return;
      }

      if (b.dataset.valAction) {
        const act = b.dataset.valAction;
        const etype = b.dataset.etype;
        const eid = Number(b.dataset.eid);
        const msg = $('#fiche-msg-body')?.value || '';
        const canal = $('#fiche-channel')?.value || 'email';
        const note = $('#fiche-note')?.value || '';
        const sched = $('#fiche-schedule')?.value || '';
        const payload = { entity_type: etype, entity_id: eid, action: act, message: msg, canal, note, motif: note };

        if (act === 'bloquer') {
          if (!confirm('Bloquer définitivement ce contact (STOP) ? Toutes les relances seront annulées.')) return;
          payload.motif = note || 'Blocage définitif opérateur';
        }
        if (act === 'envoyer_maintenant') {
          if (!confirm(`Confirmer l’envoi explicite sur ${canal} ? (En mode manuel / simulation si YALLAH_ENABLE_LIVE!=1)`)) return;
          payload.confirm = true;
        }
        if (act === 'programmer_envoi') {
          if (!sched) { toast('Sélectionnez une date/heure pour programmer l’envoi.'); return; }
          if (!confirm(`Confirmer la programmation de l’envoi sur ${canal} pour le ${sched} ?`)) return;
          payload.confirm = true;
          payload.scheduled_at = sched;
        }
        await postJson('/api/autonome/validate', payload);
        if (act === 'appeler' && b.dataset.telLink) window.open(b.dataset.telLink, '_self');
        if (act === 'repondre_whatsapp' && b.dataset.waLink) window.open(b.dataset.waLink, '_blank', 'noopener,noreferrer');
        await openFiche(etype, eid);
        toast('Action enregistrée : ' + act);
      }
    } catch (err) {
      toast(err.message);
    }
  });

  document.addEventListener('submit', async e => {
    const f = e.target;
    if (!['auto-demande-form', 'auto-pro-form', 'auto-discover-form', 'auto-reponse-form', 'autopilot-form', 'fiche-pipeline-form'].includes(f.id)) return;
    e.preventDefault();
    const raw = new FormData(f);
    const v = Object.fromEntries(raw);
    try {
      if (f.id === 'auto-demande-form') {
        v.consentement_recontact = raw.get('consentement_recontact') === 'on';
        v.consentement_whatsapp = raw.get('consentement_whatsapp') === 'on';
        const res = await postJson('/api/autonome/demandes', v);
        $('#dialog').close();
        toast(`Demande ${res.reference} analysée · Score ${res.score}/100 (${res.classification})`);
      } else if (f.id === 'auto-pro-form') {
        const res = await postJson('/api/autonome/prospects', v);
        $('#dialog').close();
        toast(`Prospect ${res.reference} scoré ${res.score}/100 (${res.classification})`);
      } else if (f.id === 'auto-discover-form') {
        const res = await postJson('/api/autonome/prospects/discover', v);
        $('#dialog').close();
        toast(`Découverte réussie : ${res.saved?.reference || ''} · Score ${res.saved?.score ?? 0}/100 (${res.saved?.classification || ''})`);
      } else if (f.id === 'auto-reponse-form') {
        const res = await postJson('/api/autonome/reponses', v);
        $('#dialog').close();
        toast(res.stop_detecte ? `STOP détecté (${res.stop_mot_cle}) : contact bloqué définitivement` : 'Réponse enregistrée et relances annulées');
      } else if (f.id === 'autopilot-form') {
        const enable = raw.get('enabled') === 'on';
        if (enable && !confirm('Confirmer l’activation explicite du mode Auto-pilot (niveau A uniquement) ?')) return;
        await postJson('/api/autonome/autopilot', {
          action: 'config',
          enabled: enable,
          confirm: enable,
          max_first_contacts_per_day: Number(v.max_first_contacts_per_day),
          max_followups: Number(v.max_followups),
          bounce_threshold_pct: Number(v.bounce_threshold_pct),
          digest_hour: v.digest_hour || '08:00',
        });
        toast('Configuration Auto-pilot enregistrée');
      } else if (f.id === 'fiche-pipeline-form') {
        await postJson('/api/autonome/pipeline', {
          entity_type: f.dataset.etype,
          entity_id: Number(f.dataset.eid),
          pipeline_stage: v.pipeline_stage,
          loss_reason: v.loss_reason,
          notes: v.notes,
        });
        await openFiche(f.dataset.etype, Number(f.dataset.eid));
        toast('Pipeline mis à jour');
      }
    } catch (err) {
      const errBox = $('#auto-form-error');
      if (errBox) errBox.textContent = err.message;
      else toast(err.message);
    }
  });

  window.AutonomeUI = {
    pages: AUTONOME_PAGES,
    render(currentPage) {
      if (currentPage === 'acquisition') return renderAcquisition();
      if (currentPage === 'demandes') return renderDemandes();
      if (currentPage === 'prospection') return renderProspection();
      if (currentPage === 'file_envoi') return renderFileEnvoi();
    },
    shortcuts: {
      acquisition: '<button type="button" data-nav="demandes">⌂ Demandes clients</button><button type="button" data-nav="prospection">◈ Prospection B2B</button><button type="button" data-nav="file_envoi">⇪ File d’envoi</button>',
      demandes: '<button type="button" data-new-demande>+ Nouvelle demande</button><button type="button" data-nav="acquisition">✦ Acquisition autonome</button><button type="button" data-nav="file_envoi">⇪ File d’envoi</button>',
      prospection: '<button type="button" data-new-pro>+ Nouveau prospect pro</button><button type="button" data-discover-pro>⌕ Découvrir URL</button><button type="button" data-nav="file_envoi">⇪ File d’envoi</button>',
      file_envoi: '<button type="button" data-new-reponse>+ Enregistrer réponse / STOP</button><button type="button" data-nav="acquisition">✦ Acquisition autonome</button>',
    },
  };
})();
