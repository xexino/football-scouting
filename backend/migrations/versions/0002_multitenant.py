"""Multi-tenant organizations (schema + data migration).

Existing single-club data is moved into ONE organization ("legacy organization") so that
nothing becomes shared reference data by accident:

* every row of every tenant table gets that organization's id;
* users.role/region become memberships of that organization;
* private player fields move to player_assessments (currency-neutral names);
* recruitment budget columns lose their "_eur" suffix;
* global unique constraints become per-organization constraints;
* child tables get composite same-organization foreign keys.

Downgrade is only possible while a single organization exists.

Revision ID: 0002_multitenant
Revises: 0001_legacy
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_multitenant"
down_revision: Union[str, Sequence[str], None] = "0001_legacy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIVATE = ["audit_logs", "match_videos", "video_observations", "match_reports", "scouting_reports",
           "pipeline_entries", "pipeline_events", "recruitment_budgets"]
SHARED_OR_PRIVATE = ["data_sources", "leagues", "clubs", "players", "player_season_stats"]
NOT_NULL = [t for t in PRIVATE if t != "audit_logs"]  # audit: NULL = platform-level event


def _org_fk(table: str) -> None:
    op.create_foreign_key(f"{table}_organization_id_fkey", table, "organizations", ["organization_id"], ["id"],
                          ondelete="CASCADE")
    op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])


def upgrade() -> None:
    conn = op.get_bind()

    # 1. new tables ---------------------------------------------------------------
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(60), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("short_name", sa.String(40)),
        sa.Column("country", sa.String(100)),
        sa.Column("primary_language", sa.String(5), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("timezone", sa.String(60), nullable=False),
        sa.Column("logo_data_url", sa.Text()),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("is_demo", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)
    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("region", sa.String(120)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_organization_id", "memberships", ["organization_id"])
    op.create_table(
        "player_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("player_id", sa.Integer(), sa.ForeignKey("players.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tactical_role", sa.String(80)),
        sa.Column("physical_profile", sa.Text()),
        sa.Column("estimated_fee", sa.Integer()),
        sa.Column("fee_estimate_source", sa.String(300)),
        sa.Column("salary_expectation", sa.Integer()),
        sa.Column("availability", sa.String(30), nullable=False),
        sa.Column("agent_name", sa.String(200)),
        sa.Column("notes", sa.Text()),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "player_id", name="uq_assessment_org_player"),
    )
    op.create_index("ix_player_assessments_organization_id", "player_assessments", ["organization_id"])
    op.create_index("ix_player_assessments_player_id", "player_assessments", ["player_id"])

    op.add_column("users", sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))

    # 2. legacy organization ------------------------------------------------------
    has_data = conn.execute(sa.text(
        "SELECT (SELECT count(*) FROM users) + (SELECT count(*) FROM players)")).scalar()
    legacy_id = None
    if has_data:
        is_demo = bool(conn.execute(sa.text(
            "SELECT count(*) FROM data_sources WHERE is_fictional AND name = 'FICTIONAL SAMPLE DATA'")).scalar())
        legacy_id = conn.execute(sa.text(
            "INSERT INTO organizations (slug, name, primary_language, currency, timezone, settings, is_demo, status, "
            "created_at) VALUES ('legacy-organization', 'Legacy organization (rename me)', 'en', 'EUR', "
            "'Africa/Casablanca', '{}', :demo, 'active', now()) RETURNING id"), {"demo": is_demo}).scalar()

    # 3. organization_id on every tenant table, existing rows -> legacy org ---------
    for t in PRIVATE + SHARED_OR_PRIVATE:
        op.add_column(t, sa.Column("organization_id", sa.Integer(), nullable=True))
        if legacy_id is not None:
            conn.execute(sa.text(f"UPDATE {t} SET organization_id = :o"), {"o": legacy_id})
        _org_fk(t)
    for t in NOT_NULL:
        op.alter_column(t, "organization_id", nullable=False)

    # 4. roles -> memberships; private player fields -> assessments ----------------
    if legacy_id is not None:
        conn.execute(sa.text(
            "INSERT INTO memberships (user_id, organization_id, role, region, is_active, created_at) "
            "SELECT id, :o, role, region, is_active, created_at FROM users"), {"o": legacy_id})
        conn.execute(sa.text(
            "INSERT INTO player_assessments (organization_id, player_id, tactical_role, physical_profile, "
            "estimated_fee, fee_estimate_source, salary_expectation, availability, agent_name, notes, updated_at) "
            "SELECT :o, id, tactical_role, physical_profile, estimated_fee_eur, fee_estimate_source, "
            "salary_expectation_eur, coalesce(availability, 'unknown'), agent_name, notes, now() FROM players"),
            {"o": legacy_id})
    for col in ("role", "region"):
        op.drop_column("users", col)
    for col in ("tactical_role", "physical_profile", "estimated_fee_eur", "fee_estimate_source",
                "salary_expectation_eur", "availability", "agent_name", "notes"):
        op.drop_column("players", col)

    # 5. budgets: currency-neutral columns ----------------------------------------
    op.alter_column("recruitment_budgets", "transfer_budget_eur", new_column_name="transfer_budget")
    op.alter_column("recruitment_budgets", "wage_budget_eur", new_column_name="wage_budget")

    # 6. per-organization uniqueness ------------------------------------------------
    op.drop_constraint("data_sources_name_key", "data_sources", type_="unique")
    op.drop_constraint("uq_league_name_country", "leagues", type_="unique")
    op.drop_constraint("uq_club_name_country", "clubs", type_="unique")
    op.drop_constraint("pipeline_entries_player_id_key", "pipeline_entries", type_="unique")
    op.drop_constraint("recruitment_budgets_season_key", "recruitment_budgets", type_="unique")
    shared, private = sa.text("organization_id IS NULL"), sa.text("organization_id IS NOT NULL")
    op.create_index("uq_data_source_shared_name", "data_sources", ["name"], unique=True, postgresql_where=shared)
    op.create_index("uq_data_source_org_name", "data_sources", ["organization_id", "name"], unique=True,
                    postgresql_where=private)
    for t in ("league", "club"):
        op.create_index(f"uq_{t}_shared", f"{t}s", ["name", "country"], unique=True, postgresql_where=shared)
        op.create_index(f"uq_{t}_org", f"{t}s", ["organization_id", "name", "country"], unique=True,
                        postgresql_where=private)
    op.create_unique_constraint("uq_pipeline_org_player", "pipeline_entries", ["organization_id", "player_id"])
    op.create_index("ix_pipeline_entries_player_id", "pipeline_entries", ["player_id"])
    op.create_unique_constraint("uq_budget_org_season", "recruitment_budgets", ["organization_id", "season"])

    # 7. same-organization composite foreign keys ---------------------------------
    op.create_unique_constraint("uq_match_video_id_org", "match_videos", ["id", "organization_id"])
    op.create_unique_constraint("uq_pipeline_entry_id_org", "pipeline_entries", ["id", "organization_id"])
    op.drop_constraint("video_observations_video_id_fkey", "video_observations", type_="foreignkey")
    op.create_foreign_key("fk_observation_video_same_org", "video_observations", "match_videos",
                          ["video_id", "organization_id"], ["id", "organization_id"], ondelete="CASCADE")
    op.drop_constraint("pipeline_events_entry_id_fkey", "pipeline_events", type_="foreignkey")
    op.create_foreign_key("fk_event_entry_same_org", "pipeline_events", "pipeline_entries",
                          ["entry_id", "organization_id"], ["id", "organization_id"], ondelete="CASCADE")


def downgrade() -> None:
    conn = op.get_bind()
    n = conn.execute(sa.text("SELECT count(*) FROM organizations")).scalar()
    if n > 1:
        raise RuntimeError("Cannot downgrade: more than one organization exists")
    org = conn.execute(sa.text("SELECT id FROM organizations")).scalar()

    op.drop_constraint("fk_event_entry_same_org", "pipeline_events", type_="foreignkey")
    op.create_foreign_key("pipeline_events_entry_id_fkey", "pipeline_events", "pipeline_entries", ["entry_id"],
                          ["id"], ondelete="CASCADE")
    op.drop_constraint("fk_observation_video_same_org", "video_observations", type_="foreignkey")
    op.create_foreign_key("video_observations_video_id_fkey", "video_observations", "match_videos", ["video_id"],
                          ["id"], ondelete="CASCADE")
    op.drop_constraint("uq_pipeline_entry_id_org", "pipeline_entries", type_="unique")
    op.drop_constraint("uq_match_video_id_org", "match_videos", type_="unique")

    op.drop_constraint("uq_budget_org_season", "recruitment_budgets", type_="unique")
    op.drop_index("ix_pipeline_entries_player_id", "pipeline_entries")
    op.drop_constraint("uq_pipeline_org_player", "pipeline_entries", type_="unique")
    for t in ("league", "club"):
        op.drop_index(f"uq_{t}_org", f"{t}s")
        op.drop_index(f"uq_{t}_shared", f"{t}s")
    op.drop_index("uq_data_source_org_name", "data_sources")
    op.drop_index("uq_data_source_shared_name", "data_sources")
    op.create_unique_constraint("recruitment_budgets_season_key", "recruitment_budgets", ["season"])
    op.create_unique_constraint("pipeline_entries_player_id_key", "pipeline_entries", ["player_id"])
    op.create_unique_constraint("uq_club_name_country", "clubs", ["name", "country"])
    op.create_unique_constraint("uq_league_name_country", "leagues", ["name", "country"])
    op.create_unique_constraint("data_sources_name_key", "data_sources", ["name"])

    op.alter_column("recruitment_budgets", "transfer_budget", new_column_name="transfer_budget_eur")
    op.alter_column("recruitment_budgets", "wage_budget", new_column_name="wage_budget_eur")

    op.add_column("players", sa.Column("tactical_role", sa.String(80)))
    op.add_column("players", sa.Column("physical_profile", sa.Text()))
    op.add_column("players", sa.Column("estimated_fee_eur", sa.Integer()))
    op.add_column("players", sa.Column("fee_estimate_source", sa.String(300)))
    op.add_column("players", sa.Column("salary_expectation_eur", sa.Integer()))
    op.add_column("players", sa.Column("availability", sa.String(30), nullable=False, server_default="unknown"))
    op.add_column("players", sa.Column("agent_name", sa.String(200)))
    op.add_column("players", sa.Column("notes", sa.Text()))
    conn.execute(sa.text(
        "UPDATE players p SET tactical_role = a.tactical_role, physical_profile = a.physical_profile, "
        "estimated_fee_eur = a.estimated_fee, fee_estimate_source = a.fee_estimate_source, "
        "salary_expectation_eur = a.salary_expectation, availability = a.availability, agent_name = a.agent_name, "
        "notes = a.notes FROM player_assessments a WHERE a.player_id = p.id"))
    op.alter_column("players", "availability", server_default=None)
    op.add_column("users", sa.Column("role", sa.String(40), nullable=True))
    op.add_column("users", sa.Column("region", sa.String(120)))
    conn.execute(sa.text("UPDATE users u SET role = m.role, region = m.region FROM memberships m "
                         "WHERE m.user_id = u.id"))
    conn.execute(sa.text("UPDATE users SET role = 'regional_scout' WHERE role IS NULL"))
    op.alter_column("users", "role", nullable=False)

    for t in PRIVATE + SHARED_OR_PRIVATE:
        op.drop_index(f"ix_{t}_organization_id", t)
        op.drop_constraint(f"{t}_organization_id_fkey", t, type_="foreignkey")
        op.drop_column(t, "organization_id")
    op.drop_column("users", "token_version")
    op.drop_column("users", "is_platform_admin")
    op.drop_table("player_assessments")
    op.drop_table("memberships")
    op.drop_table("organizations")
    del org
