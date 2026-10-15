import os
import logging

import requests
from flask import Blueprint, request, jsonify

from models import db, Admin

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint('webhooks', __name__)


def _cabeceras_panel(variable_secreto):
    """Clave del producto para llamar al panel de membresías (tarea #156).
    Es la misma que el panel guarda en el campo "clave" de ese producto."""
    secreto = os.environ.get(variable_secreto)
    return {'X-Webhook-Secret': secreto} if secreto else {}

# Slug del producto que representa TU cuenta de admin dentro de
# panel-membresias (distinto del de los negocios). Si lo creaste con otro
# nombre, cambialo acá o con la variable de entorno.
ADMIN_PRODUCTO_SLUG = os.environ.get('PANEL_ADMIN_PRODUCTO_SLUG', 'cadeteria-centro-admin')


@webhooks_bp.route('/api/webhooks/admin-membership-update', methods=['POST'])
def admin_membership_update():
    """Endpoint APARTE del de arriba, para que panel-membresías pueda
    activar/desactivar TU cuenta de administrador de Cadetería Centro
    (no la de un negocio). Usa un secreto propio (ADMIN_MEMBERSHIP_WEBHOOK_SECRET),
    distinto del de los negocios, porque acá el impacto es mayor -- bloquear
    esto te deja afuera de tu propio panel de admin.

    Header:  X-Webhook-Secret: <ADMIN_MEMBERSHIP_WEBHOOK_SECRET>
    Body:    { "email": "tu-email-de-admin@...", "activo": true }
    """
    expected_secret = os.environ.get('ADMIN_MEMBERSHIP_WEBHOOK_SECRET')
    provided_secret = request.headers.get('X-Webhook-Secret')
    if not expected_secret or provided_secret != expected_secret:
        return jsonify({'error': 'No autorizado.'}), 401

    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    activo = data.get('activo')

    if not email or activo is None:
        return jsonify({'error': 'Faltan email o activo.'}), 400

    admin = Admin.query.filter_by(email=email).first()
    if not admin:
        return jsonify({'error': 'No existe ningún admin con ese email.'}), 404

    admin.activo = bool(activo)
    db.session.commit()

    logger.info('Admin %s actualizado a activo=%s', admin.email, admin.activo)
    return jsonify({'ok': True, 'email': admin.email, 'activo': admin.activo})


def notify_panel_admin_checkin(admin):
    """Le avisa a panel-membresías, en segundo plano y sin cortar nada si
    falla, que tu cuenta de admin se usó ahora mismo -- así "última
    conexión" en el panel refleja la realidad. No afecta si podés entrar
    o no (eso lo decide admin.activo, ya actualizado por webhook aparte)."""
    panel_url = os.environ.get('PANEL_MEMBRESIAS_URL')
    if not panel_url:
        return
    try:
        requests.get(
            f'{panel_url.rstrip("/")}/api/validar-licencia',
            params={'producto': ADMIN_PRODUCTO_SLUG, 'email': admin.email, 'version': 'web'},
            headers=_cabeceras_panel('ADMIN_MEMBERSHIP_WEBHOOK_SECRET'),
            timeout=5,
        )
    except requests.RequestException as exc:
        logger.warning('No se pudo avisar el check-in del admin al panel: %s', exc)
