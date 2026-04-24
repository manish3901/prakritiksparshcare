import os

from dotenv import load_dotenv
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

db = SQLAlchemy()


def _ensure_schema():
    """
    Best-effort lightweight migrations so the app can evolve without Alembic.
    Safe to run on startup; failures are ignored (DB permissions/engine differences).
    """

    from sqlalchemy import inspect, text

    # Ensure model metadata is registered before calling create_all().
    from . import models  # noqa: F401

    db.create_all()

    inspector = inspect(db.engine)
    try:
        table_names = set(inspector.get_table_names())
    except Exception:
        table_names = set()

    def _cols(table):
        try:
            return {c["name"] for c in inspector.get_columns(table)}
        except Exception:
            return set()

    coupon_master_cols = _cols("coupon_master")
    coupon_users_cols = _cols("coupon_users")

    for col, ddl in (
        ("weight", "ALTER TABLE coupon_master ADD COLUMN weight INT DEFAULT 1"),
        ("awarded_count", "ALTER TABLE coupon_master ADD COLUMN awarded_count INT DEFAULT 0"),
    ):
        if "coupon_master" in table_names and col not in coupon_master_cols:
            try:
                db.session.execute(text(ddl))
                db.session.commit()
            except Exception:
                db.session.rollback()

    # Best-effort backfill: awarded_count reflects revealed scratches (unique_code set).
    if "coupon_master" in table_names and "coupon_users" in table_names and "awarded_count" in _cols("coupon_master"):
        try:
            db.session.execute(
                text(
                    "UPDATE coupon_master cm "
                    "SET awarded_count = sub.cnt "
                    "FROM ("
                    "  SELECT coupon_master_id, COUNT(*)::INT AS cnt "
                    "  FROM coupon_users "
                    "  WHERE coupon_master_id IS NOT NULL AND unique_code IS NOT NULL "
                    "  GROUP BY coupon_master_id"
                    ") sub "
                    "WHERE cm.coupon_master_id = sub.coupon_master_id"
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

    if "coupon_users" in table_names:
        try:
            db.session.execute(text("ALTER TABLE coupon_users ALTER COLUMN coupon_master_id DROP NOT NULL"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    if "coupon_users" in table_names and "coupon_code_id" not in coupon_users_cols:
        try:
            db.session.execute(text("ALTER TABLE coupon_users ADD COLUMN coupon_code_id INT"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    if "coupon_users" in table_names:
        try:
            db.session.execute(
                text(
                    "ALTER TABLE coupon_users "
                    "ADD CONSTRAINT fk_coupon_users_coupon_code_id "
                    "FOREIGN KEY (coupon_code_id) REFERENCES coupon_codes(id)"
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

        # Coupon codes are reusable across different users; coupon_code_id must NOT be unique.
        try:
            db.session.execute(text("ALTER TABLE coupon_users DROP CONSTRAINT IF EXISTS ix_coupon_users_coupon_code_id"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        try:
            db.session.execute(text("DROP INDEX IF EXISTS ix_coupon_users_coupon_code_id"))
            db.session.commit()
        except Exception:
            db.session.rollback()

        try:
            db.session.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_coupon_users_coupon_code_id "
                    "ON coupon_users (coupon_code_id) WHERE coupon_code_id IS NOT NULL"
                )
            )
            db.session.commit()
        except Exception:
            db.session.rollback()

    if "coupon_distribution_settings" in table_names:
        dist_cols = _cols("coupon_distribution_settings")
        for col, ddl in (
            ("level4_mult", "ALTER TABLE coupon_distribution_settings ADD COLUMN level4_mult DOUBLE PRECISION DEFAULT 0.8"),
            ("level5_mult", "ALTER TABLE coupon_distribution_settings ADD COLUMN level5_mult DOUBLE PRECISION DEFAULT 1.0"),
            ("level6_mult", "ALTER TABLE coupon_distribution_settings ADD COLUMN level6_mult DOUBLE PRECISION DEFAULT 1.3"),
            ("level7_mult", "ALTER TABLE coupon_distribution_settings ADD COLUMN level7_mult DOUBLE PRECISION DEFAULT 1.7"),
        ):
            if col not in dist_cols:
                try:
                    db.session.execute(text(ddl))
                    db.session.commit()
                except Exception:
                    db.session.rollback()


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev_secret")
    db_url = os.getenv("COUPON_DATABASE_URL") or os.getenv("DATABASE_URL", "sqlite:///psc_coupens.db")
    # Some providers still supply "postgres://" URLs; SQLAlchemy expects "postgresql://".
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://") :]
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # SQLite tuning for small deployments (reduces "database is locked" errors).
    if db_url.startswith("sqlite:"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"connect_args": {"timeout": 30}}

    # Trust proxy headers (Render/NGINX) so external links are correct.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.config.setdefault("PREFERRED_URL_SCHEME", "https")

    db.init_app(app)

    with app.app_context():
        _ensure_schema()

    from .routes import main

    app.register_blueprint(main)
    return app
