-- Research records live in the application database, shared by API and worker.
CREATE TABLE agent_conversation (
    id text PRIMARY KEY,
    active_turn_id text,
    summary text,
    summary_through_turn_id text,
    summary_version integer NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE agent_turn (
    id text PRIMARY KEY,
    sequence_id bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
    conversation_id text NOT NULL REFERENCES agent_conversation(id) ON DELETE CASCADE,
    request_id text NOT NULL,
    question text NOT NULL,
    reference_date date NOT NULL,
    status text NOT NULL CHECK (status IN
        ('running', 'cancel_requested', 'completed', 'needs_clarification',
         'unsupported', 'failed', 'cancelled')),
    decision_json text,
    evidence_id text,
    explanation text,
    error text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    UNIQUE (conversation_id, request_id)
);

CREATE INDEX agent_turn_by_conversation ON agent_turn (conversation_id, sequence_id DESC);
CREATE INDEX agent_conversation_recent ON agent_conversation (updated_at DESC, id DESC);

CREATE TABLE agent_evidence (
    id text PRIMARY KEY,
    turn_id text NOT NULL UNIQUE REFERENCES agent_turn(id) ON DELETE CASCADE,
    result_json text NOT NULL
);

CREATE TABLE agent_turn_trace (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    turn_id text NOT NULL REFERENCES agent_turn(id) ON DELETE CASCADE,
    stage text NOT NULL,
    detail_json text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX agent_trace_by_turn ON agent_turn_trace (turn_id, id);
