-- A manually reviewed public constituent candidate may be staged for private use.
-- The source label remains distinct from the licensed FMP feed and test catalogs.
ALTER TABLE catalog_stage DROP CONSTRAINT catalog_stage_source_check;
ALTER TABLE catalog_stage ADD CONSTRAINT catalog_stage_source_check
    CHECK (source IN ('fmp-sp500', 'public-sp500-provisional-v1'));
