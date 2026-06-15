# PSC Cloud Runbook (DigitalOcean + GoDaddy + Docker)

This is a practical, beginner-friendly guide that documents how we migrated PSC to the cloud, connected the domain, and the common day-to-day commands you will use.

Assumptions:
- App is deployed on a DigitalOcean Droplet (Ubuntu).
- Repo is hosted on GitHub.
- App directory on server is `/opt/psc`.
- PSC runs via Docker Compose:
  - `psc_web` (Flask/Gunicorn)
  - `psc_db` (Postgres) with 2 databases:
    - `psc_main` (main portal)
    - `psc_coupon` (external coupon system)
- Caddy is used for HTTPS reverse proxy.

## 1) What You Purchased / Created

### DigitalOcean
- Droplet: 1 vCPU / 2 GB RAM / 50 GB SSD (upgrade later if needed).
- Region: BLR1 (Bangalore) recommended for India.

### GoDaddy Domain
- Domain example: `prakritiksparshcare.com`
- DNS records:
  - `A` record: `@` -> `<DROPLET_IP>`
  - `CNAME` record: `www` -> `prakritiksparshcare.com.`
  - Remove GoDaddy "WebsiteBuilder Site" A record (it causes random GoDaddy template to appear).

## 2) First-Time Droplet Setup (Web Console)

You can use DigitalOcean "Web Console" to run commands on the droplet without SSH.

Update system packages:

```bash
apt-get update && apt-get -y upgrade
```

Firewall (UFW):

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
ufw status
```

Fail2ban (recommended for password SSH):

```bash
apt-get install -y fail2ban
systemctl enable --now fail2ban
fail2ban-client status sshd
```

If you get locked out because your IP is banned:
- Find your public IP from laptop:
  - Windows PowerShell: `curl ifconfig.me`
- Unban on droplet:
  - `fail2ban-client set sshd unbanip <YOUR_PUBLIC_IP>`

## 3) Clone Repo on Droplet (GitHub)

Install git:

```bash
apt-get install -y git
```

Clone:

```bash
mkdir -p /opt
cd /opt
git clone https://github.com/<your-user>/<your-repo>.git psc
cd /opt/psc
```

## 4) Create Server `.env` (Secrets)

Create/edit:

```bash
nano /opt/psc/.env
```

Example:

```env
SECRET_KEY=put_a_long_random_secret_here
PSC_DB_PASSWORD=strong_password_here
COUPON_DB_PASSWORD=strong_password_here
COUPON_ADMIN_PASSWORD=strong_password_for_coupon_admin
```

Save nano:
- `Ctrl+O` then `Enter`
- `Ctrl+X`

## 5) Start PSC (Docker Compose)

Ensure init scripts are executable:

```bash
chmod +x /opt/psc/deploy/initdb/*.sh
```

Build + start:

```bash
cd /opt/psc
docker compose up -d --build
docker compose ps
```

Local test (before HTTPS):
- `http://<DROPLET_IP>:8000`

Logs:

```bash
cd /opt/psc
docker compose logs --tail=200 psc_web
docker compose logs --tail=200 psc_db
```

Restart just web:

```bash
docker compose restart psc_web
```

Restart all:
```bash
docker compose restart
```

## 6) Connect Domain and Check DNS

From the droplet:

```bash
apt-get install -y dnsutils
dig +short prakritiksparshcare.com
dig +short www.prakritiksparshcare.com
```

Expected:
- Only the droplet IP shows for the domain.

If `dig` shows extra IPs (GoDaddy parking), delete extra records in GoDaddy DNS.

## 7) Setup HTTPS (Caddy)

Install Caddy:

```bash
apt-get install -y caddy
```

Write `/etc/caddy/Caddyfile`:

```bash
cat > /etc/caddy/Caddyfile <<'EOF'
prakritiksparshcare.com, www.prakritiksparshcare.com {
  encode gzip zstd
  reverse_proxy 127.0.0.1:8000
}
EOF
```

Validate + reload:

```bash
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
systemctl status caddy --no-pager
```

If HTTPS shows "invalid response" / "not secure":
- Usually DNS was still pointing to GoDaddy or not fully propagated.
- Re-check `dig` results and Caddy logs:

```bash
journalctl -u caddy --no-pager -n 120
```

## 8) Git Commands You’ll Use

### On your laptop (Windows) for code changes

Common flow:

```bash
git status
git add -A
git commit -m "Describe change"
git push
```

### On the droplet to deploy the latest code

```bash
cd /opt/psc
git pull
docker compose up -d --build
```

If only templates/static changed, you can often do:

```bash
docker compose restart psc_web
```

## 9) Database Migration (Move Local Users to Cloud)

### Export from local machine (Windows)

This uses `deploy/export_local_db.ps1`. If `pg_dump` is not on PATH, pass explicit path:

```powershell
cd "C:\path\to\psc"
.\deploy\export_local_db.ps1 `
  -HostName localhost `
  -Port 5432 `
  -UserName postgres `
  -DatabaseName psc_db `
  -PgDumpPath "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe"
```

It generates:
- `deploy\dumps\psc_main_*.dump`
- `deploy\dumps\psc_coupon_*.dump`

### Upload dumps to droplet

From laptop PowerShell:

```powershell
cd "C:\path\to\psc\deploy\dumps"
scp .\psc_main_*.dump root@<DROPLET_IP>:/opt/psc/
scp .\psc_coupon_*.dump root@<DROPLET_IP>:/opt/psc/
```

### Restore on droplet

Important: If your local dump is from Postgres 17 but server is Postgres 16, restore using a temporary `postgres:17` container for `pg_restore`.

Load `/opt/psc/.env` into your shell (so `$PSC_DB_PASSWORD` exists):

```bash
cd /opt/psc
set -a
. ./.env
set +a
```

Restore main DB:

```bash
cat psc_main_*.dump | docker run --rm -i --network psc_default \
  -e PGPASSWORD="$PSC_DB_PASSWORD" postgres:17 bash -lc \
  "pg_restore -h psc_db -U psc_admin -d psc_main --clean --if-exists --no-owner --no-privileges"
```

Restore coupon DB:

```bash
cat psc_coupon_*.dump | docker run --rm -i --network psc_default \
  -e PGPASSWORD="$PSC_DB_PASSWORD" postgres:17 bash -lc \
  "pg_restore -h psc_db -U psc_admin -d psc_coupon --clean --if-exists --no-owner --no-privileges"
```

Restart web:

```bash
cd /opt/psc
docker compose restart psc_web
```

Verify user count:

```bash
docker compose exec -T psc_db psql -U psc_admin -d psc_main -c "select count(*) from user_login;"
```

## 10) Backups (DB Backups + Full Server Backups)

Use both:

### A) DigitalOcean Droplet Backups (Full Server)
- Enable in DigitalOcean UI (Backups & Snapshots).
- This captures the whole server disk (app + DB + uploads).
- Easiest safety net.

### B) Daily database dumps + uploads (Recommended)

This repo includes a script:
- `deploy/backup_same_box.sh`

It can dump both databases and archive uploads folders.

One-time setup:

```bash
chmod +x /opt/psc/deploy/backup_same_box.sh
mkdir -p /var/backups/psc
```

Run manually:

```bash
cd /opt/psc
BACKUP_DIR=/var/backups/psc RETAIN_DAYS=14 ./deploy/backup_same_box.sh
ls -lh /var/backups/psc
```

Automate with cron:

```bash
crontab -e
```

Add:

```cron
30 2 * * * cd /opt/psc && BACKUP_DIR=/var/backups/psc RETAIN_DAYS=14 ./deploy/backup_same_box.sh >> /var/log/psc_backup.log 2>&1
```

Restore guide:
- `deploy/RESTORE_SAME_BOX.md`

## 11) Common “Fix It” Commands

Check running containers:

```bash
cd /opt/psc
docker compose ps
```

Tail web logs:

```bash
docker compose logs --tail=200 psc_web
```

Tail Caddy logs:

```bash
journalctl -u caddy --no-pager -n 120
```

Restart Caddy:

```bash
systemctl restart caddy
systemctl status caddy --no-pager
```

If a page returns 502 Bad Gateway:
- Usually `psc_web` is down or restarting.
- Check `docker compose logs --tail=200 psc_web`.

## 12) Security Notes (Next Upgrade)

Password SSH works, but it is safer to:
- Add SSH keys
- Disable password login
- Create a non-root user and use `sudo`

See:
- `deploy/SAME_BOX_SECURITY.md`

## 13) Hourly Web Watchdog

If `psc_web` stays down for an hour, the watchdog script can bring it back automatically.
It checks only once per hour, so CPU usage is negligible.

Script:

```bash
/opt/psc/deploy/watchdog_psc_web.sh
```

Install it:

```bash
chmod +x /opt/psc/deploy/watchdog_psc_web.sh
```

Add this cron entry on the droplet:

```cron
0 * * * * /opt/psc/deploy/watchdog_psc_web.sh >> /var/log/psc_watchdog.log 2>&1
```

What it does:
- If `psc_web` is running, it clears the down timer and exits.
- If `psc_web` is down, it records the time.
- If it has been down for 1 hour or more, it runs `docker compose up -d psc_web`.
