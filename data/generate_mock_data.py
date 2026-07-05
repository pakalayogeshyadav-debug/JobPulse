import random
import uuid
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def generate_data(num_records=25000):
    np.random.seed(42)
    random.seed(42)

    companies = [
        "Google", "Microsoft", "Amazon", "Meta", "Netflix", "Apple", "NVIDIA",
        "OpenAI", "Anthropic", "Snowflake", "Databricks", "Tesla", "Uber",
        "Airbnb", "LinkedIn", "Oracle", "SAP", "Cisco", "Intel", "AMD",
        "Salesforce", "Adobe", "Stripe", "Atlassian", "Cloudflare", "IBM",
        "Accenture", "Infosys", "TCS", "Wipro", "Capgemini", "Deloitte",
        "PwC", "KPMG", "EY"
    ]

    roles = [
        "Data Engineer", "Senior Data Engineer", "Analytics Engineer", "Data Architect",
        "ML Engineer", "Data Scientist", "BI Developer", "Data Analyst", "Cloud Engineer",
        "DevOps Engineer", "Backend Engineer", "Software Engineer", "Platform Engineer",
        "AI Engineer", "MLOps Engineer", "ETL Developer", "Database Engineer",
        "Solutions Architect", "Site Reliability Engineer"
    ]

    locations = [
        ("United States", "CA", "San Francisco"),
        ("United States", "NY", "New York"),
        ("United States", "WA", "Seattle"),
        ("United States", "TX", "Austin"),
        ("United States", "IL", "Chicago"),
        ("United Kingdom", "ENG", "London"),
        ("Canada", "ON", "Toronto"),
        ("Germany", "BE", "Berlin"),
        ("India", "KA", "Bengaluru"),
        ("India", "TG", "Hyderabad"),
        ("Singapore", "SG", "Singapore"),
        ("Australia", "NSW", "Sydney")
    ]

    skills_pool = [
        "Python", "SQL", "AWS", "GCP", "Azure", "Spark", "Kafka", "Snowflake",
        "Databricks", "dbt", "Airflow", "Docker", "Kubernetes", "Tableau",
        "Power BI", "Pandas", "Scikit-Learn", "TensorFlow", "PyTorch", "Java",
        "Scala", "Go", "C++", "React", "Node.js", "Redis", "PostgreSQL",
        "MongoDB", "Cassandra", "Elasticsearch", "Hadoop", "Terraform"
    ]

    benefits_pool = [
        "Health Insurance", "401k", "Equity", "Remote Work", "Flexible Hours",
        "Gym Membership", "Free Lunch", "Unlimited PTO", "Parental Leave"
    ]

    data = []
    
    start_date = datetime.now() - timedelta(days=365)
    
    for i in range(num_records):
        company = np.random.choice(companies)
        role = np.random.choice(roles)
        country, state, city = locations[np.random.randint(0, len(locations))]
        
        # Salary logic based on role and location
        base_salary = 100000
        if "Senior" in role or "Architect" in role:
            base_salary += 50000
        if "AI" in role or "ML" in role or "Data Scientist" in role:
            base_salary += 30000
        if country == "India":
            base_salary = int(base_salary * 0.3)
        elif country == "United Kingdom" or country == "Germany":
            base_salary = int(base_salary * 0.7)
            
        salary_min = int(np.random.normal(base_salary, 15000))
        salary_max = int(salary_min + np.random.normal(30000, 10000))
        
        salary_min = max(30000, salary_min)
        salary_max = max(salary_min + 5000, salary_max)

        work_model = np.random.choice(["Remote", "Hybrid", "Onsite"], p=[0.3, 0.5, 0.2])
        emp_type = np.random.choice(["Full-time", "Contract"], p=[0.9, 0.1])
        
        experience = np.random.choice(["Entry", "Mid", "Senior", "Lead", "Director"], p=[0.1, 0.4, 0.3, 0.15, 0.05])
        
        skills = ", ".join(np.random.choice(skills_pool, np.random.randint(3, 8), replace=False))
        benefits = ", ".join(np.random.choice(benefits_pool, np.random.randint(2, 6), replace=False))
        
        posted_days_ago = np.random.randint(0, 365)
        posting_date = start_date + timedelta(days=posted_days_ago)
        
        # Add a realistic URL
        url = f"https://careers.{company.lower().replace(' ', '')}.com/job/{uuid.uuid4().hex[:8]}"

        data.append({
            "job_id": str(uuid.uuid4()),
            "company": company,
            "title": role,
            "experience_level": experience,
            "country": country,
            "state": state,
            "city": city,
            "work_model": work_model,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "currency": "USD",
            "employment_type": emp_type,
            "industry": "Technology", # simplified
            "skills": skills,
            "education": np.random.choice(["Bachelor's", "Master's", "PhD", "None"], p=[0.6, 0.3, 0.05, 0.05]),
            "benefits": benefits,
            "posted_date": posting_date.strftime("%Y-%m-%d"),
            "url": url,
            "source_name": np.random.choice(["careers_page", "linkedin", "indeed", "glassdoor"], p=[0.4, 0.4, 0.1, 0.1]),
            "company_rating": round(np.random.uniform(3.5, 5.0), 1),
            "company_size": np.random.choice(["1-50", "51-200", "201-1000", "1000+"])
        })
        
        if i % 5000 == 0 and i > 0:
            print(f"Generated {i} records...")

    df = pd.DataFrame(data)
    
    # Save to file
    out_path = "c:/Users/P Yogesh Yadav/OneDrive/Desktop/DE/jobpulse/data/raw/massive_jobs.csv"
    df.to_csv(out_path, index=False)
    print(f"Successfully generated {num_records} records to {out_path}")

if __name__ == "__main__":
    generate_data(25000)
