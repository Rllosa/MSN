# Deployment Runbook — OVH VPS

Step-by-step guide to deploy the MSN Unified Messaging Dashboard on the OVH VPS.

**VPS:** `54.36.162.154` | user: `ubuntu`
**URL:** `https://dashboard.blackpalm-sxm.com`

---

## Step 1 — SSH into VPS

```bash
ssh ubuntu@54.36.162.154
```

---

## Step 2 — Install Docker

```bash
# Install Docker
curl -fsSL https://get.docker.com | sudo sh

# Add ubuntu user to docker group (no sudo needed for docker commands)
sudo usermod -aG docker ubuntu

# Apply group change without re-logging in
newgrp docker

# Verify
docker --version
docker compose version
```

---

## Step 3 — Clone the repository

```bash
cd ~
git clone https://github.com/Rllosa/MSN.git
cd MSN
```

> If the repo is private, use a personal access token:
> `git clone https://<your-token>@github.com/Rllosa/MSN.git`

---

## Step 4 — Create the .env file

```bash
cp .env.example .env
nano .env
```

Fill in all values. Key fields for production:

| Variable | Value |
|----------|-------|
| `POSTGRES_USER` | choose a username |
| `POSTGRES_PASSWORD` | strong random password |
| `POSTGRES_DB` | `msn_dashboard` |
| `BEDS24_REFRESH_TOKEN` | from Beds24 account |
| `IMAP_PASSWORD` | OVH email password |
| `SMTP_PASSWORD` | OVH email password |
| `WHATSAPP_PHONE_NUMBER_ID` | from Meta App Dashboard |
| `WHATSAPP_ACCESS_TOKEN` | permanent token from Meta Business Manager |
| `WHATSAPP_VERIFY_TOKEN` | `blackpalm-whatsapp-2026` |
| `WHATSAPP_APP_SECRET` | `9c86e553994eebc02c784f16c78e55b5` |
| `JWT_SECRET_KEY` | run `openssl rand -hex 32` |
| `APP_ENV` | `production` |
| `FRONTEND_URL` | `https://dashboard.blackpalm-sxm.com` |
| `WEB_CONCURRENCY` | `2` |

---

## Step 5 — Build and start the stack

```bash
cd ~/MSN
docker compose -f docker-compose.prod.yml up -d --build
```

This builds the backend and frontend images, then starts all 4 services (postgres, redis, backend, frontend).

Check all services are healthy:
```bash
docker compose -f docker-compose.prod.yml ps
```

All services should show `healthy` or `running`.

---

## Step 6 — Run database migrations

```bash
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

---

## Step 7 — Seed properties

```bash
docker compose -f docker-compose.prod.yml exec backend python scripts/seed_properties.py
```

---

## Step 8 — Create first admin user

```bash
docker compose -f docker-compose.prod.yml exec backend python scripts/create_admin.py \
  --email your@email.com \
  --password "choose-a-strong-password"
```

---

## Step 9 — Verify health endpoint

```bash
curl http://localhost:8000/health
# Expected: {"status": "ok", ...}
```

---

## Step 10 — Set up nginx + SSL

Follow `docs/nginx-setup.md`.

---

## Step 11 — Register WhatsApp webhook with Meta

Once the site is live at `https://dashboard.blackpalm-sxm.com`:

1. Go to [Meta App Dashboard](https://developers.facebook.com) → App: MSN → WhatsApp → Configuration
2. Set **Callback URL**: `https://dashboard.blackpalm-sxm.com/api/webhooks/whatsapp`
3. Set **Verify token**: `blackpalm-whatsapp-2026`
4. Click **Verify and Save**
5. Subscribe to the **messages** webhook field

---

## Useful commands

```bash
# View logs
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml logs -f frontend

# Restart a service
docker compose -f docker-compose.prod.yml restart backend

# Pull latest code and redeploy
cd ~/MSN
git pull origin main
docker compose -f docker-compose.prod.yml up -d --build

# Run migrations after update
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
```

---

## Rollback

```bash
# Roll back to previous image (if build fails)
git checkout <previous-commit>
docker compose -f docker-compose.prod.yml up -d --build
```
