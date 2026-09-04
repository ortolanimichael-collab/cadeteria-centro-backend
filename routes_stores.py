from flask import Blueprint, request, jsonify

from models import db, Store, STORE_CATEGORIES
from auth import role_required

stores_bp = Blueprint('stores', __name__, url_prefix='/api')


@stores_bp.route('/stores', methods=['GET'])
def list_public_stores():
    """Público: solo los negocios activos, para elegir en 'Hacé tus compras acá'."""
    stores = Store.query.filter_by(active=True).order_by(Store.order_index, Store.name).all()
    return jsonify([s.to_public_dict() for s in stores])


@stores_bp.route('/admin/stores', methods=['GET'])
@role_required('admin')
def admin_list_stores():
    """Listado completo para el admin, incluye inactivos."""
    stores = Store.query.order_by(Store.order_index, Store.name).all()
    return jsonify([s.to_admin_dict() for s in stores])


@stores_bp.route('/admin/stores', methods=['POST'])
@role_required('admin')
def admin_create_store():
    data = request.get_json(silent=True) or {}

    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Falta el nombre del negocio.'}), 400

    category = data.get('category') or 'Supermercado'
    if category not in STORE_CATEGORIES:
        return jsonify({'error': f'category inválida. Debe ser una de: {STORE_CATEGORIES}'}), 400

    store = Store(
        name=name,
        category=category,
        address=(data.get('address') or '').strip(),
        image_url=(data.get('imageUrl') or '').strip(),
        active=bool(data.get('active', True)),
        order_index=int(data.get('orderIndex') or 0),
    )
    db.session.add(store)
    db.session.commit()
    return jsonify(store.to_admin_dict()), 201


@stores_bp.route('/admin/stores/<store_id>', methods=['PUT'])
@role_required('admin')
def admin_update_store(store_id):
    store = Store.query.get(store_id)
    if not store:
        return jsonify({'error': 'No encontramos ese negocio.'}), 404

    data = request.get_json(silent=True) or {}

    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            return jsonify({'error': 'El nombre no puede quedar vacío.'}), 400
        store.name = name
    if 'category' in data:
        if data.get('category') not in STORE_CATEGORIES:
            return jsonify({'error': f'category inválida. Debe ser una de: {STORE_CATEGORIES}'}), 400
        store.category = data.get('category')
    if 'address' in data:
        store.address = (data.get('address') or '').strip()
    if 'imageUrl' in data:
        store.image_url = (data.get('imageUrl') or '').strip()
    if 'active' in data:
        store.active = bool(data.get('active'))
    if 'orderIndex' in data:
        store.order_index = int(data.get('orderIndex') or 0)

    db.session.commit()
    return jsonify(store.to_admin_dict())


@stores_bp.route('/admin/stores/<store_id>', methods=['DELETE'])
@role_required('admin')
def admin_delete_store(store_id):
    store = Store.query.get(store_id)
    if not store:
        return jsonify({'error': 'No encontramos ese negocio.'}), 404
    db.session.delete(store)
    db.session.commit()
    return jsonify({'ok': True})
