# DAX Measures Library (50+ Measures)

This document contains professional-grade DAX measures designed to be imported into a centralized `_Measures` table in Power BI.

## 1. Core KPIs
```dax
Total Jobs = COUNTROWS(fact_jobs)
Active Jobs = CALCULATE([Total Jobs], fact_jobs[is_active] = TRUE)
Inactive Jobs = CALCULATE([Total Jobs], fact_jobs[is_active] = FALSE)
Total Companies = DISTINCTCOUNT(fact_jobs[sk_company_id])
Total Locations = DISTINCTCOUNT(fact_jobs[sk_location_id])
Total Skills Mentioned = COUNTROWS(bridge_job_skill)
Avg Skills per Job = DIVIDE([Total Skills Mentioned], [Total Jobs])
Jobs with Salary Data = CALCULATE([Total Jobs], NOT ISBLANK(fact_jobs[salary_min]))
% Jobs with Salary = DIVIDE([Jobs with Salary Data], [Total Jobs])
Remote Jobs = CALCULATE([Total Jobs], dim_location[is_remote] = TRUE)
% Remote Jobs = DIVIDE([Remote Jobs], [Total Jobs])
Onsite Jobs = CALCULATE([Total Jobs], dim_location[is_remote] = FALSE)
% Onsite Jobs = DIVIDE([Onsite Jobs], [Total Jobs])
```

## 2. Salary Analytics
```dax
Avg Min Salary = AVERAGE(fact_jobs[salary_min])
Avg Max Salary = AVERAGE(fact_jobs[salary_max])
Avg Salary Midpoint = AVERAGE(fact_jobs[salary_midpoint]) -- Assumes computed column or (min+max)/2
Median Salary = MEDIANX(fact_jobs, (fact_jobs[salary_min] + fact_jobs[salary_max])/2)
Highest Salary = MAX(fact_jobs[salary_max])
Lowest Salary = MIN(fact_jobs[salary_min])
Salary Spread = [Avg Max Salary] - [Avg Min Salary]
Remote Avg Salary = CALCULATE([Avg Salary Midpoint], dim_location[is_remote] = TRUE)
Onsite Avg Salary = CALCULATE([Avg Salary Midpoint], dim_location[is_remote] = FALSE)
Salary Premium (Remote vs Onsite) = [Remote Avg Salary] - [Onsite Avg Salary]
```

## 3. Time Intelligence & Trends
```dax
Jobs Posted YTD = CALCULATE([Total Jobs], DATESYTD(dim_date[full_date]))
Jobs Posted MTD = CALCULATE([Total Jobs], DATESMTD(dim_date[full_date]))
Jobs Posted QTD = CALCULATE([Total Jobs], DATESQTD(dim_date[full_date]))
Jobs Posted Last Month = CALCULATE([Total Jobs], PREVIOUSMONTH(dim_date[full_date]))
Jobs Posted Last Year = CALCULATE([Total Jobs], SAMEPERIODLASTYEAR(dim_date[full_date]))
MoM Hiring Growth = DIVIDE([Total Jobs] - [Jobs Posted Last Month], [Jobs Posted Last Month])
YoY Hiring Growth = DIVIDE([Total Jobs] - [Jobs Posted Last Year], [Jobs Posted Last Year])
Running Total Jobs = CALCULATE([Total Jobs], FILTER(ALL(dim_date), dim_date[full_date] <= MAX(dim_date[full_date])))
Rolling 30 Days Jobs = CALCULATE([Total Jobs], DATESINPERIOD(dim_date[full_date], MAX(dim_date[full_date]), -30, DAY))
Moving Avg Salary 30D = AVERAGEX(DATESINPERIOD(dim_date[full_date], MAX(dim_date[full_date]), -30, DAY), [Avg Salary Midpoint])
```

## 4. Ranking & Advanced Analytics
```dax
Rank by Jobs = RANKX(ALL(dim_company), [Total Jobs], , DESC, Dense)
Top 10 Company Jobs = IF([Rank by Jobs] <= 10, [Total Jobs], BLANK())
Rank by Salary = RANKX(ALL(fact_jobs[job_title]), [Avg Salary Midpoint], , DESC, Dense)
Rank by Skill Demand = RANKX(ALL(dim_skill), [Total Jobs], , DESC, Dense)
Fastest Growing Skill = RANKX(ALL(dim_skill), [MoM Hiring Growth], , DESC, Dense)
```

## 5. Pipeline & Data Quality
```dax
Total Pipeline Runs = COUNTROWS(pipeline_runs)
Successful Runs = CALCULATE([Total Pipeline Runs], pipeline_runs[status] = "SUCCESS")
Failed Runs = CALCULATE([Total Pipeline Runs], pipeline_runs[status] = "FAILED")
Pipeline Success Rate = DIVIDE([Successful Runs], [Total Pipeline Runs])
Missing Salary = [Total Jobs] - [Jobs with Salary Data]
% Missing Salary = DIVIDE([Missing Salary], [Total Jobs])
Missing Location Data = CALCULATE([Total Jobs], dim_location[city] = "Unknown")
Missing Company Data = CALCULATE([Total Jobs], dim_company[company_name] = "Unknown")
```

## 6. Dynamic Visual Control & Tooltips
```dax
Dynamic Title Overview = "Executive Overview as of " & FORMAT(MAX(dim_date[full_date]), "MMMM YYYY")
Dynamic Title Salary = "Salary Analysis for " & SELECTEDVALUE(dim_skill[skill_name], "All Skills")
Color Status KPI = IF([MoM Hiring Growth] >= 0, "#00C4B4", "#FF6B6B")
Color Pipeline KPI = IF([Pipeline Success Rate] >= 0.95, "#00C4B4", "#FF6B6B")
Is Remote Flag = IF(SELECTEDVALUE(dim_location[is_remote]) = TRUE, "Remote", "Onsite")
Hover Tooltip Salary = "Min: $" & FORMAT([Avg Min Salary], "#,##0") & " | Max: $" & FORMAT([Avg Max Salary], "#,##0")
Hover Tooltip Growth = "MoM Growth: " & FORMAT([MoM Hiring Growth], "0.0%")
```
