-- Staged FMP catalog observations never become the current universe by themselves.
CREATE TABLE catalog_stage (
    stage_id uuid PRIMARY KEY,
    source text NOT NULL CHECK (source = 'fmp-sp500'),
    endpoint text NOT NULL,
    fetched_at timestamptz NOT NULL,
    source_checksum text NOT NULL,
    baseline_snapshot_id text REFERENCES universe_snapshot(snapshot_id),
    row_count integer NOT NULL CHECK (row_count > 0 AND row_count <= 700),
    minimum_count integer NOT NULL CHECK (minimum_count > 0 AND minimum_count <= 700),
    status text NOT NULL CHECK (status IN ('held', 'published')),
    validation_issues jsonb NOT NULL DEFAULT '[]'::jsonb,
    reviewed_by text,
    review_note text,
    reviewed_at timestamptz,
    published_snapshot_id text REFERENCES universe_snapshot(snapshot_id),
    CHECK ((status = 'published') = (published_snapshot_id IS NOT NULL))
);

CREATE INDEX catalog_stage_recent_idx ON catalog_stage (fetched_at DESC);

CREATE TABLE catalog_stage_member (
    stage_id uuid NOT NULL REFERENCES catalog_stage(stage_id),
    symbol text NOT NULL,
    name text NOT NULL,
    sector_label text NOT NULL,
    sub_sector text,
    cik text,
    date_first_added date,
    suggested_stock_id text REFERENCES security(stock_id),
    PRIMARY KEY (stage_id, symbol)
);
