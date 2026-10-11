SELECT b.stock_id, b.session_date, b.close, b.volume, b.vwap,
       b.traded_notional, b.provider_as_of, b.as_of_kind, b.observation_status
FROM selected_daily_bar b
JOIN universe_member m ON m.stock_id = b.stock_id
WHERE m.snapshot_id = %s AND b.source = %s AND b.feed = %s
  AND b.price_basis = %s AND b.session_date = ANY(%s::date[])
ORDER BY b.stock_id, b.session_date
