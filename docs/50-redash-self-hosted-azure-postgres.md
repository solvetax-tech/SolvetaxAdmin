# Redash self-hosted from scratch (Azure PostgreSQL, read-only user)

Owner: Engineering Team  
Last Verified On: 2026-04-08

This guide explains how to run **open-source Redash** yourself and connect it to **Azure Database for PostgreSQL** using a **read-only** database role (for example `solvetax_readonly`). It assumes you already created that role and granted `SELECT` on `solvetax` tables.

---

## 1. What you are building (mental model)

Redash has **two** different database connections:

| Piece | What it is | Where it lives |
|--------|------------|----------------|
| **Redash metadata database** | Stores Redash users, saved queries, dashboards, data-source passwords (encrypted) | A PostgreSQL instance **managed by Redash** (usually the same Docker Compose stack) |
| **Your data source** | The database you **query** in the SQL editor | Your **Azure PostgreSQL** server (e.g. `solvetax` schema) |

You do **not** install your app schema inside Redash’s metadata DB. You only **register** Azure Postgres as a **Data Source** and use `solvetax_readonly` there.

---

## 2. Prerequisites checklist

Before you start, have:

1. **An Azure PostgreSQL server** (Flexible Server or equivalent) with database `postgres` (or the DB you granted `CONNECT` on).
2. **A read-only role**, e.g. `solvetax_readonly`, with at least:
   - `GRANT CONNECT ON DATABASE ...`
   - `GRANT USAGE ON SCHEMA solvetax`
   - `GRANT SELECT ON ALL TABLES IN SCHEMA solvetax`
3. **A Linux VM or host** (recommended) with:
   - Public IP or private connectivity to Azure Postgres
   - ~2 vCPU / 4 GB RAM minimum for a small team
4. **Docker** and **Docker Compose** (v2 plugin) on that host.
5. **Azure firewall rule** allowing the **Redash host’s outbound IP** (or VNet integration) to reach port **5432** on the Azure server.

---

## 3. Azure PostgreSQL: network and SSL

### 3.1 Firewall

- In Azure Portal → your PostgreSQL server → **Networking** / **Firewall rules**:
  - Add the **public IP** of the VM where Redash will run, **or**
  - Use **VNet integration** / private endpoint if Redash runs inside Azure on the same network.

Until Redash can reach `*.postgres.database.azure.com:5432`, “Test connection” in Redash will fail.

### 3.2 SSL

Azure PostgreSQL expects **TLS**. In Redash you will set SSL mode to **`require`** (see section 8).

---

## 4. Read-only role (recap)

Run as `azure_pg_admin` (or equivalent) if you still need to align privileges:

```sql
-- Example: adjust database name if not postgres
GRANT CONNECT ON DATABASE postgres TO solvetax_readonly;
GRANT USAGE ON SCHEMA solvetax TO solvetax_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA solvetax TO solvetax_readonly;
```

For **new tables** created later, either re-run `GRANT SELECT ON ALL TABLES ...` or use `ALTER DEFAULT PRIVILEGES` as the **role that creates tables** (documented in PostgreSQL; see your DBA runbook).

---

## 5. Install Redash on a Linux VM (recommended path)

Official self-hosted setup is Docker-based. Typical flow (commands may vary slightly by Redash release; always check the current README):

### 5.1 Install Docker

Example on Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
# Follow current Docker Engine install docs for your distro
```

Install **Docker Compose** v2 (`docker compose` subcommand).

### 5.2 Clone the setup repository

Redash publishes a setup repo that generates `docker-compose.yml`:

```bash
git clone https://github.com/getredash/setup.git
cd setup
```

### 5.3 Run the setup script

```bash
sudo ./setup.sh
```

The script usually:

- Creates an `.env` or compose file
- Pulls images
- Starts PostgreSQL (for **Redash metadata**), Redis, workers, and the web app

### 5.4 Start the stack

```bash
docker compose up -d
```

(or `docker-compose up -d` on older systems)

### 5.5 Open the UI

- Browse to `http://<VM_PUBLIC_IP>:5000` (or the port mapped in `docker-compose.yml`; **5000** is common).
- **First visit:** create the **Redash admin** user (email + password).  
  This account is **only for Redash**, not your Azure `solvetax_readonly` user.

---

## 6. Optional: HTTPS and hostname

For production:

- Put **Nginx** or **Caddy** (or Azure Application Gateway) in front of Redash with a TLS certificate.
- Restrict security group / NSG so only your office VPN or IP range can reach the Redash port.

---

## 7. Add Azure PostgreSQL as a Data Source (read-only)

1. Log in to Redash as an **admin**.
2. **Settings** (gear) → **Data Sources** → **New Data Source**.
3. Choose **PostgreSQL**.
4. Fill in:

| Field | Example |
|--------|---------|
| Name | `Solvetax Azure (readonly)` |
| Host | `yourserver.postgres.database.azure.com` |
| Port | `5432` |
| User | `solvetax_readonly` |
| Password | (password for that role) |
| Database | `postgres` (or the DB you granted `CONNECT` on) |
| SSL Mode | **`require`** |

5. Click **Test Connection**. If it fails, see section 10.

6. **Schema / queries:** In SQL, qualify tables as `solvetax.your_table`, unless you configure a default `search_path` (depends on Redash version; some allow extra connection options).

Example test query:

```sql
SELECT current_user;
SELECT COUNT(*) FROM solvetax.customers;
```

(Replace `customers` with a real table name.)

---

## 8. Security practices

- Use **`solvetax_readonly` only** in Redash. Do not use the application super-user or `solvetax_app` in BI tools.
- **Rotate** the read-only password if it is shared; better: one read-only role per analyst if you need accountability.
- **Limit** who is **admin** in Redash (only people who can manage data sources and users).
- **Backup** the Redash metadata volume / database so you do not lose dashboards and queries.

---

## 9. Day-2 operations

- **Upgrade Redash:** follow the project’s upgrade notes; usually pull new images and run migrations documented in the release.
- **New tables in `solvetax`:** if `solvetax_readonly` cannot see them, run `GRANT SELECT ON ALL TABLES IN SCHEMA solvetax TO solvetax_readonly` again or fix default privileges.

---

## 10. Troubleshooting

| Symptom | Likely cause | What to check |
|---------|----------------|---------------|
| Test connection: timeout | Firewall / NSG | Azure allows Redash host IP; VM outbound not blocked |
| SSL error | TLS not enabled in client | Set SSL to `require` in Redash |
| `permission denied for schema solvetax` | Missing `USAGE` | `GRANT USAGE ON SCHEMA solvetax TO solvetax_readonly` |
| `permission denied for table` | Missing `SELECT` | `GRANT SELECT ON ALL TABLES IN SCHEMA solvetax ...` |
| Wrong user in `SELECT current_user` | Wrong credentials in data source | Re-enter user/password in Redash data source |

---

## 11. What “login” means (two logins)

1. **Redash web login:** URL of **your** server (`http://your-vm:5000`), email/password you created in Redash.  
2. **Azure Postgres:** configured **inside** the Data Source; Redash workers use `solvetax_readonly` when running queries—not when you log into the website.

You do **not** log in at `redash.io` for self-hosted Redash; that site is marketing, not your instance.

---

## 12. Reference links

- Redash repository: [https://github.com/getredash/redash](https://github.com/getredash/redash)
- Setup helper: [https://github.com/getredash/setup](https://github.com/getredash/setup)
- Azure PostgreSQL connectivity: [Microsoft Learn – Azure Database for PostgreSQL](https://learn.microsoft.com/en-us/azure/postgresql/)

---

## Document history

- **2026-04-08:** Initial from-scratch guide for self-hosted Redash + Azure Postgres read-only integration.


GRANT CONNECT ON DATABASE postgres TO solvetax_app, solvetax_readonly;
GRANT USAGE ON SCHEMA solvetax TO solvetax_app, solvetax_readonly;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA solvetax TO solvetax_app;
GRANT SELECT ON ALL TABLES IN SCHEMA solvetax TO solvetax_readonly;
-- + sequences/functions if you use them for the app user, etc.