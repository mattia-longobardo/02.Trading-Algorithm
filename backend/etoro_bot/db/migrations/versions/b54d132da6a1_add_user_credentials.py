"""add user credentials

Revision ID: b54d132da6a1
Revises: ff6b6aa54307
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b54d132da6a1"
down_revision: Union[str, None] = "ff6b6aa54307"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_credentials",
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("etoro_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("etoro_user_key_encrypted", sa.Text(), nullable=True),
        sa.Column("openai_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_credentials")
