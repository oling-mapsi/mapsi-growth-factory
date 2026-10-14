"""Persist targeted editorial repair parameters without replacing existing jobs."""
from alembic import op
import sqlalchemy as sa

revision = "20261014_0026"
down_revision = "20261014_0025"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("simple_generation_jobs", sa.Column("parameters", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("simple_generation_jobs", "parameters")
