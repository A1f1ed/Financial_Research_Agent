"""PostgreSQL business data and durable dispatch

Revision ID: 5a8715157474
Revises: none
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '5a8715157474'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE SCHEMA IF NOT EXISTS research')
    op.execute('CREATE SCHEMA IF NOT EXISTS agent')
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table('cache',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('fetched', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_cache')),
    schema='research'
    )
    op.create_table('candidate_observations',
    sa.Column('symbol', sa.String(length=30), nullable=False),
    sa.Column('session', sa.String(length=10), nullable=False),
    sa.Column('benchmark', sa.String(length=30), nullable=False),
    sa.Column('origin', sa.String(length=40), nullable=False),
    sa.Column('report_id', sa.String(length=160), server_default='', nullable=False),
    sa.Column('record_order', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.PrimaryKeyConstraint('symbol', 'session', 'benchmark', 'origin', 'report_id', name=op.f('pk_candidate_observations')),
    sa.UniqueConstraint('record_order', name=op.f('uq_candidate_observations_record_order')),
    schema='research'
    )
    op.create_table('followups',
    sa.Column('thread_id', sa.String(length=160), nullable=False),
    sa.Column('message_id', sa.String(length=160), nullable=False),
    sa.Column('report_id', sa.String(length=160), server_default='', nullable=False),
    sa.Column('questions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('thread_id', 'message_id', 'report_id', name=op.f('pk_followups')),
    schema='research'
    )
    op.create_table('hidden_tasks',
    sa.Column('id', sa.String(length=160), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hidden_tasks')),
    schema='research'
    )
    op.create_table('jobs',
    sa.Column('id', sa.String(length=160), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('schedule_id', sa.String(length=160), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('cancel_requested', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('lease_token', sa.String(length=80), nullable=True),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('record_order', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_jobs')),
    sa.UniqueConstraint('record_order', name=op.f('uq_jobs_record_order')),
    schema='research'
    )
    op.create_index(op.f('ix_jobs_schedule_id'), 'jobs', ['schedule_id'], unique=False, schema='research')
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False, schema='research')
    op.create_index('uq_jobs_active_schedule', 'jobs', ['schedule_id'], unique=True, schema='research', postgresql_where=sa.text("schedule_id IS NOT NULL AND status IN ('queued', 'running')"))
    op.create_table('outbox',
    sa.Column('id', sa.String(length=160), nullable=False),
    sa.Column('topic', sa.String(length=100), nullable=False),
    sa.Column('aggregate_id', sa.String(length=160), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('deduplication_key', sa.String(length=250), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outbox')),
    sa.UniqueConstraint('deduplication_key', name=op.f('uq_outbox_deduplication_key')),
    schema='research'
    )
    op.create_index('ix_outbox_pending', 'outbox', ['available_at'], unique=False, schema='research', postgresql_where=sa.text('delivered_at IS NULL'))
    op.create_table('preferences',
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_preferences')),
    schema='research'
    )
    op.create_table('reports',
    sa.Column('id', sa.String(length=160), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('archived', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('record_order', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reports')),
    sa.UniqueConstraint('record_order', name=op.f('uq_reports_record_order')),
    schema='research'
    )
    op.create_table('review_candidates',
    sa.Column('symbol', sa.String(length=30), nullable=False),
    sa.Column('session', sa.String(length=10), nullable=False),
    sa.Column('benchmark', sa.String(length=30), nullable=False),
    sa.Column('note', sa.Text(), server_default='', nullable=False),
    sa.Column('record_order', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.PrimaryKeyConstraint('symbol', name=op.f('pk_review_candidates')),
    sa.UniqueConstraint('record_order', name=op.f('uq_review_candidates_record_order')),
    schema='research'
    )
    op.create_table('review_checks',
    sa.Column('id', sa.String(length=160), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('settled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('record_order', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_review_checks')),
    sa.UniqueConstraint('record_order', name=op.f('uq_review_checks_record_order')),
    schema='research'
    )
    op.create_table('run_events',
    sa.Column('sequence', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('run_id', sa.String(length=160), nullable=False),
    sa.Column('event_id', sa.String(length=160), nullable=False),
    sa.Column('kind', sa.String(length=80), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('sequence', name=op.f('pk_run_events')),
    sa.UniqueConstraint('event_id', name=op.f('uq_run_events_event_id')),
    schema='research'
    )
    op.create_index(op.f('ix_run_events_run_id'), 'run_events', ['run_id'], unique=False, schema='research')
    op.create_table('schedules',
    sa.Column('id', sa.String(length=160), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('next_run', sa.DateTime(timezone=True), nullable=True),
    sa.Column('archived', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('record_order', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_schedules')),
    sa.UniqueConstraint('record_order', name=op.f('uq_schedules_record_order')),
    schema='research'
    )
    op.create_index('ix_schedules_next_run', 'schedules', ['next_run'], unique=False, schema='research')


def downgrade():
    op.drop_index('ix_schedules_next_run', table_name='schedules', schema='research')
    op.drop_table('schedules', schema='research')
    op.drop_index(op.f('ix_run_events_run_id'), table_name='run_events', schema='research')
    op.drop_table('run_events', schema='research')
    op.drop_table('review_checks', schema='research')
    op.drop_table('review_candidates', schema='research')
    op.drop_table('reports', schema='research')
    op.drop_table('preferences', schema='research')
    op.drop_index('ix_outbox_pending', table_name='outbox', schema='research', postgresql_where=sa.text('delivered_at IS NULL'))
    op.drop_table('outbox', schema='research')
    op.drop_index('uq_jobs_active_schedule', table_name='jobs', schema='research', postgresql_where=sa.text("schedule_id IS NOT NULL AND status IN ('queued', 'running')"))
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs', schema='research')
    op.drop_index(op.f('ix_jobs_schedule_id'), table_name='jobs', schema='research')
    op.drop_table('jobs', schema='research')
    op.drop_table('hidden_tasks', schema='research')
    op.drop_table('followups', schema='research')
    op.drop_table('candidate_observations', schema='research')
    op.drop_table('cache', schema='research')
    # Checkpoint schema and shared extensions are managed independently and are
    # intentionally not dropped by a business-schema downgrade.
