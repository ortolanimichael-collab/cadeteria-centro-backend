from datetime import datetime

from flask import Blueprint, request, jsonify
from sqlalchemy import func

import tiendaly_sync
from models import db, SiteSettings, Business, Product, TripRequest, Client, SiteEvent
from auth import role_required

admin_bp = Blueprint('admin', __name__, url_prefix='/api')


@admin_bp.route('/site-settings', methods=['GET'])
def get_site_settings():
    """Público: cualquiera puede leer la configuración del sitio (banner, anuncio, etc)."""
    return jsonify(SiteSettings.get_singleton().to_dict())


@admin_bp.route('/admin/site-settings', methods=['PUT'])
@role_required('admin')
def update_site_settings():
    settings = SiteSettings.get_singleton()
    data = request.get_json(silent=True) or {}

    if 'heroTitle' in data:
        settings.hero_title = (data.get('heroTitle') or '').strip()
    if 'heroSubtitle' in data:
        settings.hero_subtitle = (data.get('heroSubtitle') or '').strip()
    if 'heroImages' in data and isinstance(data.get('heroImages'), list):
        settings.hero_images = data.get('heroImages')
    if 'logoUrl' in data:
        settings.logo_url = data.get('logoUrl') or ''
    if 'promoEnabled' in data:
        settings.promo_enabled = bool(data.get('promoEnabled'))
    if 'promoText' in data:
        settings.promo_text = (data.get('promoText') or '').strip()
    if 'cadeteriaWhatsapp' in data:
        settings.cadeteria_whatsapp = (data.get('cadeteriaWhatsapp') or '').strip()

    db.session.commit()
    return jsonify(settings.to_dict())


@admin_bp.route('/admin/stats', methods=['GET'])
@role_required('admin')
def stats():
    espejo = Business.query.filter_by(source='tiendaly')
    pending_trips = TripRequest.query.filter_by(status='pendiente').count()
    return jsonify({
        'businesses': espejo.count(),
        'products': Product.query.join(Business, Product.business_id == Business.id).filter(Business.source == 'tiendaly').count(),
        'pendingTrips': pending_trips,
        'accounts': Client.query.count(),
    })


@admin_bp.route('/admin/businesses', methods=['GET'])
@role_required('admin')
def admin_list_businesses():
    """Negocios que se ven hoy en el sitio (copia de Tiendaly). Solo lectura: se administran en Tiendaly."""
    businesses = Business.query.filter_by(source='tiendaly').order_by(Business.name).all()
    return jsonify([b.to_public_dict() for b in businesses])


@admin_bp.route('/admin/sync-tiendaly', methods=['POST'])
@role_required('admin')
def admin_sync_tiendaly():
    """Fuerza ahora la lectura de Tiendaly (si no, se actualiza sola cada pocos minutos)."""
    if not tiendaly_sync.configurado():
        return jsonify({'ok': False, 'error': 'Falta configurar TIENDALY_URL y TIENDALY_CANAL_CLAVE.'}), 400
    res = tiendaly_sync.sincronizar()
    return jsonify(res), (200 if res.get('ok') else 502)


def _rango(mes):
    try:
        a, m = (int(x) for x in (mes or '').split('-'))
        ini = datetime(a, m, 1)
    except (ValueError, TypeError):
        hoy = datetime.utcnow()
        ini = datetime(hoy.year, hoy.month, 1)
    fin = datetime(ini.year + (ini.month == 12), ini.month % 12 + 1, 1)
    return ini, fin


@admin_bp.route('/admin/reporte', methods=['GET'])
@role_required('admin')
def admin_reporte():
    """Reporte mensual para el dueño del sitio: lo que mide el propio sitio (visitas, clics, vistas, pedidos de
    cadetería) más lo que informa Tiendaly (solicitudes de envío desde las tiendas, clics en sus páginas)."""
    mes = request.args.get('mes')
    ini, fin = _rango(mes)
    filas = dict(db.session.query(SiteEvent.kind, func.count(SiteEvent.id)).filter(
        SiteEvent.created_at >= ini, SiteEvent.created_at < fin).group_by(SiteEvent.kind).all())
    por_neg = {}
    for bid, kind, c in db.session.query(SiteEvent.business_id, SiteEvent.kind, func.count(SiteEvent.id)).filter(
            SiteEvent.created_at >= ini, SiteEvent.created_at < fin, SiteEvent.business_id.isnot(None)
    ).group_by(SiteEvent.business_id, SiteEvent.kind):
        por_neg.setdefault(bid, {})[kind] = int(c)
    nombres = {b.id: b.name for b in Business.query.filter(Business.id.in_(list(por_neg))).all()} if por_neg else {}
    sitio = {
        'visitas': int(filas.get('visit', 0)),
        'clics_whatsapp': int(filas.get('whatsapp_click', 0)),
        'negocios_vistos': int(filas.get('business_view', 0)),
        'pedidos_cadeteria': TripRequest.query.filter(TripRequest.created_at >= ini, TripRequest.created_at < fin).count(),
        'por_negocio': sorted(
            [{'negocio': nombres.get(k, '(ya no está)'), 'clics_whatsapp': v.get('whatsapp_click', 0),
              'vistas': v.get('business_view', 0)} for k, v in por_neg.items()],
            key=lambda x: -(x['clics_whatsapp'] + x['vistas'])),
    }
    tiendaly = None
    if tiendaly_sync.configurado():
        try:
            code, data = tiendaly_sync._get('/api/canal/reporte?mes=' + ini.strftime('%Y-%m'))
            if code == 200:
                tiendaly = data
        except Exception:
            tiendaly = None
    return jsonify({'mes': ini.strftime('%Y-%m'), 'sitio': sitio, 'tiendaly': tiendaly})


@admin_bp.route('/admin/generate-reset-link', methods=['POST'])
@role_required('admin')
def generate_reset_link():
    """Genera un link de 'restablecer contraseña' para que el admin se lo
    mande a mano a un negocio o cliente (por WhatsApp, por ejemplo), sin
    depender de que el email les llegue. Usa exactamente el mismo token
    que el flujo automático — vence en 1 hora igual."""
    import os
    from routes_auth import _reset_serializer

    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'Falta el email.'}), 400

    account = Business.query.filter_by(email=email).first()
    account_type = 'business'
    if not account:
        account = Client.query.filter_by(email=email).first()
        account_type = 'client'

    if not account:
        return jsonify({'error': 'No encontramos ninguna cuenta con ese email.'}), 404

    token = _reset_serializer().dumps({'email': email, 'type': account_type})
    frontend_url = os.environ.get('FRONTEND_URL', '').rstrip('/')
    link = f'{frontend_url}/#/restablecer?token={token}'

    return jsonify({
        'ok': True,
        'link': link,
        'name': account.name,
        'accountType': 'Negocio' if account_type == 'business' else 'Cliente',
    })


TIPOS_EVENTO = ('visit', 'whatsapp_click', 'business_view')


@admin_bp.route('/track', methods=['POST'])
def track():
    """Contador anónimo (sin IP, sin cookie, sin datos de la persona) para el reporte mensual."""
    data = request.get_json(silent=True) or {}
    kind = data.get('kind')
    if kind not in TIPOS_EVENTO:
        return jsonify({'error': 'Tipo inválido.'}), 400
    bid = data.get('businessId')
    bid = str(bid)[:36] if bid else None
    if bid and not Business.query.filter_by(id=bid).first():
        bid = None
    db.session.add(SiteEvent(kind=kind, business_id=bid))
    db.session.commit()
    return jsonify({'ok': True}), 201
