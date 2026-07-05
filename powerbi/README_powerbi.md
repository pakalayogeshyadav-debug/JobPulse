# JobPulse Power BI Analytics Layer

This directory contains all the components required to build the Executive Power BI Dashboard for the JobPulse Data Engineering project.

## Directory Structure
- `assets/` - Contains high-fidelity UI mockups (PNG) for the dashboard layout.
- `theme.json` - Corporate branding theme for automated color/font mapping.
- `power_query.md` - Optimized M scripts for connecting to PostgreSQL.
- `data_model.md` - Star schema architectural design.
- `relationships.md` - Cross-filtering and cardinality definitions.
- `dax_measures.md` - 50+ advanced DAX calculations.
- `dashboard_pages.md` - Functional requirements for the 7 report pages.
- `build_powerbi.md` - Step-by-step instructions for assembling the `.pbix` file.

## Why No `.pbix` File?
Binary `.pbix` files are inherently difficult to version-control in Git (leading to large diffs and merge conflicts). By separating the Power BI project into its constituent parts (Data Model, Power Query, DAX, Theme), the presentation layer remains completely transparent, version-controllable, and reproducible.

## Getting Started
Follow the instructions in `build_powerbi.md` to connect Power BI Desktop to your local PostgreSQL data warehouse and assemble the dashboard.
