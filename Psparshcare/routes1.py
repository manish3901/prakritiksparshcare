from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import check_password_hash
from .models import db, UserLogin

main = Blueprint('main', __name__)

@main.route('/')
def login_page():
    return render_template('pages/login.html')

@main.route('/login', methods=['POST'])
def login():
    mobile = request.form.get('mobile')
    password = request.form.get('password')

    user = UserLogin.query.filter_by(mobile=mobile).first()

    if user and user.password == password:
        return redirect(url_for('main.home'))  # Replace with session logic later
    else:
        flash('Invalid credentials. Please try again.', 'danger')
        return redirect(url_for('main.login_page'))

@main.route('/home')
def home():
    return render_template('pages/home.html')
