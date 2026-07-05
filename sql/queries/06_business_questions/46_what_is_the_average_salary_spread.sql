-- Analytics Query: 46_what_is_the_average_salary_spread.sql
SELECT AVG(salary_max - salary_min) as avg_spread FROM fact_jobs WHERE salary_max IS NOT NULL AND salary_min IS NOT NULL;
