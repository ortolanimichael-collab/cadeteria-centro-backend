from flask import Blueprint, request, jsonify

from models import db, SiteSettings, Business, Product, TripRequest, Client
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
    total_businesses = Business.query.count()
    total_products = Product.query.count()
    pending_trips = TripRequest.query.filter_by(status='pendiente').count()
    total_accounts = Business.query.count() + Client.query.count()
    return jsonify({
        'businesses': total_businesses,
        'products': total_products,
        'pendingTrips': pending_trips,
        'accounts': total_accounts,
    })


@admin_bp.route('/admin/businesses', methods=['GET'])
@role_required('admin')
def admin_list_businesses():
    """Listado completo para el admin, con estado de membresía incluido."""
    businesses = Business.query.order_by(Business.created_at.desc()).all()
    return jsonify([b.to_owner_dict() for b in businesses])


@admin_bp.route('/admin/businesses/<business_id>/subscription', methods=['PUT'])
@role_required('admin')
def admin_set_subscription(business_id):
    """Cambio manual de estado de membresía desde el propio admin de Cadetería
    Centro (además del webhook automático del panel de membresías)."""
    from models import SUBSCRIPTION_STATUSES

    business = Business.query.get(business_id)
    if not business:
        return jsonify({'error': 'No encontramos ese negocio.'}), 404

    data = request.get_json(silent=True) or {}
    new_status = data.get('status')
    if new_status not in SUBSCRIPTION_STATUSES:
        return jsonify({'error': f'status inválido. Debe ser uno de: {SUBSCRIPTION_STATUSES}'}), 400

    business.subscription_status = new_status
    db.session.commit()
    return jsonify(business.to_owner_dict())


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
