"""integrity triggers: append-only audit log, immutable evidence/notes/verified findings

Defence in depth for NFR-2: even a bug or a stray SQL session cannot rewrite history.

Revision ID: a1b2c3d4e5f6
Revises: 51ce5ec38488
Create Date: 2026-11-09 04:30:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "51ce5ec38488"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE = r"""
-- ---------------------------------------------------------------- audit_log: append-only
CREATE OR REPLACE FUNCTION bm_forbid_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% on % is forbidden (append-only)', TG_OP, TG_TABLE_NAME
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;;

CREATE TRIGGER audit_log_append_only
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION bm_forbid_change();;
CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION bm_forbid_change();;

-- ---------------------------------------------------------------- notes: append-only
CREATE TRIGGER notes_append_only
    BEFORE UPDATE OR DELETE ON notes
    FOR EACH ROW EXECUTE FUNCTION bm_forbid_change();;

-- ---------------------------------------------------------------- evidence: immutable
-- Only the exclusion columns may change, and only from not-excluded to excluded.
CREATE OR REPLACE FUNCTION bm_evidence_immutable() RETURNS trigger AS $$
DECLARE
    mutable text[] := ARRAY['excluded', 'excluded_reason', 'excluded_at', 'excluded_by'];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'evidence cannot be deleted' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF (to_jsonb(NEW) - mutable) IS DISTINCT FROM (to_jsonb(OLD) - mutable) THEN
        RAISE EXCEPTION 'evidence is immutable' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF OLD.excluded AND (to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD)) THEN
        RAISE EXCEPTION 'evidence exclusion is final' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;;

CREATE TRIGGER evidence_immutable
    BEFORE UPDATE OR DELETE ON evidence
    FOR EACH ROW EXECUTE FUNCTION bm_evidence_immutable();;

-- ---------------------------------------------------------------- findings: verified = frozen
CREATE OR REPLACE FUNCTION bm_finding_frozen() RETURNS trigger AS $$
BEGIN
    IF OLD.status = 'verified' THEN
        RAISE EXCEPTION 'verified findings are immutable'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;;

CREATE TRIGGER findings_frozen_when_verified
    BEFORE UPDATE OR DELETE ON findings
    FOR EACH ROW EXECUTE FUNCTION bm_finding_frozen();;

CREATE OR REPLACE FUNCTION bm_finding_links_frozen() RETURNS trigger AS $$
DECLARE
    fid uuid;
BEGIN
    fid := CASE WHEN TG_OP = 'DELETE' THEN OLD.finding_id ELSE NEW.finding_id END;
    IF EXISTS (SELECT 1 FROM findings WHERE id = fid AND status = 'verified') THEN
        RAISE EXCEPTION 'evidence links of a verified finding are immutable'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;;

CREATE TRIGGER finding_evidence_frozen
    BEFORE INSERT OR UPDATE OR DELETE ON finding_evidence
    FOR EACH ROW EXECUTE FUNCTION bm_finding_links_frozen();;
"""

DOWNGRADE = r"""
DROP TRIGGER IF EXISTS finding_evidence_frozen ON finding_evidence;;
DROP FUNCTION IF EXISTS bm_finding_links_frozen();;
DROP TRIGGER IF EXISTS findings_frozen_when_verified ON findings;;
DROP FUNCTION IF EXISTS bm_finding_frozen();;
DROP TRIGGER IF EXISTS evidence_immutable ON evidence;;
DROP FUNCTION IF EXISTS bm_evidence_immutable();;
DROP TRIGGER IF EXISTS notes_append_only ON notes;;
DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log;;
DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log;;
DROP FUNCTION IF EXISTS bm_forbid_change();;
"""


def _statements(sql: str) -> list[str]:
    """Split on the ';;' marker (asyncpg runs one statement per call; $$ bodies contain ';')."""
    return [s.strip() for s in sql.split(";;") if s.strip()]


def upgrade() -> None:
    for statement in _statements(UPGRADE):
        op.execute(statement)


def downgrade() -> None:
    for statement in _statements(DOWNGRADE):
        op.execute(statement)
