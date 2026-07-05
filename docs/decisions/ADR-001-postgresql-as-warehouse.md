# ADR-001: Use PostgreSQL as the Data Warehouse

**Date:** 2026-06-27
**Status:** Accepted
**Author:** [Your Name]

## Context

We need a relational database to serve as the central data warehouse
for the JobPulse ETL pipeline. The warehouse must support:
- SQL-based analytics and aggregations
- Direct connectivity from Power BI
- ACID transactions for reliable data loading
- Open-source, low-cost deployment

## Decision

We chose **PostgreSQL 15+** as the data warehouse.

## Rationale

| Criterion          | PostgreSQL | MySQL | SQLite | BigQuery |
|--------------------|-----------|-------|--------|----------|
| ACID Transactions  | ✅         | ✅    | ✅     | ✅       |
| Window Functions   | ✅         | ✅    | Limited| ✅       |
| Power BI Native    | ✅         | ✅    | ❌     | ✅       |
| Self-hosted        | ✅         | ✅    | ✅     | ❌       |
| Cost               | Free       | Free  | Free   | Pay/query|
| SQLAlchemy Support | ✅ First-class | ✅ | ✅  | ✅       |

PostgreSQL offers the best combination of features, SQL standard compliance,
and Power BI connector support at zero cost.

## Consequences

- Requires a running PostgreSQL instance (local Docker or managed RDS)
- Team must manage schema migrations (handled via Alembic)
- AWS RDS for PostgreSQL is the planned production deployment target
