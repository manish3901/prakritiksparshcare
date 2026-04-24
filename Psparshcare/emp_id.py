from .models import UserLogin

START_EMP_ID = 10001
EMP_ID_WIDTH = 5


def _parse_emp_value(emp_value):
    try:
        return int(emp_value)
    except (TypeError, ValueError):
        return None


def _highest_assigned_emp():
    numeric_ids = [
        _parse_emp_value(user.emp_id)
        for user in UserLogin.query.filter(UserLogin.emp_id.isnot(None)).all()
        if _parse_emp_value(user.emp_id) is not None
    ]
    return max(numeric_ids) if numeric_ids else None


def generate_next_emp_id():
    current_max = _highest_assigned_emp()
    next_value = current_max + 1 if current_max is not None else START_EMP_ID
    return str(next_value).zfill(EMP_ID_WIDTH)


def sync_emp_ids():
    """Ensure every user has a sequential five-digit emp_id."""
    missing = UserLogin.query.filter(
        (UserLogin.emp_id.is_(None)) | (UserLogin.emp_id == "")
    ).order_by(UserLogin.id).all()
    if not missing:
        return

    next_value = int(generate_next_emp_id())
    for user in missing:
        user.emp_id = str(next_value).zfill(EMP_ID_WIDTH)
        next_value += 1
        from . import db
        db.session.add(user)
    from . import db
    db.session.commit()
