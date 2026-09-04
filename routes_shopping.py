from flask import Blueprint, request, jsonify

from models import db, ShoppingTripRequest, Store
from auth import role_required

shopping_bp = Blueprint('shopping', __name__, url_prefix='/api')


@shopping_bp.route('/shopping-trips', methods=['POST'])
def create_shopping_trip():
    """Pedido de 'Hacé tus compras acá' -- no requiere estar logueado, igual que
    'viaje particular'."""
    data = request.get_json(silent=True) or {}

    store_id = (data.get('storeId') or '').strip()
    address = (data.get('address') or '').strip()
    shopping_list = (data.get('shoppingList') or '').strip()
    phone = (data.get('phone') or '').strip()

    if not store_id or not address or not shopping_list or not phone:
        return jsonify({'error': 'Elegí un negocio y completá dirección, lista y teléfono.'}), 400

    store = Store.query.get(store_id)
    if not store or not store.active:
        return jsonify({'error': 'Ese negocio ya no está disponible. Elegí otro de la lista.'}), 400

    trip = ShoppingTripRequest(
        store_id=store.id,
        address=address,
        shopping_list=shopping_list,
        phone=phone,
    )
    db.session.add(trip)
    db.session.commit()
    return jsonify(trip.to_dict()), 201


@shopping_bp.route('/admin/shopping-trips', methods=['GET'])
@role_required('admin')
def admin_list_shopping_trips():
    trips = ShoppingTripRequest.query.order_by(ShoppingTripRequest.created_at.desc()).all()
    return jsonify([t.to_dict() for t in trips])


@shopping_bp.route('/admin/shopping-trips/<trip_id>/status', methods=['PUT'])
@role_required('admin')
def admin_update_shopping_trip_status(trip_id):
    trip = ShoppingTripRequest.query.get(trip_id)
    if not trip:
        return jsonify({'error': 'No encontramos ese pedido.'}), 404
    data = request.get_json(silent=True) or {}
    status = data.get('status')
    if status not in ('pendiente', 'cancelado', 'entregado'):
        return jsonify({'error': 'status inválido.'}), 400
    trip.status = status
    db.session.commit()
    return jsonify(trip.to_dict())
