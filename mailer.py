import os
import logging

import requests

logger = logging.getLogger(__name__)


def send_email(to_email, subject, html_body):
    """Manda un email a través de la API de Resend (HTTP, no SMTP directo —
    Render bloquea las conexiones SMTP salientes en el plan gratuito).
    Devuelve True si se mandó, False si no (por ejemplo, si todavía no
    configuraste RESEND_API_KEY). Nunca lanza una excepción — un email que
    falla no debe romper el resto del pedido."""
    api_key = os.environ.get('RESEND_API_KEY')
    sender = os.environ.get('RESEND_FROM', 'Cadetería Centro <onboarding@resend.dev>')

    if not api_key:
        logger.warning('RESEND_API_KEY no configurada — no se envió el email a %s', to_email)
        return False

    try:
        resp = requests.post(
            'https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={'from': sender, 'to': [to_email], 'subject': subject, 'html': html_body},
            timeout=10,
        )
        if resp.status_code >= 300:
            logger.error('Resend respondió %s al mandar a %s: %s', resp.status_code, to_email, resp.text)
            return False
        return True
    except requests.RequestException as exc:
        logger.error('No se pudo enviar el email a %s: %s', to_email, exc)
        return False
