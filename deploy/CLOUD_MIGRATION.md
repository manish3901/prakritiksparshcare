# DigitalOcean Migration (Beginner Step-By-Step)

This repo contains:
- Main PSC portal (Flask app) with uploads stored on disk.
- External coupon engine embedded under: `/external-coupen-system`

We are deploying on **one DigitalOcean Droplet** with:
- App (Gunicorn) in Docker
- **Two Postgres databases on the same server** (cheapest plan):
  - `psc_main` (main portal)
  - `psc_coupon` (coupon system)

Uploads that must be copied to the server:
- `Psparshcare/static/uploads/`
- `psc_coupens/psc_coupens_app/static/uploads/`

## What You Need Before Starting

1. A DigitalOcean account
2. A domain name (optional, but recommended)
3. Your local database currently running (you already have Postgres locally)

## Step 1: Create a Droplet (DigitalOcean)

1. Create Droplet
2. Region: **Bangalore (BLR1)** (recommended for India)
3. Image: **Ubuntu 22.04 LTS**
4. Size: start with **2GB / 1 vCPU**
5. Authentication: **SSH key** (recommended)
6. Optional: enable **Droplet Backups** (easy safety net)

After creation, note the Droplet public IP:
- `<DROPLET_IP>`

## Step 2: Point Your Domain (Optional)

If you have a domain, add an **A record**:
- `your-domain.com` -> `<DROPLET_IP>`

Wait a few minutes for DNS to update.

## Step 3: SSH Into the Droplet

From your computer:

```bash
ssh root@<DROPLET_IP>
```

### If You Chose Password Authentication (temporary)

If you selected "Password" instead of SSH keys while creating the Droplet:

```bash
ssh root@<DROPLET_IP>
```

It will prompt for the root password you created in DigitalOcean.

Security note: this is OK for initial setup, but it’s safer to switch to SSH keys after the deployment is working.

## Step 4: Basic Server Setup (Updates + Firewall)

Update Ubuntu:

```bash
apt-get update && apt-get -y upgrade
```

Enable firewall (UFW):

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
ufw status
```

Note: With our Docker setup, Postgres ports are **not exposed** publicly.

For more security guidance see:
- `deploy/SAME_BOX_SECURITY.md`

## Step 5: Install Docker

Install Docker:

```bash
curl -fsSL https://get.docker.com | sh
```

Install Docker Compose plugin:

```bash
apt-get install -y docker-compose-plugin
```

## Step 6: Copy This Repo To the Server

Choose one method:

1. Git clone (recommended if repo is on GitHub)
2. Upload a zip and unzip on the server

We will assume the repo is placed at:

`/opt/psc`

## Step 7: Create Server .env (Secrets)

On the server:

```bash
cd /opt/psc
nano .env
```

Add:

```env
SECRET_KEY=<generate a long random string>
PSC_DB_PASSWORD=<strong password>
COUPON_DB_PASSWORD=<strong password>
```

Tip: avoid using a single quote character `'` in the DB passwords to keep init scripts simple.

Save and exit.

## Step 8: Start the App (Docker Compose)

```bash
cd /opt/psc
chmod +x /opt/psc/deploy/initdb/*.sh
docker compose up -d --build
docker compose ps
```

Note: the `deploy/initdb/*` scripts run only the **first time** the Postgres volume is created.
If you already started Postgres earlier, you may need to reset the DB volume (fresh migration) or manually create the DB/users.

At this point the web app listens on:
- `http://<DROPLET_IP>:8000`

## Step 9: Setup HTTPS (Caddy)

Install Caddy:

```bash
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy
```

Create the Caddy config:

```bash
nano /etc/caddy/Caddyfile
```

Example:

```caddyfile
your-domain.com {
  encode gzip zstd
  reverse_proxy 127.0.0.1:8000
}
```

Reload:

```bash
systemctl reload caddy
```

Now your website should be available at:
- `https://your-domain.com`

## Step 10: Export Your Local Database (Windows)

On your local machine (PowerShell), from the repo root:

```powershell
.\deploy\export_local_db.ps1 -HostName localhost -Port 5432 -UserName postgres -DatabaseName psc_db
```

This creates 2 dump files in `deploy\dumps\`:
- `psc_main_*.dump` (everything except `coupon_*` tables)
- `psc_coupon_*.dump` (only `coupon_*` tables)

## Step 11: Upload Dumps To the Droplet

From your local machine (run in the folder that contains the dump files):

```bash
scp psc_main_*.dump root@<DROPLET_IP>:/opt/psc/
scp psc_coupon_*.dump root@<DROPLET_IP>:/opt/psc/
```

## Step 12: Restore Dumps Into Docker Postgres (On Droplet)

SSH into the droplet and run:

```bash
cd /opt/psc

# Restore main DB
cat psc_main_*.dump | docker compose exec -T psc_db bash -lc \
  "PGPASSWORD=\"$PSC_DB_PASSWORD\" pg_restore -U psc_admin -d psc_main --clean --if-exists"

# Restore coupon DB
cat psc_coupon_*.dump | docker compose exec -T psc_db bash -lc \
  "PGPASSWORD=\"$PSC_DB_PASSWORD\" pg_restore -U psc_admin -d psc_coupon --clean --if-exists"
```

If you ever need a step-by-step restore guide later:
- `deploy/RESTORE_SAME_BOX.md`

## Step 13: Copy Uploads (Legal Docs, Events, Coupon Images)

Copy these folders from your local machine to the server:

1. PSC uploads:
```bash
scp -r Psparshcare/static/uploads root@<DROPLET_IP>:/opt/psc/Psparshcare/static/
```

2. Coupon uploads:
```bash
scp -r psc_coupens/psc_coupens_app/static/uploads root@<DROPLET_IP>:/opt/psc/psc_coupens/psc_coupens_app/static/
```

Then restart the web container to pick up any changed files:

```bash
cd /opt/psc
docker compose restart psc_web
```

## Step 14: Confirm Everything Works

1. Open the website and log in.
2. Check that:
   - Corporate legal documents open correctly
   - Events gallery images load
   - Coupon public entry page works: `/external-coupen-system/coupon/entry`
3. If something is missing, re-check uploads copy paths.

## Step 15: Enable Automatic Backups (Recommended)

You should do both:

1. DigitalOcean Droplet Backups (easy whole-server restore)
2. Daily DB dumps (faster DB restore)

This repo includes a daily backup script:
- `deploy/backup_same_box.sh`

Cron setup instructions:
- `deploy/SAME_BOX_SECURITY.md` (general hardening)
- The backup section in this file is replaced by: `deploy/backup_same_box.sh` + cron

To set cron (server):

```bash
chmod +x /opt/psc/deploy/backup_same_box.sh
sudo mkdir -p /var/backups/psc
sudo crontab -e
```

Add:

```cron
30 2 * * * cd /opt/psc && BACKUP_DIR=/var/backups/psc RETAIN_DAYS=14 ./deploy/backup_same_box.sh >> /var/log/psc_backup.log 2>&1
```

## Step 16: Switch From Password SSH to SSH Keys (Recommended)

This step improves security and helps you avoid password attacks.

### 16.1 Generate SSH key on your computer (Windows PowerShell)

```powershell
ssh-keygen -t ed25519 -C "prakritiksparshcare"
```

Show public key:

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

Copy the full line (starts with `ssh-ed25519`).

### 16.2 Add the key to the Droplet

On the Droplet:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
nano ~/.ssh/authorized_keys
```

Paste the public key line, save, then:

```bash
chmod 600 ~/.ssh/authorized_keys
```

### 16.3 Disable password login (after confirming key login works)

Open SSH config:

```bash
nano /etc/ssh/sshd_config
```

Set/ensure:

```text
PasswordAuthentication no
```

Restart SSH:

```bash
systemctl restart ssh
```

Important: Do this only after you successfully log in using the SSH key from your computer.

## Common Problems

1. Site opens on `:8000` but not on domain
- Check DNS A record
- Check Caddy is running: `systemctl status caddy`

2. Database restore fails
- Confirm dump files exist in `/opt/psc/`
- Confirm `.env` has the correct passwords
- Run: `docker compose logs psc_db`

3. Uploaded images/PDF not showing
- Re-check you copied the correct `static/uploads` folders to the correct paths
