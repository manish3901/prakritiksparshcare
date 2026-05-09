# routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, jsonify
from datetime import datetime, timedelta, date
import os
import secrets
import smtplib
import string
from urllib.parse import quote
from email.message import EmailMessage
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash
from .models import UserLogin, UserCreationRequest, WithdrawRequest, EPin, ReferenceOption
from . import db

main = Blueprint('main', __name__)

EMAIL_SMTP_HOST = os.getenv('EMAIL_SMTP_HOST', 'smtp.rediffmail.com')
EMAIL_SMTP_PORT = int(os.getenv('EMAIL_SMTP_PORT', '587'))
EMAIL_SMTP_USER = os.getenv('EMAIL_SMTP_USER', 'dixit.vikash@rediffmail.com')
EMAIL_SMTP_PASS = os.getenv('EMAIL_SMTP_PASS', '')
EMAIL_NOTIFY = os.getenv('EMAIL_NOTIFY', 'dixit.vikash@rediffmail.com')
APP_URL = os.getenv('APP_URL', 'http://localhost:5000')

NON_ADMIN_MEMBER_ROLES = {'member', 'leader', 'temp member', 'trainer'}
LEVEL_PRODUCTS = ('pad', 'diaper')
LEVEL_FILTER_OPTIONS = LEVEL_PRODUCTS + ('all',)

def normalize_mobile(value):
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits

def find_user_by_mobile(value):
    mobile_key = normalize_mobile(value)
    if len(mobile_key) != 10:
        return None

    # Handle legacy records where mobile might include country code/spaces/etc.
    candidates = UserLogin.query.filter(UserLogin.mobile.like(f"%{mobile_key}")).all()
    for candidate in candidates:
        if normalize_mobile(candidate.mobile) == mobile_key:
            return candidate
    return None


def send_email_message(subject, body, to_address):
    if not to_address:
        to_address = EMAIL_NOTIFY
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_SMTP_USER
    msg["To"] = to_address
    msg.set_content(body)

    try:
        with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=10) as server:
            server.starttls()
            if EMAIL_SMTP_PASS:
                server.login(EMAIL_SMTP_USER, EMAIL_SMTP_PASS)
            server.send_message(msg)
    except Exception as exc:
        current_app.logger.warning("Failed to send email to %s: %s", to_address, exc)


def send_user_credentials(name, mobile, password, role, recipient_email=None, notify_admin_copy=True):
    body = (
        f"Hello {name or 'SparshCare member'},\n\n"
        f"Your account is ready! Please find the login details below:\n"
        f"Mobile: {mobile}\n"
        f"Password: {password}\n"
        f"Role: {role}\n"
        f"Login: {APP_URL}/login\n\n"
        "Please change your password after your first sign-in.\n\n"
        "Warm regards,\n"
        "Prakrutik SparshCare Team"
    )
    recipients = []
    primary = (recipient_email or "").strip()
    if primary:
        recipients.append(primary)
    if notify_admin_copy and EMAIL_NOTIFY:
        admin_email = EMAIL_NOTIFY.strip()
        if admin_email and admin_email.lower() != (primary or "").lower():
            recipients.append(admin_email)

    if not recipients:
        recipients = [EMAIL_NOTIFY]

    for recipient in recipients:
        send_email_message("Your SparshCare account is ready", body, recipient)


def is_admin_session():
    # Backward-compatible helper: treat "admin" as a DB role, not a special user id.
    return is_admin_user(get_session_user())


def get_session_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return UserLogin.query.get(user_id)


def normalize_access_role(value):
    role = (value or '').strip().lower()
    return 'admin' if role == 'admin' else 'user'


def normalize_user_type(value):
    user_type = (value or '').strip().lower()
    if user_type in NON_ADMIN_MEMBER_ROLES:
        return user_type
    if user_type in {'temp_member', 'temp-member'}:
        return 'temp member'
    return 'member'


def to_type_of_user(user_type):
    normalized = normalize_user_type(user_type)
    if normalized == 'temp member':
        return 'Temp Member'
    return normalized.title()


def effective_access_role(user):
    if not user:
        return 'user'
    primary = (getattr(user, 'role', None) or '').strip().lower()
    legacy = (getattr(user, 'type_of_user', None) or '').strip().lower()
    if primary == 'admin' or legacy == 'admin':
        return 'admin'
    return 'user'


def effective_user_type(user):
    if not user:
        return 'member'
    if effective_access_role(user) == 'admin':
        return 'admin'
    legacy = (getattr(user, 'type_of_user', None) or '').strip()
    if legacy:
        return normalize_user_type(legacy)
    primary = (getattr(user, 'role', None) or '').strip().lower()
    if primary in NON_ADMIN_MEMBER_ROLES:
        return normalize_user_type(primary)
    return 'member'


def display_role_label(user):
    return 'admin' if effective_access_role(user) == 'admin' else effective_user_type(user)


def assign_user_classification(user, access_role='user', user_type='member'):
    normalized_access_role = normalize_access_role(access_role)
    if normalized_access_role == 'admin':
        user.role = 'admin'
        user.type_of_user = 'Admin'
        return normalized_access_role, 'admin'

    normalized_user_type = normalize_user_type(user_type)
    user.role = 'user'
    user.type_of_user = to_type_of_user(normalized_user_type)
    return normalized_access_role, normalized_user_type


def notify_admin_new_request(request_obj):
    subject = "New user creation request"
    body = (
        f"Admin,\n\n"
        f"A new user creation request has been submitted by {request_obj.requested_by.name or request_obj.requested_by.mobile}.\n\n"
        f"Name: {request_obj.applicant_name}\n"
        f"Mobile: {request_obj.applicant_mobile}\n"
        f"City: {request_obj.city}\n"
        f"Requested role: {request_obj.requested_role or 'member'}\n"
        f"Pin Type: {request_obj.pin_type or 'N/A'}\n"
        f"Notes: {request_obj.notes or 'None'}\n\n"
        f"Approve or reject here: {APP_URL}/home?target=hierarchySection\n"
    )
    send_email_message(subject, body, EMAIL_NOTIFY)


def build_hierarchy_snapshot(user, depth=3, limit_per_level=4):
    def walk(node, level):
        if not node or level > depth:
            return None
        children_query = node.children.order_by(UserLogin.id).limit(limit_per_level)
        children = children_query.all()
        return {
            'id': node.id,
            'name': node.name or node.mobile or 'User',
            'mobile': node.mobile,
            'role': display_role_label(node),
            'level': node.level or 0,
            'referrals': node.referral_count or 0,
            'children': [walk(child, level + 1) for child in children],
        }
    return walk(user, 1)


def get_downline_user_ids(user):
    if not user:
        return set()
    downline_ids = set()
    queue = list(user.children.all())
    while queue:
        node = queue.pop(0)
        if not node or node.id in downline_ids:
            continue
        downline_ids.add(node.id)
        queue.extend(node.children.all())
    return downline_ids


def calculate_level_income(referral_count, level_plans):
    remaining = max(referral_count or 0, 0)
    contributions = []
    total_income = 0
    total_reward = 0
    for plan in sorted(level_plans, key=lambda lp: lp.level_no):
        if remaining <= 0:
            break
        target = plan.number_of_id or 0
        if target <= 0:
            continue
        count = min(target, remaining)
        income_total = count * (plan.income_per_id or 0)
        reward_total = count * (plan.reward_per_id or 0)
        contributions.append({
            'level': plan.level_no,
            'target': target,
            'count': count,
            'income_per_id': plan.income_per_id or 0,
            'reward_per_id': plan.reward_per_id or 0,
            'income_total': income_total,
            'reward_total': reward_total,
            'grand_total': income_total + reward_total
        })
        total_income += income_total
        total_reward += reward_total
        remaining -= count
    return {
        'contributions': contributions,
        'total_income': total_income,
        'total_reward': total_reward,
        'grand_total': total_income + total_reward,
        'current_level': contributions[-1]['level'] if contributions else 0,
        'leftover': remaining,
        'referral_count': referral_count
    }


def build_level_breakdown_rows(level_plans, achieved_count):
    remaining = max(achieved_count or 0, 0)
    rows = []
    for plan in sorted(level_plans, key=lambda lp: lp.level_no):
        target = plan.number_of_id or 0
        current_count = min(target, remaining) if target > 0 else 0
        total_income = current_count * (plan.income_per_id or 0)
        total_reward = current_count * (plan.reward_per_id or 0)
        rows.append({
            'level_no': plan.level_no,
            'count': current_count,
            'target': target,
            'income_per_id': plan.income_per_id or 0,
            'reward_per_id': plan.reward_per_id or 0,
            'total_income': total_income,
            'total_reward': total_reward,
            'total_amount': total_income + total_reward,
        })
        remaining = max(remaining - current_count, 0)
    return rows


def level_progress_status(actual_count, target, level_no):
    actual = max(actual_count or 0, 0)
    cap = max(target or 0, 0)
    if cap <= 0:
        return {'key': 'muted', 'label': 'No Target'}

    # Level 1 explicit banding from business rule: 1-40 Green, 41-50 Yellow, >50 Red (when cap is 50).
    # For other caps/levels, we keep the same 80%/100%/overflow pattern.
    green_limit = max(1, int(cap * 0.8))
    if level_no == 1 and cap == 50:
        green_limit = 40

    if actual <= green_limit:
        return {'key': 'success', 'label': 'Within Range'}
    if actual <= cap:
        return {'key': 'warning', 'label': 'Near Limit'}
    return {'key': 'danger', 'label': 'Limit Exceeded'}


def build_hierarchy_level_counts_by_product(root_user, max_depth=5):
    counts = {
        product_key: {depth: 0 for depth in range(1, max_depth + 1)}
        for product_key in LEVEL_PRODUCTS
    }
    if not root_user:
        return counts

    users = UserLogin.query.with_entities(
        UserLogin.id,
        UserLogin.parent_user_id,
        UserLogin.product_type,
        UserLogin.approval_status
    ).all()
    by_parent = {}
    for row in users:
        by_parent.setdefault(row.parent_user_id, []).append(row)

    current_ids = [root_user.id]
    for depth in range(1, max_depth + 1):
        next_ids = []
        for parent_id in current_ids:
            for child in by_parent.get(parent_id, []):
                if child.approval_status and child.approval_status != 'Approved':
                    continue
                for product_key in normalize_user_product_keys(child.product_type):
                    counts[product_key][depth] = counts[product_key].get(depth, 0) + 1
                next_ids.append(child.id)
        if not next_ids:
            break
        current_ids = next_ids
    return counts


def build_usage_level_counts_by_product(root_user, max_depth=5):
    counts = {
        product_key: {depth: 0 for depth in range(1, max_depth + 1)}
        for product_key in LEVEL_PRODUCTS
    }
    if not root_user:
        return counts

    from .models import PinUsageReport, ProductType

    users = UserLogin.query.with_entities(
        UserLogin.id,
        UserLogin.parent_user_id,
        UserLogin.approval_status
    ).all()
    by_parent = {}
    for row in users:
        by_parent.setdefault(row.parent_user_id, []).append(row)

    depth_by_user = {}
    current_ids = [root_user.id]
    for depth in range(1, max_depth + 1):
        next_ids = []
        for parent_id in current_ids:
            for child in by_parent.get(parent_id, []):
                if child.approval_status and child.approval_status != 'Approved':
                    continue
                depth_by_user[child.id] = depth
                next_ids.append(child.id)
        if not next_ids:
            break
        current_ids = next_ids

    if not depth_by_user:
        return counts

    usage_rows = db.session.query(
        PinUsageReport.user_id,
        ProductType.name
    ).join(
        EPin, PinUsageReport.pin_id == EPin.id
    ).outerjoin(
        ProductType, EPin.product_type_id == ProductType.id
    ).filter(
        PinUsageReport.user_id.in_(list(depth_by_user.keys()))
    ).all()

    seen_user_product = set()
    for seller_user_id, product_name in usage_rows:
        depth = depth_by_user.get(seller_user_id)
        if not depth or depth < 1 or depth > max_depth:
            continue
        product_key = normalize_level_product(product_name, 'pad')
        dedupe_key = (seller_user_id, product_key)
        if dedupe_key in seen_user_product:
            continue
        seen_user_product.add(dedupe_key)
        counts[product_key][depth] = counts[product_key].get(depth, 0) + 1

    return counts


def build_hierarchy_level_view(level_plans, level_counts_by_depth):
    rows = []
    total_income = 0
    total_reward = 0
    current_level = 0

    for plan in sorted(level_plans, key=lambda lp: lp.level_no):
        level_no = plan.level_no or 0
        actual_count = max(level_counts_by_depth.get(level_no, 0), 0)
        target = max(plan.number_of_id or 0, 0)
        eligible_count = min(actual_count, target) if target > 0 else 0
        total_income_row = eligible_count * (plan.income_per_id or 0)
        total_reward_row = eligible_count * (plan.reward_per_id or 0)
        status = level_progress_status(actual_count, target, level_no)
        if actual_count > 0:
            current_level = max(current_level, level_no)

        rows.append({
            'level_no': level_no,
            'count': actual_count,
            'target': target,
            'eligible_count': eligible_count,
            'income_per_id': plan.income_per_id or 0,
            'reward_per_id': plan.reward_per_id or 0,
            'total_income': total_income_row,
            'total_reward': total_reward_row,
            'total_amount': total_income_row + total_reward_row,
            'status_key': status['key'],
            'status_label': status['label'],
        })
        total_income += total_income_row
        total_reward += total_reward_row

    return {
        'rows': rows,
        'total_income': total_income,
        'total_reward': total_reward,
        'grand_total': total_income + total_reward,
        'current_level': current_level,
        'total_ids': sum(max(level_counts_by_depth.get(plan.level_no or 0, 0), 0) for plan in level_plans),
    }


def compute_hierarchy_income_totals(user, product_keys=None, max_depth=5):
    if not user:
        return {'by_product': {k: 0 for k in LEVEL_PRODUCTS}, 'total': 0}

    from .models import LevelPlan

    keys = product_keys or normalize_user_product_keys(getattr(user, 'product_type', None))
    all_level_plans = LevelPlan.query.order_by(LevelPlan.product_type.asc(), LevelPlan.level_no.asc()).all()
    level_plans_by_product = {
        product_key: [plan for plan in all_level_plans if normalize_level_product(getattr(plan, 'product_type', 'pad')) == product_key]
        for product_key in LEVEL_PRODUCTS
    }
    hierarchy_counts = build_hierarchy_level_counts_by_product(user, max_depth=max_depth)
    by_product = {}
    for product_key in LEVEL_PRODUCTS:
        view = build_hierarchy_level_view(level_plans_by_product.get(product_key, []), hierarchy_counts.get(product_key, {}))
        by_product[product_key] = view.get('grand_total', 0)

    total = sum(by_product.get(k, 0) for k in keys)
    return {'by_product': by_product, 'total': total}


def build_user_level_views(user, level_plans_by_product, max_depth=5):
    hierarchy_level_counts = build_hierarchy_level_counts_by_product(user, max_depth=max_depth)
    usage_level_counts = build_usage_level_counts_by_product(user, max_depth=max_depth)
    level_views = {}
    for product_key in LEVEL_PRODUCTS:
        product_level_plans = level_plans_by_product.get(product_key, [])
        summary = build_hierarchy_level_view(product_level_plans, hierarchy_level_counts.get(product_key, {}))
        usage_by_level = usage_level_counts.get(product_key, {})
        usage_total_income = 0
        usage_total_reward = 0
        usage_current_level = 0
        for row in summary.get('rows', []):
            created_count = max(row.get('count', 0) or 0, 0)
            usage_count = usage_by_level.get(row.get('level_no', 0), 0)
            target = max(row.get('target', 0) or 0, 0)
            eligible_usage_count = min(max(usage_count, 0), target) if target > 0 else 0
            usage_total_income_row = eligible_usage_count * (row.get('income_per_id', 0) or 0)
            usage_total_reward_row = eligible_usage_count * (row.get('reward_per_id', 0) or 0)
            status = level_progress_status(usage_count, target, row.get('level_no', 0))

            row['created_count'] = created_count
            row['usage_count'] = usage_count
            row['pending_usage_count'] = max(created_count - usage_count, 0)
            row['count'] = usage_count
            row['eligible_count'] = eligible_usage_count
            row['total_income'] = usage_total_income_row
            row['total_reward'] = usage_total_reward_row
            row['total_amount'] = usage_total_income_row + usage_total_reward_row
            row['status_key'] = status['key']
            row['status_label'] = status['label']
            if usage_count > 0:
                usage_current_level = max(usage_current_level, row.get('level_no', 0) or 0)
            usage_total_income += usage_total_income_row
            usage_total_reward += usage_total_reward_row

        summary['created_ids'] = sum(max(row.get('created_count', 0), 0) for row in summary.get('rows', []))
        summary['total_ids'] = sum(max(row.get('count', 0), 0) for row in summary.get('rows', []))
        summary['total_income'] = usage_total_income
        summary['total_reward'] = usage_total_reward
        summary['grand_total'] = usage_total_income + usage_total_reward
        summary['current_level'] = usage_current_level
        summary['usage_logged_ids'] = sum(max(row.get('usage_count', 0), 0) for row in summary.get('rows', []))
        summary['pending_usage_ids'] = sum(max(row.get('pending_usage_count', 0), 0) for row in summary.get('rows', []))
        summary['product_key'] = product_key
        summary['product_label'] = to_level_product_label(product_key)
        level_views[product_key] = summary
    return level_views


def annotate_user_creation_requests_with_usage(request_rows):
    from .models import PinUsageReport

    rows = list(request_rows or [])
    normalized_mobiles = {
        normalize_mobile(getattr(req, 'applicant_mobile', None))
        for req in rows
        if getattr(req, 'status', None) == 'Approved'
    }
    normalized_mobiles = {m for m in normalized_mobiles if len(m) == 10}

    user_by_mobile = {}
    if normalized_mobiles:
        all_users = UserLogin.query.with_entities(UserLogin.id, UserLogin.mobile).all()
        for usr in all_users:
            nmobile = normalize_mobile(getattr(usr, 'mobile', None))
            if nmobile in normalized_mobiles and nmobile not in user_by_mobile:
                user_by_mobile[nmobile] = usr

    usage_count_by_user = {}
    if user_by_mobile:
        user_ids = [usr.id for usr in user_by_mobile.values()]
        usage_rows = db.session.query(
            PinUsageReport.user_id,
            func.count(PinUsageReport.id)
        ).filter(
            PinUsageReport.user_id.in_(user_ids)
        ).group_by(PinUsageReport.user_id).all()
        usage_count_by_user = {uid: int(cnt or 0) for uid, cnt in usage_rows}

    summary = {
        'approved_total': 0,
        'approved_usage_done': 0,
        'approved_pending_usage': 0,
        'approved_user_missing': 0,
    }

    for req in rows:
        req.usage_log_count = 0
        req.approved_user_id = None
        req.manage_level_note = "-"
        req.manage_level_ready = False
        if getattr(req, 'status', None) != 'Approved':
            continue

        summary['approved_total'] += 1
        nmobile = normalize_mobile(getattr(req, 'applicant_mobile', None))
        linked_user = user_by_mobile.get(nmobile) if len(nmobile) == 10 else None
        if not linked_user:
            req.manage_level_note = "Approved, user record sync pending."
            summary['approved_user_missing'] += 1
            continue

        req.approved_user_id = linked_user.id
        req.usage_log_count = usage_count_by_user.get(linked_user.id, 0)
        if req.usage_log_count > 0:
            req.manage_level_note = "Usage log added. Included in Manage Levels and income."
            req.manage_level_ready = True
            summary['approved_usage_done'] += 1
        else:
            req.manage_level_note = "Usage log not added yet. Not included in Manage Levels or income."
            summary['approved_pending_usage'] += 1

    return rows, summary


def summarize_pin_inventory(pins):
    rows = []
    for pin in pins:
        rows.append({
            'id': pin.id,
            'code': pin.code,
            'status': pin.status,
            'display_status': getattr(pin, 'display_status', pin.status),
            'pin_type': getattr(pin.pin_type, 'name', None),
            'product_type': getattr(pin.product_type, 'name', None),
            'created_at': pin.created_at
        })
    return rows


def summarize_pin_usage(reports):
    rows = []
    for row in reports:
        rows.append({
            'id': row.id,
            'pin_code': getattr(row.pin, 'code', 'N/A'),
            'pin_type': getattr(getattr(row.pin, 'pin_type', None), 'name', 'Generic'),
            'buyer_name': row.buyer_name,
            'buyer_mobile': row.buyer_mobile,
            'city': row.city,
            'sold_at': row.sold_at,
            'notes': row.notes,
            'created_by': getattr(getattr(row, 'user', None), 'name', None) or getattr(getattr(row, 'user', None), 'mobile', None) or 'User'
        })
    return rows


def summarize_transfer_history(transfers, current_user_id=None):
    rows = []
    for transfer in transfers:
        recipient = transfer.to_user_rel
        pin = transfer.epin
        sender = transfer.from_user_rel
        direction = 'Sent'
        counterpart_name = recipient.name if recipient else 'User'
        counterpart_mobile = recipient.mobile if recipient else 'Unknown'
        if current_user_id and transfer.to_user == current_user_id:
            direction = 'Received'
            counterpart_name = sender.name if sender else 'User'
            counterpart_mobile = sender.mobile if sender else 'Unknown'
        rows.append({
            'id': transfer.id,
            'pin_code': getattr(pin, 'code', 'N/A'),
            'pin_type': getattr(getattr(pin, 'pin_type', None), 'name', 'Generic'),
            'sender': sender.name if sender else 'User',
            'sender_mobile': sender.mobile if sender else 'Unknown',
            'recipient': recipient.name if recipient else 'User',
            'recipient_mobile': recipient.mobile if recipient else 'Unknown',
            'type': transfer.type,
            'date': transfer.transfer_date,
            'status': getattr(transfer, 'status', 'Active'),
            'pin_status': getattr(pin, 'status', 'Unknown'),
            'direction': direction,
            'counterpart_name': counterpart_name,
            'counterpart_mobile': counterpart_mobile
        })
    return rows


def get_reserved_request_pin_ids(user_id):
    if not user_id:
        return set()
    reserved = db.session.query(UserCreationRequest.selected_epin_id).filter(
        UserCreationRequest.requested_by_id == user_id,
        UserCreationRequest.status == 'Pending',
        UserCreationRequest.selected_epin_id.isnot(None)
    ).all()
    return {row[0] for row in reserved if row and row[0]}


def get_effective_reserved_pin_ids(user_id):
    """
    Pins that should be treated as "reserved" for a user.

    This includes:
    - pins explicitly reserved by pending UserCreationRequest rows (selected_epin_id)
    - the earliest eligible unused pins that we implicitly hold back when there are pending
      requests without a selected pin yet (requested_pin_count > 0 but selected_epin_id is NULL).

    Keeping this logic centralized avoids a UX bug where a pin is shown as "Unused" but fails
    validation when selected for registration.
    """
    if not user_id:
        return set()

    explicit_reserved = get_reserved_request_pin_ids(user_id)

    pending_requests = UserCreationRequest.query.filter_by(
        requested_by_id=user_id,
        status='Pending'
    ).order_by(UserCreationRequest.created_at.asc()).all()

    unassigned_pending_count = sum(
        max(req.requested_pin_count or 1, 1)
        for req in pending_requests
        if not req.selected_epin_id
    )
    if unassigned_pending_count <= 0:
        return set(explicit_reserved)

    eligible_pin_type_names = {'top up', 'trial pin'}
    candidate_pins = EPin.query.filter_by(owner_id=user_id, status='Unused').order_by(EPin.created_at.asc()).all()
    candidate_pins = [
        pin for pin in candidate_pins
        if (getattr(getattr(pin, 'pin_type', None), 'name', '') or '').strip().lower() in eligible_pin_type_names
        and pin.id not in explicit_reserved
    ]

    held_ids = {pin.id for pin in candidate_pins[:unassigned_pending_count]}
    return set(explicit_reserved) | held_ids


def get_available_subuser_pins_for_user(user_id):
    if not user_id:
        return []

    all_unused_pins = EPin.query.filter_by(owner_id=user_id, status='Unused').order_by(EPin.created_at.asc()).all()
    if not all_unused_pins:
        return []

    eligible_pin_type_names = {'top up', 'trial pin'}
    all_unused_pins = [
        pin for pin in all_unused_pins
        if (getattr(getattr(pin, 'pin_type', None), 'name', '') or '').strip().lower() in eligible_pin_type_names
    ]
    if not all_unused_pins:
        return []

    reserved_pin_ids = get_effective_reserved_pin_ids(user_id)
    return [pin for pin in all_unused_pins if pin.id not in reserved_pin_ids]


def build_pin_history_rows(pins, usage_reports):
    usage_by_code = {}
    for report in usage_reports:
        pin_code = getattr(getattr(report, 'pin', None), 'code', None)
        if not pin_code:
            continue
        usage_by_code[pin_code] = {
            'pin_code': pin_code,
            'pin_type': getattr(getattr(report, 'pin', None), 'pin_type', None).name if getattr(getattr(report, 'pin', None), 'pin_type', None) else 'Generic',
            'buyer_name': report.buyer_name or 'N/A',
            'buyer_mobile': report.buyer_mobile or 'N/A',
            'city': report.city or 'N/A',
            'sold_at': report.sold_at,
            'notes': report.notes or ''
        }

    grouped = {}
    for pin in pins:
        pin_type = getattr(pin.pin_type, 'name', None) or 'Generic'
        row = grouped.setdefault(pin_type, {
            'pin_type': pin_type,
            'unused_count': 0,
            'used_count': 0,
            'unused_details': [],
            'used_details': []
        })
        if pin.status == 'Unused':
            row['unused_count'] += 1
            row['unused_details'].append({
                'code': pin.code,
                'product_type': getattr(pin.product_type, 'name', None) or 'N/A',
                'created_at': pin.created_at
            })
        else:
            row['used_count'] += 1
            detail = usage_by_code.get(pin.code, {
                'pin_code': pin.code,
                'pin_type': pin_type,
                'buyer_name': 'N/A',
                'buyer_mobile': 'N/A',
                'city': 'N/A',
                'sold_at': None,
                'notes': ''
            })
            row['used_details'].append(detail)

    return sorted(grouped.values(), key=lambda item: item['pin_type'].lower())


def get_hierarchy_chain(start_user):
    chain = []
    current = start_user
    while current:
        chain.append(current)
        current = current.parent_user
    return chain


def count_downline_members(user):
    if not user:
        return {'total': 0, 'direct': 0}

    total = 0
    queue = [child for child in user.children.all()]
    direct = len(queue)
    while queue:
        node = queue.pop(0)
        total += 1
        queue.extend(node.children.all())
    return {'total': total, 'direct': direct}


def get_subtree_user_ids(user):
    if not user:
        return []
    user_ids = []
    queue = [user]
    while queue:
        node = queue.pop(0)
        if not node:
            continue
        user_ids.append(node.id)
        queue.extend(node.children.all())
    return user_ids


def get_whatsapp_admin_number(company_profile=None):
    raw_value = (
        os.getenv('WHATSAPP_ENQUIRY_NUMBER')
        or getattr(company_profile, 'phone', None)
        or ''
    )
    digits = ''.join(ch for ch in raw_value if ch.isdigit())
    if len(digits) == 10:
        return f"91{digits}"
    if len(digits) >= 12 and digits.startswith('91'):
        return digits
    return digits or ''


def normalize_level_product(value, default='pad', allow_all=False):
    normalized = (value or default).strip().lower()
    allowed = LEVEL_FILTER_OPTIONS if allow_all else LEVEL_PRODUCTS
    fallback = default if default in allowed else ('all' if allow_all else LEVEL_PRODUCTS[0])
    return normalized if normalized in allowed else fallback


def to_level_product_label(product_key):
    normalized = normalize_level_product(product_key, 'pad', allow_all=True)
    if normalized == 'pad':
        return 'Pad'
    if normalized == 'diaper':
        return 'Diaper'
    return 'All Products'


def normalize_user_product_keys(product_value):
    raw_value = (product_value or '').strip().lower()
    if not raw_value or raw_value == 'both':
        return list(LEVEL_PRODUCTS)

    cleaned = (
        raw_value.replace('&', ',')
        .replace('/', ',')
        .replace('|', ',')
        .replace('+', ',')
        .replace('-', ',')
    )
    keys = []
    for token in cleaned.split(','):
        key = token.strip().lower()
        if key in LEVEL_PRODUCTS and key not in keys:
            keys.append(key)

    return keys or list(LEVEL_PRODUCTS)


def format_user_product_display(product_value):
    keys = normalize_user_product_keys(product_value)
    labels = [to_level_product_label(key) for key in keys if key in LEVEL_PRODUCTS]
    return ', '.join(labels) if labels else 'Pad, Diaper'


def ensure_default_pin_types():
    from .models import PinType

    defaults = [
        ('Joining', 'Legacy onboarding pin type'),
        ('Top up', 'Requires admin approval for new user creation'),
        ('Product pin', 'Used for existing-user product usage logging'),
        ('Trial Pin', 'Training pin for testing user creation without level impact'),
    ]
    existing = {row.name.strip().lower(): row for row in PinType.query.all() if getattr(row, 'name', None)}
    changed = False
    for name, description in defaults:
        if name.strip().lower() in existing:
            continue
        db.session.add(PinType(name=name, description=description))
        changed = True
    if changed:
        db.session.commit()


def get_reference_options(category, include_inactive=False):
    query = ReferenceOption.query.filter_by(category=category)
    if not include_inactive:
        query = query.filter_by(is_active=True)
    return query.order_by(ReferenceOption.sort_order.asc(), ReferenceOption.label.asc()).all()


def get_reference_option_map(*categories):
    return {category: get_reference_options(category) for category in categories}


def total_plan_capacity(level_plans):
    return sum(max(plan.number_of_id or 0, 0) for plan in (level_plans or []))


def determine_user_level(referral_count, level_plans):
    if not level_plans:
        return 1
    referrals = max(referral_count or 0, 0)
    level_no = 1
    cumulative = 0
    for plan in sorted(level_plans, key=lambda lp: lp.level_no):
        threshold = plan.number_of_id or 0
        if threshold <= 0:
            continue
        cumulative += threshold
        if referrals >= cumulative:
            level_no = max(level_no, plan.level_no or level_no)
        else:
            break
    return max(level_no, 1)


def refresh_user_levels(users, level_plans):
    if not users:
        return
    for usr in users:
        if not usr:
            continue
        usr.level = determine_user_level(usr.referral_count, level_plans)
        db.session.add(usr)


def resolve_plan_for_referral(rank, level_plans):
    if not level_plans:
        return None

    cumulative = 0
    for plan in sorted(level_plans, key=lambda lp: lp.level_no):
        limit = plan.number_of_id or 0
        if limit <= 0:
            continue
        cumulative += limit
        if rank <= cumulative:
            return plan
    return level_plans[-1]


def credit_referral_income(user, level_plans, desc_prefix="Referral"):
    if not user or not level_plans:
        return

    total_referrals = min(user.referral_count or 0, total_plan_capacity(level_plans))
    already_paid = user.referral_paid or 0
    if total_referrals <= already_paid:
        return

    from .models import WalletTransaction

    new_total = already_paid
    for idx in range(already_paid + 1, total_referrals + 1):
        plan = resolve_plan_for_referral(idx, level_plans)
        if not plan:
            break
        amount = (plan.income_per_id or 0) + (plan.reward_per_id or 0)
        if amount <= 0:
            continue
        tx = WalletTransaction(
            user_id=user.id,
            amount=amount,
            description=f"{desc_prefix} bonus for count #{idx}"
        )
        db.session.add(tx)
        new_total = idx

    user.referral_paid = new_total
    db.session.add(user)


def apply_pin_sale_progress(seller, product_key='pad'):
    if not seller:
        return

    from .models import LevelPlan

    affected_users = get_hierarchy_chain(seller)
    if not affected_users:
        return

    for usr in affected_users:
        usr.referral_count = (usr.referral_count or 0) + 1
        db.session.add(usr)

    product_label = to_level_product_label(product_key)
    level_plans = LevelPlan.query.filter_by(product_type=product_label).order_by(LevelPlan.level_no).all()
    refresh_user_levels(affected_users, level_plans)

    for idx, usr in enumerate(affected_users):
        prefix = f"{product_label} personal pin sale" if idx == 0 else f"{product_label} team pin sale"
        credit_referral_income(usr, level_plans, desc_prefix=prefix)


def create_user_record(mobile, name, city=None, role='member', status='Active', parent_id=None,
                       pin_type=None, email=None, approval_status='Approved', emp_id=None,
                       product_type=None, access_role='user'):
    from .models import UserProfile
    from .emp_id import generate_next_emp_id

    plain_password = generate_initial_password()
    assigned_emp_id = (str(emp_id).strip() if emp_id is not None else "")
    if (not assigned_emp_id.isdigit()) or len(assigned_emp_id) != 5 or UserLogin.query.filter_by(emp_id=assigned_emp_id).first():
        assigned_emp_id = generate_next_emp_id()
    user = UserLogin(
        mobile=mobile,
        password=generate_password_hash(plain_password),
        status=status,
        name=name,
        role='user',
        city=city,
        product_type=product_type,
        pin_type=pin_type,
        level=1,
        parent_user_id=parent_id or None,
        emp_id=assigned_emp_id,
        approval_status=approval_status
    )
    assign_user_classification(user, access_role=access_role, user_type=role)
    db.session.add(user)
    db.session.flush()

    profile = UserProfile(
        user_id=user.id,
        name=name,
        mobile=mobile,
        city=city,
        email=email,
    )
    db.session.add(profile)

    db.session.commit()
    return user, plain_password

def generate_initial_password():
    # 8 chars total: 3 alphabet, 4 numeric, 1 special
    letters = [secrets.choice(string.ascii_letters) for _ in range(3)]
    numbers = [secrets.choice(string.digits) for _ in range(4)]
    specials = [secrets.choice("!@#$%&*?") for _ in range(1)]
    chars = letters + numbers + specials
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def generate_epin_code(prefix="PIN"):
    from .models import EPin

    for _ in range(20):
        candidate = f"{prefix}{secrets.randbelow(10**10):010d}"
        if not EPin.query.filter_by(code=candidate).first():
            return candidate
    return f"{prefix}{secrets.token_hex(6).upper()}"

def redirect_home_with_target(default_target="#dashboardSection", collapse_id=None):
    target = (request.form.get('target') or request.args.get('target') or default_target or "").strip()
    if target.startswith("#"):
        target = target[1:]

    collapse_value = (collapse_id or request.form.get('collapse') or request.args.get('collapse') or "").strip()
    if collapse_value.startswith("#"):
        collapse_value = collapse_value[1:]

    params = {'target': target}
    if collapse_value:
        params['collapse'] = collapse_value
    return redirect(url_for('main.home', **params))


def compute_redeemable_balance(wallet_balance):
    available_balance = round(max(wallet_balance or 0, 0), 2)
    gst_rate = 18.0
    gst_amount = round(available_balance * (gst_rate / 100), 2)
    redeemable_balance = round(max(available_balance - gst_amount, 0), 2)
    return {
        'available_balance': available_balance,
        'gst_rate': gst_rate,
        'gst_amount': gst_amount,
        'redeemable_balance': redeemable_balance
    }


def is_admin_user(user):
    return effective_access_role(user) == 'admin' if user else False

# ----- Login -----
@main.route('/', methods=['GET', 'POST'])
@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        # Avoid showing stale flash messages on the login screen
        session.pop('_flashes', None)
        try:
            from .models import LoginPageVisit
            today = date.today()
            row = LoginPageVisit.query.filter_by(visit_date=today).first()
            if not row:
                row = LoginPageVisit(visit_date=today, visit_count=0)
                db.session.add(row)
            row.visit_count = int(row.visit_count or 0) + 1
            db.session.commit()
        except Exception:
            db.session.rollback()

    if request.method == 'POST':
        mobile = normalize_mobile(request.form.get('mobile'))
        password = request.form.get('password')

        # 🔹 Step 1: Check if user exists
        user = find_user_by_mobile(mobile)

        if user:
            # 🔹 Step 2: Check Status
            if user.status != 'Active':
                flash("Your account is currently inactive. Please contact support.", "warning")

            # 🔹 Step 3: Compare password
            elif check_password_hash(user.password, password) or user.password == password:
                session['user_id'] = user.id
                session['mobile'] = user.mobile
                session['user_name'] = user.name or "User"
                session['user_role'] = effective_access_role(user)
                return redirect(url_for('main.home'))
            else:
                flash("Invalid password.", "danger")
        else:
            flash("User not found.", "danger")

    from .models import CarouselImage, CompanyProfile
    carousel_items = CarouselImage.query.filter_by(is_active=True).order_by(CarouselImage.order).all()
    active_user_count = UserLogin.query.filter_by(status='Active', approval_status='Approved').count()
    company_profile = CompanyProfile.query.first()
    whatsapp_admin_number = get_whatsapp_admin_number(company_profile)

    max_visit_count = 0
    max_visit_date = None
    try:
        from .models import LoginPageVisit
        max_row = LoginPageVisit.query.order_by(LoginPageVisit.visit_count.desc(), LoginPageVisit.visit_date.desc()).first()
        if max_row:
            max_visit_count = int(max_row.visit_count or 0)
            max_visit_date = max_row.visit_date
    except Exception:
        pass

    return render_template(
        'pages/login.html',
        carousel_items=carousel_items,
        active_user_count=active_user_count,
        max_visit_count=max_visit_count,
        max_visit_date=max_visit_date,
        whatsapp_admin_number=whatsapp_admin_number,
        company_profile=company_profile
    )


@main.route('/login/whatsapp-enquiry', methods=['POST'])
def login_whatsapp_enquiry():
    from .models import CompanyProfile

    name = (request.form.get('name') or '').strip()
    mobile = normalize_mobile(request.form.get('mobile'))
    enquiry_details = (request.form.get('enquiry_details') or '').strip()

    if not name or len(mobile) != 10 or not enquiry_details:
        flash("Please enter your name, valid mobile number, and enquiry details.", "danger")
        return redirect(url_for('main.login'))

    company_profile = CompanyProfile.query.first()
    whatsapp_number = get_whatsapp_admin_number(company_profile)
    if not whatsapp_number:
        flash("WhatsApp enquiry is not configured yet. Please contact admin directly.", "warning")
        return redirect(url_for('main.login'))

    message = (
        "Hello Admin,%0A%0A"
        f"Name: {name}%0A"
        f"Mobile: {mobile}%0A"
        f"Enquiry: {enquiry_details}%0A%0A"
        "Please contact me regarding my enquiry."
    )
    return redirect(f"https://wa.me/{whatsapp_number}?text={quote(message, safe='%')}")


@main.route('/user/request-create', methods=['POST'])
def user_request_create():
    return_target = (request.form.get('target') or "#hierarchySection").strip() or "#hierarchySection"
    if 'user_id' not in session:
        return redirect(url_for('main.login'))

    current_user = get_session_user()
    if not current_user:
        session.clear()
        session['validation_popup'] = "Please sign in again to continue."
        return redirect(url_for('main.login'))

    if current_user.status != 'Active':
        session['validation_popup'] = "Only active users can submit sub-user requests."
        return redirect_home_with_target(return_target)

    pin_quantity = 1
    selected_epin_id = request.form.get('selected_epin_id', type=int)
    selected_pin = None
    selected_pin_type_name = ''

    if effective_access_role(current_user) != 'admin':
        eligible_pins = get_available_subuser_pins_for_user(current_user.id)
        eligible_pin_ids = {pin.id for pin in eligible_pins}

        if selected_epin_id:
            if selected_epin_id not in eligible_pin_ids:
                session['validation_popup'] = "The selected pin is no longer available for registration. Please choose another unused pin."
                return redirect_home_with_target(return_target)
            selected_pin = next((pin for pin in eligible_pins if pin.id == selected_epin_id), None)
        else:
            if not eligible_pins:
                session['validation_popup'] = "You need at least one unused transferred pin before creating a user below you."
                return redirect_home_with_target(return_target)
            selected_pin = eligible_pins[0]
            selected_epin_id = selected_pin.id
        selected_pin_type_name = (getattr(getattr(selected_pin, 'pin_type', None), 'name', '') or '').strip()
    mobile = normalize_mobile(request.form.get('mobile'))
    if len(mobile) != 10:
        session['validation_popup'] = "Please submit a valid 10-digit mobile number."
        return redirect_home_with_target(return_target)

    if find_user_by_mobile(mobile):
        session['validation_popup'] = "A user with this mobile number already exists."
        return redirect_home_with_target(return_target)

    existing_request = UserCreationRequest.query.filter_by(applicant_mobile=mobile, status='Pending').first()
    if existing_request:
        session['validation_popup'] = "A pending approval request already exists for this mobile number."
        return redirect_home_with_target(return_target)

    requested_role = (request.form.get('requested_role') or '').strip() or None
    if requested_role and requested_role.lower() == 'admin':
        session['validation_popup'] = "Sub-users cannot be requested with admin role."
        return redirect_home_with_target(return_target)

    if effective_access_role(current_user) != 'admin':
        selected_pin_type_key = selected_pin_type_name.lower()
        if selected_pin_type_key == 'product pin':
            session['validation_popup'] = "Product pins cannot be used to create users below you. They are only for existing-user usage logging."
            return redirect_home_with_target(return_target)

        if selected_pin_type_key == 'trial pin':
            new_user, plain_password = create_user_record(
                mobile=mobile,
                name=request.form.get('name') or f"User {mobile}",
                city=request.form.get('city'),
                role='member',
                status='Active',
                parent_id=session['user_id'],
                pin_type=selected_pin_type_name or 'Trial Pin',
                email=request.form.get('email'),
                access_role='user',
                product_type=getattr(current_user, 'product_type', None)
            )
            if selected_pin:
                from .models import EPinTransfer
                selected_pin.owner_id = new_user.id
                db.session.add(selected_pin)
                db.session.add(EPinTransfer(
                    epin_id=selected_pin.id,
                    from_user=session['user_id'],
                    to_user=new_user.id,
                    type='Sent'
                ))
            db.session.commit()
            session['generated_password'] = plain_password
            session['generated_password_user'] = f"{new_user.name or 'User'} ({new_user.mobile})"
            session['user_action_msg'] = "Trial pin user created successfully. No admin approval was needed."
            return redirect_home_with_target(return_target)

    new_request = UserCreationRequest(
        requested_by_id=session['user_id'],
        applicant_mobile=mobile,
        applicant_name=request.form.get('name'),
        applicant_email=request.form.get('email'),
        city=request.form.get('city'),
        pin_type=request.form.get('pin_type') or getattr(getattr(selected_pin, 'pin_type', None), 'name', None),
        requested_pin_count=pin_quantity,
        selected_epin_id=selected_epin_id,
        requested_role=requested_role,
        notes=request.form.get('notes'),
        status='Pending'
    )
    db.session.add(new_request)
    db.session.commit()
    notify_admin_new_request(new_request)
    session['user_action_msg'] = "Your new user request was submitted successfully and sent to admin for approval."
    return redirect_home_with_target(return_target)


@main.route('/admin/pending-requests/status', methods=['GET'])
def admin_pending_requests_status():
    """
    Lightweight endpoint for the admin UI to poll and detect new approval requests.

    The portal is largely server-rendered; without polling, an admin who keeps the
    page open will not see new DB rows until they refresh.
    """
    current_user = get_session_user()
    if not is_admin_user(current_user):
        return jsonify({"error": "forbidden"}), 403

    q = UserCreationRequest.query.filter_by(status='Pending')
    count = q.count()
    latest = q.order_by(UserCreationRequest.created_at.desc()).first()
    return jsonify({
        "count": int(count),
        "latest_id": int(latest.id) if latest else None,
        "latest_created_at": latest.created_at.isoformat() if (latest and latest.created_at) else None,
    })

def get_home_context():
    """Assembles real database data for the portal with placeholder fallbacks."""
    from .models import (
        UserLogin, UserProfile, AccountSettings, EPin, 
        WalletTransaction, SupportTicket, News, CarouselImage, 
        Event, EventImage, CompanyProfile, QuickLink, SchemaMeta,
        ProductType, PinType, UserRole, UserCreationRequest, PinUsageReport,
        EPinTransfer, WithdrawRequest, LegalDocument, ReferenceOption
    )
    from sqlalchemy import func

    user_id = session.get('user_id')
    current_user = UserLogin.query.get(user_id) if user_id else None
    selected_level_product = normalize_level_product(request.args.get('level_product'), 'all', allow_all=True)
    user_level_product_keys = normalize_user_product_keys(getattr(current_user, 'product_type', None)) if current_user else []
    is_admin_view = bool(is_admin_user(current_user))
    if is_admin_view:
        user_level_product_keys = []

    # If any route used Flask flash(), translate those messages into our existing modal UX
    # so every form submission behaves consistently.
    flashes = []
    try:
        flashes = list(session.get('_flashes') or [])
    except Exception:
        flashes = []
    if flashes:
        session.pop('_flashes', None)
        if not session.get('validation_popup'):
            for category, message in flashes:
                if str(category).lower() in {'danger', 'warning', 'error'} and message:
                    session['validation_popup'] = str(message)
                    break
        if not session.get('user_action_msg'):
            for category, message in flashes:
                if str(category).lower() in {'success', 'info'} and message:
                    session['user_action_msg'] = str(message)
                    break

    # Clamp product filter for non-admin users:
    # - If user has BOTH products -> allow 'all', 'pad', 'diaper'
    # - If user has ONE product -> allow only that product (no 'all')
    if is_admin_view:
        allowed_level_filters = list(LEVEL_FILTER_OPTIONS)
    else:
        allowed_level_filters = list(user_level_product_keys or list(LEVEL_PRODUCTS))
        if len(user_level_product_keys) > 1:
            allowed_level_filters = ['all'] + allowed_level_filters

    if allowed_level_filters:
        if selected_level_product not in allowed_level_filters:
            selected_level_product = allowed_level_filters[0]
        if selected_level_product == 'all' and (not is_admin_view) and len(user_level_product_keys) <= 1:
            selected_level_product = allowed_level_filters[0]

    level_product_filter_options = []
    if is_admin_view:
        level_product_filter_options = [
            {'key': 'all', 'label': 'All'},
            {'key': 'pad', 'label': 'Pad'},
            {'key': 'diaper', 'label': 'Diaper'},
        ]
    else:
        if 'all' in allowed_level_filters:
            level_product_filter_options.append({'key': 'all', 'label': 'All'})
        for product_key in (user_level_product_keys or list(LEVEL_PRODUCTS)):
            if product_key in LEVEL_PRODUCTS:
                level_product_filter_options.append({'key': product_key, 'label': to_level_product_label(product_key)})
    available_subuser_pin_count = 0
    available_subuser_pins = []
    if current_user:
        available_subuser_pins = get_available_subuser_pins_for_user(current_user.id)
        available_subuser_pin_count = len(available_subuser_pins)

    can_request_subuser = bool(
        current_user
        and current_user.status == 'Active'
        and (
            effective_access_role(current_user) == 'admin'
            or available_subuser_pin_count > 0
        )
    )
    subuser_request_block_reason = None
    if current_user:
        if current_user.status != 'Active':
            subuser_request_block_reason = "Your account is inactive. Only active users can create users below them."
        elif effective_access_role(current_user) != 'admin' and available_subuser_pin_count <= 0:
            subuser_request_block_reason = "No unused transferred pins are available in your account. Ask admin or your parent user to transfer pins before creating users below you."
    
    # 1. Fetch Core Profile Data
    profile_db = UserProfile.query.filter_by(user_id=user_id).first()
    profile = {
        'name': (profile_db.name if profile_db and profile_db.name else (current_user.name if current_user and current_user.name else session.get('user_name', 'User'))),
        'mobile': (profile_db.mobile if profile_db and profile_db.mobile else (current_user.mobile if current_user and current_user.mobile else session.get('mobile', '---'))),
        'email': profile_db.email if profile_db else 'N/A',
        'address': profile_db.address if profile_db else 'Not provided',
        'city': profile_db.city if profile_db else 'N/A',
        'state': profile_db.state if profile_db else 'N/A',
    }
    profile_member_id = (getattr(current_user, 'emp_id', None) if current_user else None) or (str(user_id).zfill(5) if user_id else '-----')

    # 2. Bank Details
    bank_db = AccountSettings.query.filter_by(user_id=user_id).first()
    bank = {
        'bank_name': bank_db.bank_name if bank_db else 'N/A',
        'acc_no': bank_db.acc_no if bank_db else '---',
        'ifsc': bank_db.ifsc if bank_db else '---',
        'acc_holder': bank_db.acc_holder if bank_db else profile['name'],
        'branch': bank_db.branch if bank_db else ''
    }

    # 3. Real Wallet & Income Stats
    wallet_sum = db.session.query(func.sum(WalletTransaction.amount)).filter_by(user_id=user_id).scalar() or 0
    # Dummy income aggregation logic - in real world this might be a complex query
    # Using a mix of real sum + placeholder baseline for visual fullness as requested
    actual_balance = wallet_sum if wallet_sum > 0 else 0
    wallet_summary = compute_redeemable_balance(actual_balance)
    
    # 4. Metrics
    downline_counts = count_downline_members(current_user)
    metrics = {
        'wallet_balance': actual_balance,
        'total_income': wallet_sum,
        'total_team': downline_counts['total'],
        'total_direct': downline_counts['direct'],
    }

    # 5. E-Pins
    if is_admin_user(current_user):
        # For admins, treat the "Inventory" table as assignable pins, i.e. pins that are
        # not yet assigned to any user. Otherwise, after assigning, they would still show
        # up as "Unused" which is confusing.
        unused_pins = EPin.query.filter(
            EPin.status == 'Unused',
            (EPin.owner_id.is_(None)) | (EPin.owner_id == user_id)
        ).order_by(EPin.created_at.desc()).all()
        used_pins = EPin.query.filter_by(status='Used').count()
    else:
        unused_pins = EPin.query.filter_by(owner_id=user_id, status='Unused').all()
        used_pins = EPin.query.filter_by(owner_id=user_id, status='Used').count() if user_id else 0
    # Reserve pins that are explicitly selected in pending requests, plus pins held back for
    # pending requests that have not selected a specific pin yet.
    reserved_request_pin_ids = get_effective_reserved_pin_ids(user_id)
    reserved_unused_pins = [pin for pin in unused_pins if pin.id in reserved_request_pin_ids]
    available_inventory_pins = [pin for pin in unused_pins if pin.id not in reserved_request_pin_ids]
    for pin in available_inventory_pins:
        pin.display_status = 'Unused'
    for pin in reserved_unused_pins:
        pin.display_status = 'Reserved'
    epin_summary = {
        'unused': len(available_inventory_pins),
        'reserved': len(reserved_unused_pins),
        'used': used_pins,
        'total': len(unused_pins) + used_pins
    }
    epin_results = available_inventory_pins + reserved_unused_pins

    # 6. News & Carousel
    news_start = request.args.get('news_start')
    news_end = request.args.get('news_end')
    
    n_query = News.query
    if news_start:
        try:
            nsd = datetime.strptime(news_start, '%Y-%m-%d')
            n_query = n_query.filter(News.created_at >= nsd)
        except: pass
    if news_end:
        try:
            ned = datetime.strptime(news_end, '%Y-%m-%d')
            import datetime as dt_mod
            ned_plus_one = ned + dt_mod.timedelta(days=1)
            n_query = n_query.filter(News.created_at < ned_plus_one)
        except: pass

    news_list = n_query.order_by(News.created_at.desc()).all()
    carousel_items = CarouselImage.query.filter_by(is_active=True).order_by(CarouselImage.order).all()

    # 7. Support Filtering (Advanced)
    ticket_no = request.args.get('ticket_no')
    query_type = request.args.get('query_type')
    u_filter = request.args.get('user_filter') # Select2 UID
    s_filter = request.args.get('status_filter')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    def filter_tickets(query):
        if ticket_no: query = query.filter(SupportTicket.ticket_no.ilike(f"%{ticket_no}%"))
        if query_type and query_type != 'All': query = query.filter_by(query_type=query_type)
        if u_filter and u_filter != 'All': query = query.filter_by(user_id=int(u_filter))
        if s_filter and s_filter != 'All': query = query.filter_by(status=s_filter)
        if start_date:
            try: query = query.filter(SupportTicket.created_at >= datetime.strptime(start_date, '%Y-%m-%d'))
            except: pass
        if end_date:
            try: query = query.filter(SupportTicket.created_at <= datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59))
            except: pass
        return query

    my_tickets = filter_tickets(SupportTicket.query.filter_by(user_id=user_id)).order_by(SupportTicket.created_at.desc()).all()
    all_tickets = filter_tickets(SupportTicket.query).order_by(SupportTicket.created_at.desc()).all()

    # 8. Events
    e_start = request.args.get('e_start')
    e_end = request.args.get('e_end')
    e_query = Event.query
    if e_start: 
        try: e_query = e_query.filter(Event.event_date >= datetime.strptime(e_start, '%Y-%m-%d'))
        except: pass
    if e_end:
        try: e_query = e_query.filter(Event.event_date <= datetime.strptime(e_end, '%Y-%m-%d'))
        except: pass
    events = e_query.order_by(Event.event_date.desc()).all()
    for ev in events:
        ev.images = EventImage.query.filter_by(event_id=ev.id).all()
        
    company_profile = CompanyProfile.query.first()
    quick_links = QuickLink.query.order_by(QuickLink.order).all()
    ensure_default_pin_types()
    reference_options = get_reference_option_map(
        'access_role',
        'user_status',
        'approval_status',
        'request_status',
        'withdraw_status',
        'support_ticket_status',
        'support_query_type',
        'epin_status',
        'epin_transfer_status',
        'product_filter',
    )

    # 10. Financial Reports (I-Wallet & Income)
    # Fetching real data where available, otherwise using placeholder logic for fullness
    wallet_txs = WalletTransaction.query.filter_by(user_id=user_id).order_by(WalletTransaction.date.desc()).all()
    withdraw_requests = []
    withdraw_history_rows = []
    admin_withdraw_requests = []
    withdraw_start = request.args.get('withdraw_start')
    withdraw_end = request.args.get('withdraw_end')
    withdraw_status = (request.args.get('withdraw_status') or 'All').strip()

    def apply_withdraw_filters(query):
        if withdraw_start:
            try:
                query = query.filter(WithdrawRequest.created_at >= datetime.strptime(withdraw_start, '%Y-%m-%d'))
            except Exception:
                pass
        if withdraw_end:
            try:
                query = query.filter(WithdrawRequest.created_at <= datetime.strptime(withdraw_end, '%Y-%m-%d').replace(hour=23, minute=59, second=59))
            except Exception:
                pass
        if withdraw_status and withdraw_status != 'All':
            query = query.filter(WithdrawRequest.status == withdraw_status)
        return query

    if user_id:
        withdraw_query = apply_withdraw_filters(WithdrawRequest.query.filter_by(user_id=user_id))
        withdraw_requests = withdraw_query.order_by(WithdrawRequest.created_at.desc()).all()
        withdraw_history_rows = list(withdraw_requests)
    if is_admin_user(current_user):
        withdraw_history_query = apply_withdraw_filters(WithdrawRequest.query)
        withdraw_history_rows = withdraw_history_query.order_by(WithdrawRequest.created_at.desc()).all()
        admin_withdraw_query = WithdrawRequest.query.filter_by(status='Pending')
        if withdraw_start:
            try:
                admin_withdraw_query = admin_withdraw_query.filter(WithdrawRequest.created_at >= datetime.strptime(withdraw_start, '%Y-%m-%d'))
            except Exception:
                pass
        if withdraw_end:
            try:
                admin_withdraw_query = admin_withdraw_query.filter(WithdrawRequest.created_at <= datetime.strptime(withdraw_end, '%Y-%m-%d').replace(hour=23, minute=59, second=59))
            except Exception:
                pass
        admin_withdraw_requests = admin_withdraw_query.order_by(WithdrawRequest.created_at.desc()).all()
    iwallet = {
        'transactions': [{'date': tx.date.strftime('%Y-%m-%d %H:%M'), 'type': 'Credit' if tx.amount > 0 else 'Debit', 'amount': abs(tx.amount), 'remark': tx.description} for tx in wallet_txs]
    }
    if not iwallet['transactions']:
        iwallet['transactions'] = [
            {'date': '2026-02-28 10:30', 'type': 'Credit', 'amount': 1500, 'remark': 'Admin Credit'},
            {'date': '2026-03-01 14:20', 'type': 'Debit', 'amount': 250, 'remark': 'EPin Purchase'}
        ]

    income = {
        'records': [
            {'date': '2026-02-28', 'type': 'Direct', 'from': 'Member 1024', 'amount': 500},
            {'date': '2026-03-01', 'type': 'Binary', 'from': 'Network Left', 'amount': 1200}
        ]
    }

    # 11. Schema & Admin Data
    all_users = UserLogin.query.all()
    schema_data = SchemaMeta.query.all()
    
    # 12. Level / Product Management Data
    from .models import LevelPlan
    all_level_plans = LevelPlan.query.order_by(LevelPlan.product_type.asc(), LevelPlan.level_no.asc()).all()
    level_plans_by_product = {
        product_key: [plan for plan in all_level_plans if normalize_level_product(getattr(plan, 'product_type', 'pad')) == product_key]
        for product_key in LEVEL_PRODUCTS
    }
    master_level_product_keys = list(LEVEL_PRODUCTS) if selected_level_product == 'all' else [selected_level_product]
    level_plans = [
        plan
        for product_key in master_level_product_keys
        for plan in level_plans_by_product.get(product_key, [])
    ]
    level_plan_tables = [
        {
            'product_key': product_key,
            'product_label': to_level_product_label(product_key),
            'plans': level_plans_by_product.get(product_key, []),
        }
        for product_key in master_level_product_keys
    ]
    level_views = build_user_level_views(current_user, level_plans_by_product, max_depth=5)
    product_referral_counts = {product_key: level_views.get(product_key, {}).get('created_ids', 0) for product_key in LEVEL_PRODUCTS}
    product_usage_qualified_counts = {product_key: level_views.get(product_key, {}).get('total_ids', 0) for product_key in LEVEL_PRODUCTS}

    # user_level_product_keys is computed earlier (and empty for admin view).
    if selected_level_product in LEVEL_PRODUCTS:
        level_income = level_views.get(selected_level_product, calculate_level_income(0, level_plans_by_product.get(selected_level_product, [])))
    else:
        level_income = {
            'grand_total': sum(level_views.get(k, {}).get('grand_total', 0) for k in user_level_product_keys)
        }
    product_income_totals = {k: level_views.get(k, {}).get('grand_total', 0) for k in LEVEL_PRODUCTS}
    combined_level_income = sum(product_income_totals.get(k, 0) for k in user_level_product_keys)
    metrics['total_income'] = combined_level_income if not is_admin_user(current_user) else wallet_sum
    effective_wallet_balance = wallet_sum if is_admin_user(current_user) else max(wallet_sum, combined_level_income)
    metrics['wallet_balance'] = effective_wallet_balance
    wallet_summary = compute_redeemable_balance(effective_wallet_balance)
    wallet_balance_rows = db.session.query(
        WalletTransaction.user_id,
        func.sum(WalletTransaction.amount)
    ).group_by(WalletTransaction.user_id).all()
    wallet_balance_by_user = {uid: (float(total) if total is not None else 0.0) for uid, total in wallet_balance_rows}
    admin_user_wallet_rows = []
    admin_user_level_rows = []
    if is_admin_user(current_user):
        admin_users = UserLogin.query.filter(UserLogin.role != 'admin').order_by(UserLogin.name.asc(), UserLogin.mobile.asc()).all()
        scoped_product_keys = list(LEVEL_PRODUCTS) if selected_level_product == 'all' else [selected_level_product]
        for usr in admin_users:
            user_keys = normalize_user_product_keys(getattr(usr, 'product_type', None))
            user_level_views = build_user_level_views(usr, level_plans_by_product, max_depth=5)
            user_product_income_totals = {k: user_level_views.get(k, {}).get('grand_total', 0) for k in LEVEL_PRODUCTS}
            user_combined_income = sum(user_product_income_totals.get(k, 0) for k in user_keys)
            user_wallet_sum = wallet_balance_by_user.get(usr.id, 0.0)
            user_effective_balance = max(user_wallet_sum, user_combined_income)
            user_redeemable = compute_redeemable_balance(user_effective_balance).get('redeemable_balance', 0)
            admin_user_wallet_rows.append({
                'user_id': usr.id,
                'name': usr.name or 'User',
                'mobile': usr.mobile,
                'product_access': ', '.join(to_level_product_label(k) for k in user_keys) if user_keys else '-',
                'pad_balance': user_product_income_totals.get('pad', 0),
                'diaper_balance': user_product_income_totals.get('diaper', 0),
                'combined_balance': user_combined_income,
                'wallet_tx_balance': user_wallet_sum,
                'effective_balance': user_effective_balance,
                'redeemable_balance': user_redeemable,
            })
            for product_key in scoped_product_keys:
                if product_key not in user_keys:
                    continue
                view = user_level_views.get(product_key, {})
                current_level_no = int(view.get('current_level', 0) or 0)
                income_per_id = 0
                reward_per_id = 0
                plans_for_product = level_plans_by_product.get(product_key, [])
                if plans_for_product:
                    plan_match = next((p for p in plans_for_product if int(getattr(p, 'level_no', 0) or 0) == current_level_no), None)
                    if not plan_match and current_level_no > 0:
                        eligible_plans = [
                            p for p in plans_for_product
                            if int(getattr(p, 'level_no', 0) or 0) <= current_level_no
                        ]
                        if eligible_plans:
                            plan_match = sorted(eligible_plans, key=lambda p: int(getattr(p, 'level_no', 0) or 0))[-1]
                    if plan_match:
                        income_per_id = int(getattr(plan_match, 'income_per_id', 0) or 0)
                        reward_per_id = int(getattr(plan_match, 'reward_per_id', 0) or 0)
                admin_user_level_rows.append({
                    'user_id': usr.id,
                    'name': usr.name or 'User',
                    'mobile': usr.mobile,
                    'product_label': to_level_product_label(product_key),
                    'current_level': current_level_no,
                    'total_ids': view.get('total_ids', 0),
                    'created_ids': view.get('created_ids', 0),
                    'usage_logged_ids': view.get('usage_logged_ids', 0),
                    'pending_usage_ids': view.get('pending_usage_ids', 0),
                    'income_per_id': income_per_id,
                    'reward_per_id': reward_per_id,
                    'total_income': view.get('total_income', 0),
                    'total_reward': view.get('total_reward', 0),
                    'total_amount': view.get('grand_total', 0),
                })
    all_withdraw_requests = WithdrawRequest.query.all() if is_admin_user(current_user) else []
    admin_wallet_totals = {
        'pad_balance': sum(float(row.get('pad_balance', 0) or 0) for row in admin_user_wallet_rows),
        'diaper_balance': sum(float(row.get('diaper_balance', 0) or 0) for row in admin_user_wallet_rows),
        'combined_balance': sum(float(row.get('combined_balance', 0) or 0) for row in admin_user_wallet_rows),
        'available_balance': sum(float(row.get('effective_balance', 0) or 0) for row in admin_user_wallet_rows),
        'withdraw_request_amount': sum(float(req.requested_amount or 0) for req in all_withdraw_requests),
        'withdraw_pending_count': sum(1 for req in all_withdraw_requests if (req.status or '') == 'Pending'),
        'withdraw_total_count': len(all_withdraw_requests),
    }
    hierarchy_tree = build_hierarchy_snapshot(current_user) if current_user else None
    if is_admin_user(current_user):
        owned_pins = EPin.query.order_by(EPin.created_at.desc()).all()
        pin_reports = PinUsageReport.query.order_by(PinUsageReport.sold_at.desc()).all()
        transfer_history = EPinTransfer.query.order_by(EPinTransfer.transfer_date.desc()).limit(200).all()
    else:
        owned_pins = EPin.query.filter_by(owner_id=user_id).order_by(EPin.created_at.desc()).all()
        pin_reports = PinUsageReport.query.filter_by(user_id=user_id).order_by(PinUsageReport.sold_at.desc()).all()
        transfer_history = []
        if user_id:
            transfer_history = EPinTransfer.query.filter(
                (EPinTransfer.from_user == user_id) | (EPinTransfer.to_user == user_id)
            ).order_by(EPinTransfer.transfer_date.desc()).limit(20).all()
    usable_owned_pins = []
    if is_admin_user(current_user):
        usable_owned_pins = owned_pins
    else:
        usable_owned_pins = [
            pin for pin in owned_pins
            if not (pin.status == 'Unused' and pin.id in reserved_request_pin_ids)
        ]
    pin_inventory = summarize_pin_inventory(usable_owned_pins)
    pin_usage = summarize_pin_usage(pin_reports)
    pin_history_rows = build_pin_history_rows(owned_pins, pin_reports)
    if is_admin_user(current_user):
        transfer_type_counts = {}
        for transfer in transfer_history:
            if getattr(transfer, 'status', 'Active') != 'Active':
                continue
            pin_type_name = getattr(getattr(transfer.epin, 'pin_type', None), 'name', None) or 'Generic'
            transfer_type_counts[pin_type_name] = transfer_type_counts.get(pin_type_name, 0) + 1
        for row in pin_history_rows:
            row['unused_count'] = transfer_type_counts.get(row['pin_type'], 0)
    product_purchase_summary = {'pad': 0, 'diaper': 0}
    for report in pin_reports:
        product_name = (getattr(getattr(report.pin, 'product_type', None), 'name', '') or '').strip().lower()
        if product_name == 'pad':
            product_purchase_summary['pad'] += 1
        elif product_name == 'diaper':
            product_purchase_summary['diaper'] += 1
    pin_transfer_history = summarize_transfer_history(transfer_history, user_id if not is_admin_user(current_user) else None)

    transfer_candidates = []
    if current_user:
        if effective_access_role(current_user) == 'admin':
            transfer_candidates = UserLogin.query.filter(UserLogin.id != current_user.id).order_by(UserLogin.name.asc(), UserLogin.mobile.asc()).all()
        else:
            downline_ids = get_downline_user_ids(current_user)
            if downline_ids:
                transfer_candidates = UserLogin.query.filter(
                    UserLogin.id.in_(downline_ids),
                    UserLogin.status == 'Active',
                    UserLogin.approval_status == 'Approved'
                ).order_by(UserLogin.name.asc(), UserLogin.mobile.asc()).all()

    direct_members = []
    if current_user:
        direct_members = current_user.children.order_by(UserLogin.created_at.desc()).all()
        for member in direct_members:
            member.display_role = display_role_label(member)
            member.access_role = effective_access_role(member)
            member.user_type = effective_user_type(member)

    product_types = ProductType.query.order_by(ProductType.name).all()
    pin_types = PinType.query.order_by(PinType.name).all()
    user_roles = UserRole.query.order_by(UserRole.name).all()
    schema_data = SchemaMeta.query.all()
    pending_requests = []
    # Use DB-backed admin detection; session flags can be missing/stale.
    if is_admin_view:
        pending_requests = UserCreationRequest.query.filter_by(status='Pending').order_by(UserCreationRequest.created_at.desc()).all()
    user_request_history = []
    if user_id:
        user_request_history = UserCreationRequest.query.filter_by(requested_by_id=user_id).order_by(UserCreationRequest.created_at.desc()).all()
    user_request_history, user_request_usage_summary = annotate_user_creation_requests_with_usage(user_request_history)
    admin_approved_request_usage_summary = {
        'approved_total': 0,
        'approved_usage_done': 0,
        'approved_pending_usage': 0,
        'approved_user_missing': 0,
    }
    admin_pending_usage_rows = []
    if is_admin_user(current_user):
        approved_requests_all = UserCreationRequest.query.filter_by(status='Approved').order_by(UserCreationRequest.created_at.desc()).all()
        approved_requests_all, admin_approved_request_usage_summary = annotate_user_creation_requests_with_usage(approved_requests_all)
        approved_user_ids = [req.approved_user_id for req in approved_requests_all if getattr(req, 'approved_user_id', None)]
        linked_users_by_id = {}
        if approved_user_ids:
            linked_users = UserLogin.query.filter(UserLogin.id.in_(approved_user_ids)).all()
            linked_users_by_id = {usr.id: usr for usr in linked_users}

        for req in approved_requests_all:
            if req.status != 'Approved' or getattr(req, 'manage_level_ready', False):
                continue
            linked_user = linked_users_by_id.get(getattr(req, 'approved_user_id', None))
            product_display = (getattr(linked_user, 'product_type', None) or req.pin_type or '-')
            requester_name = getattr(getattr(req, 'requested_by', None), 'name', None) or 'User'
            requester_mobile = getattr(getattr(req, 'requested_by', None), 'mobile', None) or '-'
            admin_pending_usage_rows.append({
                'applicant_name': (getattr(linked_user, 'name', None) or req.applicant_name or 'User'),
                'applicant_mobile': (getattr(linked_user, 'mobile', None) or req.applicant_mobile or '-'),
                'member_id': (getattr(linked_user, 'emp_id', None) or (str(getattr(linked_user, 'id', '')) if linked_user else '-')),
                'requester_name': requester_name,
                'requester_mobile': requester_mobile,
                'product_type': product_display,
                'approved_at': req.approved_at,
                'usage_log_count': getattr(req, 'usage_log_count', 0),
                'note': getattr(req, 'manage_level_note', 'Usage log not added yet.'),
            })
    legal_documents = LegalDocument.query.order_by(LegalDocument.created_at.desc()).all()

    # 10. User Management (Admin Only)
    m_mobile = request.args.get('m_mobile')
    m_name = request.args.get('m_name')
    m_status = request.args.get('m_status')
    m_city = request.args.get('m_city')
    m_product = request.args.get('m_product')
    m_role = request.args.get('m_role')
    m_pin_type = request.args.get('m_pin_type')
    m_approval = request.args.get('m_approval')
    
    user_list = []
    if is_admin_view:
        u_query = UserLogin.query
        if m_mobile: u_query = u_query.filter(UserLogin.mobile.ilike(f"%{m_mobile}%"))
        if m_name: u_query = u_query.filter(UserLogin.name.ilike(f"%{m_name}%"))
        if m_status and m_status != 'All': u_query = u_query.filter_by(status=m_status)
        if m_city and m_city != 'All': u_query = u_query.filter(UserLogin.city == m_city)
        if m_product and m_product != 'All': u_query = u_query.filter(UserLogin.product_type == m_product)
        if m_role and m_role != 'All':
            role_filter = (m_role or '').strip().lower()
            if role_filter == 'admin':
                u_query = u_query.filter(UserLogin.role == 'admin')
            else:
                u_query = u_query.filter(UserLogin.role == 'user').filter(UserLogin.type_of_user.ilike(role_filter))
        if m_pin_type and m_pin_type != 'All': u_query = u_query.filter(UserLogin.pin_type == m_pin_type)
        if m_approval and m_approval != 'All': u_query = u_query.filter(UserLogin.approval_status == m_approval)
        
        user_list = u_query.order_by(UserLogin.created_at.desc()).all()

    available_cities = sorted({(u.city or '').strip() for u in user_list if (u.city or '').strip()})
    for usr in user_list:
        usr.display_role = display_role_label(usr)
        usr.access_role = effective_access_role(usr)
        usr.user_type = effective_user_type(usr)
    for req in pending_requests:
        req.requested_by.display_role = display_role_label(req.requested_by)
    for req in user_request_history:
        req.requested_by.display_role = display_role_label(req.requested_by)

    role_choices = {'admin'}
    role_choices.update({
        (role.name or '').strip()
        for role in user_roles
        if (role.name or '').strip() and (role.name or '').strip().lower() not in {'user', 'admin'}
    })
    role_choices.update({effective_user_type(u) for u in user_list if u and effective_access_role(u) != 'admin'})
    role_options = sorted(role_choices)

    # Compact dashboard analytics payload (single chart area with switch buttons + range switch)
    analytics_now = datetime.utcnow()
    analytics_ranges = {
        'weekly': {'label': 'Weekly', 'since': analytics_now - timedelta(days=6)},
        'monthly': {'label': 'Monthly', 'since': analytics_now - timedelta(days=29)},
    }

    def in_range(dt_value, since_dt):
        if not dt_value:
            return False
        return dt_value >= since_dt

    def status_counts(rows, since_dt, status_field='status', date_field='created_at'):
        out = {'Pending': 0, 'Approved': 0, 'Rejected': 0}
        for row in rows:
            row_dt = getattr(row, date_field, None)
            if not in_range(row_dt, since_dt):
                continue
            status_key = str(getattr(row, status_field, '') or '').strip().title()
            if status_key in out:
                out[status_key] += 1
        return out

    def build_user_wallet_activity_series(transactions, mode_key):
        tx_rows = [tx for tx in (transactions or []) if getattr(tx, 'date', None)]
        if mode_key == 'monthly':
            start_date = (analytics_now - timedelta(days=29)).date()
            labels = []
            values = []
            for idx in range(5):
                bucket_start = start_date + timedelta(days=idx * 6)
                bucket_end = min(start_date + timedelta(days=(idx + 1) * 6 - 1), analytics_now.date())
                total_amount = 0.0
                for tx in tx_rows:
                    tx_day = tx.date.date()
                    if bucket_start <= tx_day <= bucket_end:
                        total_amount += float(getattr(tx, 'amount', 0) or 0)
                labels.append(f"{bucket_start.strftime('%d %b')} - {bucket_end.strftime('%d %b')}")
                values.append(round(total_amount, 2))
            return labels, values

        start_date = (analytics_now - timedelta(days=6)).date()
        labels = []
        values = []
        for idx in range(7):
            day = start_date + timedelta(days=idx)
            total_amount = 0.0
            for tx in tx_rows:
                if tx.date.date() == day:
                    total_amount += float(getattr(tx, 'amount', 0) or 0)
            labels.append(day.strftime('%d %b'))
            values.append(round(total_amount, 2))
        return labels, values

    all_creation_requests = UserCreationRequest.query.all()
    all_user_withdraw_requests = WithdrawRequest.query.filter_by(user_id=user_id).all() if user_id else []

    level_agg_by_no = {}
    for product_key in user_level_product_keys:
        for row in level_views.get(product_key, {}).get('rows', []):
            level_no = int(row.get('level_no', 0) or 0)
            if level_no <= 0:
                continue
            bucket = level_agg_by_no.setdefault(level_no, {'created': 0, 'qualified': 0})
            bucket['created'] += int(row.get('created_count', row.get('count', 0)) or 0)
            bucket['qualified'] += int(row.get('count', 0) or 0)

    level_numbers = sorted(level_agg_by_no.keys())
    level_labels = [f"L{lv}" for lv in level_numbers]
    level_created = [level_agg_by_no[lv]['created'] for lv in level_numbers]
    level_qualified = [level_agg_by_no[lv]['qualified'] for lv in level_numbers]

    top_wallet_rows = sorted(
        admin_user_wallet_rows,
        key=lambda r: float(r.get('combined_balance', 0) or 0),
        reverse=True
    )[:5]

    dashboard_analytics = {
        'is_admin': bool(is_admin_user(current_user)),
        'default_range': 'weekly',
        'range_options': [{'key': key, 'label': meta['label']} for key, meta in analytics_ranges.items()],
        'charts_by_range': {}
    }

    if is_admin_user(current_user):
        dashboard_analytics['default_key'] = 'product_balance'
        dashboard_analytics['buttons'] = [
            {'key': 'product_balance', 'label': 'Product Balance'},
            {'key': 'approval_pipeline', 'label': 'Approval Pipeline'},
            {'key': 'withdraw_status', 'label': 'Withdraw Status'},
            {'key': 'top_earners', 'label': 'Top Earners'},
        ]
        for range_key, range_meta in analytics_ranges.items():
            since_dt = range_meta['since']
            request_status_counts = status_counts(all_creation_requests, since_dt, status_field='status', date_field='created_at')
            withdraw_status_counts = status_counts(all_withdraw_requests, since_dt, status_field='status', date_field='created_at')
            approved_pending_usage_count = 0
            for req in (approved_requests_all if 'approved_requests_all' in locals() else []):
                req_dt = getattr(req, 'approved_at', None) or getattr(req, 'created_at', None)
                if in_range(req_dt, since_dt) and not getattr(req, 'manage_level_ready', False):
                    approved_pending_usage_count += 1

            dashboard_analytics['charts_by_range'][range_key] = {
                'product_balance': {
                    'type': 'doughnut',
                    'labels': ['Pad', 'Diaper'],
                    'datasets': [{
                        'label': 'Balance',
                        'data': [
                            float(admin_wallet_totals.get('pad_balance', 0) or 0),
                            float(admin_wallet_totals.get('diaper_balance', 0) or 0),
                        ],
                        'backgroundColor': ['#2563eb', '#0f766e'],
                        'borderWidth': 1
                    }]
                },
                'approval_pipeline': {
                    'type': 'bar',
                    'labels': ['Pending', 'Approved', 'Rejected', 'Approved Pending Usage'],
                    'datasets': [{
                        'label': f"Requests ({range_meta['label']})",
                        'data': [
                            request_status_counts.get('Pending', 0),
                            request_status_counts.get('Approved', 0),
                            request_status_counts.get('Rejected', 0),
                            approved_pending_usage_count,
                        ],
                        'backgroundColor': ['#f59e0b', '#16a34a', '#dc2626', '#ea580c'],
                        'borderRadius': 8,
                    }]
                },
                'withdraw_status': {
                    'type': 'doughnut',
                    'labels': ['Pending', 'Approved', 'Rejected'],
                    'datasets': [{
                        'label': f"Withdraw Requests ({range_meta['label']})",
                        'data': [
                            withdraw_status_counts.get('Pending', 0),
                            withdraw_status_counts.get('Approved', 0),
                            withdraw_status_counts.get('Rejected', 0),
                        ],
                        'backgroundColor': ['#f59e0b', '#16a34a', '#dc2626'],
                        'borderWidth': 1
                    }]
                },
                'top_earners': {
                    'type': 'bar',
                    'labels': [row.get('name', 'User') for row in top_wallet_rows],
                    'datasets': [{
                        'label': 'Combined Income',
                        'data': [float(row.get('combined_balance', 0) or 0) for row in top_wallet_rows],
                        'backgroundColor': '#4f46e5',
                        'borderRadius': 8,
                    }]
                },
            }
    else:
        user_pad_income = float(product_income_totals.get('pad', 0) or 0)
        user_diaper_income = float(product_income_totals.get('diaper', 0) or 0)
        dashboard_analytics['default_key'] = 'income_split'
        dashboard_analytics['buttons'] = [
            {'key': 'income_split', 'label': 'Income Split'},
            {'key': 'level_progress', 'label': 'Level Progress'},
            {'key': 'wallet_activity', 'label': 'Wallet Activity'},
        ]
        for range_key, range_meta in analytics_ranges.items():
            since_dt = range_meta['since']
            user_pending_withdraw_amount = sum(
                float(getattr(req, 'requested_amount', 0) or 0)
                for req in all_user_withdraw_requests
                if str(getattr(req, 'status', '') or '').strip().title() == 'Pending'
                and in_range(getattr(req, 'created_at', None), since_dt)
            )
            wallet_labels, wallet_values = build_user_wallet_activity_series(wallet_txs, range_key)
            dashboard_analytics['charts_by_range'][range_key] = {
                'income_split': {
                    'type': 'doughnut',
                    'labels': ['Pad', 'Diaper'],
                    'datasets': [{
                        'label': 'Income',
                        'data': [user_pad_income, user_diaper_income],
                        'backgroundColor': ['#2563eb', '#0f766e'],
                        'borderWidth': 1
                    }]
                },
                'level_progress': {
                    'type': 'bar',
                    'labels': level_labels if level_labels else ['L1'],
                    'datasets': [
                        {
                            'label': 'Created IDs',
                            'data': level_created if level_created else [0],
                            'backgroundColor': '#94a3b8',
                            'borderRadius': 8,
                        },
                        {
                            'label': 'Qualified IDs',
                            'data': level_qualified if level_qualified else [0],
                            'backgroundColor': '#16a34a',
                            'borderRadius': 8,
                        },
                    ]
                },
                'wallet_activity': {
                    'type': 'line',
                    'labels': wallet_labels,
                    'datasets': [
                        {
                            'label': f"Net Activity ({range_meta['label']})",
                            'data': wallet_values,
                            'borderColor': '#4f46e5',
                            'backgroundColor': 'rgba(79,70,229,0.08)',
                            'fill': True,
                            'tension': 0.35,
                        },
                        {
                            'label': 'Pending Withdraw Amount',
                            'data': [user_pending_withdraw_amount for _ in wallet_labels],
                            'borderColor': '#f59e0b',
                            'borderDash': [6, 4],
                            'pointRadius': 0,
                            'fill': False,
                            'tension': 0,
                        }
                    ]
                },
            }

    context = {
        'metrics': metrics,
        'current_user': current_user,
        'is_admin_view': is_admin_view,
        'profile': profile,
        'profile_member_id': profile_member_id,
        'news_list': news_list,
        'carousel_items': carousel_items,
        'events': events,
        'company_profile': company_profile,
        'quick_links': quick_links,
        'bank': bank,
        'epin_summary': epin_summary,
        'epin_results': epin_results,
        'iwallet': iwallet,
        'income': income,
        'wallet_summary': wallet_summary,
        'withdraw_requests': withdraw_requests,
        'withdraw_history_rows': withdraw_history_rows,
        'admin_withdraw_requests': admin_withdraw_requests,
        'withdraw_start': withdraw_start or '',
        'withdraw_end': withdraw_end or '',
        'withdraw_status': withdraw_status or 'All',
        'reference_options': reference_options,
        'access_role_options': reference_options.get('access_role', []),
        'user_status_options': reference_options.get('user_status', []),
        'approval_status_options': reference_options.get('approval_status', []),
        'request_status_options': reference_options.get('request_status', []),
        'withdraw_status_options': reference_options.get('withdraw_status', []),
        'support_ticket_status_options': reference_options.get('support_ticket_status', []),
        'support_query_type_options': reference_options.get('support_query_type', []),
        'epin_status_options': reference_options.get('epin_status', []),
        'epin_transfer_status_options': reference_options.get('epin_transfer_status', []),
        'product_filter_options': reference_options.get('product_filter', []),
        'admin_wallet_totals': admin_wallet_totals,
        'hierarchy_tree': hierarchy_tree,
        'level_income_summary': level_income,
        'combined_level_income': combined_level_income,
        'product_income_totals': product_income_totals,
        'level_views': level_views,
        'admin_user_wallet_rows': admin_user_wallet_rows,
        'admin_user_level_rows': admin_user_level_rows,
        'selected_level_product': selected_level_product,
        'selected_level_product_label': to_level_product_label(selected_level_product),
        'level_product_filter_options': level_product_filter_options,
        'master_level_product_keys': master_level_product_keys,
        'level_plan_tables': level_plan_tables,
        'product_referral_counts': product_referral_counts,
        'product_usage_qualified_counts': product_usage_qualified_counts,
        'level_plans_by_product': level_plans_by_product,
        'user_level_product_keys': user_level_product_keys,
        'product_purchase_summary': product_purchase_summary,
        'pin_inventory': pin_inventory,
        'pin_usage': pin_usage,
        'pin_history_rows': pin_history_rows,
        'pin_transfer_history': pin_transfer_history,
        'transfer_candidates': transfer_candidates,
        'direct_members': direct_members,
        'all_users': all_users,
        'user_list': user_list,
        'available_cities': available_cities,
        'schema_data': schema_data,
        'show_ticket_popup': session.pop('new_ticket_no', None),
        'show_update_popup': session.pop('ticket_updated', None),
        'show_user_popup': session.pop('user_action_msg', None),
        'show_news_popup': session.pop('news_action_msg', None),
        'show_about_popup': session.pop('about_action_msg', None),
        'show_validation_popup': session.pop('validation_popup', None),
        'generated_password': session.pop('generated_password', None),
        'generated_password_user': session.pop('generated_password_user', None),
        'coupon_engine_admin_url': current_app.config.get('COUPON_ENGINE_ADMIN_URL', '/external-coupen-system/admin'),
        'coupon_engine_public_url': current_app.config.get('COUPON_ENGINE_PUBLIC_URL', '/external-coupen-system/coupon/entry'),
        'all_tickets': all_tickets,
        'support': my_tickets,
        'level_plans': level_plans,
        'product_types': product_types,
        'pin_types': pin_types,
        'current_user_product_display': format_user_product_display(getattr(current_user, 'product_type', None)) if current_user else 'Pad, Diaper',
        'user_roles': user_roles,
        'role_options': role_options,
        'pending_requests': pending_requests,
        'user_request_history': user_request_history,
        'user_request_usage_summary': user_request_usage_summary,
        'admin_approved_request_usage_summary': admin_approved_request_usage_summary,
        'admin_pending_usage_rows': admin_pending_usage_rows,
        'legal_documents': legal_documents,
        'can_request_subuser': can_request_subuser,
        'subuser_request_block_reason': subuser_request_block_reason,
        'available_subuser_pin_count': available_subuser_pin_count,
        'available_subuser_pins': available_subuser_pins,
        'dashboard_analytics': dashboard_analytics,
        'current_year': datetime.now().year
    }
    return context

# ----- Dashboard -----
@main.route('/home')
def home():
    if 'user_id' not in session:
        return redirect(url_for('main.login'))

    context = get_home_context()
    return render_template('pages/home.html', **context)

# ----- Account Settings -----
@main.route('/account-settings', methods=['GET', 'POST'])
def account_settings():
    if request.method == 'POST':
        flash("Account settings updated successfully", "success")
        return redirect_home_with_target() # Redirect back to the dashboard

    context = get_home_context()
    return render_template('pages/home.html', **context)

# ----- AJAX/Search Routes (Now redirecting to home with updated context) -----
@main.route('/iwallet/search', methods=['POST'])
def iwallet_search():
    flash("Wallet search filters applied", "info")
    return redirect_home_with_target()

@main.route('/wallet/withdraw-request', methods=['POST'])
def wallet_withdraw_request():
    if 'user_id' not in session:
        return redirect(url_for('main.login'))

    user_id = session['user_id']
    current_user = UserLogin.query.get(user_id)
    wallet_sum = db.session.query(func.sum(WalletTransaction.amount)).filter_by(user_id=user_id).scalar() or 0
    hierarchy_income_total = 0 if is_admin_user(current_user) else compute_hierarchy_income_totals(current_user).get('total', 0)
    actual_balance = max(wallet_sum, hierarchy_income_total)
    summary = compute_redeemable_balance(actual_balance)

    raw_amount = (request.form.get('withdraw_amount') or '').strip()
    try:
        requested_amount = round(float(raw_amount), 2)
    except (TypeError, ValueError):
        session['validation_popup'] = "Please enter a valid withdrawal amount."
        return redirect_home_with_target("#iwalletSection")

    if requested_amount < 1:
        session['validation_popup'] = "Withdrawal amount cannot be less than Rs. 1."
        return redirect_home_with_target("#iwalletSection")

    if requested_amount > summary['redeemable_balance']:
        session['validation_popup'] = "Withdrawal amount cannot be more than the redeemable balance."
        return redirect_home_with_target("#iwalletSection")

    gst_rate = summary['gst_rate']
    gst_amount = round(requested_amount * (gst_rate / 100), 2)
    net_amount = round(max(requested_amount - gst_amount, 0), 2)

    withdraw_request = WithdrawRequest(
        user_id=user_id,
        requested_amount=requested_amount,
        available_balance=summary['available_balance'],
        redeemable_balance=summary['redeemable_balance'],
        gst_rate=gst_rate,
        gst_amount=gst_amount,
        net_amount=net_amount,
        status='Pending',
        remarks=(request.form.get('remarks') or '').strip() or None
    )
    db.session.add(withdraw_request)
    db.session.commit()

    session['user_action_msg'] = "Withdraw request submitted successfully."
    return redirect_home_with_target("#iwalletSection")


@main.route('/wallet/withdraw-request/<int:req_id>/approve', methods=['POST'])
def wallet_withdraw_approve(req_id):
    current_user = get_session_user()
    if not is_admin_user(current_user):
        return redirect_home_with_target("#iwalletSection")

    withdraw_request = WithdrawRequest.query.get(req_id)
    if not withdraw_request or withdraw_request.status != 'Pending':
        session['validation_popup'] = "This withdrawal request is no longer pending."
        return redirect_home_with_target("#iwalletSection")

    withdraw_request.status = 'Approved'
    withdraw_request.remarks = (request.form.get('remarks') or '').strip() or withdraw_request.remarks
    db.session.add(withdraw_request)
    db.session.commit()
    session['user_action_msg'] = "Withdrawal request approved successfully."
    return redirect_home_with_target("#iwalletSection")


@main.route('/wallet/withdraw-request/<int:req_id>/reject', methods=['POST'])
def wallet_withdraw_reject(req_id):
    current_user = get_session_user()
    if not is_admin_user(current_user):
        return redirect_home_with_target("#iwalletSection")

    withdraw_request = WithdrawRequest.query.get(req_id)
    if not withdraw_request or withdraw_request.status != 'Pending':
        session['validation_popup'] = "This withdrawal request is no longer pending."
        return redirect_home_with_target("#iwalletSection")

    withdraw_request.status = 'Rejected'
    withdraw_request.remarks = (request.form.get('remarks') or '').strip() or withdraw_request.remarks
    db.session.add(withdraw_request)
    db.session.commit()
    session['user_action_msg'] = "Withdrawal request rejected."
    return redirect_home_with_target("#iwalletSection")

@main.route('/income/search', methods=['POST'])
def income_search():
    flash("Income records filtered", "info")
    return redirect_home_with_target()

@main.route('/epin/search', methods=['GET', 'POST'])
def epin_search():
    flash("E-pin search completed", "info")
    return redirect_home_with_target()

@main.route('/transactions/search', methods=['POST'])
def transactions_search():
    flash("Transaction reports updated", "info")
    return redirect_home_with_target()

# ----- Support Tickets -----
@main.route('/support/create', methods=['POST'])
def support_create():
    if 'user_id' not in session:
        return redirect(url_for('main.login'))
    
    query_type = request.form.get('query_type')
    description = request.form.get('description')
    
    # 200 word limit check
    if len(description.split()) > 200:
        flash("Description exceeds 200 words limit.", "danger")
        return redirect_home_with_target("#supportSection")

    # Unique Ticket Number Generation
    import random, string
    ticket_no = "TCK-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    # Handle File Uploads
    from werkzeug.utils import secure_filename
    import os
    
    upload_folder = 'Psparshcare/static/uploads/tickets'
    os.makedirs(upload_folder, exist_ok=True)
    
    attachment_paths = []
    files = request.files.getlist('attachments')
    for file in files:
        if file and file.filename:
            filename = secure_filename(f"{ticket_no}_{file.filename}")
            filepath = os.path.join(upload_folder, filename)
            file.save(filepath)
            # Store path relative to static/
            attachment_paths.append(filepath.replace('Psparshcare/static/', ''))

    from .models import SupportTicket, UserProfile
    profile = UserProfile.query.filter_by(user_id=session['user_id']).first()
    
    new_ticket = SupportTicket(
        ticket_no=ticket_no,
        user_id=session['user_id'],
        user_name=profile.name if profile else "Unknown",
        mobile=session['mobile'],
        query_type=query_type,
        description=description,
        attachments=','.join(attachment_paths),
        status='Open'
    )
    
    db.session.add(new_ticket)
    db.session.commit()
    
    session['new_ticket_no'] = ticket_no
    return redirect_home_with_target("#supportSection")

@main.route('/support/ticket/update', methods=['POST'])
def ticket_update():
    """Alias for support_status_update — called from the admin view ticket modal."""
    ticket_id = request.form.get('ticket_id')
    new_status = request.form.get('status')
    remarks = request.form.get('remarks')

    from .models import SupportTicket
    ticket = SupportTicket.query.get(ticket_id)
    if ticket:
        ticket.status = new_status
        ticket.admin_remarks = remarks
        db.session.commit()
        session['ticket_updated'] = ticket.ticket_no

    return redirect_home_with_target("#supportSection")

@main.route('/support/status-update', methods=['POST'])
def support_status_update():
    # Simplistic admin check
    ticket_id = request.form.get('ticket_id')
    new_status = request.form.get('status')
    remarks = request.form.get('remarks')
    
    from .models import SupportTicket
    ticket = SupportTicket.query.get(ticket_id)
    if ticket:
        ticket.status = new_status
        ticket.admin_remarks = remarks
        db.session.commit()
        session['ticket_updated'] = ticket.ticket_no
    
    return redirect_home_with_target("#supportSection")

# ----- News Management -----
@main.route('/admin/news/create', methods=['POST'])
def news_create():
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
    
    title = request.form.get('title')
    description = request.form.get('description')
    file = request.files.get('image')
    attachment = request.files.get('attachment')
    
    from werkzeug.utils import secure_filename
    import os
    
    img_path = None
    if file and file.filename:
        filename = secure_filename(f"news_{file.filename}")
        os.makedirs('Psparshcare/static/img/news', exist_ok=True)
        file.save(os.path.join('Psparshcare/static/img/news', filename))
        img_path = f"img/news/{filename}"
        
    attach_path = None
    if attachment and attachment.filename:
        filename = secure_filename(f"news_att_{attachment.filename}")
        os.makedirs('Psparshcare/static/uploads/news', exist_ok=True)
        attachment.save(os.path.join('Psparshcare/static/uploads/news', filename))
        attach_path = f"uploads/news/{filename}"

    from .models import News
    new_news = News(
        title=title,
        description=description,
        image_path=img_path,
        attachments=attach_path
    )
    db.session.add(new_news)
    db.session.commit()
    session['news_action_msg'] = "News created successfully."
    return redirect_home_with_target("#corporateCenterSection", "#collapseNews")

@main.route('/admin/news/update', methods=['POST'])
def news_update():
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
        
    news_id = request.form.get('news_id')
    title = request.form.get('title')
    description = request.form.get('description')
    
    from .models import News
    news = News.query.get(news_id)
    if news:
        news.title = title
        news.description = description
        
        # Optional image update
        file = request.files.get('image')
        if file and file.filename:
            from werkzeug.utils import secure_filename
            import os
            filename = secure_filename(f"news_{file.filename}")
            file.save(os.path.join('Psparshcare/static/img/news', filename))
            news.image_path = f"img/news/{filename}"
            
        db.session.commit()
        session['news_action_msg'] = "News updated successfully."
        
    return redirect_home_with_target("#corporateCenterSection", "#collapseNews")

@main.route('/admin/news/delete/<int:id>')
def news_delete(id):
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
        
    from .models import News
    news = News.query.get(id)
    if news:
        db.session.delete(news)
        db.session.commit()
        session['news_action_msg'] = "News deleted successfully."
        
    return redirect_home_with_target("#corporateCenterSection", "#collapseNews")


@main.route('/admin/legal-document/create', methods=['POST'])
def legal_document_create():
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()

    title = (request.form.get('title') or '').strip()
    description = (request.form.get('description') or '').strip()
    attachment = request.files.get('attachment')

    if not title:
        session['validation_popup'] = "Please enter the document name."
        return redirect_home_with_target("#corporateCenterSection", "#collapseLegal")

    if not attachment or not attachment.filename:
        session['validation_popup'] = "Please attach an image or PDF for the legal document."
        return redirect_home_with_target("#corporateCenterSection", "#collapseLegal")

    from werkzeug.utils import secure_filename
    ext = os.path.splitext(attachment.filename)[1].lower()
    allowed_map = {
        '.pdf': 'pdf',
        '.png': 'image',
        '.jpg': 'image',
        '.jpeg': 'image',
        '.webp': 'image'
    }
    file_type = allowed_map.get(ext)
    if not file_type:
        session['validation_popup'] = "Only PDF, PNG, JPG, JPEG, and WEBP files are allowed."
        return redirect_home_with_target("#corporateCenterSection", "#collapseLegal")

    upload_folder = 'Psparshcare/static/uploads/legal_documents'
    os.makedirs(upload_folder, exist_ok=True)
    filename = secure_filename(f"legal_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{attachment.filename}")
    attachment.save(os.path.join(upload_folder, filename))

    from .models import LegalDocument
    new_document = LegalDocument(
        title=title,
        description=description,
        file_path=f"uploads/legal_documents/{filename}",
        file_type=file_type
    )
    db.session.add(new_document)
    db.session.commit()
    session['news_action_msg'] = "Legal document uploaded successfully."
    return redirect_home_with_target("#corporateCenterSection", "#collapseLegal")

# ----- Carousel Management -----
@main.route('/admin/carousel/add', methods=['POST'])
def carousel_add():
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
        
    title = request.form.get('title')
    caption = request.form.get('caption')
    file = request.files.get('image')
    
    from werkzeug.utils import secure_filename
    import os
    
    img_path = None
    if file and file.filename:
        filename = secure_filename(f"carousel_{file.filename}")
        os.makedirs('Psparshcare/static/img/carousel', exist_ok=True)
        file.save(os.path.join('Psparshcare/static/img/carousel', filename))
        img_path = f"img/carousel/{filename}"
    
    from .models import CarouselImage
    new_slide = CarouselImage(
        title=title,
        caption=caption,
        image_path=img_path or 'img/carousal1.jpg' # Placeholder if none
    )
    db.session.add(new_slide)
    db.session.commit()
    session['carousel_action_msg'] = "Slide added to carousel."
    return redirect_home_with_target("#carouselMgmtSection")

@main.route('/admin/carousel/update', methods=['POST'])
def carousel_update():
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
        
    slide_id = request.form.get('slide_id')
    title = request.form.get('title')
    caption = request.form.get('caption')
    file = request.files.get('image')
    
    from .models import CarouselImage
    slide = CarouselImage.query.get(slide_id)
    if slide:
        slide.title = title
        slide.caption = caption
        
        if file and file.filename:
            from werkzeug.utils import secure_filename
            import os
            filename = secure_filename(f"carousel_{file.filename}")
            os.makedirs('Psparshcare/static/img/carousel', exist_ok=True)
            file.save(os.path.join('Psparshcare/static/img/carousel', filename))
            slide.image_path = f"img/carousel/{filename}"
            
        db.session.commit()
        session['carousel_action_msg'] = "Carousel slide updated."
        
    return redirect_home_with_target("#carouselMgmtSection")
@main.route('/admin/carousel/delete/<int:id>')
def carousel_delete(id):
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
        
    from .models import CarouselImage
    img = CarouselImage.query.get(id)
    if img:
        db.session.delete(img)
        db.session.commit()
        flash("Slide removed.", "info")
    return redirect_home_with_target("#carouselMgmtSection")

# ----- Support View -----
@main.route('/support/view/<int:ticket_id>')
def support_view(ticket_id):
    # Example: fetch ticket details from DB or dummy data
    ticket = {
        'id': ticket_id,
        'date': '2025-09-01',
        'subject': 'Sample Ticket',
        'status': 'Open',
        'details': 'Details of the support ticket here'
    }
    return render_template('pages/support_view.html', ticket=ticket)

@main.route('/schema/sync')
def schema_sync():
    try:
        from schema_manager import populate_schema_meta
        populate_schema_meta()
        flash("Database schema metadata synced successfully!", "success")
    except Exception as e:
        flash(f"Error syncing schema: {str(e)}", "danger")
    
    return redirect_home_with_target()

# ----- User Management -----
@main.route('/admin/user/check-mobile', methods=['POST'])
def user_check_mobile():
    if not is_admin_user(get_session_user()):
        return {'error': 'unauthorized'}, 403

    data = request.get_json(silent=True) or {}
    mobile = normalize_mobile(data.get('mobile'))
    if len(mobile) != 10:
        return {'exists': False, 'name': ''}

    user = find_user_by_mobile(mobile)
    return {'exists': bool(user), 'name': user.name if user else ''}

@main.route('/admin/user/create', methods=['POST'])
def user_create():
    if not is_admin_session():
        return redirect_home_with_target()

    current_user = get_session_user()
    if not current_user:
        session.clear()
        flash("Please sign in again to continue.", "warning")
        return redirect(url_for('main.login'))

    name = (request.form.get('name') or '').strip()
    mobile = normalize_mobile(request.form.get('mobile'))
    status = request.form.get('status', 'Active')

    user_type_raw = (request.form.get('type_of_user') or request.form.get('role') or '').strip()
    city = request.form.get('city')
    product_type = (request.form.get('product_type') or '').strip()
    pin_type = (request.form.get('pin_type') or '').strip()

    if not name:
        flash("Please enter the user's name.", "danger")
        return redirect_home_with_target("#userMgmtSection")

    if len(mobile) != 10:
        flash("Please enter a valid 10 digit mobile number.", "danger")
        return redirect_home_with_target("#userMgmtSection")

    if find_user_by_mobile(mobile):
        flash("User with this mobile number already exists.", "danger")
        return redirect_home_with_target("#userMgmtSection")

    if not user_type_raw:
        flash("Please select a user type.", "danger")
        return redirect_home_with_target("#userMgmtSection")

    if not product_type:
        flash("Please select a product type.", "danger")
        return redirect_home_with_target("#userMgmtSection")

    if not pin_type:
        flash("Please select a pin type.", "danger")
        return redirect_home_with_target("#userMgmtSection")

    user_type = normalize_user_type(user_type_raw)

    parent_id = current_user.id
    access_role = normalize_access_role(request.form.get('access_role') or 'user')
    if access_role == 'admin':
        parent_id = None

    new_user, plain_password = create_user_record(
        mobile=mobile,
        name=name,
        city=city,
        role=user_type,
        status=status,
        approval_status='Approved',
        parent_id=parent_id,
        product_type=product_type,
        pin_type=pin_type,
        email=request.form.get('email'),
        access_role=access_role
    )
    session['generated_password'] = plain_password
    session['generated_password_user'] = f"{name} ({mobile})"
    session['user_action_msg'] = f"User {name} ({mobile}) created successfully."
    send_user_credentials(name, mobile, plain_password, 'Administrator' if access_role == 'admin' else to_type_of_user(user_type), request.form.get('email'))
    return redirect_home_with_target("#userMgmtSection")


@main.route('/admin/request/<int:req_id>/approve', methods=['POST'])
def approve_user_request(req_id):
    if not is_admin_session():
        return redirect_home_with_target()

    from .models import EPin, EPinTransfer

    return_target = (request.form.get('target') or "#hierarchySection").strip() or "#hierarchySection"

    req = UserCreationRequest.query.get_or_404(req_id)
    if req.status != 'Pending':
        flash("This request has already been processed.", "warning")
        return redirect_home_with_target(return_target)

    existing = find_user_by_mobile(req.applicant_mobile)
    if existing:
        flash("A user with this mobile number already exists.", "danger")
        return redirect_home_with_target(return_target)

    user_type = normalize_user_type(request.form.get('type_of_user') or req.requested_role or 'member')
    requested_pin_count = max(req.requested_pin_count or 0, 0)
    pin_ids_to_transfer = []
    if requested_pin_count > 0:
        if req.selected_epin_id:
            selected_pin = EPin.query.filter_by(
                id=req.selected_epin_id,
                owner_id=req.requested_by_id,
                status='Unused'
            ).first()
            if not selected_pin:
                flash("The selected registration pin is no longer available to assign to the new user.", "warning")
                return redirect_home_with_target(return_target)
            pin_ids_to_transfer = [selected_pin.id]
        else:
            pins_to_transfer = EPin.query.filter_by(owner_id=req.requested_by_id, status='Unused').order_by(EPin.created_at.asc()).limit(requested_pin_count).all()
            if len(pins_to_transfer) < requested_pin_count:
                flash("This requester no longer has enough unused pins to assign to the new user.", "warning")
                return redirect_home_with_target(return_target)
            pin_ids_to_transfer = [pin.id for pin in pins_to_transfer]

    new_user, plain_password = create_user_record(
        mobile=req.applicant_mobile,
        name=req.applicant_name or f"User {req.applicant_mobile}",
        city=req.city,
        role=user_type,
        status='Active',
        parent_id=req.requested_by_id,
        pin_type=req.pin_type,
        email=req.applicant_email,
        access_role='user'
    )
    if pin_ids_to_transfer:
        pins_to_transfer = EPin.query.filter(EPin.id.in_(pin_ids_to_transfer)).all()
        for pin in pins_to_transfer:
            pin.owner_id = new_user.id
            db.session.add(EPinTransfer(
                epin_id=pin.id,
                from_user=req.requested_by_id,
                to_user=new_user.id,
                type='Sent'
            ))
    session['generated_password'] = plain_password
    session['generated_password_user'] = f"{new_user.name or req.applicant_name or 'User'} ({new_user.mobile})"
    session['user_action_msg'] = f"Request approved and user {new_user.mobile} created."
    req.status = 'Approved'
    req.assigned_role = user_type
    req.approved_by_id = session['user_id']
    req.approved_at = datetime.utcnow()
    req.updated_at = datetime.utcnow()
    approval_remarks = (request.form.get('remarks') or '').strip()
    if approval_remarks:
        req.notes = f"{req.notes or ''}\nApproved: {approval_remarks}".strip()
    db.session.add(req)
    db.session.commit()
    send_user_credentials(req.applicant_name, req.applicant_mobile, plain_password, to_type_of_user(user_type), req.applicant_email)
    return redirect_home_with_target(return_target)


@main.route('/admin/request/<int:req_id>/reject', methods=['POST'])
def reject_user_request(req_id):
    if not is_admin_session():
        return redirect_home_with_target()

    return_target = (request.form.get('target') or "#hierarchySection").strip() or "#hierarchySection"

    req = UserCreationRequest.query.get_or_404(req_id)
    if req.status != 'Pending':
        flash("This request has already been processed.", "warning")
        return redirect_home_with_target(return_target)

    req.status = 'Rejected'
    req.approved_by_id = session['user_id']
    req.approved_at = datetime.utcnow()
    rejection_reason = (request.form.get('remarks') or '').strip()
    req.notes = f"{req.notes or ''}\nRejected: {rejection_reason or 'No reason provided.'}"
    db.session.add(req)
    db.session.commit()
    subject = "Your SparshCare account request was rejected"
    body = (
        f"Hello {req.applicant_name or 'applicant'},\n\n"
        "Your account creation request was rejected by the admin. "
        f"{rejection_reason or 'Contact support for more details.'}\n\n"
        "Regards,\n"
        "Prakrutik SparshCare Team"
    )
    send_email_message(subject, body, req.applicant_email or EMAIL_NOTIFY)
    flash("Request rejected.", "info")
    return redirect_home_with_target(return_target)

@main.route('/admin/user/update', methods=['POST'])
def user_update():
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
    user_id = request.form.get('user_id')
    name = request.form.get('name')
    mobile = request.form.get('mobile')
    password = request.form.get('password')
    status = request.form.get('status')
    access_role = normalize_access_role(request.form.get('role'))
    user_type = normalize_user_type(request.form.get('type_of_user') or request.form.get('role') or 'member')
    city = request.form.get('city')
    product_type = request.form.get('product_type')
    pin_type = request.form.get('pin_type')
    approval_status = request.form.get('approval_status')
    level_raw = request.form.get('level')
    
    user = UserLogin.query.get(user_id)
    if user:
        user.name = name
        user.mobile = mobile
        user.status = status
        assign_user_classification(user, access_role=access_role, user_type=user_type)
        user.city = city
        user.product_type = product_type
        user.pin_type = pin_type
        try:
            user.level = int(level_raw) if level_raw is not None and str(level_raw).strip() != "" else 1
        except ValueError:
            user.level = 1
        if user.level < 1:
            user.level = 1
        if approval_status:
            user.approval_status = approval_status
            
        if password:
            user.password = generate_password_hash(password)
            
        # Update profile name too
        from .models import UserProfile
        profile = UserProfile.query.filter_by(user_id=user_id).first()
        if profile:
            profile.name = name
            profile.mobile = mobile
            
        db.session.commit()
        session['user_action_msg'] = f"User {name} updated successfully."
        
    return redirect_home_with_target("#userMgmtSection")

@main.route('/admin/user/delete/<int:id>')
def user_delete(id):
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
    
    user = UserLogin.query.get_or_404(id)
    if is_admin_user(user):
        session['validation_popup'] = "Admin user cannot be deleted."
        return redirect_home_with_target("#userMgmtSection")

    name = user.name
    parent_user_id = user.parent_user_id
    reassigned_children_count = user.children.count()

    from .models import (
        UserProfile, AccountSettings, SupportTicket, WalletTransaction,
        PinUsageReport, EPinTransfer, WithdrawRequest
    )

    # Keep the hierarchy connected by reassigning this user's direct children to this user's parent.
    UserLogin.query.filter_by(parent_user_id=id).update(
        {UserLogin.parent_user_id: parent_user_id},
        synchronize_session=False
    )

    # Remove request rows where this user is requester or approver.
    UserCreationRequest.query.filter(
        (UserCreationRequest.requested_by_id == id) | (UserCreationRequest.approved_by_id == id)
    ).delete(synchronize_session=False)

    # Delete dependent records tied to this user.
    UserProfile.query.filter_by(user_id=id).delete(synchronize_session=False)
    AccountSettings.query.filter_by(user_id=id).delete(synchronize_session=False)
    SupportTicket.query.filter_by(user_id=id).delete(synchronize_session=False)
    WalletTransaction.query.filter_by(user_id=id).delete(synchronize_session=False)
    WithdrawRequest.query.filter_by(user_id=id).delete(synchronize_session=False)

    # Delete pin usage/transfer history before deleting the owned pins.
    PinUsageReport.query.filter_by(user_id=id).delete(synchronize_session=False)
    owned_pin_ids = [row[0] for row in db.session.query(EPin.id).filter_by(owner_id=id).all()]
    if owned_pin_ids:
        # Some user creation requests (raised by other users) can reference pins owned by this user.
        # Null out the FK so we can safely delete those pins without breaking integrity.
        UserCreationRequest.query.filter(
            UserCreationRequest.selected_epin_id.in_(owned_pin_ids)
        ).update(
            {UserCreationRequest.selected_epin_id: None},
            synchronize_session=False
        )
        PinUsageReport.query.filter(PinUsageReport.pin_id.in_(owned_pin_ids)).delete(synchronize_session=False)
        EPinTransfer.query.filter(EPinTransfer.epin_id.in_(owned_pin_ids)).delete(synchronize_session=False)
    EPinTransfer.query.filter(
        (EPinTransfer.from_user == id) | (EPinTransfer.to_user == id)
    ).delete(synchronize_session=False)
    EPin.query.filter_by(owner_id=id).delete(synchronize_session=False)

    db.session.delete(user)
    db.session.commit()

    if reassigned_children_count > 0:
        session['user_action_msg'] = f"User {name} deleted successfully. {reassigned_children_count} direct downline user(s) were reassigned to the parent hierarchy."
    else:
        session['user_action_msg'] = f"User {name} deleted successfully."
    return redirect_home_with_target("#userMgmtSection")


@main.route('/admin/user/disable/<int:id>', methods=['POST'])
def user_disable(id):
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()

    user = UserLogin.query.get_or_404(id)
    if is_admin_user(user):
        session['validation_popup'] = "Admin user cannot be disabled."
        return redirect_home_with_target("#userMgmtSection")

    user.status = 'Inactive'
    db.session.commit()
    session['user_action_msg'] = f"User {user.name} disabled successfully. You can re-enable them later from Edit User."
    return redirect_home_with_target("#userMgmtSection")


@main.route('/admin/pin/assign', methods=['POST'])
def admin_pin_assign():
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()

    mobile = normalize_mobile(request.form.get('recipient_mobile'))
    quantity = int(request.form.get('quantity') or 1)
    pin_type_name = request.form.get('pin_type')
    product_type_name = request.form.get('product_type')

    if quantity <= 0:
        session['validation_popup'] = "Please specify a positive quantity."
        return redirect_home_with_target("#epinSection")

    if quantity > 25:
        quantity = 25

    if len(mobile) != 10:
        session['validation_popup'] = "Enter a valid 10-digit recipient number."
        return redirect_home_with_target("#epinSection")

    recipient = find_user_by_mobile(mobile)
    if not recipient:
        session['validation_popup'] = "Recipient not found."
        return redirect_home_with_target("#epinSection")
    if recipient.id == session.get('user_id'):
        session['validation_popup'] = "Please choose another user to assign pins."
        return redirect_home_with_target("#epinSection")

    from .models import PinType, ProductType, EPin, EPinTransfer

    pin_type = PinType.query.filter_by(name=pin_type_name).first()
    product_type = ProductType.query.filter_by(name=product_type_name).first()

    created_codes = []
    for _ in range(quantity):
        code = generate_epin_code()
        pin = EPin(
            code=code,
            owner_id=recipient.id,
            status='Unused',
            pin_type_id=pin_type.id if pin_type else None,
            product_type_id=product_type.id if product_type else None
        )
        db.session.add(pin)
        db.session.flush()
        transfer = EPinTransfer(
            epin_id=pin.id,
            from_user=session['user_id'],
            to_user=recipient.id,
            type='Sent'
        )
        db.session.add(transfer)
        created_codes.append(code)

    db.session.commit()
    session['user_action_msg'] = f"Assigned {len(created_codes)} pin(s) to {recipient.name or recipient.mobile}."
    return redirect_home_with_target("#epinSection")


@main.route('/pin/transfer', methods=['POST'])
def pin_transfer():
    if 'user_id' not in session:
        return redirect(url_for('main.login'))

    from_user_id = session['user_id']
    current_user = get_session_user()
    if not current_user:
        session.clear()
        flash("Please sign in again to continue.", "warning")
        return redirect(url_for('main.login'))

    mobile = normalize_mobile(request.form.get('recipient_mobile'))
    quantity = int(request.form.get('transfer_quantity') or 1)
    selected_pin_id = request.form.get('pin_id')

    if len(mobile) != 10:
        session['validation_popup'] = "Please enter a valid mobile number."
        return redirect_home_with_target("#epinSection")

    recipient = find_user_by_mobile(mobile)
    if not recipient:
        session['validation_popup'] = "Recipient not found."
        return redirect_home_with_target("#epinSection")

    if recipient.id == from_user_id:
        session['validation_popup'] = "You cannot transfer pins to yourself."
        return redirect_home_with_target("#epinSection")

    if effective_access_role(current_user) != 'admin':
        downline_ids = get_downline_user_ids(current_user)
        if recipient.id not in downline_ids:
            session['validation_popup'] = "You can only transfer pins to users connected below you in your hierarchy."
            return redirect_home_with_target("#epinSection")

    if quantity <= 0:
        session['validation_popup'] = "Quantity must be at least one."
        return redirect_home_with_target("#epinSection")

    from .models import EPin, EPinTransfer

    if selected_pin_id:
        selected_pin = EPin.query.filter_by(id=selected_pin_id, owner_id=from_user_id, status='Unused').first()
        if not selected_pin:
            session['validation_popup'] = "Selected pin is no longer available for transfer."
            return redirect_home_with_target("#epinSection")
        available_pins = [selected_pin]
        quantity = 1
    else:
        available_pins = EPin.query.filter_by(owner_id=from_user_id, status='Unused').order_by(EPin.created_at).limit(quantity).all()
    if len(available_pins) < quantity:
        session['validation_popup'] = "You do not have enough unused pins to transfer."
        return redirect_home_with_target("#epinSection")

    for pin in available_pins:
        pin.owner_id = recipient.id
        transfer = EPinTransfer(
            epin_id=pin.id,
            from_user=from_user_id,
            to_user=recipient.id,
            type='Sent'
        )
        db.session.add(transfer)

    db.session.commit()
    session['user_action_msg'] = f"Transferred {quantity} pin(s) to {recipient.name or recipient.mobile}."
    return redirect_home_with_target("#epinSection")


@main.route('/pin/report', methods=['POST'])
def pin_report():
    if 'user_id' not in session:
        return redirect(url_for('main.login'))

    user_id = session['user_id']
    pin_id = request.form.get('pin_id')
    buyer_name = (request.form.get('buyer_name') or '').strip()
    buyer_mobile = normalize_mobile(request.form.get('buyer_mobile'))
    city = (request.form.get('city') or '').strip()
    notes = request.form.get('notes')

    if not pin_id:
        flash("Please select a pin to report.", "warning")
        return redirect_home_with_target("#epinSection")

    from .models import EPin, PinUsageReport

    pin = EPin.query.filter_by(id=pin_id, owner_id=user_id).first()
    if not pin:
        flash("Pin not found or is not assigned to you.", "danger")
        return redirect_home_with_target("#epinSection")

    if pin.status != 'Unused':
        flash("This pin has already been saved in pin history.", "warning")
        return redirect_home_with_target("#epinSection")

    if not buyer_name:
        flash("Buyer name is required for each pin history entry.", "warning")
        return redirect_home_with_target("#epinSection")

    if len(buyer_mobile) != 10:
        flash("Please enter a valid 10-digit buyer mobile number.", "warning")
        return redirect_home_with_target("#epinSection")

    pin.status = 'Used'
    report = PinUsageReport(
        pin_id=pin.id,
        user_id=user_id,
        buyer_name=buyer_name,
        buyer_mobile=buyer_mobile,
        city=city or None,
        notes=notes
    )
    db.session.add(pin)
    db.session.add(report)
    pin_type_name = (getattr(getattr(pin, 'pin_type', None), 'name', '') or '').strip().lower()
    if pin_type_name != 'trial pin':
        product_key = normalize_level_product(getattr(getattr(pin, 'product_type', None), 'name', None), 'pad')
        apply_pin_sale_progress(UserLogin.query.get(user_id), product_key=product_key)
    db.session.commit()
    if pin_type_name == 'trial pin':
        flash("Trial pin history recorded. No level progress was applied.", "success")
    else:
        flash("Pin history recorded and level progress updated.", "success")
    return redirect_home_with_target("#epinSection")


@main.route('/pin/transfer/<int:transfer_id>/disable', methods=['POST'])
def pin_transfer_disable(transfer_id):
    current_user = get_session_user()
    if not is_admin_user(current_user):
        return redirect_home_with_target("#epinSection")

    from .models import EPinTransfer, EPin

    transfer = EPinTransfer.query.get(transfer_id)
    if not transfer:
        session['validation_popup'] = "Pin transfer record not found."
        return redirect_home_with_target("#epinSection")

    if (transfer.status or 'Active') != 'Active':
        session['validation_popup'] = "This pin transfer is already disabled."
        return redirect_home_with_target("#epinSection")

    pin = EPin.query.get(transfer.epin_id)
    if not pin:
        session['validation_popup'] = "The linked pin record was not found."
        return redirect_home_with_target("#epinSection")

    if pin.status != 'Unused':
        session['validation_popup'] = "Only unused transferred pins can be disabled."
        return redirect_home_with_target("#epinSection")

    if pin.owner_id != transfer.to_user:
        session['validation_popup'] = "This transfer can no longer be disabled because the pin has already moved again."
        return redirect_home_with_target("#epinSection")

    pin.owner_id = transfer.from_user
    transfer.status = 'Disabled'
    transfer.disabled_at = datetime.utcnow()
    transfer.disabled_reason = (request.form.get('remarks') or '').strip() or 'Disabled by admin'
    db.session.add(pin)
    db.session.add(transfer)
    db.session.commit()

    session['user_action_msg'] = "Pin transfer disabled and pin returned successfully."
    return redirect_home_with_target("#epinSection")

@main.route('/admin/level-plan/update', methods=['POST'])
def level_plan_update():
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()

    level_plan_id_raw = (request.form.get('level_plan_id') or '').strip()
    level_product = normalize_level_product(request.form.get('level_product'), 'pad')
    try:
        level_plan_id = int(level_plan_id_raw)
    except (TypeError, ValueError):
        level_plan_id = None

    if not level_plan_id:
        flash("Please select a valid level to update.", "warning")
        return redirect_home_with_target("#levelMgmtSection")

    from .models import LevelPlan
    selected_product_label = to_level_product_label(level_product)
    plan = LevelPlan.query.filter_by(id=level_plan_id, product_type=selected_product_label).first()
    if not plan:
        # Fallback for legacy records with inconsistent casing.
        plan = LevelPlan.query.filter(
            LevelPlan.id == level_plan_id,
            func.lower(LevelPlan.product_type) == level_product
        ).first()
    if not plan:
        flash("Level configuration not found for selected product.", "danger")
        return redirect_home_with_target("#levelMgmtSection")

    def parse_positive_int(value, default=0):
        try:
            parsed = int(value)
            return parsed if parsed >= 0 else default
        except (TypeError, ValueError):
            return default

    plan.number_of_id = parse_positive_int(request.form.get('number_of_id'), plan.number_of_id or 0)
    plan.income_per_id = parse_positive_int(request.form.get('income_per_id'), plan.income_per_id or 0)
    plan.reward_per_id = parse_positive_int(request.form.get('reward_per_id'), plan.reward_per_id or 0)

    db.session.commit()
    resolved_product_key = normalize_level_product(plan.product_type, level_product)
    flash(f"{plan.product_type} level {plan.level_no} updated.", "success")
    return redirect(url_for('main.home', target='levelMgmtSection', level_product=resolved_product_key))

# ----- About Us & Events Management -----
@main.route('/admin/event/create', methods=['POST'])
def event_create():
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
        
    title = request.form.get('title')
    description = request.form.get('description')
    event_date_str = request.form.get('event_date')
    files = request.files.getlist('images')
    
    from datetime import datetime
    event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date() if event_date_str else datetime.utcnow().date()
    
    from .models import Event, EventImage
    new_event = Event(title=title, description=description, event_date=event_date)
    db.session.add(new_event)
    db.session.flush() # Get ID before commit
    
    import os
    from werkzeug.utils import secure_filename
    os.makedirs('Psparshcare/static/uploads/events', exist_ok=True)
    
    for file in files:
        if file and file.filename:
            filename = secure_filename(f"ev_{new_event.id}_{file.filename}")
            file.save(os.path.join('Psparshcare/static/uploads/events', filename))
            img = EventImage(event_id=new_event.id, image_path=f"uploads/events/{filename}")
            db.session.add(img)
            
    db.session.commit()
    session['about_action_msg'] = "Event added successfully."
    return redirect_home_with_target("#corporateCenterSection", "#collapseEvents")

@main.route('/admin/event/update', methods=['POST'])
def event_update():
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
        
    event_id = request.form.get('event_id')
    title = request.form.get('title')
    description = request.form.get('description')
    event_date_str = request.form.get('event_date')
    files = request.files.getlist('images')
    
    from .models import Event, EventImage
    event = Event.query.get(event_id)
    if event:
        event.title = title
        event.description = description
        if event_date_str:
            from datetime import datetime
            event.event_date = datetime.strptime(event_date_str, '%Y-%m-%d').date()
            
        if files:
            import os
            from werkzeug.utils import secure_filename
            os.makedirs('Psparshcare/static/uploads/events', exist_ok=True)
            for file in files:
                if file and file.filename:
                    filename = secure_filename(f"ev_{event.id}_{file.filename}")
                    file.save(os.path.join('Psparshcare/static/uploads/events', filename))
                    img = EventImage(event_id=event.id, image_path=f"uploads/events/{filename}")
                    db.session.add(img)
                    
        db.session.commit()
        session['about_action_msg'] = "Event updated successfully."
        
    return redirect_home_with_target("#corporateCenterSection", "#collapseEvents")

@main.route('/admin/event/delete/<int:id>')
def event_delete(id):
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
        
    from .models import Event, EventImage
    event = Event.query.get(id)
    if event:
        # Delete related images from DB (and ideally disk too)
        images = EventImage.query.filter_by(event_id=id).all()
        for img in images:
            db.session.delete(img)
        db.session.delete(event)
        db.session.commit()
        session['about_action_msg'] = "Event removed."
        
    return redirect_home_with_target("#corporateCenterSection", "#collapseEvents")

@main.route('/profile/update', methods=['POST'])
def user_profile_update():
    if 'user_id' not in session:
        return redirect(url_for('main.login'))
        
    user_id = session['user_id']
    from .models import UserProfile
    profile = UserProfile.query.filter_by(user_id=user_id).first()
    current_user = UserLogin.query.get(user_id)
    if not profile:
        profile = UserProfile(user_id=user_id)
        db.session.add(profile)
    
    profile.name = request.form.get('name')
    profile.email = request.form.get('email')
    profile.city = request.form.get('city')
    profile.address = request.form.get('address')
    if not profile.mobile:
        profile.mobile = current_user.mobile if current_user else None

    # Optional profile photo upload (stored on user_login.image_path)
    try:
        file = request.files.get('profile_photo')
        if file and file.filename and current_user:
            import os
            from datetime import datetime
            from werkzeug.utils import secure_filename

            filename_raw = secure_filename(file.filename)
            _, ext = os.path.splitext(filename_raw)
            ext = (ext or '').lower()
            allowed_ext = {'.jpg', '.jpeg', '.png', '.webp'}
            if ext not in allowed_ext:
                session['validation_popup'] = "Profile photo must be JPG, PNG, or WebP."
                return redirect_home_with_target("#profileSection")

            upload_dir = os.path.join('Psparshcare', 'static', 'uploads', 'profile_photos')
            os.makedirs(upload_dir, exist_ok=True)
            stamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            filename = f"user_{user_id}_{stamp}{ext}"
            abs_path = os.path.join(upload_dir, filename)
            file.save(abs_path)
            current_user.image_path = f"uploads/profile_photos/{filename}"
            db.session.add(current_user)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Profile photo upload failed.")
     
    db.session.commit()
    session['user_name'] = profile.name # Update session cache
    session['user_action_msg'] = "Profile updated successfully."
     
    return redirect_home_with_target("#profileSection")

@main.route('/bank/update', methods=['POST'])
def bank_update():
    if 'user_id' not in session:
        return redirect(url_for('main.login'))

    from .models import AccountSettings

    user_id = session['user_id']
    bank = AccountSettings.query.filter_by(user_id=user_id).first()
    if not bank:
        bank = AccountSettings(user_id=user_id)
        db.session.add(bank)

    bank.bank_name = (request.form.get('bank_name') or '').strip()
    bank.branch = (request.form.get('branch') or '').strip()
    bank.ifsc = (request.form.get('ifsc') or '').strip().upper()
    bank.acc_no = (request.form.get('acc_no') or '').strip()
    bank.acc_holder = (request.form.get('acc_holder') or '').strip()

    db.session.commit()
    session['user_action_msg'] = "Bank details updated successfully."
    return redirect_home_with_target("#accountSettingsSection")

@main.route('/admin/company/update', methods=['POST'])
def profile_update():
    """Handles company profile updates (About, Vision, etc.) by Admin."""
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
        
    from .models import CompanyProfile
    profile = CompanyProfile.query.first()
    if not profile:
        profile = CompanyProfile()
        db.session.add(profile)
        
    if request.form.get('about_us'): profile.about_us = request.form.get('about_us')
    if request.form.get('vision'): profile.vision = request.form.get('vision')
    if request.form.get('mission'): profile.mission = request.form.get('mission')
    if request.form.get('address'): profile.address = request.form.get('address')
    if request.form.get('email'): profile.email = request.form.get('email')
    if request.form.get('phone'): profile.phone = request.form.get('phone')
    if request.form.get('map_url'): profile.map_url = request.form.get('map_url')
    
    db.session.commit()
    session['about_action_msg'] = "Company information updated."
    return redirect_home_with_target("#corporateCenterSection")

@main.route('/admin/quick-link/add', methods=['POST'])
def quick_link_add():
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
        
    title = request.form.get('title')
    url = request.form.get('url')
    order = request.form.get('order', 0)
    
    from .models import QuickLink
    new_link = QuickLink(title=title, url=url, order=order)
    db.session.add(new_link)
    db.session.commit()
    session['about_action_msg'] = "Quick link added."
    return redirect_home_with_target("#corporateCenterSection", "#collapseContact")

@main.route('/admin/quick-link/delete/<int:id>')
def quick_link_delete(id):
    if not is_admin_user(get_session_user()):
        return redirect_home_with_target()
        
    from .models import QuickLink
    link = QuickLink.query.get(id)
    if link:
        db.session.delete(link)
        db.session.commit()
        session['about_action_msg'] = "Quick link removed."
        
    return redirect_home_with_target("#corporateCenterSection", "#collapseContact")


# ----- Coupon Management -----
# ----- Logout -----
@main.route('/logout')
def logout():
    session.clear()
    flash("Logged out successfully", "info")
    return redirect(url_for('main.login'))
