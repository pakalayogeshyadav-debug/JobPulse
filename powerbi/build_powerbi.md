# Building the JobPulse Power BI Dashboard

Follow these step-by-step instructions to assemble the dashboard using the provided assets.

## Prerequisites
- Power BI Desktop installed (Latest Version).
- Access to the JobPulse PostgreSQL Data Warehouse (`jobpulse_dw`).
- The `powerbi/` folder assets downloaded.

## Step 1: Initialize the Project
1. Open Power BI Desktop and start a new blank report.
2. Go to **View** > **Themes** > **Browse for themes**.
3. Import `powerbi/theme.json` to automatically apply the JobPulse dark theme.

## Step 2: Connect to PostgreSQL & Apply Power Query
1. Click **Get Data** > **PostgreSQL database**.
2. Enter your server and database name.
3. Select the following tables from the `public` schema:
   - `fact_jobs`
   - `dim_company`
   - `dim_location`
   - `dim_skill`
   - `dim_date`
   - `bridge_job_skill`
   - `pipeline_runs`
   - `data_sources`
4. Click **Transform Data** to open Power Query.
5. Apply the transformations detailed in `power_query.md` using the Advanced Editor for each query.
6. Click **Close & Apply**.

## Step 3: Establish the Data Model
1. Navigate to the **Model View** on the left pane.
2. Arrange the tables into a Star Schema with `fact_jobs` in the center.
3. Define the relationships as specified in `relationships.md`.
4. Ensure the `bridge_job_skill` has Bi-directional filtering enabled between it and `fact_jobs`.

## Step 4: Create the Measures Table
1. On the Home ribbon, click **Enter Data**.
2. Name the table `_Measures` and click Load.
3. Open `dax_measures.md` and begin creating the DAX measures inside the `_Measures` table.
4. Once your first measure is created, hide the default `Column1` so the table transforms into a dedicated Measure Group (identified by a calculator icon).

## Step 5: Build the Layouts
1. Build the 7 report pages as defined in `dashboard_pages.md`.
2. Use the provided high-fidelity mockups in `powerbi/assets/` as a visual reference for spatial alignment, colors, and typography.
3. Implement a custom navigation bar on the left using buttons and Page Navigation actions.

## Step 6: Publish
1. Save the file as `JobPulse.pbix`.
2. Publish to your Power BI Workspace and configure the Gateway for scheduled refreshes.
