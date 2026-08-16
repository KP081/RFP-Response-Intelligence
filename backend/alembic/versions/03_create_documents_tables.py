"""03_create_documents_tables

Revision ID: 03_create_documents_tables
Revises: a99d25c5fbc2
Create Date: 2026-08-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.db.rls import enable_rls

# revision identifiers, used by Alembic.
revision: str = '03_create_documents_tables'
down_revision: Union[str, Sequence[str], None] = 'a99d25c5fbc2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Create document_type enum type
    document_type_enum = postgresql.ENUM(
        'rfp',
        'rfq',
        'rfi',
        'knowledge_base',
        'other',
        name='document_type',
        create_type=True
    )
    document_type_enum.create(op.get_bind(), checkfirst=True)

    # Create document_status enum type
    document_status_enum = postgresql.ENUM(
        'uploaded',
        'processing',
        'ready',
        'failed',
        name='document_status',
        create_type=True
    )
    document_status_enum.create(op.get_bind(), checkfirst=True)

    # Create documents table (RLS-scoped)
    op.create_table(
        'documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('uploaded_by_user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('document_type', sa.Enum('rfp', 'rfq', 'rfi', 'knowledge_base', 'other', name='document_type', native_enum=False), nullable=False, server_default='other'),
        sa.Column('status', sa.Enum('uploaded', 'processing', 'ready', 'failed', name='document_status', native_enum=False), nullable=False, server_default='uploaded'),
        sa.Column('storage_key', sa.String(500), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_documents_org_id', 'documents', ['org_id'])
    op.create_index('ix_documents_uploaded_by_user_id', 'documents', ['uploaded_by_user_id'])

    # Create document_versions table (RLS-scoped)
    op.create_table(
        'document_versions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('org_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('storage_key', sa.String(500), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['orgs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_document_versions_org_id', 'document_versions', ['org_id'])
    op.create_index('ix_document_versions_document_id', 'document_versions', ['document_id'])
    op.create_unique_constraint('uq_document_version', 'document_versions', ['document_id', 'id'])

    # Enable RLS on tenant-scoped tables with FORCE to prevent owner bypass.
    for table in ['documents', 'document_versions']:
        for stmt in enable_rls(table):
            op.execute(stmt)


def downgrade() -> None:
    """Downgrade schema."""

    # Drop tables (cascade will clean up RLS policies)
    op.drop_table('document_versions')
    op.drop_table('documents')

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS document_status CASCADE;")
    op.execute("DROP TYPE IF EXISTS document_type CASCADE;")