ALTER TABLE trading_session ADD COLUMN calendar_source text;

CREATE TABLE alpaca_collection_preparation (
    preparation_id uuid PRIMARY KEY,
    snapshot_id text NOT NULL REFERENCES universe_snapshot(snapshot_id),
    source_checksum text NOT NULL,
    fetched_at timestamptz NOT NULL,
    requested_start date NOT NULL,
    requested_end date NOT NULL,
    comparison_session date NOT NULL,
    calendar_source text NOT NULL DEFAULT 'alpaca-trading-calendar',
    status text NOT NULL CHECK (status IN ('held', 'prepared')),
    reviewed_by text,
    review_note text,
    reviewed_at timestamptz,
    CHECK (comparison_session < requested_start AND requested_start <= requested_end)
);

CREATE TABLE alpaca_preparation_asset (
    preparation_id uuid NOT NULL REFERENCES alpaca_collection_preparation(preparation_id),
    asset_id uuid NOT NULL,
    symbol text NOT NULL,
    exchange text NOT NULL,
    name text NOT NULL,
    asset_status text NOT NULL,
    asset_class text NOT NULL,
    PRIMARY KEY (preparation_id, asset_id),
    UNIQUE (preparation_id, symbol, exchange)
);

CREATE TABLE alpaca_preparation_session (
    preparation_id uuid NOT NULL REFERENCES alpaca_collection_preparation(preparation_id),
    session_date date NOT NULL,
    open_at timestamptz NOT NULL,
    close_at timestamptz NOT NULL,
    session_type text NOT NULL CHECK (session_type IN ('regular', 'half_day')),
    PRIMARY KEY (preparation_id, session_date),
    CHECK (open_at < close_at)
);

CREATE TABLE alpaca_alias_approval (
    preparation_id uuid NOT NULL REFERENCES alpaca_collection_preparation(preparation_id),
    stock_id text NOT NULL REFERENCES security(stock_id),
    asset_id uuid NOT NULL,
    symbol text NOT NULL,
    exchange text NOT NULL,
    verified_from date NOT NULL,
    verified_to date,
    evidence text NOT NULL,
    PRIMARY KEY (preparation_id, stock_id),
    UNIQUE (preparation_id, asset_id),
    UNIQUE (preparation_id, symbol),
    FOREIGN KEY (preparation_id, asset_id)
        REFERENCES alpaca_preparation_asset(preparation_id, asset_id),
    CHECK (verified_to IS NULL OR verified_to >= verified_from)
);
