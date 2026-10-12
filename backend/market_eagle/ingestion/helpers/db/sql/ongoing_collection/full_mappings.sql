SELECT count(*) AS members,
       count(a.stock_id) FILTER (
           WHERE a.verified_from <= %(target)s
             AND a.verified_to IS NULL
             AND EXISTS (
                 SELECT 1 FROM alpaca_preparation_asset pa
                 WHERE pa.preparation_id = a.preparation_id
                   AND pa.asset_id = a.asset_id
                   AND pa.symbol = a.symbol
                   AND pa.exchange = a.exchange
                   AND pa.asset_status = 'active'
                   AND pa.asset_class = 'us_equity'
             )
             AND (
                 SELECT count(*) FROM security_symbol ss
                 WHERE ss.stock_id = a.stock_id
                   AND ss.source = 'alpaca'
                   AND ss.valid_from <= %(target)s
                   AND (ss.valid_to IS NULL OR ss.valid_to >= %(target)s)
             ) = 1
             AND EXISTS (
                 SELECT 1 FROM security_symbol ss
                 WHERE ss.stock_id = a.stock_id
                   AND ss.source = 'alpaca'
                   AND ss.ticker = a.symbol
                   AND ss.exchange = a.exchange
                   AND ss.valid_from <= %(target)s
                   AND ss.valid_to IS NULL
             )
       ) AS mapped
FROM universe_member m
LEFT JOIN alpaca_alias_approval a
  ON a.preparation_id = %(preparation_id)s AND a.stock_id = m.stock_id
WHERE m.snapshot_id = %(snapshot_id)s;
