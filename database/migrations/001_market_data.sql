-- Application database only. Temporal uses separate databases and credentials.
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE security (
    stock_id text PRIMARY KEY,
    name text NOT NULL,
    share_class text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE security_symbol (
    stock_id text NOT NULL REFERENCES security(stock_id),
    ticker text NOT NULL,
    exchange text NOT NULL,
    valid_from date NOT NULL,
    valid_to date,
    source text NOT NULL,
    PRIMARY KEY (stock_id, ticker, exchange, valid_from, source),
    CHECK (valid_to IS NULL OR valid_to >= valid_from),
    EXCLUDE USING gist (source WITH =, ticker WITH =, exchange WITH =,
        daterange(valid_from, valid_to, '[]') WITH &&)
);

CREATE TABLE sector (
    taxonomy text NOT NULL,
    sector_code text NOT NULL,
    sector_name text NOT NULL,
    PRIMARY KEY (taxonomy, sector_code)
);

CREATE TABLE universe_snapshot (
    snapshot_id text PRIMARY KEY,
    source text NOT NULL,
    taxonomy text NOT NULL,
    as_of date NOT NULL,
    captured_at timestamptz NOT NULL,
    published_at timestamptz,
    source_checksum text NOT NULL,
    validation_state text NOT NULL CHECK (validation_state IN ('held', 'published')),
    CHECK ((validation_state = 'published') = (published_at IS NOT NULL))
);

CREATE TABLE universe_member (
    snapshot_id text NOT NULL REFERENCES universe_snapshot(snapshot_id),
    stock_id text NOT NULL REFERENCES security(stock_id),
    source_ticker text NOT NULL,
    taxonomy text NOT NULL,
    sector_code text NOT NULL,
    PRIMARY KEY (snapshot_id, stock_id),
    FOREIGN KEY (taxonomy, sector_code) REFERENCES sector(taxonomy, sector_code),
    UNIQUE (snapshot_id, source_ticker)
);

CREATE TABLE catalog_current (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    snapshot_id text NOT NULL REFERENCES universe_snapshot(snapshot_id)
);

CREATE TABLE listing_period (
    stock_id text NOT NULL REFERENCES security(stock_id),
    exchange text NOT NULL,
    valid_from date NOT NULL,
    valid_to date,
    source text NOT NULL,
    PRIMARY KEY (stock_id, exchange, valid_from, source),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);

CREATE TABLE trading_session (
    exchange text NOT NULL,
    session_date date NOT NULL,
    session_type text NOT NULL CHECK (session_type IN ('regular', 'half_day', 'synthetic')),
    open_at timestamptz,
    close_at timestamptz,
    PRIMARY KEY (exchange, session_date)
);

CREATE TABLE data_source (
    source text NOT NULL,
    feed text NOT NULL,
    rights_version text NOT NULL,
    provider text NOT NULL,
    synthetic boolean NOT NULL DEFAULT false,
    PRIMARY KEY (source, feed)
);

CREATE TABLE ingest_batch (
    batch_id uuid PRIMARY KEY,
    collection_run_id text NOT NULL,
    source text NOT NULL,
    feed text NOT NULL,
    endpoint text NOT NULL,
    requested_symbols jsonb NOT NULL,
    requested_start date NOT NULL,
    requested_end date NOT NULL,
    price_basis text NOT NULL,
    fetched_at timestamptz NOT NULL,
    provider_as_of timestamptz,
    parser_version text NOT NULL,
    accepted_count integer NOT NULL,
    rejected_count integer NOT NULL,
    FOREIGN KEY (source, feed) REFERENCES data_source(source, feed),
    CHECK (requested_start <= requested_end),
    CHECK (accepted_count >= 0 AND rejected_count >= 0)
);

CREATE TABLE daily_bar_revision (
    revision_id uuid PRIMARY KEY,
    stock_id text NOT NULL REFERENCES security(stock_id),
    session_date date NOT NULL,
    source text NOT NULL,
    feed text NOT NULL,
    price_basis text NOT NULL,
    open numeric(24, 8) NOT NULL,
    high numeric(24, 8) NOT NULL,
    low numeric(24, 8) NOT NULL,
    close numeric(24, 8) NOT NULL,
    volume bigint NOT NULL,
    vwap numeric(24, 8),
    traded_notional numeric(30, 8),
    provider_as_of timestamptz NOT NULL,
    as_of_kind text NOT NULL CHECK (as_of_kind IN ('provider', 'fetched')),
    observation_status text NOT NULL CHECK (observation_status IN ('historical', 'provisional')),
    fetched_at timestamptz NOT NULL,
    batch_id uuid NOT NULL REFERENCES ingest_batch(batch_id),
    content_key text NOT NULL UNIQUE,
    FOREIGN KEY (source, feed) REFERENCES data_source(source, feed),
    CHECK (open > 0 AND high > 0 AND low > 0 AND close > 0),
    CHECK (high >= greatest(open, close, low) AND low <= least(open, close, high)),
    CHECK (volume >= 0),
    CHECK (vwap IS NULL OR vwap > 0),
    CHECK (traded_notional IS NULL OR traded_notional >= 0),
    UNIQUE (revision_id, stock_id, session_date, source, feed, price_basis)
);

CREATE INDEX daily_bar_revision_history_idx
    ON daily_bar_revision (stock_id, session_date, source, feed, price_basis, provider_as_of DESC);

CREATE TABLE daily_bar_current (
    stock_id text NOT NULL,
    session_date date NOT NULL,
    source text NOT NULL,
    feed text NOT NULL,
    price_basis text NOT NULL,
    revision_id uuid NOT NULL UNIQUE,
    selected_provider_as_of timestamptz NOT NULL,
    last_checked_at timestamptz NOT NULL,
    PRIMARY KEY (stock_id, session_date, source, feed, price_basis),
    FOREIGN KEY (revision_id, stock_id, session_date, source, feed, price_basis)
        REFERENCES daily_bar_revision(revision_id, stock_id, session_date, source, feed, price_basis)
);

CREATE INDEX daily_bar_current_window_idx
    ON daily_bar_current (source, feed, price_basis, session_date, stock_id);

CREATE VIEW selected_daily_bar AS
SELECT c.stock_id, c.session_date, c.source, c.feed, c.price_basis,
       r.open, r.high, r.low, r.close, r.volume, r.vwap, r.traded_notional,
       r.provider_as_of, r.as_of_kind, r.observation_status, r.fetched_at,
       c.last_checked_at, r.revision_id
FROM daily_bar_current c
JOIN daily_bar_revision r ON r.revision_id = c.revision_id;
