-- =============================================================================
-- Yallah Services (Casablanca, Maroc) — Schéma PostgreSQL prêt pour la production
-- Compatible avec la structure SQLite embarquée dans yallah_autonome.py
-- 14 tables minimales : sources, contacts, consentements, demandes_clients,
-- prospects, messages, campagnes, envois, reponses, blocages, relances,
-- daily_digests, audit_log, settings
-- =============================================================================

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id BIGINT,
    detail TEXT NOT NULL DEFAULT '',
    created TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log (created DESC);

CREATE TABLE IF NOT EXISTS sources (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL,
    categorie TEXT NOT NULL CHECK (categorie IN ('b2c_entrant', 'b2b_public')),
    url TEXT NOT NULL DEFAULT '',
    extrait_preuve TEXT NOT NULL DEFAULT '',
    consulte_le TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    autorise BOOLEAN NOT NULL DEFAULT TRUE,
    created TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_sources_code ON sources (code);

CREATE TABLE IF NOT EXISTS contacts (
    id BIGSERIAL PRIMARY KEY,
    type_contact TEXT NOT NULL CHECK (type_contact IN ('b2c', 'b2b')),
    nom TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    email_norm TEXT NOT NULL DEFAULT '',
    tel TEXT NOT NULL DEFAULT '',
    tel_norm TEXT NOT NULL DEFAULT '',
    whatsapp TEXT NOT NULL DEFAULT '',
    whatsapp_norm TEXT NOT NULL DEFAULT '',
    ville TEXT NOT NULL DEFAULT '',
    quartier TEXT NOT NULL DEFAULT '',
    langue_preferee TEXT NOT NULL DEFAULT 'fr',
    canal_prefere TEXT NOT NULL DEFAULT '',
    dedup_key TEXT NOT NULL UNIQUE,
    created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts (email_norm);
CREATE INDEX IF NOT EXISTS idx_contacts_tel ON contacts (tel_norm);
CREATE INDEX IF NOT EXISTS idx_contacts_wa ON contacts (whatsapp_norm);

CREATE TABLE IF NOT EXISTS consentements (
    id BIGSERIAL PRIMARY KEY,
    contact_id BIGINT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    canal TEXT NOT NULL CHECK (canal IN ('recontact', 'email', 'whatsapp', 'telephone', 'sms')),
    accorde BOOLEAN NOT NULL,
    preuve TEXT NOT NULL,
    source_code TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    notice_version TEXT NOT NULL DEFAULT '2026-11-28',
    retire_le TIMESTAMPTZ,
    actor TEXT NOT NULL DEFAULT 'system',
    created TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_consentements_contact_canal ON consentements (contact_id, canal, created DESC);

CREATE TABLE IF NOT EXISTS demandes_clients (
    id BIGSERIAL PRIMARY KEY,
    reference TEXT NOT NULL UNIQUE,
    contact_id BIGINT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    source_id BIGINT REFERENCES sources(id) ON DELETE SET NULL,
    intake_id BIGINT,
    nom TEXT NOT NULL,
    ville TEXT NOT NULL DEFAULT '',
    quartier TEXT NOT NULL DEFAULT '',
    type_besoin TEXT NOT NULL DEFAULT '',
    type_contrat TEXT NOT NULL DEFAULT '',
    frequence TEXT NOT NULL DEFAULT '',
    date_souhaitee TEXT NOT NULL DEFAULT '',
    urgence TEXT NOT NULL DEFAULT '',
    budget_indicatif TEXT NOT NULL DEFAULT '',
    langue_detectee TEXT NOT NULL DEFAULT 'fr',
    canal_prefere TEXT NOT NULL DEFAULT '',
    canal_recommande TEXT NOT NULL DEFAULT '',
    contraintes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    message_brut TEXT NOT NULL,
    analyse_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    score INTEGER NOT NULL DEFAULT 0 CHECK (score BETWEEN 0 AND 100),
    score_detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    classification TEXT NOT NULL DEFAULT 'B' CHECK (classification IN ('A', 'B', 'C', 'Exclu')),
    consentement_recontact BOOLEAN NOT NULL DEFAULT FALSE,
    consentement_whatsapp BOOLEAN NOT NULL DEFAULT FALSE,
    statut_validation TEXT NOT NULL DEFAULT 'a_valider'
        CHECK (statut_validation IN ('a_valider', 'valide', 'rejete', 'bloque', 'verification_demandee', 'programme', 'envoye')),
    etape_pipeline TEXT NOT NULL DEFAULT 'demande_recue'
        CHECK (etape_pipeline IN (
            'demande_recue', 'qualifiee', 'rdv_programme', 'besoin_confirme',
            'candidats_proposes', 'mission_confirmee', 'gagnee', 'perdue'
        )),
    motif_perte TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    doublon_de BIGINT REFERENCES demandes_clients(id) ON DELETE SET NULL,
    created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_demandes_class_score ON demandes_clients (classification, score DESC);
CREATE INDEX IF NOT EXISTS idx_demandes_pipeline ON demandes_clients (etape_pipeline);

CREATE TABLE IF NOT EXISTS prospects (
    id BIGSERIAL PRIMARY KEY,
    reference TEXT NOT NULL UNIQUE,
    contact_id BIGINT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    source_id BIGINT REFERENCES sources(id) ON DELETE SET NULL,
    record_id BIGINT,
    nom TEXT NOT NULL,
    segment TEXT NOT NULL DEFAULT 'entreprise',
    ville TEXT NOT NULL DEFAULT 'Casablanca',
    quartier TEXT NOT NULL DEFAULT '',
    besoin_probable TEXT NOT NULL DEFAULT '',
    signaux_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    potentiel_estime TEXT NOT NULL DEFAULT 'moyen',
    source_type TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    source_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    preuve_extrait TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    tel TEXT NOT NULL DEFAULT '',
    whatsapp TEXT NOT NULL DEFAULT '',
    canal_recommande TEXT NOT NULL DEFAULT '',
    score INTEGER NOT NULL DEFAULT 0 CHECK (score BETWEEN 0 AND 100),
    score_detail_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    classification TEXT NOT NULL DEFAULT 'B' CHECK (classification IN ('A', 'B', 'C', 'Exclu')),
    statut_validation TEXT NOT NULL DEFAULT 'a_valider'
        CHECK (statut_validation IN ('a_valider', 'valide', 'rejete', 'bloque', 'verification_demandee', 'programme', 'envoye')),
    etape_pipeline TEXT NOT NULL DEFAULT 'prospect_identifie'
        CHECK (etape_pipeline IN (
            'prospect_identifie', 'contact_valide', 'message_envoye', 'reponse_recue',
            'rdv_programme', 'besoin_confirme', 'proposition_envoyee', 'gagne', 'perdu'
        )),
    motif_perte TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_prospects_class_score ON prospects (classification, score DESC);
CREATE INDEX IF NOT EXISTS idx_prospects_pipeline ON prospects (etape_pipeline);

CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('demande', 'prospect')),
    entity_id BIGINT NOT NULL,
    contact_id BIGINT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    canal TEXT NOT NULL CHECK (canal IN ('email', 'whatsapp', 'telephone')),
    langue TEXT NOT NULL DEFAULT 'fr',
    type_message TEXT NOT NULL DEFAULT 'initial',
    objet TEXT NOT NULL DEFAULT '',
    corps TEXT NOT NULL,
    alertes_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    statut TEXT NOT NULL DEFAULT 'brouillon'
        CHECK (statut IN ('brouillon', 'valide', 'modifie', 'rejete', 'envoye')),
    valide_par TEXT NOT NULL DEFAULT '',
    valide_le TIMESTAMPTZ,
    created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_messages_entity ON messages (entity_type, entity_id);

CREATE TABLE IF NOT EXISTS campagnes (
    id BIGSERIAL PRIMARY KEY,
    nom TEXT NOT NULL,
    type_cible TEXT NOT NULL CHECK (type_cible IN ('b2b', 'b2c')),
    canal TEXT NOT NULL CHECK (canal IN ('email', 'whatsapp')),
    mode TEXT NOT NULL DEFAULT 'manuel' CHECK (mode IN ('manuel', 'simulation', 'autopilot')),
    statut TEXT NOT NULL DEFAULT 'brouillon',
    plafond_jour INTEGER NOT NULL DEFAULT 15,
    created_by TEXT NOT NULL DEFAULT 'system',
    created TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS envois (
    id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('demande', 'prospect')),
    entity_id BIGINT NOT NULL,
    contact_id BIGINT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    message_id BIGINT REFERENCES messages(id) ON DELETE SET NULL,
    campagne_id BIGINT REFERENCES campagnes(id) ON DELETE SET NULL,
    canal TEXT NOT NULL CHECK (canal IN ('email', 'whatsapp', 'telephone')),
    destination TEXT NOT NULL,
    objet TEXT NOT NULL DEFAULT '',
    message_final TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'simulation' CHECK (mode IN ('manuel', 'simulation', 'reel', 'autopilot')),
    statut TEXT NOT NULL DEFAULT 'en_attente'
        CHECK (statut IN ('en_attente', 'programme', 'simule', 'envoye', 'bloque', 'echoue', 'annule')),
    preuve_consentement TEXT NOT NULL DEFAULT '',
    scheduled_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    provider_id TEXT NOT NULL DEFAULT '',
    resultat TEXT NOT NULL DEFAULT '',
    erreur TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT 'system',
    created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_envois_contact_date ON envois (contact_id, created DESC);
CREATE INDEX IF NOT EXISTS idx_envois_statut ON envois (statut);

CREATE TABLE IF NOT EXISTS reponses (
    id BIGSERIAL PRIMARY KEY,
    contact_id BIGINT REFERENCES contacts(id) ON DELETE SET NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id BIGINT,
    canal TEXT NOT NULL,
    expediteur TEXT NOT NULL,
    objet TEXT NOT NULL DEFAULT '',
    contenu TEXT NOT NULL,
    est_stop BOOLEAN NOT NULL DEFAULT FALSE,
    mot_cle_stop TEXT NOT NULL DEFAULT '',
    provider_id TEXT NOT NULL DEFAULT '',
    created TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_reponses_contact ON reponses (contact_id);

CREATE TABLE IF NOT EXISTS blocages (
    id BIGSERIAL PRIMARY KEY,
    contact_key TEXT NOT NULL UNIQUE,
    contact_id BIGINT REFERENCES contacts(id) ON DELETE SET NULL,
    canal TEXT NOT NULL DEFAULT 'tous',
    motif TEXT NOT NULL,
    mot_cle TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT 'system',
    created TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_blocages_contact ON blocages (contact_id);

CREATE TABLE IF NOT EXISTS relances (
    id BIGSERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('demande', 'prospect')),
    entity_id BIGINT NOT NULL,
    contact_id BIGINT NOT NULL REFERENCES contacts(id) ON DELETE RESTRICT,
    envoi_initial_id BIGINT REFERENCES envois(id) ON DELETE SET NULL,
    etape INTEGER NOT NULL CHECK (etape IN (1, 2, 3)),
    delai_jours INTEGER NOT NULL CHECK (delai_jours IN (3, 7, 14)),
    canal TEXT NOT NULL,
    scheduled_at TIMESTAMPTZ NOT NULL,
    statut TEXT NOT NULL DEFAULT 'planifiee'
        CHECK (statut IN ('planifiee', 'envoyee', 'annulee', 'bloquee')),
    motif_annulation TEXT NOT NULL DEFAULT '',
    message_corps TEXT NOT NULL DEFAULT '',
    created TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_relances_sched ON relances (statut, scheduled_at);

CREATE TABLE IF NOT EXISTS daily_digests (
    id BIGSERIAL PRIMARY KEY,
    digest_date DATE NOT NULL UNIQUE,
    payload_json JSONB NOT NULL,
    email_subject TEXT NOT NULL DEFAULT '',
    email_html TEXT NOT NULL DEFAULT '',
    email_text TEXT NOT NULL DEFAULT '',
    whatsapp_body TEXT NOT NULL DEFAULT '',
    sent_email_at TIMESTAMPTZ,
    sent_whatsapp_at TIMESTAMPTZ,
    created TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
