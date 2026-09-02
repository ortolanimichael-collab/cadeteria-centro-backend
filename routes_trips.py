from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    jwt_required, get_jwt, get_jwt_identity, verify_jwt_in_request
)

from models import db, TripRequest

trips_bp = Blueprint('trips', __name__, url_prefix='/api/trips')


def _current_owner():
    """Si viene un JWT válido en el header, devuelve (owner_type, owner_id).
    Si no hay token (pedido anónimo), devuelve (None, None) sin cortar la request."""
    try:
        verify_jwt_in_request(optional=True)
    except Exception:
        return None, None
    identity = get_jwt_identity()
    if not identity:
        return None, None
    claims = get_jwt()
    return claims.get('type'), identity


@trips_bp.route('', methods=['POST'])
def create_trip():
    data = request.get_json(silent=True) or {}
    origin = (data.get('origin') or '').strip()
    dest = (data.get('dest') or '').strip()
    description = (data.get('description') or '').strip()
    phone = (data.get('phone') or '').strip()

    if not all([origin, dest, description, phone]):
        return jsonify({'error': 'Completá todos los campos.'}), 400

    owner_type, owner_id = _current_owner()

    trip = TripRequest(
        origin=origin, destination=dest, description=description, phone=phone,
        owner_type=owner_type, owner_id=owner_id,
    )
    db.session.add(trip)
    db.session.commit()
    return jsonify(trip.to_dict()), 201


@trips_bp.route('/mine', methods=['GET'])
@jwt_required()
def my_trips():
    claims = get_jwt()
    owner_type = claims.get('type')
    owner_id = get_jwt_identity()
    if owner_type not in ('client', 'business'):
        return jsonify([])
    trips = (
        TripRequest.query
        .filter_by(owner_type=owner_type, owner_id=owner_id)
        .order_by(TripRequest.created_at.desc())
        .all()
    )
    return jsonify([t.to_dict() for t in trips])


@trips_bp.route('/<trip_id>/cancel', methods=['PUT'])
@jwt_required()
def cancel_trip(trip_id):
    claims = get_jwt()
    owner_type = claims.get('type')
    owner_id = get_jwt_identity()

    trip = TripRequest.query.get(trip_id)
    if not trip or trip.owner_type != owner_type or trip.owner_id != owner_id:
        return jsonify({'error': 'No encontramos ese pedido.'}), 404

    trip.status = 'cancelado'
    db.session.commit()
    return jsonify(trip.to_dict())
