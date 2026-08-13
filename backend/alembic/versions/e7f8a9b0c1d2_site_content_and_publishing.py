"""Editable site copy, and explicit permission to publish patient material.

The landing page grew from "clinic name plus a price list" into something a
clinic is judged by, so the copy has to be theirs to change. site_content is a
key/JSON table rather than columns on clinics: the page will keep gaining
sections and each one would otherwise cost a migration and a deploy.

The publishing columns matter more than the copy. Before/after photos and
written reviews are the two things that actually convert an aesthetics visitor,
and both already accumulate as a byproduct of ordinary operations — every visit
is photographed, every visit is followed by a rating request. What was missing
was permission, and permission is not a boolean:

  consent_given_at / consent_by / consent_note   the patient agreed, who
                                                 recorded it, and how
  is_published                                   the clinic chose this one

A photo goes public only when both are true, and clearing consent takes it down
immediately. Under Nghị định 13/2023 a patient's image tied to their treatment
is sensitive personal data; a clinical record must never drift into marketing
because someone forgot which switch did what.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, None] = 'd6e7f8a9b0c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'site_content',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('clinic_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('value', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['clinic_id'], ['clinics.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['updated_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('clinic_id', 'key', name='uq_site_content_key'),
    )
    op.create_index('ix_site_content_clinic_id', 'site_content', ['clinic_id'])
    op.create_index('ix_site_content_key', 'site_content', ['key'])

    # Patient photos: consent and publication, both defaulting to off. Existing
    # photos were taken as clinical records and nobody was asked about a website,
    # so none of them may become public by virtue of this migration running.
    op.add_column('visit_photos', sa.Column('consent_given_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('visit_photos', sa.Column('consent_by', sa.Integer(), nullable=True))
    op.add_column('visit_photos', sa.Column('consent_note', sa.String(), nullable=True))
    op.add_column('visit_photos', sa.Column('is_published', sa.Boolean(), nullable=False,
                                            server_default=sa.false()))
    op.add_column('visit_photos', sa.Column('showcase_group', sa.String(), nullable=True))
    op.add_column('visit_photos', sa.Column('public_title', sa.String(), nullable=True))
    op.create_index('ix_visit_photos_showcase_group', 'visit_photos', ['showcase_group'])
    with op.batch_alter_table('visit_photos') as batch:
        batch.create_foreign_key('fk_visit_photos_consent_by', 'users',
                                 ['consent_by'], ['id'], ondelete='SET NULL')

    # Reviews: same principle. A five-star rating was written for the clinic,
    # not for a public page, and the patient's name is personal data — so
    # publication is per-review and the displayed name is entered separately
    # rather than taken from the patient record.
    op.add_column('review_requests', sa.Column('is_published', sa.Boolean(), nullable=False,
                                               server_default=sa.false()))
    op.add_column('review_requests', sa.Column('public_name', sa.String(), nullable=True))
    op.add_column('review_requests', sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('review_requests', 'published_at')
    op.drop_column('review_requests', 'public_name')
    op.drop_column('review_requests', 'is_published')
    op.drop_index('ix_visit_photos_showcase_group', table_name='visit_photos')
    with op.batch_alter_table('visit_photos') as batch:
        batch.drop_constraint('fk_visit_photos_consent_by', type_='foreignkey')
    for column in ('public_title', 'showcase_group', 'is_published',
                   'consent_note', 'consent_by', 'consent_given_at'):
        op.drop_column('visit_photos', column)
    op.drop_index('ix_site_content_key', table_name='site_content')
    op.drop_index('ix_site_content_clinic_id', table_name='site_content')
    op.drop_table('site_content')
