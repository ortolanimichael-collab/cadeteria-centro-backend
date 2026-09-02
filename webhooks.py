import os
import logging

import requests
from flask import Blueprint, request, jsonify

from models import db, Business, SUBSCRIPTION_STATUSES

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint('webhooks', __name__)

PRODUCT_SLUG = 'cadeteria-centro'


def notify_panel_new_business(business):
    """Le avisa al panel de membresías que se registró un negocio nuevo,
    para que cree ahí la ficha de membresía (arranca en período de prueba).
    No hacemos que el registro falle si el panel está caído: solo lo logueamos.
    """
    panel_url = os.environ.get('PANEL_MEMBRESIAS_URL')
    api_key = os.environ.get('PANEL_MEMBRESIAS_API_KEY')
    if not panel_url or not api_key:
        logger.warning('PANEL_MEMBRESIAS_URL / API_KEY no configurados — no se avisó al panel.')
        return

    payload = {
        'product': PRODUCT_SLUG,
        'external_id': business.id,
        'business_name': business.name,
        'email': business.email,
        'created_at': business.created_at.isoformat() if business.created_at else None,
    }
    try:
        resp = requests.post(
            f'{panel_url.rstrip("/")}/api/webhooks/new-subscriber',
            json=payload,
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=8,
        )
        if resp.status_code >= 300:
            logger.error('El panel de membresías respondió %s: %s', resp.status_code, resp.text)
    except requests.RequestException as exc:
        logger.error('No se pudo avisar al panel de membresías: %s', exc)


@webhooks_bp.route('/api/webhooks/membership-update', methods=['POST'])
def membership_update():
    """Endpoint que llama el PANEL DE MEMBRESÍAS cuando cambia el estado de pago
    de un negocio (activó, se atrasó, canceló, etc).

    Espera un header:  X-Webhook-Secret: <MEMBERSHIP_WEBHOOK_SECRET>
    Y un body JSON:     { "external_id": "<business.id>", "status": "active" }
    """
    expected_secret = os.environ.get('MEMBERSHIP_WEBHOOK_SECRET')
    provided_secret = request.headers.get('X-Webhook-Secret')
    if not expected_secret or provided_secret != expected_secret:
        return jsonify({'error': 'No autorizado.'}), 401

    data = request.get_json(silent=True) or {}
    business_id = data.get('external_id')
    new_status = data.get('status')

    if not business_id or not new_status:
        return jsonify({'error': 'Faltan external_id o status.'}), 400
    if new_status not in SUBSCRIPTION_STATUSES:
        return jsonify({'error': f'status inválido. Debe ser uno de: {SUBSCRIPTION_STATUSES}'}), 400

    business = Business.query.get(business_id)
    if not business:
        return jsonify({'error': 'No existe ningún negocio con ese external_id.'}), 404

    business.subscription_status = new_status
    db.session.commit()

    logger.info('Membresía de %s (%s) actualizada a %s', business.name, business.id, new_status)
    return jsonify({'ok': True, 'business_id': business.id, 'subscription_status': new_status})
