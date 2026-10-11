SELECT m.stock_id,
       count(b.stock_id) FILTER (WHERE b.close > 0 AND b.volume >= 0) AS observed_usable_days,
       count(b.stock_id) FILTER (
           WHERE b.close > 0 AND b.volume >= 0 AND (/* DAILY_CONDITION */)
       ) AS qualifying_days,
       min(b.provider_as_of) FILTER (WHERE b.close > 0 AND b.volume >= 0) AS data_as_of,
       bool_or(b.as_of_kind = 'provider') FILTER (WHERE b.close > 0 AND b.volume >= 0) AS has_provider_as_of,
       bool_or(b.as_of_kind = 'fetched') FILTER (WHERE b.close > 0 AND b.volume >= 0) AS has_fetched_as_of,
       bool_or(b.observation_status = 'provisional') FILTER (WHERE b.close > 0 AND b.volume >= 0) AS provisional,
       bool_or(b.traded_notional IS NOT NULL) FILTER (WHERE b.close > 0 AND b.volume >= 0) AS has_reported_notional,
       bool_or(b.traded_notional IS NULL AND b.vwap IS NOT NULL) FILTER (
           WHERE b.close > 0 AND b.volume >= 0
       ) AS has_vwap_estimate,
       bool_or(b.traded_notional IS NULL AND b.vwap IS NULL) FILTER (
           WHERE b.close > 0 AND b.volume >= 0
       ) AS has_close_estimate
FROM universe_member m
LEFT JOIN selected_daily_bar b ON b.stock_id = m.stock_id
    AND b.source = %s AND b.feed = %s AND b.price_basis = %s
    AND b.session_date BETWEEN %s AND %s
WHERE m.snapshot_id = %s
GROUP BY m.stock_id
ORDER BY m.stock_id
