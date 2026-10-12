ALTER TABLE data_source ADD COLUMN private_use_approved boolean NOT NULL DEFAULT false;

CREATE TABLE ongoing_collection_approval (
    approval_id uuid PRIMARY KEY,
    preparation_id uuid NOT NULL UNIQUE REFERENCES alpaca_collection_preparation(preparation_id),
    snapshot_id text NOT NULL REFERENCES universe_snapshot(snapshot_id),
    catalog_source text NOT NULL,
    source text NOT NULL,
    feed text NOT NULL,
    price_basis text NOT NULL,
    rights_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('active', 'held')),
    reviewed_by text NOT NULL,
    review_note text NOT NULL,
    reviewed_at timestamptz NOT NULL DEFAULT now(),
    CHECK (source = 'alpaca' AND feed = 'sip' AND price_basis = 'raw'),
    CHECK (catalog_source IN ('fmp-sp500', 'public-sp500-provisional-v1'))
);
