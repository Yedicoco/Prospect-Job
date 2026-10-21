// Tests DOM sans navigateur et sans appel externe / envoi de prospection.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { execFileSync } = require('node:child_process');
const { JSDOM } = require('jsdom');

const fixture = JSON.parse(execFileSync('python3', ['-c', `
import json, tempfile
from pathlib import Path
import webapp, campaigns, operations
with tempfile.TemporaryDirectory() as directory:
    webapp.DB = Path(directory) / 'test.sqlite3'
    webapp.initialize()
    operations.execute('opportunity', {'record_id':1,'title':'Besoin de test','stage':'besoin_confirme','owner':'Équipe','next_action':'Confirmer','due':webapp.validation.today().isoformat()})
    data = webapp.state()
    data['token'] = 'test-token'
    print(json.dumps({'state': data, 'automation': campaigns.dashboard(), 'operations': operations.dashboard(), 'health': campaigns.health()}))
`], { encoding: 'utf8' }));

async function setup() {
  const dom = new JSDOM(readFileSync('web/index.html', 'utf8'), {
    url: 'https://example.invalid', runScripts: 'outside-only',
  });
  const w = dom.window;
  const requests = [];
  w.fetch = async (url, options) => {
    requests.push({ url, options });
    assert(!options?.method, 'Les boutons de raccourci ne doivent pas écrire ni envoyer.');
    return { ok: true, json: async () => JSON.parse(JSON.stringify(url === '/api/campaigns' ? fixture.automation : url === '/api/operations' ? fixture.operations : url === '/api/health' ? fixture.health : fixture.state)) };
  };
  w.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  w.HTMLDialogElement.prototype.close = function () { this.open = false; };
  w.eval(readFileSync('web/operations.js', 'utf8')+'\n'+readFileSync('web/app.js', 'utf8'));
  await new Promise(resolve => setImmediate(resolve));
  return { dom, w, document: w.document, requests };
}

function click(document, selector) {
  const element = document.querySelector(selector);
  assert(element, 'Bouton introuvable : ' + selector);
  element.click();
}

test('accès rapide : formulaires B2B, B2C et besoin confirmé', async t => {
  const { dom, document } = await setup();
  t.after(() => dom.window.close());
  assert.equal(document.querySelectorAll('.feature-button').length, 9);
  for (const kind of ['b2b', 'b2c', 'emploi']) {
    click(document, `.feature-center [data-new="${kind}"]`);
    assert.equal(document.querySelector('#editform').dataset.kind, kind);
    click(document, '#close');
  }
});

test('simulation email et WhatsApp : canal présélectionné sans envoi', async t => {
  const { dom, document, requests } = await setup();
  t.after(() => dom.window.close());
  for (const channel of ['email', 'whatsapp']) {
    click(document, `.feature-center [data-new-campaign="${channel}"]`);
    assert.equal(document.querySelector('#campaignform [name="channel"]').value, channel);
    assert.equal(document.querySelectorAll('#campaignform input[name="ids"]:checked').length, 0);
    assert.match(document.querySelector('#campaignform button').textContent, /aucun envoi/);
    click(document, '#close');
  }
  assert(requests.every(r => !r.options?.method));
});

test('boutons de filtrage et réinitialisation', async t => {
  const { dom, document } = await setup();
  t.after(() => dom.window.close());
  click(document, '[data-shortcut="verify"]');
  assert.equal(document.querySelector('#status').value, 'A ACTUALISER');
  click(document, '[data-reset-filters]');
  assert.equal(document.querySelector('#status').value, '');
  click(document, '.feature-toolbar [data-nav="messages"]');
  click(document, '[data-shortcut="ready"]');
  assert.equal(document.querySelector('#status').value, 'PRET - envoi manuel');
});

test('toutes les rubriques proposent des boutons contextuels', async t => {
  const { dom, document } = await setup();
  t.after(() => dom.window.close());
  for (const page of ['prospects', 'messages', 'emploi', 'b2c', 'campaigns', 'history', 'crm', 'tasks', 'recruitment', 'inbox', 'insights', 'system']) {
    click(document, `#nav [data-nav="${page}"]`);
    assert(document.querySelector('.feature-toolbar button[data-refresh]'));
    assert(document.querySelectorAll('.feature-toolbar button').length >= 2);
  }
});

test('état fournisseur, export et actualisation', async t => {
  const { dom, document, requests } = await setup();
  t.after(() => dom.window.close());
  const csv = document.querySelector('.feature-center a[download]');
  assert(csv.href.includes('/api/export?'));
  assert.equal(csv.getAttribute('download'), 'messages.csv');
  click(document, '[data-provider-settings]');
  assert.match(document.querySelector('#modal').textContent, /Resend/);
  assert.match(document.querySelector('#modal').textContent, /Meta/);
  assert.equal(document.querySelectorAll('#modal input').length, 0);
  click(document, '#close');
  const before = requests.length;
  click(document, '[data-refresh]');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests.length, before + 4);
  assert.match(document.querySelector('#toast').textContent, /actualisées/);
});


test('CRM : opportunité, tâches et besoin lié accessible avec confirmation', async t => {
  const { dom, document } = await setup();
  t.after(() => dom.window.close());
  click(document, '#nav [data-nav="crm"]');
  assert.equal(document.querySelectorAll('.pipeline-column').length, 8);
  click(document, '[data-op-detail]');
  click(document, '[data-opp-need]');
  assert.equal(document.querySelector('#editform').dataset.opportunityId, '1');
  assert(document.querySelector('[name="confirm_need"][required]'));
});

test('recrutement : champs de disponibilité et accord requis', async t => {
  const { dom, document } = await setup();
  t.after(() => dom.window.close());
  click(document, '#nav [data-nav="recruitment"]');
  click(document, '[data-op-form="candidate"]');
  assert(document.querySelector('[name="skills"][multiple][required]'));
  assert(document.querySelector('[name="availability_verified"][required]'));
  assert(document.querySelector('[name="consent_proof"][required]'));
});

test('supervision : aucun clic de navigation ne déclenche un arrêt ou une sauvegarde', async t => {
  const { dom, document, requests } = await setup();
  t.after(() => dom.window.close());
  click(document, '#nav [data-nav="system"]');
  assert(document.querySelector('[data-global-stop="true"]'));
  assert(document.querySelector('#backup-now'));
  assert(requests.every(r => !r.options?.method));
});
