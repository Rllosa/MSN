# Nginx Setup — dashboard.blackpalm-sxm.com

This guide sets up the nginx server block for the MSN dashboard subdomain on the OVH VPS.
Run these steps **after** completing the deployment runbook (`deployment.md`).

## Prerequisites

- DNS A record `dashboard.blackpalm-sxm.com → 54.36.162.154` is live
- Docker Compose stack is running (`docker compose -f docker-compose.prod.yml up -d`)
- You are SSH'd into the VPS as `ubuntu`

---

## Step 1 — Copy the dashboard nginx config

```bash
sudo cp ~/MSN/docker/nginx/dashboard.conf /etc/nginx/sites-available/dashboard
```

## Step 2 — Enable the site

```bash
sudo ln -s /etc/nginx/sites-available/dashboard /etc/nginx/sites-enabled/dashboard
```

## Step 3 — Test the config

```bash
sudo nginx -t
```

Expected output:
```
nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
nginx: configuration file /etc/nginx/nginx.conf test is successful
```

## Step 4 — Reload nginx (HTTP only first)

```bash
sudo systemctl reload nginx
```

At this point `http://dashboard.blackpalm-sxm.com` should proxy to the frontend container.

## Step 5 — Issue SSL certificate with Certbot

```bash
sudo certbot --nginx -d dashboard.blackpalm-sxm.com
```

Certbot will:
1. Verify domain ownership via HTTP challenge
2. Issue the Let's Encrypt certificate
3. Automatically update `/etc/nginx/sites-available/dashboard` with SSL directives
4. Set up auto-renewal

## Step 6 — Verify HTTPS

```bash
curl -I https://dashboard.blackpalm-sxm.com/health
# Expected: HTTP/2 200
```

Open `https://dashboard.blackpalm-sxm.com` in a browser — you should see the login page.

---

## Troubleshooting

**502 Bad Gateway on `/api/`**
Backend container may not be running. Check: `docker compose -f ~/MSN/docker-compose.prod.yml ps`

**502 Bad Gateway on `/`**
Frontend container may not be running, or port 3001 is not exposed.
Check: `docker compose -f ~/MSN/docker-compose.prod.yml logs frontend`

**WebSocket not connecting**
Ensure the `/ws` location block comes before `/api/` in `dashboard.conf` (already correct).
Check browser console for the WS connection URL.

**Certbot fails — domain not resolving**
Run `dig dashboard.blackpalm-sxm.com +short` — must return `54.36.162.154`.
Wait for DNS propagation (up to 30 minutes) and retry.
