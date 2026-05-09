from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os
from sqlalchemy import inspect, text
from werkzeug.middleware.proxy_fix import ProxyFix

# Load environment variables
load_dotenv()

# Create SQLAlchemy instance (no app bound yet)
db = SQLAlchemy()

LEVEL_PLAN_BASE_SEEDS = [
    {"level_no": 1, "number_of_id": 50, "income_per_id": 10, "reward_per_id": 10},
    {"level_no": 2, "number_of_id": 400, "income_per_id": 9, "reward_per_id": 10},
    {"level_no": 3, "number_of_id": 4000, "income_per_id": 8, "reward_per_id": 10},
    {"level_no": 4, "number_of_id": 8000, "income_per_id": 7, "reward_per_id": 10},
    {"level_no": 5, "number_of_id": 25000, "income_per_id": 6, "reward_per_id": 10},
]

LEVEL_PLAN_PRODUCTS = ("Pad", "Diaper")


def build_level_plan_seeds():
    seeds = []
    for product in LEVEL_PLAN_PRODUCTS:
        for seed in LEVEL_PLAN_BASE_SEEDS:
            row = dict(seed)
            row["product_type"] = product
            seeds.append(row)
    return seeds

def ensure_user_login_level_column(app: Flask):
    """Guardrail to add user_login.level when the backing table is still old."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        if 'user_login' not in inspector.get_table_names():
            return

        columns = {col_info['name'] for col_info in inspector.get_columns('user_login')}
        try:
            with engine.begin() as conn:
                if 'level' not in columns:
                    conn.execute(text("ALTER TABLE user_login ADD COLUMN level INTEGER NOT NULL DEFAULT 1;"))
                    app.logger.info("Added missing user_login.level column via auto-migration.")

                conn.execute(text("ALTER TABLE user_login ALTER COLUMN level SET DEFAULT 1;"))
                conn.execute(text("UPDATE user_login SET level = 1 WHERE level IS NULL OR level < 1;"))
        except Exception:
            # Do not crash the app if the connected DB user doesn't have DDL privileges
            # (this can happen after restoring DB dumps with different owners).
            app.logger.exception("Skipping ensure_user_login_level_column due to DB permissions or engine error.")


def ensure_user_login_columns(app: Flask):
    """Ensure extra attributes needed for hierarchy/tracking exist on user_login."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        if 'user_login' not in inspector.get_table_names():
            return

        columns = {col['name'] for col in inspector.get_columns('user_login')}
        updates = []
        if 'parent_user_id' not in columns:
            updates.append("ALTER TABLE user_login ADD COLUMN parent_user_id INTEGER REFERENCES user_login(id);")
        if 'referral_count' not in columns:
            updates.append("ALTER TABLE user_login ADD COLUMN referral_count INTEGER NOT NULL DEFAULT 0;")
        if 'type_of_user' not in columns:
            updates.append("ALTER TABLE user_login ADD COLUMN type_of_user VARCHAR(50);")

        if not updates:
            updates = []

        with engine.begin() as conn:
            for sql in updates:
                conn.execute(text(sql))

            # Keep legacy and current role columns aligned for older databases.
            conn.execute(text("""
                UPDATE user_login
                SET type_of_user = CASE
                    WHEN LOWER(TRIM(role)) = 'temp member' THEN 'Temp Member'
                    WHEN LOWER(TRIM(role)) IN ('member', 'leader') THEN INITCAP(TRIM(role))
                    WHEN LOWER(TRIM(role)) = 'admin' THEN 'Admin'
                    ELSE type_of_user
                END
                WHERE LOWER(TRIM(role)) IN ('member', 'leader', 'temp member', 'admin')
                  AND (type_of_user IS NULL OR TRIM(type_of_user) = '');
            """))
            conn.execute(text("""
                UPDATE user_login
                SET type_of_user = 'Temp Member'
                WHERE LOWER(TRIM(COALESCE(type_of_user, ''))) IN ('temp_member', 'temp-member');
            """))
            conn.execute(text("""
                UPDATE user_login
                SET role = 'admin'
                WHERE LOWER(TRIM(COALESCE(type_of_user, ''))) = 'admin';
            """))
            conn.execute(text("""
                 UPDATE user_login
                 SET role = 'user'
                 WHERE LOWER(TRIM(COALESCE(type_of_user, 'member'))) <> 'admin';
             """))
            conn.execute(text("""
                UPDATE user_login
                SET type_of_user = 'Member'
                WHERE type_of_user IS NULL OR TRIM(type_of_user) = '';
            """))

            if updates:
                app.logger.info("Added hierarchy columns to user_login.")


def ensure_user_login_profile_photo_column(app: Flask):
    """Add user_login.image_path for profile photo uploads when missing."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        if 'user_login' not in inspector.get_table_names():
            return

        columns = {col_info['name'] for col_info in inspector.get_columns('user_login')}
        if 'image_path' in columns:
            return

        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE user_login ADD COLUMN image_path VARCHAR(255);"))
                app.logger.info("Added missing user_login.image_path column via auto-migration.")
        except Exception:
            app.logger.exception("Skipping ensure_user_login_profile_photo_column due to DB permissions or engine error.")

def ensure_base_schema(app: Flask):
    """
    Ensure the core schema exists on a fresh database.

    Many of our lightweight "ensure_*" auto-migrations assume base tables like
    user_login already exist (because they were created historically).
    On a brand-new cloud DB, those tables do not exist yet, so we must create
    all model tables first (checkfirst=True) and then apply additive migrations.
    """
    with app.app_context():
        # Ensure model metadata is registered before create_all().
        from . import models  # noqa: F401
        db.create_all()


def ensure_schema_bootstrap(app: Flask):
    """
    Run schema bootstrap + additive migrations exactly-once at a time.

    Gunicorn runs multiple worker processes. On a fresh database, running schema
    DDL concurrently can race (especially Postgres ENUM type creation).
    We serialize all schema work using a Postgres advisory lock.
    """
    with app.app_context():
        engine = db.get_engine()
        lock_key = 2026042401  # any constant int; project-specific lock key
        conn = engine.connect()
        try:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": lock_key})

            def _best_effort(label: str, fn, critical: bool = False):
                try:
                    fn(app)
                except Exception:
                    app.logger.exception("Auto-migration failed (%s).", label)
                    if critical:
                        raise

            # Base schema is required on a fresh install; if it fails, we should crash loudly.
            _best_effort("base_schema", ensure_base_schema, critical=True)

            # Everything else is additive migration. If permissions prevent DDL, we log and continue.
            _best_effort("user_login_level", ensure_user_login_level_column)
            _best_effort("user_login_columns", ensure_user_login_columns)
            _best_effort("user_login_profile_photo", ensure_user_login_profile_photo_column)
            _best_effort("level_plans", ensure_level_plans_table)
            _best_effort("user_creation_requests", ensure_user_creation_requests_table)
            _best_effort("user_creation_request_columns", ensure_user_creation_request_columns)
            _best_effort("reference_tables", ensure_reference_tables)
            _best_effort("epin_columns", ensure_epin_columns)
            _best_effort("epin_transfer_columns", ensure_epin_transfer_columns)
            _best_effort("pin_usage_table", ensure_pin_usage_table)
            _best_effort("legal_documents_table", ensure_legal_documents_table)
            _best_effort("withdraw_requests_table", ensure_withdraw_requests_table)
            _best_effort("login_page_visits_table", ensure_login_page_visits_table)
            _best_effort("referral_paid_column", ensure_referral_paid_column)
            _best_effort("emp_id_sequence", ensure_emp_id_sequence)
        finally:
            try:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key})
            except Exception:
                pass
            conn.close()


def ensure_user_creation_requests_table(app: Flask):
    """Auto-create the approval queue table if it is missing."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        if 'user_creation_requests' in inspector.get_table_names():
            return

        from .models import UserCreationRequest
        UserCreationRequest.__table__.create(engine, checkfirst=True)
        app.logger.info("Created user_creation_requests table via auto-migration.")


def ensure_user_creation_request_columns(app: Flask):
    """Add newer request queue columns to older databases."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        if 'user_creation_requests' not in inspector.get_table_names():
            return

        columns = {col['name'] for col in inspector.get_columns('user_creation_requests')}
        updates = []
        if 'requested_pin_count' not in columns:
            updates.append("ALTER TABLE user_creation_requests ADD COLUMN requested_pin_count INTEGER NOT NULL DEFAULT 1;")
        if 'selected_epin_id' not in columns:
            updates.append("ALTER TABLE user_creation_requests ADD COLUMN selected_epin_id INTEGER REFERENCES epins(id);")

        if not updates:
            return

        with engine.begin() as conn:
            for sql in updates:
                conn.execute(text(sql))
            conn.execute(text("UPDATE user_creation_requests SET requested_pin_count = 1 WHERE requested_pin_count IS NULL OR requested_pin_count < 1;"))

        app.logger.info("Updated user_creation_requests schema with pin allocation columns.")


def ensure_epin_columns(app: Flask):
    """Ensure new EPin columns exist after schema changes."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        if 'epins' not in inspector.get_table_names():
            return

        columns = {col['name'] for col in inspector.get_columns('epins')}
        updates = []
        if 'pin_type_id' not in columns:
            updates.append("ALTER TABLE epins ADD COLUMN pin_type_id INTEGER REFERENCES pin_types(id);")
        if 'product_type_id' not in columns:
            updates.append("ALTER TABLE epins ADD COLUMN product_type_id INTEGER REFERENCES product_types(id);")

        if not updates:
            return

        with engine.begin() as conn:
            for sql in updates:
                conn.execute(text(sql))
            app.logger.info("Added column(s) to epins via auto-migration.")


def ensure_epin_transfer_columns(app: Flask):
    """Ensure transfer status columns exist for disabling mistaken transfers."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        if 'epin_transfers' not in inspector.get_table_names():
            return

        columns = {col['name'] for col in inspector.get_columns('epin_transfers')}
        updates = []
        if 'status' not in columns:
            updates.append("ALTER TABLE epin_transfers ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'Active';")
        if 'disabled_at' not in columns:
            updates.append("ALTER TABLE epin_transfers ADD COLUMN disabled_at TIMESTAMP;")
        if 'disabled_reason' not in columns:
            updates.append("ALTER TABLE epin_transfers ADD COLUMN disabled_reason VARCHAR(255);")

        if not updates:
            return

        with engine.begin() as conn:
            for sql in updates:
                conn.execute(text(sql))
            conn.execute(text("UPDATE epin_transfers SET status = 'Active' WHERE status IS NULL OR TRIM(status) = '';"))
        app.logger.info("Updated epin_transfers schema with transfer status columns.")


def ensure_pin_usage_table(app: Flask):
    """Create the pin usage report table if it is missing."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        if 'pin_usage_reports' in inspector.get_table_names():
            return

        from .models import PinUsageReport
        PinUsageReport.__table__.create(engine, checkfirst=True)
        app.logger.info("Created pin_usage_reports table via auto-migration.")


def ensure_legal_documents_table(app: Flask):
    """Create the legal documents table if it is missing."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        if 'legal_documents' in inspector.get_table_names():
            return

        from .models import LegalDocument
        LegalDocument.__table__.create(engine, checkfirst=True)
        app.logger.info("Created legal_documents table via auto-migration.")


def ensure_withdraw_requests_table(app: Flask):
    """Create the withdraw request table if it is missing."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        if 'withdraw_requests' in inspector.get_table_names():
            return

        from .models import WithdrawRequest
        WithdrawRequest.__table__.create(engine, checkfirst=True)
        app.logger.info("Created withdraw_requests table via auto-migration.")

def ensure_login_page_visits_table(app: Flask):
    """Create the login page visit counter table if it is missing."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        if 'login_page_visits' in inspector.get_table_names():
            return

        from .models import LoginPageVisit
        LoginPageVisit.__table__.create(engine, checkfirst=True)
        app.logger.info("Created login_page_visits table via auto-migration.")


def ensure_reference_tables(app: Flask):
    from .models import ProductType, PinType, UserRole, ReferenceOption

    with app.app_context():
        engine = db.get_engine()
        ProductType.__table__.create(engine, checkfirst=True)
        PinType.__table__.create(engine, checkfirst=True)
        UserRole.__table__.create(engine, checkfirst=True)
        ReferenceOption.__table__.create(engine, checkfirst=True)

        session = db.session
        seeds = {
            ProductType: [("Pad", "CBD pad product line"), ("Diaper", "Diaper product line")],
            PinType: [
                ("Joining", "Legacy onboarding pin type"),
                ("Top up", "Re-charge pin"),
                ("Product pin", "Product entitlement pin"),
                ("Trial Pin", "Training/testing pin without level impact")
            ],
            UserRole: [
                ("admin", "System administrator"),
                ("user", "General user"),
                ("member", "Regular member"),
                ("leader", "Team leader"),
                ("temp member", "Temporary member"),
                ("trainer", "Trainer user")
            ]
        }
        added = False
        for model, values in seeds.items():
            for name, desc in values:
                existing = session.query(model).filter_by(name=name).first()
                if not existing:
                    session.add(model(name=name, description=desc))
                    added = True
        if added:
            session.commit()
            app.logger.info("Seeded reference tables (product_type, pin_type, user_role).")

        option_seeds = {
            "access_role": [
                ("user", "User", "Standard portal user"),
                ("admin", "Administrator", "Administrative portal access"),
            ],
            "user_status": [
                ("Active", "Active", "Can sign in and transact"),
                ("Inactive", "Inactive", "Cannot use active workflows"),
            ],
            "approval_status": [
                ("Pending", "Pending", "Waiting for approval"),
                ("Approved", "Approved", "Approved for portal use"),
                ("Rejected", "Rejected", "Rejected by admin"),
            ],
            "request_status": [
                ("Pending", "Pending", "Waiting for admin decision"),
                ("Approved", "Approved", "Approved by admin"),
                ("Rejected", "Rejected", "Rejected by admin"),
            ],
            "withdraw_status": [
                ("Pending", "Pending", "Waiting for admin decision"),
                ("Approved", "Approved", "Approved by admin"),
                ("Rejected", "Rejected", "Rejected by admin"),
            ],
            "support_ticket_status": [
                ("Open", "Open", "New or active support ticket"),
                ("Pending", "Pending", "Waiting for action or response"),
                ("Closed", "Closed", "Resolved support ticket"),
            ],
            "support_query_type": [
                ("Wallet", "Wallet Issue", "Wallet, balance, or withdrawal help"),
                ("Pin", "E-Pin Issue", "Pin transfer, registration, or usage help"),
                ("Profile", "Profile / Bank", "Profile or bank details help"),
                ("Income", "Income Issue", "Income, level, or reward help"),
                ("Other", "Other", "General support request"),
            ],
            "epin_status": [
                ("Unused", "Unused", "Available pin"),
                ("Reserved", "Reserved", "Held for an approval request"),
                ("Used", "Used", "Consumed pin"),
            ],
            "epin_transfer_status": [
                ("Active", "Active", "Valid transfer"),
                ("Disabled", "Disabled", "Transfer disabled by admin"),
            ],
            "product_filter": [
                ("All", "All", "All products"),
                ("Pad", "Pad", "Pad product line"),
                ("Diaper", "Diaper", "Diaper product line"),
                ("Both", "Both", "Pad and Diaper access"),
            ],
        }
        option_added = False
        for category, rows in option_seeds.items():
            for sort_order, (value, label, description) in enumerate(rows, start=1):
                existing = session.query(ReferenceOption).filter_by(category=category, value=value).first()
                if not existing:
                    session.add(ReferenceOption(
                        category=category,
                        value=value,
                        label=label,
                        description=description,
                        sort_order=sort_order,
                        is_active=True
                    ))
                    option_added = True
        if option_added:
            session.commit()
            app.logger.info("Seeded generic reference_options.")


def ensure_referral_paid_column(app: Flask):
    """Add referral_paid tracker to user_login if missing."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        if 'user_login' not in inspector.get_table_names():
            return

        columns = {col['name'] for col in inspector.get_columns('user_login')}
        if 'referral_paid' in columns:
            return

        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE user_login ADD COLUMN referral_paid INTEGER NOT NULL DEFAULT 0;"))
        app.logger.info("Added user_login.referral_paid column via auto-migration.")


def ensure_emp_id_sequence(app: Flask):
    """Backfill/create sequential employee IDs for every user_login row."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        if 'user_login' not in inspector.get_table_names():
            return

        from .emp_id import sync_emp_ids

        sync_emp_ids()

def ensure_level_plans_table(app: Flask):
    """Make sure the level_plans table exists and contains the default seed rows."""
    with app.app_context():
        engine = db.get_engine()
        inspector = inspect(engine)
        table_missing = 'level_plans' not in inspector.get_table_names()

        creation_sql = text(
            """
            CREATE TABLE level_plans (
                id SERIAL PRIMARY KEY,
                product_type VARCHAR(50) NOT NULL DEFAULT 'Pad',
                level_no INT NOT NULL,
                number_of_id INT NOT NULL DEFAULT 0,
                income_per_id INT NOT NULL DEFAULT 0,
                reward_per_id INT NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT uq_level_plans_product_level UNIQUE (product_type, level_no)
            );
            """
        )

        insert_sql = text(
            """
            INSERT INTO level_plans (product_type, level_no, number_of_id, income_per_id, reward_per_id)
            VALUES (:product_type, :level_no, :number_of_id, :income_per_id, :reward_per_id)
            ON CONFLICT (product_type, level_no) DO UPDATE SET
              number_of_id = EXCLUDED.number_of_id,
              income_per_id = EXCLUDED.income_per_id,
              reward_per_id = EXCLUDED.reward_per_id;
            """
        )

        with engine.begin() as conn:
            if table_missing:
                conn.execute(creation_sql)
                app.logger.info("Created missing level_plans table via auto-migration.")
            else:
                columns = {col['name'] for col in inspector.get_columns('level_plans')}
                if 'product_type' not in columns:
                    conn.execute(text("ALTER TABLE level_plans ADD COLUMN product_type VARCHAR(50) DEFAULT 'Pad';"))
                    conn.execute(text("UPDATE level_plans SET product_type = 'Pad' WHERE product_type IS NULL OR TRIM(product_type) = '';"))

                unique_constraints = inspector.get_unique_constraints('level_plans')
                for constraint in unique_constraints:
                    columns_in_constraint = tuple(constraint.get('column_names') or [])
                    if columns_in_constraint == ('level_no',) and constraint.get('name'):
                        conn.execute(text(f'ALTER TABLE level_plans DROP CONSTRAINT IF EXISTS "{constraint["name"]}";'))

                existing_product_levels = conn.execute(text("SELECT product_type, level_no FROM level_plans")).fetchall()
                existing_keys = {(row[0], row[1]) for row in existing_product_levels}
                base_pad_rows = conn.execute(text("""
                    SELECT level_no, number_of_id, income_per_id, reward_per_id
                    FROM level_plans
                    WHERE product_type = 'Pad'
                """)).fetchall()
                for row in base_pad_rows:
                    key = ('Diaper', row[0])
                    if key not in existing_keys:
                        conn.execute(text("""
                            INSERT INTO level_plans (product_type, level_no, number_of_id, income_per_id, reward_per_id)
                            VALUES ('Diaper', :level_no, :number_of_id, :income_per_id, :reward_per_id)
                        """), {
                            'level_no': row[0],
                            'number_of_id': row[1],
                            'income_per_id': row[2],
                            'reward_per_id': row[3]
                        })

                conn.execute(text("""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'uq_level_plans_product_level'
                        ) THEN
                            ALTER TABLE level_plans
                            ADD CONSTRAINT uq_level_plans_product_level UNIQUE (product_type, level_no);
                        END IF;
                    END $$;
                """))

            for seed in build_level_plan_seeds():
                conn.execute(insert_sql, seed)

def create_app():
    app = Flask(__name__)

    # Config from .env
    app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "dev_secret")

    # Main PSC database. In cloud deployments we recommend using a dedicated DB for PSC
    # and a separate DB for the external coupon engine.
    db_url = os.getenv("PSC_DATABASE_URL") or os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:password@localhost:5432/psc_db",
    )
    # Some providers still supply "postgres://" URLs; SQLAlchemy expects "postgresql://".
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://") :]
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['COUPON_ENGINE_ADMIN_URL'] = os.getenv(
        "COUPON_ENGINE_ADMIN_URL",
        "/external-coupen-system/admin"
    )
    app.config['COUPON_ENGINE_PUBLIC_URL'] = os.getenv(
        "COUPON_ENGINE_PUBLIC_URL",
        "/external-coupen-system/coupon/entry"
    )

    # Initialize db
    db.init_app(app)

    # Trust proxy headers (Caddy/NGINX/DO Load Balancer) so external links + redirects use https correctly.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    app.config.setdefault("PREFERRED_URL_SCHEME", "https")

    ensure_schema_bootstrap(app)

    # Register blueprints
    from .routes import main
    app.register_blueprint(main)

    return app
