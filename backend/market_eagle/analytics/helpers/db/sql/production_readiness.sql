SELECT EXISTS (
    SELECT 1
    FROM catalog_current AS cc
    JOIN universe_snapshot AS snapshot
      ON snapshot.snapshot_id = cc.snapshot_id
    JOIN data_source AS price_source
      ON price_source.source = %s
     AND price_source.feed = %s
    WHERE cc.singleton
      AND snapshot.source IN ('fmp-sp500', 'public-sp500-provisional-v1')
      AND snapshot.validation_state = 'published'
      AND NOT price_source.synthetic
      AND (
          SELECT count(*)
          FROM universe_member AS member
          WHERE member.snapshot_id = snapshot.snapshot_id
      ) >= 450
) AS ready;
