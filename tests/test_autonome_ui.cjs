// Tests DOM des 4 nouvelles pages autonomes, des 9 boutons de validation et du formulaire public /demande
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { execFileSync } = require('node:child_process');
const { JSDOM } = require('jsdom');

const fixture = JSON.parse(execFileSync('python3', ['-c', `
import json, tempfile
from pathlib import Path
import webapp, campaigns, operations, yallah_autonome as autonome
with tempfile.TemporaryDirectory() as directory:
    webapp.DB = Path(directory) / 'test_ui.sqlite3'
    webapp.initialize()
    dem = autonome.capturer_demande_b2c({
        'nom': 'Nadia Benjelloun', 'ville': 'Casablanca', 'quartier': 'Anfa',
        'email': 'nadia@exemple.ma', 'whatsapp': '+212661112233',
        'message_brut': 'Bonjour, je cherche une femme de ménage à Anfa 3 fois par semaine.',
        'source': 'formulaire_prestation',
        'consentement_recontact': True, 'consentement_whatsapp': True,
    })
    autonome.generer_daily_digest()
    fiche = autonome.fiche_detail('demande', dem['id'])
    data = webapp.state()
    data['token'] = 'test-token'
    data['user'] = {'username': 'admin', 'role': 'admin'}
    print(json.dumps({
        'state': data,
        'automation': campaigns.dashboard(),
        'operations': operations.dashboard(),
        'health': campaigns.health(),
        'fiche': fiche,
    }))
`], { encoding: 'utf8' }));

async function setupFullApp(role = 'admin') {
  const dom = new JSDOM(readFileSync('web/index.html', 'utf8'), {
    url: 'https://example.invalid', runScripts: 'outside-only',
  });
  const w = dom.window;
  const requests = [];
  w.fetch = async (url, options) => {
    requests.push({ url, options });
    assert(!options?.method, 'Navigation UI ne doit jamais écrire ou envoyer automatiquement.');
    let payload = fixture.state;
    if (url === '/api/campaigns') payload = fixture.automation;
    else if (url === '/api/operations') payload = fixture.operations;
    else if (url === '/api/health') payload = fixture.health;
    else if (url.startsWith('/api/autonome/fiche')) payload = fixture.fiche;
    else {
      payload = JSON.parse(JSON.stringify(fixture.state));
      payload.user = { username: role, role };
    }
    return { ok: true, json: async () => JSON.parse(JSON.stringify(payload)) };
  };
  w.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  w.HTMLDialogElement.prototype.close = function () { this.open = false; };
  w.eval(
    readFileSync('web/operations.js', 'utf8') + '\n' +
    readFileSync('web/autonome.js', 'utf8') + '\n' +
    readFileSync('web/app.js', 'utf8')
  );
  await new Promise(resolve => setImmediate(resolve));
  return { dom, w, document: w.document, requests };
}

test('4 nouvelles pages autonomes rendues sans écriture avec barre d’outils et KPIs', async t => {
  const { dom, document, requests } = await setupFullApp('admin');
  t.after(() => dom.window.close());

  for (const p of ['acquisition', 'demandes', 'prospection', 'file_envoi']) {
    const btn = document.querySelector(`#nav [data-nav="${p}"]`);
    assert(btn, `Bouton nav manquant pour ${p}`);
    btn.click();
    assert(document.querySelector('.feature-toolbar button[data-refresh]'), `Bouton refresh manquant sur ${p}`);
    assert(document.querySelectorAll('.feature-toolbar button').length >= 2, `Moins de 2 boutons sur ${p}`);
  }

  // Vérifier Acquisition autonome (Admin) : Daily Digest, Auto-pilot Kill Switch & Export Audit
  document.querySelector('#nav [data-nav="acquisition"]').click();
  assert(document.querySelector('[data-autopilot-kill]'), 'Kill switch Auto-pilot manquant pour admin');
  assert(document.querySelector('a[href="/api/audit/export?format=csv"]'), 'Lien export audit CSV manquant pour admin');
  assert.match(document.querySelector('#content').textContent, /Daily Prospect Digest/);
  assert.match(document.querySelector('#content').textContent, /DÉSACTIVÉ/);

  // Vérifier Demandes Clients (8 étapes pipeline Familles) + ouverture fiche avec les 9 boutons de validation
  document.querySelector('#nav [data-nav="demandes"]').click();
  assert.equal(document.querySelectorAll('[data-filter-demande-stage]').length, 9); // 8 étapes + Toutes
  document.querySelector('[data-open-fiche="demande_b2c"]').click();
  await new Promise(resolve => setImmediate(resolve));
  const valActions = [...document.querySelectorAll('#modal [data-val-action]')].map(b => b.dataset.valAction);
  for (const expected of ['valider', 'modifier_message', 'rejeter', 'bloquer', 'demander_verification', 'appeler', 'repondre_whatsapp', 'envoyer_maintenant', 'programmer_envoi']) {
    assert(valActions.includes(expected), `Bouton validation manquant : ${expected}`);
  }

  // Vérifier Prospection B2B (9 étapes pipeline Professionnels)
  document.querySelector('#close').click();
  document.querySelector('#nav [data-nav="prospection"]').click();
  assert.equal(document.querySelectorAll('[data-filter-pro-stage]').length, 10); // 9 étapes + Tous

  assert(requests.every(r => !r.options?.method));
});

test('Auto-pilot et Export Audit masqués pour un compte commercial non-admin', async t => {
  const { dom, document } = await setupFullApp('commercial');
  t.after(() => dom.window.close());
  document.querySelector('#nav [data-nav="acquisition"]').click();
  assert.equal(document.querySelector('[data-autopilot-kill]'), null);
  assert.equal(document.querySelector('a[href="/api/audit/export?format=csv"]'), null);
  assert.match(document.querySelector('#content').textContent, /Seul un administrateur/);
});

test('formulaire public /demande : 2 cases distinctes non précochées et mention STOP exacte', async t => {
  const dom = new JSDOM(readFileSync('web/public.html', 'utf8'), { url: 'https://example.invalid/demande' });
  t.after(() => dom.window.close());
  const doc = dom.window.document;
  const c1 = doc.querySelector('input[name="consentement_recontact"][type="checkbox"]');
  const c2 = doc.querySelector('input[name="consentement_whatsapp"][type="checkbox"]');
  assert(c1 && !c1.checked, 'Case consentement_recontact doit exister et être décochée');
  assert(c2 && !c2.checked, 'Case consentement_whatsapp doit exister et être décochée');
  const txt = doc.body.textContent;
  assert(txt.includes('J’accepte que Yallah Services me recontacte au sujet de ma demande.'));
  assert(txt.includes('J’accepte de recevoir des messages de Yallah Services sur WhatsApp.'));
  assert(txt.includes('Vous pouvez demander l’arrêt des communications à tout moment en répondant STOP.'));
});
