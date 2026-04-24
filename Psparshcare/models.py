# models.py
from . import db
from datetime import datetime

# User login model
class UserLogin(db.Model):
    __tablename__ = 'user_login'

    id = db.Column(db.Integer, primary_key=True)
    mobile = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    status = db.Column(db.String(20), default='Active', index=True) # Active, Inactive
    name = db.Column(db.String(100), index=True)
    role = db.Column(db.String(20), default='user') # admin, user
    
    # New Fields
    city = db.Column(db.String(100))
    product_type = db.Column(db.String(50)) # Pad, Diaper, both
    pin_type = db.Column(db.String(50)) # Top up, joining, product pin
    approval_status = db.Column(db.String(20), default='Pending') # Pending, Approved
    emp_id = db.Column(db.String(20), unique=True) # 5 numbers
    type_of_user = db.Column(db.String(50))
    level = db.Column(db.Integer, default=1)
    parent_user_id = db.Column(db.Integer, db.ForeignKey('user_login.id'))
    parent_user = db.relationship('UserLogin', remote_side=[id], backref=db.backref('children', lazy='dynamic'), foreign_keys=[parent_user_id])
    referral_count = db.Column(db.Integer, default=0)
    referral_paid = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<UserLogin {self.mobile}>"

# User profile model
class UserProfile(db.Model):
    __tablename__ = 'user_profile'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user_login.id'), nullable=False)
    title = db.Column(db.String(10))
    name = db.Column(db.String(100))
    father_name = db.Column(db.String(100))
    gender = db.Column(db.String(10))
    dob = db.Column(db.Date)
    marital_status = db.Column(db.String(20))
    mobile = db.Column(db.String(15))
    email = db.Column(db.String(120))
    country = db.Column(db.String(50))
    state = db.Column(db.String(50))
    city = db.Column(db.String(50))
    pincode = db.Column(db.String(10))
    address = db.Column(db.Text)

    def __repr__(self):
        return f"<UserProfile {self.name}>"

# Account/bank details
class AccountSettings(db.Model):
    __tablename__ = 'account_settings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user_login.id'), nullable=False)
    ifsc = db.Column(db.String(20))
    bank_name = db.Column(db.String(100))
    branch = db.Column(db.String(100))
    acc_no = db.Column(db.String(30))
    acc_holder = db.Column(db.String(100))

    def __repr__(self):
        return f"<AccountSettings {self.bank_name} - {self.acc_no}>"

# E-pin records
class EPin(db.Model):
    __tablename__ = 'epins'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    status = db.Column(db.String(20), default="Unused")
    owner_id = db.Column(db.Integer, db.ForeignKey('user_login.id'))
    pin_type_id = db.Column(db.Integer, db.ForeignKey('pin_types.id'))
    product_type_id = db.Column(db.Integer, db.ForeignKey('product_types.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    pin_type = db.relationship('PinType', foreign_keys=[pin_type_id])
    product_type = db.relationship('ProductType', foreign_keys=[product_type_id])

    def __repr__(self):
        return f"<EPin {self.code} - {self.status}>"

# E-pin transfers
class EPinTransfer(db.Model):
    __tablename__ = 'epin_transfers'

    id = db.Column(db.Integer, primary_key=True)
    epin_id = db.Column(db.Integer, db.ForeignKey('epins.id'))
    from_user = db.Column(db.Integer, db.ForeignKey('user_login.id'))
    to_user = db.Column(db.Integer, db.ForeignKey('user_login.id'))
    transfer_date = db.Column(db.DateTime, default=datetime.utcnow)
    type = db.Column(db.String(20))  # Sent / Received
    status = db.Column(db.String(20), default='Active')
    disabled_at = db.Column(db.DateTime)
    disabled_reason = db.Column(db.String(255))

    epin = db.relationship('EPin', foreign_keys=[epin_id])
    from_user_rel = db.relationship('UserLogin', foreign_keys=[from_user], backref=db.backref('sent_transfers', lazy='dynamic'))
    to_user_rel = db.relationship('UserLogin', foreign_keys=[to_user], backref=db.backref('received_transfers', lazy='dynamic'))

    def __repr__(self):
        return f"<EPinTransfer {self.type} - {self.epin_id}>"


class PinUsageReport(db.Model):
    __tablename__ = 'pin_usage_reports'

    id = db.Column(db.Integer, primary_key=True)
    pin_id = db.Column(db.Integer, db.ForeignKey('epins.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user_login.id'), nullable=False)
    buyer_name = db.Column(db.String(120))
    buyer_mobile = db.Column(db.String(15))
    city = db.Column(db.String(120))
    sold_at = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.String(255))

    pin = db.relationship('EPin', foreign_keys=[pin_id])
    user = db.relationship('UserLogin', foreign_keys=[user_id])

    def __repr__(self):
        return f"<PinUsageReport pin={self.pin_id} buyer={self.buyer_mobile}>"

# Wallet transactions
class WalletTransaction(db.Model):
    __tablename__ = 'wallet_transactions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user_login.id'), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    description = db.Column(db.String(255))
    amount = db.Column(db.Float)

    def __repr__(self):
        return f"<WalletTransaction {self.description} - {self.amount}>"


class WithdrawRequest(db.Model):
    __tablename__ = 'withdraw_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user_login.id'), nullable=False)
    requested_amount = db.Column(db.Float, nullable=False)
    available_balance = db.Column(db.Float, default=0)
    redeemable_balance = db.Column(db.Float, default=0)
    gst_rate = db.Column(db.Float, default=18.0)
    gst_amount = db.Column(db.Float, default=0)
    net_amount = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default='Pending')
    remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = db.relationship('UserLogin', foreign_keys=[user_id], backref=db.backref('withdraw_requests', lazy='dynamic'))

    def __repr__(self):
        return f"<WithdrawRequest user={self.user_id} amount={self.requested_amount} status={self.status}>"

# Schema metadata
class SchemaMeta(db.Model):
    __tablename__ = 'schema_meta'

    id = db.Column(db.Integer, primary_key=True)
    table_name = db.Column(db.String(100), nullable=False)
    column_name = db.Column(db.String(100), nullable=False)
    data_type = db.Column(db.String(50), nullable=False)
    constraints = db.Column(db.Text)
    is_nullable = db.Column(db.Boolean, default=True)
    default_value = db.Column(db.String(255))
    version = db.Column(db.Integer, default=1)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    remarks = db.Column(db.Text)

    def __repr__(self):
        return f"<SchemaMeta {self.table_name}.{self.column_name}>"

# Support ticket model
class SupportTicket(db.Model):
    __tablename__ = 'support_tickets'

    id = db.Column(db.Integer, primary_key=True)
    ticket_no = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user_login.id'), nullable=False)
    user_name = db.Column(db.String(100))
    mobile = db.Column(db.String(15))
    query_type = db.Column(db.String(50))
    description = db.Column(db.Text)
    attachments = db.Column(db.Text)
    status = db.Column(db.String(20), default="Open")
    admin_remarks = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<SupportTicket {self.ticket_no} - {self.status}>"

# Carousel image model
class CarouselImage(db.Model):
    __tablename__ = 'carousel_images'

    id = db.Column(db.Integer, primary_key=True)
    image_path = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(100))
    caption = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f"<CarouselImage {self.title}>"

# News model
class News(db.Model):
    __tablename__ = 'news'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    image_path = db.Column(db.String(255)) # Optional
    attachments = db.Column(db.Text) # Comma separated file paths
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<News {self.title}>"


class LegalDocument(db.Model):
    __tablename__ = 'legal_documents'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    file_path = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<LegalDocument {self.title}>"

# Event model
class Event(db.Model):
    __tablename__ = 'events'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    event_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Event {self.title}>"

# Multi-photo support for events
class EventImage(db.Model):
    __tablename__ = 'event_images'
    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('events.id'), nullable=False)
    image_path = db.Column(db.String(255), nullable=False)

    def __repr__(self):
        return f"<EventImage {self.image_path}>"

# Company Profile / Static Content
class CompanyProfile(db.Model):
    __tablename__ = 'company_profile'
    id = db.Column(db.Integer, primary_key=True)
    about_us = db.Column(db.Text)
    vision = db.Column(db.Text)
    mission = db.Column(db.Text)
    address = db.Column(db.Text)
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    map_url = db.Column(db.Text)

    def __repr__(self):
        return "<CompanyProfile>"

# Quick Links management
class QuickLink(db.Model):
    __tablename__ = 'quick_links'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(255), nullable=False)
    order = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f"<QuickLink {self.title}>"

class UserCreationRequest(db.Model):
    __tablename__ = 'user_creation_requests'

    id = db.Column(db.Integer, primary_key=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey('user_login.id'), nullable=False)
    requested_by = db.relationship('UserLogin', foreign_keys=[requested_by_id], backref='creation_requests')
    applicant_mobile = db.Column(db.String(80), nullable=False)
    applicant_name = db.Column(db.String(120))
    applicant_email = db.Column(db.String(120))
    city = db.Column(db.String(120))
    pin_type = db.Column(db.String(50))
    requested_pin_count = db.Column(db.Integer, default=1)
    selected_epin_id = db.Column(db.Integer, db.ForeignKey('epins.id'))
    selected_epin = db.relationship('EPin', foreign_keys=[selected_epin_id])
    requested_role = db.Column(db.String(40))
    notes = db.Column(db.Text)
    status = db.Column(db.Enum('Pending', 'Approved', 'Rejected', name='request_status'), default='Pending')
    assigned_role = db.Column(db.String(50))
    approved_by_id = db.Column(db.Integer, db.ForeignKey('user_login.id'))
    approved_by = db.relationship('UserLogin', foreign_keys=[approved_by_id])
    approved_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<UserCreationRequest {self.applicant_mobile} status={self.status}>"

class ProductType(db.Model):
    __tablename__ = 'product_types'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    description = db.Column(db.String(255))

    def __repr__(self):
        return f"<ProductType {self.name}>"


class PinType(db.Model):
    __tablename__ = 'pin_types'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    description = db.Column(db.String(255))

    def __repr__(self):
        return f"<PinType {self.name}>"


class UserRole(db.Model):
    __tablename__ = 'user_roles'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    description = db.Column(db.String(255))

    def __repr__(self):
        return f"<UserRole {self.name}>"


class ReferenceOption(db.Model):
    __tablename__ = 'reference_options'
    __table_args__ = (
        db.UniqueConstraint('category', 'value', name='uq_reference_options_category_value'),
    )

    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(80), nullable=False, index=True)
    value = db.Column(db.String(80), nullable=False)
    label = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255))
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True, index=True)

    def __repr__(self):
        return f"<ReferenceOption {self.category}:{self.value}>"


class LoginPageVisit(db.Model):
    __tablename__ = 'login_page_visits'
    __table_args__ = (
        db.UniqueConstraint('visit_date', name='uq_login_page_visits_visit_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    visit_date = db.Column(db.Date, nullable=False, index=True)
    visit_count = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<LoginPageVisit {self.visit_date}={self.visit_count}>"



# Levels / Income & Reward Plan
class LevelPlan(db.Model):
    __tablename__ = 'level_plans'
    __table_args__ = (
        db.UniqueConstraint('product_type', 'level_no', name='uq_level_plans_product_level'),
    )
    id = db.Column(db.Integer, primary_key=True)
    product_type = db.Column(db.String(50), nullable=False, default='Pad')
    level_no = db.Column(db.Integer, nullable=False)
    number_of_id = db.Column(db.Integer, nullable=False, default=0)
    income_per_id = db.Column(db.Integer, nullable=False, default=0)
    reward_per_id = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<LevelPlan {self.product_type} L{self.level_no}>"
