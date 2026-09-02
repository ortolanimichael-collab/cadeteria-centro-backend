from functools import wraps

from flask import jsonify
from flask_jwt_extended import get_jwt, get_jwt_identity, verify_jwt_in_request

from models import Business


def role_required(*allowed_types):
    """Decorador: exige un JWT válido cuyo 'type' esté en allowed_types.
    Uso: @role_required('business')  o  @role_required('business', 'admin')
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            verify_jwt_in_request()
            claims = get_jwt()
            user_type = claims.get('type')
            if user_type not in allowed_types:
                return jsonify({'error': 'No tenés permiso para esto.'}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def business_access_required(fn):
    """Como role_required('business'), pero además corta el acceso si la
    membresía del negocio está suspendida o cancelada."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        claims = get_jwt()
        if claims.get('type') != 'business':
            return jsonify({'error': 'No tenés permiso para esto.'}), 403
        business = Business.query.get(get_jwt_identity())
        if not business:
            return jsonify({'error': 'Cuenta no encontrada.'}), 404
        if not business.is_access_allowed:
            return jsonify({
                'error': 'membership_inactive',
                'message': 'Tu membresía no está activa. Contactá a Cadetería Centro para reactivar tu acceso.'
            }), 403
        return fn(*args, **kwargs)
    return wrapper
