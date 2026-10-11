-- Keep the private sample's residual identity assumption visible after approval.
ALTER TABLE alpaca_sample_stage ADD COLUMN identity_assumption text;
