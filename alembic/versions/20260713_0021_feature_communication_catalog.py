"""feature communication catalog

Revision ID: 20260713_0021
Revises: 20260713_0020
Create Date: 2026-07-13 13:10:00
"""

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "20260713_0021"
down_revision = "20260713_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feature_communication_catalog",
        sa.Column("feature_id", sa.String(length=128), nullable=False),
        sa.Column("module", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("functional_description", sa.Text(), nullable=False, server_default=""),
        sa.Column("user_benefit", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_roles", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("target_modules", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("minimum_version", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("availability", sa.String(length=64), nullable=False, server_default="general"),
        sa.Column("deep_link_template", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("communication_priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("last_communicated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("minimum_repeat_delay", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("source_evidence_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.PrimaryKeyConstraint("feature_id"),
    )

    now = datetime.now(timezone.utc)
    op.bulk_insert(
        sa.table(
            "feature_communication_catalog",
            sa.column("feature_id", sa.String()),
            sa.column("module", sa.String()),
            sa.column("title", sa.String()),
            sa.column("functional_description", sa.Text()),
            sa.column("user_benefit", sa.Text()),
            sa.column("target_roles", sa.JSON()),
            sa.column("target_modules", sa.JSON()),
            sa.column("minimum_version", sa.String()),
            sa.column("availability", sa.String()),
            sa.column("deep_link_template", sa.String()),
            sa.column("communication_priority", sa.Integer()),
            sa.column("last_communicated_at", sa.DateTime(timezone=True)),
            sa.column("minimum_repeat_delay", sa.Integer()),
            sa.column("source_evidence_ids", sa.JSON()),
            sa.column("enabled", sa.Boolean()),
        ),
        [
            {
                "feature_id": "planning_weekly_review",
                "module": "planning",
                "title": "Rappel utile sur votre revue planning",
                "functional_description": "Le module planning peut servir de point d'entree simple pour revoir vos actions de la semaine.",
                "user_benefit": "Retrouver rapidement les points a verifier dans votre routine MAPSI.",
                "target_roles": [],
                "target_modules": ["planning"],
                "minimum_version": "1.0.0",
                "availability": "general",
                "deep_link_template": "https://{instance_key}.example/planning",
                "communication_priority": 20,
                "last_communicated_at": None,
                "minimum_repeat_delay": 21,
                "source_evidence_ids": ["catalog:planning_weekly_review"],
                "enabled": True,
            },
            {
                "feature_id": "risk_review_tip",
                "module": "risk",
                "title": "Astuce pour mieux suivre vos risques",
                "functional_description": "Une revue courte et reguliere du module risque aide a garder les bonnes priorites visibles.",
                "user_benefit": "Rendre le suivi des risques plus simple d'une semaine a l'autre.",
                "target_roles": ["risk_manager", "risk_officer"],
                "target_modules": ["risk"],
                "minimum_version": "1.0.0",
                "availability": "targeted",
                "deep_link_template": "https://{instance_key}.example/risk",
                "communication_priority": 15,
                "last_communicated_at": None,
                "minimum_repeat_delay": 28,
                "source_evidence_ids": ["catalog:risk_review_tip"],
                "enabled": True,
            },
            {
                "feature_id": "document_workflow_guide",
                "module": "documents",
                "title": "Mini-parcours pour vos documents MAPSI",
                "functional_description": "Un mini-parcours simple aide a reprendre les bons gestes dans le module documentaire.",
                "user_benefit": "Mieux utiliser un workflow documentaire sans surcharge technique.",
                "target_roles": ["document_manager", "records_manager"],
                "target_modules": ["documents"],
                "minimum_version": "1.0.0",
                "availability": "targeted",
                "deep_link_template": "https://{instance_key}.example/documents",
                "communication_priority": 25,
                "last_communicated_at": now,
                "minimum_repeat_delay": 35,
                "source_evidence_ids": ["catalog:document_workflow_guide"],
                "enabled": True,
            },
            {
                "feature_id": "new_user_navigation_tip",
                "module": "dashboard",
                "title": "Premier repere pour vos 14 premiers jours",
                "functional_description": "Un repere simple aide les nouveaux utilisateurs a trouver plus vite le bon point d'entree dans MAPSI.",
                "user_benefit": "Prendre plus vite ses marques dans MAPSI.",
                "target_roles": [],
                "target_modules": [],
                "minimum_version": "1.0.0",
                "availability": "general",
                "deep_link_template": "https://{instance_key}.example/",
                "communication_priority": 30,
                "last_communicated_at": None,
                "minimum_repeat_delay": 14,
                "source_evidence_ids": ["catalog:new_user_navigation_tip"],
                "enabled": True,
            },
        ],
    )

    if op.get_bind().dialect.name != "sqlite":
        for column in (
            "module",
            "title",
            "functional_description",
            "user_benefit",
            "target_roles",
            "target_modules",
            "minimum_version",
            "availability",
            "deep_link_template",
            "communication_priority",
            "minimum_repeat_delay",
            "source_evidence_ids",
            "enabled",
        ):
            op.alter_column("feature_communication_catalog", column, server_default=None)


def downgrade() -> None:
    op.drop_table("feature_communication_catalog")
