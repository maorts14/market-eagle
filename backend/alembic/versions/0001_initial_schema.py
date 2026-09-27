"""Create the Market Eagle application schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-27
"""

from alembic import op

from app import models  # noqa: F401
from app.database import Base


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
