# Restore (Same-Box Docker Postgres)

This restores from backups created by `deploy/backup_same_box.sh`.

## 1) Copy Backup Folder To Server

Example backup folder:

`/var/backups/psc/20260424_093000/`

It contains:
- `psc_main.dump`
- `psc_coupon.dump`
- `uploads_psc.tar.gz`
- `uploads_coupon.tar.gz`

## 2) Stop Web Container (Optional but recommended)

```bash
cd /opt/psc
docker compose stop psc_web
```

## 3) Restore Databases

Warning: this will overwrite data in the target DB.

```bash
cd /opt/psc

# MAIN DB
docker compose exec -T psc_db bash -lc \
  "PGPASSWORD=\"${PSC_DB_PASSWORD}\" dropdb -U psc_admin --if-exists psc_main && createdb -U psc_admin psc_main"
cat /var/backups/psc/<BACKUP_FOLDER>/psc_main.dump | docker compose exec -T psc_db bash -lc \
  "PGPASSWORD=\"${PSC_DB_PASSWORD}\" pg_restore -U psc_admin -d psc_main --clean --if-exists"

# COUPON DB
docker compose exec -T psc_db bash -lc \
  "PGPASSWORD=\"${PSC_DB_PASSWORD}\" dropdb -U psc_admin --if-exists psc_coupon && createdb -U psc_admin psc_coupon"
cat /var/backups/psc/<BACKUP_FOLDER>/psc_coupon.dump | docker compose exec -T psc_db bash -lc \
  "PGPASSWORD=\"${PSC_DB_PASSWORD}\" pg_restore -U psc_admin -d psc_coupon --clean --if-exists"
```

## 4) Restore Uploads

```bash
cd /opt/psc
tar -xzf /var/backups/psc/<BACKUP_FOLDER>/uploads_psc.tar.gz -C /opt/psc
tar -xzf /var/backups/psc/<BACKUP_FOLDER>/uploads_coupon.tar.gz -C /opt/psc
```

## 5) Start Web Container

```bash
cd /opt/psc
docker compose start psc_web
```
