"""Create ownership and audit tables.

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'owned_campaigns',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('instance_url', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('alias', sa.String(255), nullable=False),
        sa.Column('owner_marker', sa.String(120), nullable=False, unique=True),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('geo_stream_id', sa.Integer),
        sa.Column('offers_stream_id', sa.Integer),
        sa.Column('error', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('campaign_id', sa.Integer, sa.ForeignKey('owned_campaigns.id'), nullable=False),
        sa.Column('action', sa.String(48), nullable=False),
        sa.Column('details', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

def downgrade():
    op.drop_table('audit_logs')
    op.drop_table('owned_campaigns')
