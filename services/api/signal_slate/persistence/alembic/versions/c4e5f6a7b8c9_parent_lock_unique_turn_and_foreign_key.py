"""parent_lock_unique_turn_and_foreign_key

Revision ID: c4e5f6a7b8c9
Revises: b7fabd84d9b9
Create Date: 2026-09-08 22:35:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e5f6a7b8c9"
down_revision: str | None = "b7fabd84d9b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Clean up any orphaned test rows in turn_reservations before adding foreign key
    op.execute(
        "DELETE FROM turn_reservations "
        "WHERE workflow_id NOT IN (SELECT workflow_id FROM workflow_sessions)"
    )

    # Add unique constraint on (workflow_id, turn_number)
    op.create_unique_constraint(
        "uq_turn_reservations_wf_turn",
        "turn_reservations",
        ["workflow_id", "turn_number"],
    )

    # Add foreign key from turn_reservations.workflow_id to workflow_sessions.workflow_id
    op.create_foreign_key(
        "fk_turn_reservations_workflow_id",
        "turn_reservations",
        "workflow_sessions",
        ["workflow_id"],
        ["workflow_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_turn_reservations_workflow_id", "turn_reservations", type_="foreignkey")
    op.drop_constraint("uq_turn_reservations_wf_turn", "turn_reservations", type_="unique")
