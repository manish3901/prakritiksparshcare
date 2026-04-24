-- psc_cloud_schema.sql
-- Manual PostgreSQL schema for the current PSC application.
-- Generated from Psparshcare.models SQLAlchemy metadata.
-- Includes current tables, primary keys, foreign keys, unique constraints, indexes, enum types, SQL defaults, and safe baseline reference seeds.
-- Intended for a fresh/empty cloud PostgreSQL database. Review before running on an existing database.

BEGIN;

-- Enum types
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'request_status') THEN
        CREATE TYPE request_status AS ENUM ('Pending', 'Approved', 'Rejected');
    END IF;
END $$;

-- Tables and inline constraints
-- Table: carousel_images

CREATE TABLE IF NOT EXISTS carousel_images (
	id SERIAL NOT NULL, 
	image_path VARCHAR(255) NOT NULL, 
	title VARCHAR(100), 
	caption VARCHAR(255), 
	is_active BOOLEAN DEFAULT TRUE, 
	"order" INTEGER DEFAULT 0, 
	PRIMARY KEY (id)
);

-- Table: company_profile

CREATE TABLE IF NOT EXISTS company_profile (
	id SERIAL NOT NULL, 
	about_us TEXT, 
	vision TEXT, 
	mission TEXT, 
	address TEXT, 
	email VARCHAR(120), 
	phone VARCHAR(20), 
	map_url TEXT, 
	PRIMARY KEY (id)
);

-- Table: events

CREATE TABLE IF NOT EXISTS events (
	id SERIAL NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	description TEXT, 
	event_date DATE, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

-- Table: legal_documents

CREATE TABLE IF NOT EXISTS legal_documents (
	id SERIAL NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	description TEXT, 
	file_path VARCHAR(255) NOT NULL, 
	file_type VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

-- Table: level_plans

CREATE TABLE IF NOT EXISTS level_plans (
	id SERIAL NOT NULL, 
	product_type VARCHAR(50) DEFAULT 'Pad' NOT NULL, 
	level_no INTEGER NOT NULL, 
	number_of_id INTEGER DEFAULT 0 NOT NULL, 
	income_per_id INTEGER DEFAULT 0 NOT NULL, 
	reward_per_id INTEGER DEFAULT 0 NOT NULL, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_level_plans_product_level UNIQUE (product_type, level_no)
);

-- Table: news

CREATE TABLE IF NOT EXISTS news (
	id SERIAL NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	description TEXT NOT NULL, 
	image_path VARCHAR(255), 
	attachments TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

-- Table: pin_types

CREATE TABLE IF NOT EXISTS pin_types (
	id SERIAL NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	description VARCHAR(255), 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

-- Table: product_types

CREATE TABLE IF NOT EXISTS product_types (
	id SERIAL NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	description VARCHAR(255), 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

-- Table: quick_links

CREATE TABLE IF NOT EXISTS quick_links (
	id SERIAL NOT NULL, 
	title VARCHAR(100) NOT NULL, 
	url VARCHAR(255) NOT NULL, 
	"order" INTEGER DEFAULT 0, 
	PRIMARY KEY (id)
);

-- Table: schema_meta

CREATE TABLE IF NOT EXISTS schema_meta (
	id SERIAL NOT NULL, 
	table_name VARCHAR(100) NOT NULL, 
	column_name VARCHAR(100) NOT NULL, 
	data_type VARCHAR(50) NOT NULL, 
	constraints TEXT, 
	is_nullable BOOLEAN DEFAULT TRUE, 
	default_value VARCHAR(255), 
	version INTEGER DEFAULT 1, 
	last_updated TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	remarks TEXT, 
	PRIMARY KEY (id)
);

-- Table: user_login

CREATE TABLE IF NOT EXISTS user_login (
	id SERIAL NOT NULL, 
	mobile VARCHAR(80) NOT NULL, 
	password VARCHAR(200) NOT NULL, 
	status VARCHAR(20) DEFAULT 'Active', 
	name VARCHAR(100), 
	role VARCHAR(20) DEFAULT 'user', 
	city VARCHAR(100), 
	product_type VARCHAR(50), 
	pin_type VARCHAR(50), 
	approval_status VARCHAR(20) DEFAULT 'Pending', 
	emp_id VARCHAR(20), 
	type_of_user VARCHAR(50), 
	level INTEGER DEFAULT 1, 
	parent_user_id INTEGER, 
	referral_count INTEGER DEFAULT 0, 
	referral_paid INTEGER DEFAULT 0, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	UNIQUE (mobile), 
	UNIQUE (emp_id), 
	FOREIGN KEY(parent_user_id) REFERENCES user_login (id)
);

-- Table: user_roles

CREATE TABLE IF NOT EXISTS user_roles (
	id SERIAL NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	description VARCHAR(255), 
	PRIMARY KEY (id), 
	UNIQUE (name)
);

-- Table: reference_options

CREATE TABLE IF NOT EXISTS reference_options (
	id SERIAL NOT NULL, 
	category VARCHAR(80) NOT NULL, 
	value VARCHAR(80) NOT NULL, 
	label VARCHAR(120) NOT NULL, 
	description VARCHAR(255), 
	sort_order INTEGER DEFAULT 0, 
	is_active BOOLEAN DEFAULT TRUE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_reference_options_category_value UNIQUE (category, value)
);

-- Table: login_page_visits

CREATE TABLE IF NOT EXISTS login_page_visits (
	id SERIAL NOT NULL, 
	visit_date DATE NOT NULL, 
	visit_count INTEGER DEFAULT 0, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_login_page_visits_visit_date UNIQUE (visit_date)
);

-- Table: account_settings

CREATE TABLE IF NOT EXISTS account_settings (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	ifsc VARCHAR(20), 
	bank_name VARCHAR(100), 
	branch VARCHAR(100), 
	acc_no VARCHAR(30), 
	acc_holder VARCHAR(100), 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_login (id)
);

-- Table: epins

CREATE TABLE IF NOT EXISTS epins (
	id SERIAL NOT NULL, 
	code VARCHAR(50) NOT NULL, 
	status VARCHAR(20) DEFAULT 'Unused', 
	owner_id INTEGER, 
	pin_type_id INTEGER, 
	product_type_id INTEGER, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	UNIQUE (code), 
	FOREIGN KEY(owner_id) REFERENCES user_login (id), 
	FOREIGN KEY(pin_type_id) REFERENCES pin_types (id), 
	FOREIGN KEY(product_type_id) REFERENCES product_types (id)
);

-- Table: event_images

CREATE TABLE IF NOT EXISTS event_images (
	id SERIAL NOT NULL, 
	event_id INTEGER NOT NULL, 
	image_path VARCHAR(255) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(event_id) REFERENCES events (id)
);

-- Table: support_tickets

CREATE TABLE IF NOT EXISTS support_tickets (
	id SERIAL NOT NULL, 
	ticket_no VARCHAR(20) NOT NULL, 
	user_id INTEGER NOT NULL, 
	user_name VARCHAR(100), 
	mobile VARCHAR(15), 
	query_type VARCHAR(50), 
	description TEXT, 
	attachments TEXT, 
	status VARCHAR(20) DEFAULT 'Open', 
	admin_remarks TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	UNIQUE (ticket_no), 
	FOREIGN KEY(user_id) REFERENCES user_login (id)
);

-- Table: user_profile

CREATE TABLE IF NOT EXISTS user_profile (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	title VARCHAR(10), 
	name VARCHAR(100), 
	father_name VARCHAR(100), 
	gender VARCHAR(10), 
	dob DATE, 
	marital_status VARCHAR(20), 
	mobile VARCHAR(15), 
	email VARCHAR(120), 
	country VARCHAR(50), 
	state VARCHAR(50), 
	city VARCHAR(50), 
	pincode VARCHAR(10), 
	address TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_login (id)
);

-- Table: wallet_transactions

CREATE TABLE IF NOT EXISTS wallet_transactions (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	date TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	description VARCHAR(255), 
	amount FLOAT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_login (id)
);

-- Table: withdraw_requests

CREATE TABLE IF NOT EXISTS withdraw_requests (
	id SERIAL NOT NULL, 
	user_id INTEGER NOT NULL, 
	requested_amount FLOAT NOT NULL, 
	available_balance FLOAT DEFAULT 0, 
	redeemable_balance FLOAT DEFAULT 0, 
	gst_rate FLOAT DEFAULT 18.0, 
	gst_amount FLOAT DEFAULT 0, 
	net_amount FLOAT DEFAULT 0, 
	status VARCHAR(20) DEFAULT 'Pending', 
	remarks TEXT, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES user_login (id)
);

-- Table: epin_transfers

CREATE TABLE IF NOT EXISTS epin_transfers (
	id SERIAL NOT NULL, 
	epin_id INTEGER, 
	from_user INTEGER, 
	to_user INTEGER, 
	transfer_date TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	type VARCHAR(20), 
	status VARCHAR(20) DEFAULT 'Active', 
	disabled_at TIMESTAMP WITHOUT TIME ZONE, 
	disabled_reason VARCHAR(255), 
	PRIMARY KEY (id), 
	FOREIGN KEY(epin_id) REFERENCES epins (id), 
	FOREIGN KEY(from_user) REFERENCES user_login (id), 
	FOREIGN KEY(to_user) REFERENCES user_login (id)
);

-- Table: pin_usage_reports

CREATE TABLE IF NOT EXISTS pin_usage_reports (
	id SERIAL NOT NULL, 
	pin_id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	buyer_name VARCHAR(120), 
	buyer_mobile VARCHAR(15), 
	city VARCHAR(120), 
	sold_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	notes VARCHAR(255), 
	PRIMARY KEY (id), 
	FOREIGN KEY(pin_id) REFERENCES epins (id), 
	FOREIGN KEY(user_id) REFERENCES user_login (id)
);

-- Table: user_creation_requests

CREATE TABLE IF NOT EXISTS user_creation_requests (
	id SERIAL NOT NULL, 
	requested_by_id INTEGER NOT NULL, 
	applicant_mobile VARCHAR(80) NOT NULL, 
	applicant_name VARCHAR(120), 
	applicant_email VARCHAR(120), 
	city VARCHAR(120), 
	pin_type VARCHAR(50), 
	requested_pin_count INTEGER DEFAULT 1, 
	selected_epin_id INTEGER, 
	requested_role VARCHAR(40), 
	notes TEXT, 
	status request_status DEFAULT 'Pending', 
	assigned_role VARCHAR(50), 
	approved_by_id INTEGER, 
	approved_at TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	FOREIGN KEY(requested_by_id) REFERENCES user_login (id), 
	FOREIGN KEY(selected_epin_id) REFERENCES epins (id), 
	FOREIGN KEY(approved_by_id) REFERENCES user_login (id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS ix_user_login_name ON user_login (name);
CREATE INDEX IF NOT EXISTS ix_user_login_status ON user_login (status);
CREATE INDEX IF NOT EXISTS ix_reference_options_category ON reference_options (category);
CREATE INDEX IF NOT EXISTS ix_reference_options_is_active ON reference_options (is_active);
CREATE INDEX IF NOT EXISTS ix_login_page_visits_visit_date ON login_page_visits (visit_date);

-- Baseline reference data used by dropdowns and level calculations
INSERT INTO product_types (name, description) VALUES
    ('Pad', 'Sanitary pad product line'),
    ('Diaper', 'Diaper product line')
ON CONFLICT (name) DO NOTHING;

INSERT INTO pin_types (name, description) VALUES
    ('Joining', 'Joining pin'),
    ('Top up', 'Top up pin'),
    ('Product pin', 'Product usage/sale pin'),
    ('Trial Pin', 'Training/testing pin without level impact')
ON CONFLICT (name) DO NOTHING;

INSERT INTO user_roles (name, description) VALUES
    ('member', 'Member user'),
    ('leader', 'Leader user'),
    ('temp member', 'Temporary member user'),
    ('trainer', 'Trainer user')
ON CONFLICT (name) DO NOTHING;

INSERT INTO reference_options (category, value, label, description, sort_order, is_active) VALUES
    ('access_role', 'user', 'User', 'Standard portal user', 1, TRUE),
    ('access_role', 'admin', 'Administrator', 'Administrative portal access', 2, TRUE),
    ('user_status', 'Active', 'Active', 'Can sign in and transact', 1, TRUE),
    ('user_status', 'Inactive', 'Inactive', 'Cannot use active workflows', 2, TRUE),
    ('approval_status', 'Pending', 'Pending', 'Waiting for approval', 1, TRUE),
    ('approval_status', 'Approved', 'Approved', 'Approved for portal use', 2, TRUE),
    ('approval_status', 'Rejected', 'Rejected', 'Rejected by admin', 3, TRUE),
    ('request_status', 'Pending', 'Pending', 'Waiting for admin decision', 1, TRUE),
    ('request_status', 'Approved', 'Approved', 'Approved by admin', 2, TRUE),
    ('request_status', 'Rejected', 'Rejected', 'Rejected by admin', 3, TRUE),
    ('withdraw_status', 'Pending', 'Pending', 'Waiting for admin decision', 1, TRUE),
    ('withdraw_status', 'Approved', 'Approved', 'Approved by admin', 2, TRUE),
    ('withdraw_status', 'Rejected', 'Rejected', 'Rejected by admin', 3, TRUE),
    ('support_ticket_status', 'Open', 'Open', 'New or active support ticket', 1, TRUE),
    ('support_ticket_status', 'Pending', 'Pending', 'Waiting for action or response', 2, TRUE),
    ('support_ticket_status', 'Closed', 'Closed', 'Resolved support ticket', 3, TRUE),
    ('support_query_type', 'Wallet', 'Wallet Issue', 'Wallet, balance, or withdrawal help', 1, TRUE),
    ('support_query_type', 'Pin', 'E-Pin Issue', 'Pin transfer, registration, or usage help', 2, TRUE),
    ('support_query_type', 'Profile', 'Profile / Bank', 'Profile or bank details help', 3, TRUE),
    ('support_query_type', 'Income', 'Income Issue', 'Income, level, or reward help', 4, TRUE),
    ('support_query_type', 'Other', 'Other', 'General support request', 5, TRUE),
    ('epin_status', 'Unused', 'Unused', 'Available pin', 1, TRUE),
    ('epin_status', 'Reserved', 'Reserved', 'Held for an approval request', 2, TRUE),
    ('epin_status', 'Used', 'Used', 'Consumed pin', 3, TRUE),
    ('epin_transfer_status', 'Active', 'Active', 'Valid transfer', 1, TRUE),
    ('epin_transfer_status', 'Disabled', 'Disabled', 'Transfer disabled by admin', 2, TRUE),
    ('product_filter', 'All', 'All', 'All products', 1, TRUE),
    ('product_filter', 'Pad', 'Pad', 'Pad product line', 2, TRUE),
    ('product_filter', 'Diaper', 'Diaper', 'Diaper product line', 3, TRUE),
    ('product_filter', 'Both', 'Both', 'Pad and Diaper access', 4, TRUE)
ON CONFLICT (category, value) DO UPDATE SET
    label = EXCLUDED.label,
    description = EXCLUDED.description,
    sort_order = EXCLUDED.sort_order,
    is_active = EXCLUDED.is_active;

INSERT INTO level_plans (product_type, level_no, number_of_id, income_per_id, reward_per_id) VALUES
    ('Pad', 1, 50, 10, 10),
    ('Pad', 2, 400, 9, 10),
    ('Pad', 3, 4000, 8, 10),
    ('Pad', 4, 8000, 7, 10),
    ('Pad', 5, 25000, 6, 10),
    ('Diaper', 1, 50, 10, 10),
    ('Diaper', 2, 400, 9, 10),
    ('Diaper', 3, 4000, 8, 10),
    ('Diaper', 4, 8000, 7, 10),
    ('Diaper', 5, 25000, 6, 10)
ON CONFLICT (product_type, level_no) DO UPDATE SET
    number_of_id = EXCLUDED.number_of_id,
    income_per_id = EXCLUDED.income_per_id,
    reward_per_id = EXCLUDED.reward_per_id;

COMMIT;
