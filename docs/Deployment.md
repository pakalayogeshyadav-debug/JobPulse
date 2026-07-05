# Deployment Guide

JobPulse is containerized using Docker and orchestrated with Docker Compose for local development. Production deployments should target managed container services (e.g., AWS ECS, EKS) and managed databases (AWS RDS).

## Local Deployment (Docker Compose)

The easiest way to stand up the full stack is via `docker compose`.

1. **Clone the repository:**
   ```bash
   git clone https://github.com/<your-username>/jobpulse.git
   cd jobpulse
   ```

2. **Configure Environment:**
   Copy the example environment file and fill in necessary credentials.
   ```bash
   cp .env.example .env
   ```

3. **Start the Stack:**
   ```bash
   docker compose up -d --build
   ```
   This provisions:
   - **PostgreSQL** on `localhost:5432`
   - **pgAdmin** on `http://localhost:5050` (Login: `admin@jobpulse.local` / `admin`)
   - **JobPulse Pipeline** container

4. **View Logs:**
   ```bash
   docker compose logs -f jobpulse
   ```

## Production Deployment Considerations

When moving from local Docker Compose to a production environment (e.g., AWS):

1. **Database**: Do not run PostgreSQL inside a container for production. Use **AWS RDS** or **Aurora** for automatic backups, Multi-AZ failover, and scaling.
2. **Secrets Management**: Use **AWS Secrets Manager** or **HashiCorp Vault** instead of `.env` files. Airflow natively integrates with these backends.
3. **Execution Environment**: 
   - Deploy Airflow via the official **Helm Chart** on an EKS cluster, or use a managed service like **Amazon MWAA** (Managed Workflows for Apache Airflow).
   - Use `CeleryExecutor` with a Redis broker to distribute Airflow tasks across multiple worker nodes.
4. **Staging Storage**: Replace local `./data/staging/` with an **AWS S3** bucket. Airflow tasks should read/write Parquet files to `s3://your-bucket-name/staging/`.
5. **CI/CD**: The provided GitHub Actions workflow `.github/workflows/ci.yml` automatically tests and lints code on every push to `main`.
