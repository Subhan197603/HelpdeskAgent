# Alembic revisions

The physical PostgreSQL baseline is installed externally and represented by the empty
`0000_physical_baseline` marker. Every later schema change belongs in a reviewed, linear Alembic
revision. See `docs/operations/database-migrations.md` for the required workflow and review policy.
