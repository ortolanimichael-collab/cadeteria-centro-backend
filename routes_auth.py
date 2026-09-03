import os
import secrets

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from models import db, Business, Client, Admin
from webhooks import notify_panel_new_business, notify_panel_admin_checkin
from mailer import send_email

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

RESET_TOKEN_MAX_AGE = 60 * 60  # 1 hora


def _valid_email(email):
    return bool(email) and '@' in email and '.' in email.split('@')[-1]


def _reset_serializer():
    return URLSafeTimedSerializer(current_app.config['JWT_SECRET_KEY'], salt='password-reset')


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


@auth_bp.route('/google', methods=['POST'])
def google_auth():
    """Login (o registro automático, si es la primera vez) de un cliente
    usando su cuenta de Google. El frontend manda el 'credential' que le da
    Google Identity Services; acá lo verificamos contra los servidores de
    Google antes de confiar en el email que dice traer."""
    data = request.get_json(silent=True) or {}
    credential = data.get('credential')
    if not credential:
        return jsonify({'error': 'Falta el token de Google.'}), 400

    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    if not client_id:
        return jsonify({'error': 'El login con Google no está configurado en el servidor.'}), 500

    try:
        idinfo = google_id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)
    except Exception:
        return jsonify({'error': 'No pudimos verificar tu cuenta de Google. Probá de nuevo en un momento.'}), 401

    if not idinfo.get('email_verified', False):
        return jsonify({'error': 'Tu email de Google no está verificado.'}), 401

    email = (idinfo.get('email') or '').strip().lower()
    name = idinfo.get('name') or email.split('@')[0]
    google_sub = idinfo.get('sub')

    if Business.query.filter_by(email=email).first():
        return jsonify({'error': 'Ese email ya está registrado como negocio. Iniciá sesión con tu contraseña.'}), 409

    client = Client.query.filter_by(email=email).first()
    if not client:
        client = Client(name=name, email=email, google_id=google_sub)
        client.set_password(secrets.token_urlsafe(32))  # nadie va a usar esta clave, es solo para cumplir el campo
        db.session.add(client)
        db.session.commit()
    elif not client.google_id:
        client.google_id = google_sub
        db.session.commit()

    token = create_access_token(identity=client.id, additional_claims={'type': 'client'})
    return jsonify({'token': token, 'type': 'client', 'client': client.to_dict()})


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'Completá el email y la contraseña.'}), 400

    admin = Admin.query.filter_by(email=email).first()
    if admin and admin.check_password(password):
        if not admin.activo:
            return jsonify({'error': 'Tu acceso de administrador está desactivado. Contactá a soporte para reactivarlo.'}), 403
        notify_panel_admin_checkin(admin)
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


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    """Pide el email y, si existe una cuenta (negocio o cliente), le manda un
    link para elegir una contraseña nueva. Responde siempre con el mismo
    mensaje genérico, exista o no la cuenta — así nadie puede usar este
    endpoint para averiguar qué emails están registrados."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()

    generic_response = jsonify({
        'ok': True,
        'message': 'Si existe una cuenta con ese email, te mandamos un link para restablecer la contraseña.'
    })

    if not _valid_email(email):
        return generic_response

    account = Business.query.filter_by(email=email).first()
    account_type = 'business'
    if not account:
        account = Client.query.filter_by(email=email).first()
        account_type = 'client'

    if account:
        token = _reset_serializer().dumps({'email': email, 'type': account_type})
        frontend_url = os.environ.get('FRONTEND_URL', '').rstrip('/')
        reset_link = f'{frontend_url}/#/restablecer?token={token}'
        html = f"""
            <p>Hola {account.name},</p>
            <p>Pediste restablecer tu contraseña en Cadetería Centro.
               Hacé clic en el siguiente link para elegir una nueva
               (vence en 1 hora):</p>
            <p><a href="{reset_link}">Restablecer mi contraseña</a></p>
            <p>Si no fuiste vos quien lo pidió, podés ignorar este mensaje
               tranquilo — tu contraseña actual sigue siendo válida.</p>
        """
        send_email(email, 'Restablecer tu contraseña — Cadetería Centro', html)

    return generic_response


@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json(silent=True) or {}
    token = data.get('token') or ''
    password = data.get('password') or ''
    password2 = data.get('password2') or ''

    if not token:
        return jsonify({'error': 'Falta el token.'}), 400
    if password != password2:
        return jsonify({'error': 'Las contraseñas no coinciden.'}), 400
    if len(password) < 6:
        return jsonify({'error': 'La contraseña tiene que tener al menos 6 caracteres.'}), 400

    try:
        payload = _reset_serializer().loads(token, max_age=RESET_TOKEN_MAX_AGE)
    except SignatureExpired:
        return jsonify({'error': 'Este link venció. Pedí uno nuevo.'}), 400
    except BadSignature:
        return jsonify({'error': 'Este link no es válido.'}), 400

    email = payload.get('email')
    account_type = payload.get('type')

    if account_type == 'business':
        account = Business.query.filter_by(email=email).first()
    else:
        account = Client.query.filter_by(email=email).first()

    if not account:
        return jsonify({'error': 'No encontramos esa cuenta.'}), 404

    account.set_password(password)
    db.session.commit()
    return jsonify({'ok': True})
