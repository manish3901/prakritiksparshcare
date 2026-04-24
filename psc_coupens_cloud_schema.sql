-- psc_coupens_cloud_schema.sql
-- Manual PostgreSQL schema for the external PSC coupon system.
-- Generated from psc_coupens/psc_coupens_app/models.py SQLAlchemy metadata.
-- This file is intentionally separate from psc_cloud_schema.sql so coupon users/data remain isolated.
-- Includes coupon tables, primary keys, foreign keys, unique constraints, indexes, and SQL defaults.
-- Intended for a fresh/empty cloud PostgreSQL database or a separate external coupon database/schema.

BEGIN;

-- Tables and inline constraints
-- Table: coupon_name

CREATE TABLE IF NOT EXISTS coupon_name (
	coupon_name_id SERIAL NOT NULL, 
	coupon_name VARCHAR(100) NOT NULL, 
	description TEXT, 
	status VARCHAR(8) DEFAULT 'Active', 
	barcode_value VARCHAR(32), 
	PRIMARY KEY (coupon_name_id)
);

-- Table: coupon_validators

CREATE TABLE IF NOT EXISTS coupon_validators (
	id SERIAL NOT NULL, 
	mobile_no VARCHAR(10) NOT NULL, 
	name VARCHAR(120), 
	city VARCHAR(120), 
	status VARCHAR(8) DEFAULT 'Active', 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id)
);

-- Table: coupon_codes

CREATE TABLE IF NOT EXISTS coupon_codes (
	id SERIAL NOT NULL, 
	coupon_name_id INTEGER NOT NULL, 
	code VARCHAR(32) NOT NULL, 
	status VARCHAR(8) DEFAULT 'Active', 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	FOREIGN KEY(coupon_name_id) REFERENCES coupon_name (coupon_name_id)
);

-- Table: coupon_distribution_settings

CREATE TABLE IF NOT EXISTS coupon_distribution_settings (
	coupon_name_id INTEGER NOT NULL, 
	unlock_at INTEGER DEFAULT 1000, 
	window1_end INTEGER DEFAULT 1500, 
	window2_end INTEGER DEFAULT 2000, 
	level1_cap_w1 INTEGER DEFAULT 1, 
	level1_cap_w2 INTEGER DEFAULT 2, 
	level2_cap_w1 INTEGER DEFAULT 2, 
	level3_cap_w1 INTEGER DEFAULT 2, 
	level1_mult FLOAT DEFAULT 0.35, 
	level2_mult FLOAT DEFAULT 1.0, 
	level3_mult FLOAT DEFAULT 1.8, 
	level4_mult FLOAT DEFAULT 0.8, 
	level5_mult FLOAT DEFAULT 1.0, 
	level6_mult FLOAT DEFAULT 1.3, 
	level7_mult FLOAT DEFAULT 1.7, 
	PRIMARY KEY (coupon_name_id), 
	FOREIGN KEY(coupon_name_id) REFERENCES coupon_name (coupon_name_id)
);

-- Table: coupon_master

CREATE TABLE IF NOT EXISTS coupon_master (
	coupon_master_id SERIAL NOT NULL, 
	coupon_name_id INTEGER NOT NULL, 
	coupon_type VARCHAR(50) NOT NULL, 
	max_allowed INTEGER DEFAULT 0, 
	prize_level INTEGER, 
	weight INTEGER DEFAULT 1, 
	awarded_count INTEGER DEFAULT 0, 
	status VARCHAR(8) DEFAULT 'Active', 
	prize_image VARCHAR(255), 
	PRIMARY KEY (coupon_master_id), 
	FOREIGN KEY(coupon_name_id) REFERENCES coupon_name (coupon_name_id)
);

-- Table: coupon_users

CREATE TABLE IF NOT EXISTS coupon_users (
	coupon_user_id SERIAL NOT NULL, 
	first_name VARCHAR(100) NOT NULL, 
	last_name VARCHAR(100), 
	mobile_no VARCHAR(10) NOT NULL, 
	area_zone VARCHAR(100), 
	coupon_master_id INTEGER, 
	coupon_code_id INTEGER, 
	unique_code VARCHAR(5), 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (coupon_user_id), 
	FOREIGN KEY(coupon_master_id) REFERENCES coupon_master (coupon_master_id), 
	FOREIGN KEY(coupon_code_id) REFERENCES coupon_codes (id)
);

-- Table: coupon_prize_audit

CREATE TABLE IF NOT EXISTS coupon_prize_audit (
	id SERIAL NOT NULL, 
	coupon_user_id INTEGER NOT NULL, 
	coupon_name_id INTEGER NOT NULL, 
	coupon_master_id INTEGER NOT NULL, 
	prize_level INTEGER, 
	selection_mode VARCHAR(32) DEFAULT 'weighted', 
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP, 
	PRIMARY KEY (id), 
	FOREIGN KEY(coupon_user_id) REFERENCES coupon_users (coupon_user_id), 
	FOREIGN KEY(coupon_name_id) REFERENCES coupon_name (coupon_name_id), 
	FOREIGN KEY(coupon_master_id) REFERENCES coupon_master (coupon_master_id)
);

-- Indexes
CREATE UNIQUE INDEX IF NOT EXISTS ix_coupon_name_barcode_value ON coupon_name (barcode_value);
CREATE INDEX IF NOT EXISTS ix_coupon_name_status ON coupon_name (status);
CREATE INDEX IF NOT EXISTS ix_coupon_validators_created_at ON coupon_validators (created_at);
CREATE UNIQUE INDEX IF NOT EXISTS ix_coupon_validators_mobile_no ON coupon_validators (mobile_no);
CREATE INDEX IF NOT EXISTS ix_coupon_validators_status ON coupon_validators (status);
CREATE UNIQUE INDEX IF NOT EXISTS ix_coupon_codes_code ON coupon_codes (code);
CREATE INDEX IF NOT EXISTS ix_coupon_codes_coupon_name_id ON coupon_codes (coupon_name_id);
CREATE INDEX IF NOT EXISTS ix_coupon_codes_created_at ON coupon_codes (created_at);
CREATE INDEX IF NOT EXISTS ix_coupon_codes_status ON coupon_codes (status);
CREATE INDEX IF NOT EXISTS ix_coupon_master_status ON coupon_master (status);
CREATE INDEX IF NOT EXISTS ix_coupon_users_created_at ON coupon_users (created_at);
CREATE INDEX IF NOT EXISTS ix_coupon_users_mobile_no ON coupon_users (mobile_no);
CREATE UNIQUE INDEX IF NOT EXISTS ix_coupon_users_unique_code ON coupon_users (unique_code);
CREATE INDEX IF NOT EXISTS ix_coupon_prize_audit_coupon_master_id ON coupon_prize_audit (coupon_master_id);
CREATE INDEX IF NOT EXISTS ix_coupon_prize_audit_coupon_name_id ON coupon_prize_audit (coupon_name_id);
CREATE INDEX IF NOT EXISTS ix_coupon_prize_audit_coupon_user_id ON coupon_prize_audit (coupon_user_id);
CREATE INDEX IF NOT EXISTS ix_coupon_prize_audit_created_at ON coupon_prize_audit (created_at);
CREATE INDEX IF NOT EXISTS ix_coupon_prize_audit_prize_level ON coupon_prize_audit (prize_level);
CREATE INDEX IF NOT EXISTS ix_coupon_prize_audit_selection_mode ON coupon_prize_audit (selection_mode);

-- Safety cleanup from older coupon schemas: coupon_code_id must be indexed, not unique.
ALTER TABLE coupon_users DROP CONSTRAINT IF EXISTS ix_coupon_users_coupon_code_id;
DROP INDEX IF EXISTS ix_coupon_users_coupon_code_id;
CREATE INDEX IF NOT EXISTS ix_coupon_users_coupon_code_id ON coupon_users (coupon_code_id) WHERE coupon_code_id IS NOT NULL;

COMMIT;
