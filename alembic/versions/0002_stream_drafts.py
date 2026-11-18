"""Local draft editor state and removed-offer archive.

Revision ID: 0002_stream_drafts
Revises: 0001_initial
"""
from alembic import op
import sqlalchemy as sa

revision = '0002_stream_drafts'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'stream_drafts',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('campaign_id', sa.Integer, sa.ForeignKey('owned_campaigns.id'), nullable=False, unique=True),
        sa.Column('stream_id', sa.Integer, nullable=False),
        sa.Column('base_revision', sa.String(64), nullable=False),
        sa.Column('published_json', sa.Text, nullable=False),
        sa.Column('draft_json', sa.Text, nullable=False),
        sa.Column('version', sa.Integer, nullable=False),
        sa.Column('dirty', sa.Boolean, nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('stream_drafts')
