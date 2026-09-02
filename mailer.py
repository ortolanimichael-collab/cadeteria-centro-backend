import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)


def send_email(to_email, subject, html_body):
    """Manda un email por SMTP. Devuelve True si se mandó, False si no
    (por ejemplo, si todavía no configuraste las variables SMTP_*).
    Nunca lanza una excepción — un email que falla no debe romper el resto
    del pedido (como el registro de un negocio o un pedido de reset)."""
    host = os.environ.get('SMTP_HOST')
    port = int(os.environ.get('SMTP_PORT', '587'))
    user = os.environ.get('SMTP_USER')
    password = os.environ.get('SMTP_PASSWORD')
    sender = os.environ.get('SMTP_FROM', user)

    if not all([host, user, password, sender]):
        logger.warning('SMTP no configurado (faltan variables SMTP_*) — no se envió el email a %s', to_email)
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = to_email
    msg.attach(MIMEText(html_body, 'html'))

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            server.login(user, password)
            server.sendmail(sender, [to_email], msg.as_string())
        return True
    except Exception as exc:
        logger.error('No se pudo enviar el email a %s: %s', to_email, exc)
        return False
