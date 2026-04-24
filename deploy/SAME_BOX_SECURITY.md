# Same-Box Postgres Security (Recommended Checklist)

This is for the plan where:
- the Flask app runs on a cloud VPS/Droplet
- Postgres also runs on the same VPS (in Docker containers via `docker-compose.yml`)

## 1) Database Is Not Publicly Exposed

In our `docker-compose.yml` the Postgres services **do not publish ports** to the host.
This means there is no `:5432` open on the internet.

## 2) Firewall Rules (UFW)

Allow only:
- SSH (22) from your IP (best)
- HTTP (80) and HTTPS (443) for users

Example:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 22/tcp
sudo ufw enable
sudo ufw status
```

If possible, restrict SSH to your IP:

```bash
sudo ufw delete allow 22/tcp
sudo ufw allow from <YOUR_PUBLIC_IP> to any port 22 proto tcp
```

## 3) Strong Secrets (.env on server)

Create a `.env` on the server with:
- `SECRET_KEY` (random)
- `PSC_DB_PASSWORD` (strong)
- `COUPON_DB_PASSWORD` (strong)

These are consumed by Docker Compose and used in:
- `PSC_DATABASE_URL`
- `COUPON_DATABASE_URL`

## 4) OS Hardening (Quick wins)

- Keep system updated:
```bash
sudo apt-get update && sudo apt-get -y upgrade
```

- Disable password SSH login and use SSH keys (recommended).

## 5) Backups (must-have)

Even with same-box DB, you should have **off-server** backups:

- Daily snapshot/backups from your provider (easy).
- Or schedule a nightly `pg_dump` and upload to safe storage (S3/Spaces/Drive).

At minimum, test restore once so you know the backup is actually usable.

## 6) Uploads Persistence

Uploads are persisted via host volumes:
- `./Psparshcare/static/uploads:/app/Psparshcare/static/uploads`
- `./psc_coupens/psc_coupens_app/static/uploads:/app/psc_coupens/psc_coupens_app/static/uploads`

Include these directories in your server backups too.

