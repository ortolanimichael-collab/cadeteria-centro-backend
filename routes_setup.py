import os

from flask import Blueprint, request, jsonify

from models import db, Admin

setup_bp = Blueprint('setup', __name__, url_prefix='/api/setup')


@setup_bp.route('/create-admin', methods=['POST'])
def create_admin():
    """Crea el primer (y único) admin, sin necesitar acceso a una consola.

    Protegido por dos capas:
    1. Un secreto que solo vos conocés (SETUP_SECRET), mandado en el header X-Setup-Secret.
    2. Se niega a funcionar si YA existe un admin — así que una vez usado, queda inutilizado
       para siempre (no sirve para crear admins extra ni aunque alguien consiga el secreto).
    """
    expected_secret = os.environ.get('SETUP_SECRET')
    provided_secret = request.headers.get('X-Setup-Secret')

    if not expected_secret:
        return jsonify({'error': 'SETUP_SECRET no está configurado en el servidor.'}), 500
    if provided_secret != expected_secret:
        return jsonify({'error': 'No autorizado.'}), 401

    if Admin.query.count() > 0:
        return jsonify({'error': 'Ya existe un admin. Este endpoint ya cumplió su función.'}), 403

    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or '@' not in email:
        return jsonify({'error': 'El email no es válido.'}), 400
    if len(password) < 8:
        return jsonify({'error': 'La contraseña tiene que tener al menos 8 caracteres.'}), 400

    admin = Admin(email=email, name='Administrador')
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()

    return jsonify({'ok': True, 'email': email}), 201
