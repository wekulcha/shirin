"""Remove the retired Market integration replay cache.

Revision ID: 7b425c210cc9
Revises: 4dfa111600fd
"""

import sqlalchemy as sa
from alembic import op

revision = "7b425c210cc9"
down_revision = "4dfa111600fd"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_integration_nonces_expires_at", table_name="integration_nonces")
    op.drop_table("integration_nonces")


def downgrade():
    op.create_table(
        "integration_nonces",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_integration_nonces_expires_at", "integration_nonces", ["expires_at"])
