-- Disposable full-universe benchmark data. Settings are supplied by the caller.
INSERT INTO sector(taxonomy, sector_code, sector_name)
SELECT 'benchmark', 'sector-' || n, 'Synthetic sector ' || n
FROM generate_series(1, 11) AS n;

INSERT INTO security(stock_id, name)
SELECT 'stock-' || n, 'Synthetic stock ' || n
FROM generate_series(1, current_setting('market_eagle.benchmark_stocks')::integer) AS n;

INSERT INTO universe_snapshot(snapshot_id, source, taxonomy, as_of, captured_at,
                              published_at, source_checksum, validation_state)
VALUES ('benchmark-snapshot', 'benchmark', 'benchmark',
        current_setting('market_eagle.benchmark_end')::date, now(), now(),
        'disposable-benchmark', 'published');

INSERT INTO universe_member(snapshot_id, stock_id, source_ticker, taxonomy, sector_code)
SELECT 'benchmark-snapshot', 'stock-' || n, 'SYM' || n, 'benchmark',
       'sector-' || ((n - 1) % 11 + 1)
FROM generate_series(1, current_setting('market_eagle.benchmark_stocks')::integer) AS n;

INSERT INTO catalog_current(singleton, snapshot_id)
VALUES (true, 'benchmark-snapshot');

INSERT INTO trading_session(exchange, session_date, session_type)
SELECT 'BENCHMARK', day::date, 'synthetic'
FROM generate_series(
    current_setting('market_eagle.benchmark_start')::date - interval '7 days',
    current_setting('market_eagle.benchmark_end')::date,
    interval '1 day'
) AS day
WHERE extract(isodow FROM day) <= 5;

INSERT INTO data_source(source, feed, rights_version, provider, synthetic)
VALUES ('benchmark', 'synthetic', 'disposable', 'generated', true);

INSERT INTO ingest_batch(batch_id, collection_run_id, source, feed, endpoint,
                         requested_symbols, requested_start, requested_end,
                         price_basis, fetched_at, parser_version, accepted_count,
                         rejected_count)
VALUES ('00000000-0000-0000-0000-000000000001', 'disposable-benchmark',
        'benchmark', 'synthetic', 'generated', '[]'::jsonb,
        current_setting('market_eagle.benchmark_start')::date - 7,
        current_setting('market_eagle.benchmark_end')::date,
        'raw', now(), 'benchmark-v1', 0, 0);

INSERT INTO daily_bar_revision(revision_id, stock_id, session_date, source, feed,
                               price_basis, open, high, low, close, volume,
                               provider_as_of, as_of_kind, observation_status,
                               fetched_at, batch_id, content_key)
SELECT md5(s.stock_id || ':' || t.session_date)::uuid,
       s.stock_id, t.session_date, 'benchmark', 'synthetic', 'raw',
       50 + substring(s.stock_id FROM 7)::integer / 10.0
          + (t.session_date - current_setting('market_eagle.benchmark_start')::date) / 1000.0,
       51 + substring(s.stock_id FROM 7)::integer / 10.0
          + (t.session_date - current_setting('market_eagle.benchmark_start')::date) / 1000.0,
       49 + substring(s.stock_id FROM 7)::integer / 10.0
          + (t.session_date - current_setting('market_eagle.benchmark_start')::date) / 1000.0,
       50 + substring(s.stock_id FROM 7)::integer / 10.0
          + (t.session_date - current_setting('market_eagle.benchmark_start')::date) / 1000.0,
       1000 + substring(s.stock_id FROM 7)::integer,
       t.session_date::timestamptz, 'provider', 'historical', now(),
       '00000000-0000-0000-0000-000000000001',
       md5('benchmark:' || s.stock_id || ':' || t.session_date)
FROM security AS s CROSS JOIN trading_session AS t;

INSERT INTO daily_bar_current(stock_id, session_date, source, feed, price_basis,
                              revision_id, selected_provider_as_of, last_checked_at)
SELECT stock_id, session_date, source, feed, price_basis, revision_id,
       provider_as_of, fetched_at
FROM daily_bar_revision;

ANALYZE;
