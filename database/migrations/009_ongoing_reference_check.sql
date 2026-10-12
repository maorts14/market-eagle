CREATE TABLE ongoing_reference_check (
    approval_id uuid NOT NULL REFERENCES ongoing_collection_approval(approval_id),
    checked_on date NOT NULL,
    checked_at timestamptz NOT NULL,
    coverage_start date NOT NULL,
    coverage_end date NOT NULL,
    matched_assets integer NOT NULL CHECK (matched_assets >= 0),
    status text NOT NULL CHECK (status IN ('passed', 'failed')),
    PRIMARY KEY (approval_id, checked_on),
    CHECK (coverage_start <= coverage_end),
    CHECK (status = 'failed' OR matched_assets >= 450)
);
