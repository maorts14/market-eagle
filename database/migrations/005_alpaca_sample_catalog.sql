-- A private five-stock validation cohort. It never changes catalog_current.
CREATE TABLE alpaca_sample_stage (
    stage_id uuid PRIMARY KEY,
    source_checksum text NOT NULL,
    fetched_at timestamptz NOT NULL,
    requested_start date NOT NULL,
    requested_end date NOT NULL,
    comparison_session date NOT NULL,
    status text NOT NULL CHECK (status IN ('held', 'published')),
    reviewed_by text,
    review_note text,
    reviewed_at timestamptz,
    snapshot_id text REFERENCES universe_snapshot(snapshot_id),
    preparation_id uuid REFERENCES alpaca_collection_preparation(preparation_id),
    CHECK (comparison_session < requested_start AND requested_start <= requested_end),
    CHECK ((status = 'published') = (snapshot_id IS NOT NULL AND preparation_id IS NOT NULL))
);

CREATE TABLE alpaca_sample_asset (
    stage_id uuid NOT NULL REFERENCES alpaca_sample_stage(stage_id),
    asset_id uuid NOT NULL,
    stock_id text NOT NULL,
    symbol text NOT NULL,
    exchange text NOT NULL,
    name text NOT NULL,
    PRIMARY KEY (stage_id, asset_id),
    UNIQUE (stage_id, stock_id),
    UNIQUE (stage_id, symbol)
);

CREATE TABLE alpaca_sample_session (
    stage_id uuid NOT NULL REFERENCES alpaca_sample_stage(stage_id),
    session_date date NOT NULL,
    open_at timestamptz NOT NULL,
    close_at timestamptz NOT NULL,
    session_type text NOT NULL CHECK (session_type IN ('regular', 'half_day')),
    PRIMARY KEY (stage_id, session_date),
    CHECK (open_at < close_at)
);
