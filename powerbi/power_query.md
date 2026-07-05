# Power Query (M) Scripts

This document outlines the Power Query implementation used to load the Star Schema from PostgreSQL.

## Connection Parameters
Create a parameter in Power Query:
- `ServerName`: (e.g., `localhost:5432`)
- `DatabaseName`: (e.g., `jobpulse`)

## 1. fact_jobs

```powerquery
let
    Source = PostgreSQL.Database(ServerName, DatabaseName),
    public_fact_jobs = Source{[Schema="public",Item="fact_jobs"]}[Data],
    #"Removed Columns" = Table.RemoveColumns(public_fact_jobs,{"created_at", "updated_at"}),
    #"Changed Type" = Table.TransformColumnTypes(#"Removed Columns",{{"salary_min", Currency.Type}, {"salary_max", Currency.Type}})
in
    #"Changed Type"
```

## 2. dim_company

```powerquery
let
    Source = PostgreSQL.Database(ServerName, DatabaseName),
    public_dim_company = Source{[Schema="public",Item="dim_company"]}[Data],
    #"Removed Columns" = Table.RemoveColumns(public_dim_company,{"created_at", "updated_at"})
in
    #"Removed Columns"
```

## 3. dim_location

```powerquery
let
    Source = PostgreSQL.Database(ServerName, DatabaseName),
    public_dim_location = Source{[Schema="public",Item="dim_location"]}[Data],
    #"Removed Columns" = Table.RemoveColumns(public_dim_location,{"created_at", "updated_at"})
in
    #"Removed Columns"
```

## 4. dim_skill

```powerquery
let
    Source = PostgreSQL.Database(ServerName, DatabaseName),
    public_dim_skill = Source{[Schema="public",Item="dim_skill"]}[Data],
    #"Removed Columns" = Table.RemoveColumns(public_dim_skill,{"created_at", "updated_at"})
in
    #"Removed Columns"
```

## 5. bridge_job_skill

```powerquery
let
    Source = PostgreSQL.Database(ServerName, DatabaseName),
    public_bridge_job_skill = Source{[Schema="public",Item="bridge_job_skill"]}[Data],
    #"Removed Columns" = Table.RemoveColumns(public_bridge_job_skill,{"created_at"})
in
    #"Removed Columns"
```

## 6. dim_date

```powerquery
let
    Source = PostgreSQL.Database(ServerName, DatabaseName),
    public_dim_date = Source{[Schema="public",Item="dim_date"]}[Data],
    #"Changed Type" = Table.TransformColumnTypes(public_dim_date,{{"full_date", type date}})
in
    #"Changed Type"
```

## Query Folding Verification
Ensure that the "View Native Query" option is available on the last step of each query. We specifically removed auditing columns (`created_at`, `updated_at`) early to allow the PostgreSQL engine to strip them before transmitting data over the wire (Query Folding).
