from datetime import datetime

from . import db


CouponNameStatus = db.Enum("Active", "Disabled", name="coupon_name_status", native_enum=False)
CouponStatus = db.Enum("Active", "Disabled", name="coupon_status", native_enum=False)
CouponValidatorStatus = db.Enum(
    "Active", "Disabled", name="coupon_validator_status", native_enum=False
)
CouponCodeStatus = db.Enum("Active", "Disabled", name="coupon_code_status", native_enum=False)


class CouponName(db.Model):
    __tablename__ = "coupon_name"

    coupon_name_id = db.Column(db.Integer, primary_key=True)
    coupon_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(CouponNameStatus, default="Active", index=True)
    barcode_value = db.Column(db.String(32), unique=True, index=True)

    def __repr__(self):
        return f"<CouponName {self.coupon_name}>"


class CouponMaster(db.Model):
    __tablename__ = "coupon_master"

    coupon_master_id = db.Column(db.Integer, primary_key=True)
    coupon_name_id = db.Column(db.Integer, db.ForeignKey("coupon_name.coupon_name_id"), nullable=False)
    coupon_type = db.Column(db.String(50), nullable=False)
    max_allowed = db.Column(db.Integer, default=0)
    prize_level = db.Column(db.Integer)  # 1,2,3.. (lower = higher value)
    weight = db.Column(db.Integer, default=1)  # relative probability within the same level
    awarded_count = db.Column(db.Integer, default=0)  # revealed scratches awarded for this master
    status = db.Column(CouponStatus, default="Active", index=True)
    prize_image = db.Column(db.String(255))  # 'uploads/coupons/<file>'

    coupon_name = db.relationship("CouponName", backref=db.backref("masters", lazy=True))

    def __repr__(self):
        return f"<CouponMaster {self.coupon_type} (Level {self.prize_level})>"


class CouponUser(db.Model):
    __tablename__ = "coupon_users"

    coupon_user_id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100))
    mobile_no = db.Column(db.String(10), nullable=False, index=True)
    area_zone = db.Column(db.String(100))
    # Assigned at scratch reveal time; allow NULL for "registered but not revealed".
    coupon_master_id = db.Column(db.Integer, db.ForeignKey("coupon_master.coupon_master_id"), nullable=True)
    coupon_code_id = db.Column(db.Integer, db.ForeignKey("coupon_codes.id"), index=True)
    unique_code = db.Column(db.String(5), unique=True, index=True)  # reference code shown after reveal
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    coupon_master = db.relationship("CouponMaster", backref=db.backref("users", lazy=True))
    coupon_code = db.relationship("CouponCode", backref=db.backref("users", lazy=True))

    def __repr__(self):
        return f"<CouponUser {self.first_name} - {self.unique_code}>"


class CouponValidator(db.Model):
    __tablename__ = "coupon_validators"

    id = db.Column(db.Integer, primary_key=True)
    mobile_no = db.Column(db.String(10), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120))
    city = db.Column(db.String(120))
    status = db.Column(CouponValidatorStatus, default="Active", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<CouponValidator {self.mobile_no}>"


class CouponCode(db.Model):
    __tablename__ = "coupon_codes"

    id = db.Column(db.Integer, primary_key=True)
    coupon_name_id = db.Column(db.Integer, db.ForeignKey("coupon_name.coupon_name_id"), nullable=False, index=True)
    code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    status = db.Column(CouponCodeStatus, default="Active", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    coupon_name = db.relationship("CouponName", backref=db.backref("coupon_codes", lazy=True))

    def __repr__(self):
        return f"<CouponCode {self.code}>"


class CouponDistributionSettings(db.Model):
    """
    Per-campaign (coupon_name) distribution settings for level unlock/caps and weight multipliers.
    """

    __tablename__ = "coupon_distribution_settings"

    coupon_name_id = db.Column(
        db.Integer,
        db.ForeignKey("coupon_name.coupon_name_id"),
        primary_key=True,
    )

    unlock_at = db.Column(db.Integer, default=1000)
    window1_end = db.Column(db.Integer, default=1500)
    window2_end = db.Column(db.Integer, default=2000)

    level1_cap_w1 = db.Column(db.Integer, default=1)
    level1_cap_w2 = db.Column(db.Integer, default=2)
    level2_cap_w1 = db.Column(db.Integer, default=2)
    level3_cap_w1 = db.Column(db.Integer, default=2)

    level1_mult = db.Column(db.Float, default=0.35)
    level2_mult = db.Column(db.Float, default=1.0)
    level3_mult = db.Column(db.Float, default=1.8)
    level4_mult = db.Column(db.Float, default=0.8)
    level5_mult = db.Column(db.Float, default=1.0)
    level6_mult = db.Column(db.Float, default=1.3)
    level7_mult = db.Column(db.Float, default=1.7)

    coupon_name = db.relationship("CouponName", backref=db.backref("distribution_settings", uselist=False))

    def __repr__(self):
        return f"<CouponDistributionSettings coupon_name_id={self.coupon_name_id}>"


class CouponPrizeAudit(db.Model):
    __tablename__ = "coupon_prize_audit"

    id = db.Column(db.Integer, primary_key=True)
    coupon_user_id = db.Column(db.Integer, db.ForeignKey("coupon_users.coupon_user_id"), nullable=False, index=True)
    coupon_name_id = db.Column(db.Integer, db.ForeignKey("coupon_name.coupon_name_id"), nullable=False, index=True)
    coupon_master_id = db.Column(db.Integer, db.ForeignKey("coupon_master.coupon_master_id"), nullable=False, index=True)
    prize_level = db.Column(db.Integer, index=True)
    selection_mode = db.Column(db.String(32), default="weighted", index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    coupon_user = db.relationship("CouponUser", backref=db.backref("prize_audits", lazy=True))
    coupon_name = db.relationship("CouponName")
    coupon_master = db.relationship("CouponMaster")

    def __repr__(self):
        return f"<CouponPrizeAudit user={self.coupon_user_id} master={self.coupon_master_id}>"

