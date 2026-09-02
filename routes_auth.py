from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token

from models import db, Business, Client, Admin
from webhooks import notify_panel_new_business

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def _valid_email(email):
    return bool(email) and '@' in email and '.' in email.split('@')[-1]


@auth_bp.route('/register/business', methods=['POST'])
def register_business():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    category = (data.get('category') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    password2 = data.get('password2') or ''

    if not all([name, category, email, password, password2]):
        return jsonify({'error': 'Completá todos los campos.'}), 400
    if not _valid_email(email):
        return jsonify({'error': 'El email no es válido.'}), 400
    if password != password2:
        return jsonify({'error': 'Las contraseñas no coinciden.'}), 400
    if len(password) < 6:
        return jsonify({'error': 'La contraseña tiene que tener al menos 6 caracteres.'}), 400

    if Business.query.filter_by(email=email).first() or Client.query.filter_by(email=email).first():
        return jsonify({'error': 'Ya existe una cuenta con ese email.'}), 409

    business = Business(name=name, category=category, email=email)
    business.set_password(password)
    db.session.add(business)
    db.session.commit()

    notify_panel_new_business(business)

    token = create_access_token(identity=business.id, additional_claims={'type': 'business'})
    return jsonify({'token': token, 'business': business.to_owner_dict()}), 201


@auth_bp.route('/register/client', methods=['POST'])
def register_client():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    password2 = data.get('password2') or ''

    if not all([name, email, password, password2]):
        return jsonify({'error': 'Completá todos los campos.'}), 400
    if not _valid_email(email):
        return jsonify({'error': 'El email no es válido.'}), 400
    if password != password2:
        return jsonify({'error': 'Las contraseñas no coinciden.'}), 400
    if len(password) < 6:
        return jsonify({'error': 'La contraseña tiene que tener al menos 6 caracteres.'}), 400

    if Client.query.filter_by(email=email).first() or Business.query.filter_by(email=email).first():
        return jsonify({'error': 'Ya existe una cuenta con ese email.'}), 409

    client = Client(name=name, email=email)
    client.set_password(password)
    db.session.add(client)
    db.session.commit()

    token = create_access_token(identity=client.id, additional_claims={'type': 'client'})
    return jsonify({'token': token, 'client': client.to_dict()}), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'Completá el email y la contraseña.'}), 400

    admin = Admin.query.filter_by(email=email).first()
    if admin and admin.check_password(password):
        token = create_access_token(identity=admin.id, additional_claims={'type': 'admin'})
        return jsonify({'token': token, 'type': 'admin', 'name': admin.name})

    business = Business.query.filter_by(email=email).first()
    if business and business.check_password(password):
        token = create_access_token(identity=business.id, additional_claims={'type': 'business'})
        return jsonify({
            'token': token, 'type': 'business', 'business': business.to_owner_dict(),
            'membershipWarning': None if business.is_access_allowed else (
                'Tu membresía no está activa. Podés iniciar sesión pero no vas a poder '
                'editar tu negocio hasta que se regularice.'
            ),
        })

    client = Client.query.filter_by(email=email).first()
    if client and client.check_password(password):
        token = create_access_token(identity=client.id, additional_claims={'type': 'client'})
        return jsonify({'token': token, 'type': 'client', 'client': client.to_dict()})

    return jsonify({'error': 'Email o contraseña incorrectos.'}), 401
