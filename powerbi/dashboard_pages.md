# Dashboard Pages & Layout Design

The JobPulse Power BI dashboard consists of 7 high-fidelity report pages designed for executive leadership. This document specifies the layout, visuals, and interactions for each page.

## Global Features
- **Theme**: JobPulse Executive Theme (Dark mode, glassmorphism UI, vibrant accents).
- **Navigation**: Left-hand navigation pane with icon buttons linked via Bookmarks to each page.
- **Slicers**: Sync slicers (Date Range, Location, Job Category) available on a hidden collapsible filter pane.

---

## Page 1: Executive Overview
**Audience**: C-Suite & VP Level
- **Top Row KPIs**: Total Jobs, Active Jobs, Remote %, Median Salary (Dynamic KPI cards with MoM sparklines).
- **Visual 1 (Line Chart)**: Hiring Trend (Rolling 30 Days Jobs vs Previous 30 Days).
- **Visual 2 (Bar Chart)**: Top 5 Hiring Companies.
- **Visual 3 (Donut Chart)**: Jobs by Source System.
- **Visual 4 (Tree Map)**: Jobs by Role Category.

## Page 2: Salary Analytics
**Audience**: HR Leaders & Recruiters
- **Top Row KPIs**: Avg Salary, Highest Salary, Salary Spread, Remote vs Onsite Premium.
- **Visual 1 (Box & Whisker Plot)**: Salary Range Distribution by Top 10 Job Titles.
- **Visual 2 (Heatmap)**: Avg Salary by State and Role.
- **Visual 3 (Clustered Bar Chart)**: Top 20 Highest Paying Companies.
- **Interactions**: Drillthrough enabled from "Job Title" to a hidden "Role Details" page.

## Page 3: Skills Dashboard
**Audience**: Technical Recruiters & Engineering Managers
- **Visual 1 (Matrix)**: Skill Co-occurrence (Rows: Skill A, Columns: Skill B, Value: Count of Jobs).
- **Visual 2 (Slope Chart)**: Fastest Growing Skills (Rank MoM).
- **Visual 3 (Tornado Chart)**: Cloud vs On-Premise Skill Demand.
- **Visual 4 (Bar Chart)**: Top 15 Programming Languages by Demand.
- **Tooltips**: Custom Report Page Tooltip showing "Top Companies Hiring for this Skill" when hovering over a skill bar.

## Page 4: Company Dashboard
**Audience**: Market Intelligence & Strategy
- **Visual 1 (Search Slicer)**: Single-select Company search box.
- **Visual 2 (Card Grid)**: Open Positions, Avg Salary, Remote %, Top Skill Required (for the selected company).
- **Visual 3 (Line Chart)**: Historical Hiring Trend for the company.
- **Visual 4 (Table)**: Raw active job listings for the selected company with hyperlink to posting_url.

## Page 5: Geographic Dashboard
**Audience**: Talent Acquisition Teams
- **Visual 1 (Shape Map)**: Jobs by State (Color saturation based on Job Volume).
- **Visual 2 (Map/Bubble)**: Top Hiring Cities (Bubble size = volume, Color = Avg Salary).
- **Visual 3 (Pie Chart)**: Remote vs Onsite distribution.
- **Visual 4 (Bar Chart)**: Top Hiring Cities ranked.
- **Interactions**: Cross-filtering enabled; clicking a State updates the City map and Remote %.

## Page 6: Pipeline Monitoring
**Audience**: Data Engineers & IT Ops
- **Top Row KPIs**: Total Runs, Success Rate, Failed Runs.
- **Visual 1 (Area Chart)**: Rows Extracted vs Rows Loaded over time.
- **Visual 2 (Line Chart)**: Pipeline Execution Time (Duration) over the last 30 days.
- **Visual 3 (Stacked Bar)**: Failures by Stage (Extraction, Transformation, Load).

## Page 7: Data Quality
**Audience**: Data Stewards & Analysts
- **Visual 1 (Gauge)**: % Missing Salary (Target < 20%).
- **Visual 2 (Card)**: Duplicate Rows identified.
- **Visual 3 (Donut)**: Missing Company vs Missing Location vs Clean Records.
- **Visual 4 (Table)**: Anomaly Detection Log (Detailed list of records failing structural constraints).
