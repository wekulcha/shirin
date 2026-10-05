"""Keep Telegram update IDs independent for the three Shirin bots.

Revision ID: 850bd278e491
Revises: 7b425c210cc9
"""

import sqlalchemy as sa
from alembic import op

revision = "850bd278e491"
down_revision = "7b425c210cc9"
branch_labels = None
depends_on = None


def queue_table(name, roles):
    columns = [sa.Column("id", sa.BigInteger(), primary_key=True)]
    if roles:
        columns.append(sa.Column("bot_role", sa.String(16), primary_key=True))
    return op.create_table(
        name,
        *columns,
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
    )


def upgrade():
    old = sa.table(
        "webhook_updates",
        sa.column("id"), sa.column("payload"), sa.column("state"),
        sa.column("attempts"), sa.column("next_attempt_at"),
    )
    new = queue_table("webhook_updates_by_bot", roles=True)
    op.get_bind().execute(new.insert().from_select(
        ["id", "bot_role", "payload", "state", "attempts", "next_attempt_at"],
        sa.select(old.c.id, sa.literal("user"), old.c.payload, old.c.state, old.c.attempts, old.c.next_attempt_at),
    ))
    op.drop_table("webhook_updates")
    op.rename_table("webhook_updates_by_bot", "webhook_updates")


def downgrade():
    # The previous app had only the user bot. Keep its updates on downgrade.
    old = sa.table(
        "webhook_updates", sa.column("id"), sa.column("bot_role"), sa.column("payload"),
        sa.column("state"), sa.column("attempts"), sa.column("next_attempt_at"),
    )
    new = queue_table("webhook_updates_single_bot", roles=False)
    fields = ["id", "payload", "state", "attempts", "next_attempt_at"]
    op.get_bind().execute(new.insert().from_select(
        fields, sa.select(*(old.c[field] for field in fields)).where(old.c.bot_role == "user"),
    ))
    op.drop_table("webhook_updates")
    op.rename_table("webhook_updates_single_bot", "webhook_updates")
