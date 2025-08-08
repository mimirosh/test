# alembic revision -m "add password_hash to operators"

from alembic import op
import sqlalchemy as sa

revision = "add_password_hash_to_operators"
down_revision = "<prev_revision>"  # подставь

def upgrade():
    op.add_column("operators", sa.Column("password_hash", sa.Text(), nullable=True))
    # опционально, если email должен быть уникальным:
    # op.create_unique_constraint("uq_operators_email", "operators", ["email"])

def downgrade():
    # op.drop_constraint("uq_operators_email", "operators", type_="unique")
    op.drop_column("operators", "password_hash")
