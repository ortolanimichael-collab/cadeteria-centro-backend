import os
import logging

import requests
from flask import Blueprint, request, jsonify

from models import db, Business

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint('webhooks', __name__)

PRODUCTO_SLUG = 'cadeteria-centro'


def notify_panel_new_business(business):
    """Le avisa a tu panel de membresías (panel-membresias) que se registró
    un negocio nuevo, usando su endpoint real /api/registro-externo.
    No hacemos que el registro falle si el panel está caído o no está
    configurado: solo lo logueamos.
    """
    panel_url = os.environ.get('PANEL_MEMBRESIAS_URL')
    if not panel_url:
        logger.warning('PANEL_MEMBRESIAS_URL no configurada — no se avisó al panel.')
        return

    payload = {
        'producto': PRODUCTO_SLUG,
        'nombre': business.name,
        'email': business.email,
        'dias_prueba': 15,
        'id_externo': business.id,
    }
    try:
        resp = requests.post(
            f'{panel_url.rstrip("/")}/api/registro-externo',
            json=payload,
            timeout=8,
        )
        if resp.status_code >= 300:
            logger.error('El panel de membresías respondió %s: %s', resp.status_code, resp.text)
    except requests.RequestException as exc:
        logger.error('No se pudo avisar al panel de membresías: %s', exc)


@webhooks_bp.route('/api/webhooks/membership-update', methods=['POST'])
def membership_update():
    """Endpoint que llama TU PANEL DE MEMBRESÍAS cuando renueva o cancela la
    suscripción de un negocio (función sincronizar_producto() -> tipo
    'webhook' en panel-membresias).

    Header:  X-Webhook-Secret: <MEMBERSHIP_WEBHOOK_SECRET>  (tiene que ser
             el mismo valor que cargues en el campo webhook_secret del
             producto 'cadeteria-centro' dentro de panel-membresias)
    Body:    { "email": "...", "fecha_vencimiento": "2026-10-01", "activo": true }

    Nota: el panel manda "activo" como booleano, no un estado con nombre —
    lo traducimos a nuestros propios estados: activo=true -> 'active',
    activo=false -> 'suspended' (no 'cancelled': si de verdad querés dar
    de baja del todo a un negocio, eso lo hacés a mano desde el panel de
    admin de Cadetería Centro, para no borrar la página pública de alguien
    solo porque se atrasó un día con el pago).
    """
    expected_secret = os.environ.get('MEMBERSHIP_WEBHOOK_SECRET')
    provided_secret = request.headers.get('X-Webhook-Secret')
    if not expected_secret or provided_secret != expected_secret:
        return jsonify({'error': 'No autorizado.'}), 401

    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    activo = data.get('activo')

    if not email or activo is None:
        return jsonify({'error': 'Faltan email o activo.'}), 400

    business = Business.query.filter_by(email=email).first()
    if not business:
        return jsonify({'error': 'No existe ningún negocio con ese email.'}), 404

    business.subscription_status = 'active' if activo else 'suspended'
    db.session.commit()

    logger.info('Membresía de %s (%s) actualizada a %s', business.name, business.email, business.subscription_status)
    return jsonify({'ok': True, 'business_id': business.id, 'subscription_status': business.subscription_status})
