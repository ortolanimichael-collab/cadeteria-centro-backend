from datetime import datetime

from flask import Blueprint, request, jsonify

from models import db, Banner, BANNER_POSITIONS, BANNER_IMAGE_POSITIONS
from auth import role_required

banners_bp = Blueprint('banners', __name__, url_prefix='/api')


def _parse_fecha(valor):
    """Convierte un string ISO (ej. '2026-09-10' o '2026-09-10T00:00:00') a datetime,
    o None si viene vacío. Lanza ValueError si el formato es incorrecto."""
    if not valor:
        return None
    return datetime.fromisoformat(valor.replace('Z', '+00:00'))


@banners_bp.route('/banners', methods=['GET'])
def list_public_banners():
    """Público: solo los banners activos y dentro de su rango de fechas ahora mismo."""
    todos = Banner.query.order_by(Banner.order_index, Banner.created_at).all()
    vivos = [b.to_public_dict() for b in todos if b.is_live]
    return jsonify(vivos)


@banners_bp.route('/admin/banners', methods=['GET'])
@role_required('admin')
def admin_list_banners():
    """Listado completo para el admin, incluye inactivos y vencidos."""
    banners = Banner.query.order_by(Banner.created_at.desc()).all()
    return jsonify([b.to_admin_dict() for b in banners])


@banners_bp.route('/admin/banners', methods=['POST'])
@role_required('admin')
def admin_create_banner():
    data = request.get_json(silent=True) or {}

    image_url = (data.get('imageUrl') or '').strip()
    if not image_url:
        return jsonify({'error': 'Falta la imagen del banner.'}), 400

    position = data.get('position') or 'grid'
    if position not in BANNER_POSITIONS:
        return jsonify({'error': f'position inválida. Debe ser una de: {BANNER_POSITIONS}'}), 400

    image_position = data.get('imagePosition') or 'center center'
    if image_position not in BANNER_IMAGE_POSITIONS:
        return jsonify({'error': f'imagePosition inválida. Debe ser una de: {BANNER_IMAGE_POSITIONS}'}), 400

    try:
        start_date = _parse_fecha(data.get('startDate'))
        end_date = _parse_fecha(data.get('endDate'))
    except ValueError:
        return jsonify({'error': 'Fecha inválida.'}), 400

    banner = Banner(
        image_url=image_url,
        link_url=(data.get('linkUrl') or '').strip(),
        advertiser_name=(data.get('advertiserName') or '').strip(),
        position=position,
        image_position=image_position,
        active=bool(data.get('active', True)),
        order_index=int(data.get('orderIndex') or 0),
        start_date=start_date,
        end_date=end_date,
    )
    db.session.add(banner)
    db.session.commit()
    return jsonify(banner.to_admin_dict()), 201


@banners_bp.route('/admin/banners/<banner_id>', methods=['PUT'])
@role_required('admin')
def admin_update_banner(banner_id):
    banner = Banner.query.get(banner_id)
    if not banner:
        return jsonify({'error': 'No encontramos ese banner.'}), 404

    data = request.get_json(silent=True) or {}

    if 'imageUrl' in data:
        image_url = (data.get('imageUrl') or '').strip()
        if not image_url:
            return jsonify({'error': 'La imagen no puede quedar vacía.'}), 400
        banner.image_url = image_url
    if 'linkUrl' in data:
        banner.link_url = (data.get('linkUrl') or '').strip()
    if 'advertiserName' in data:
        banner.advertiser_name = (data.get('advertiserName') or '').strip()
    if 'position' in data:
        if data.get('position') not in BANNER_POSITIONS:
            return jsonify({'error': f'position inválida. Debe ser una de: {BANNER_POSITIONS}'}), 400
        banner.position = data.get('position')
    if 'imagePosition' in data:
        if data.get('imagePosition') not in BANNER_IMAGE_POSITIONS:
            return jsonify({'error': f'imagePosition inválida. Debe ser una de: {BANNER_IMAGE_POSITIONS}'}), 400
        banner.image_position = data.get('imagePosition')
    if 'active' in data:
        banner.active = bool(data.get('active'))
    if 'orderIndex' in data:
        banner.order_index = int(data.get('orderIndex') or 0)
    if 'startDate' in data:
        try:
            banner.start_date = _parse_fecha(data.get('startDate'))
        except ValueError:
            return jsonify({'error': 'Fecha de inicio inválida.'}), 400
    if 'endDate' in data:
        try:
            banner.end_date = _parse_fecha(data.get('endDate'))
        except ValueError:
            return jsonify({'error': 'Fecha de fin inválida.'}), 400

    db.session.commit()
    return jsonify(banner.to_admin_dict())


@banners_bp.route('/admin/banners/<banner_id>', methods=['DELETE'])
@role_required('admin')
def admin_delete_banner(banner_id):
    banner = Banner.query.get(banner_id)
    if not banner:
        return jsonify({'error': 'No encontramos ese banner.'}), 404
    db.session.delete(banner)
    db.session.commit()
    return jsonify({'ok': True})
