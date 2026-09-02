from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity

from models import db, Business, Product
from auth import business_access_required

business_bp = Blueprint('business', __name__, url_prefix='/api')


# ---------- PÚBLICO ----------

@business_bp.route('/businesses', methods=['GET'])
def list_businesses():
    """Listado público. Filtros opcionales: ?category=Rotisería"""
    category = request.args.get('category')
    query = Business.query.filter(Business.subscription_status != 'cancelled')
    if category and category != 'Todos':
        query = query.filter_by(category=category)
    businesses = query.order_by(Business.created_at.desc()).all()
    return jsonify([b.to_public_dict() for b in businesses])


@business_bp.route('/businesses/<business_id>', methods=['GET'])
def get_business(business_id):
    business = Business.query.get(business_id)
    if not business or not business.is_publicly_visible:
        return jsonify({'error': 'No encontramos este negocio.'}), 404
    return jsonify(business.to_public_dict())


@business_bp.route('/products/search', methods=['GET'])
def search_products():
    """Busca productos por nombre/descripción, o negocios por nombre/descripción
    (en cuyo caso devuelve todos sus productos). ?q=milanesa&category=Rotisería"""
    q = (request.args.get('q') or '').strip().lower()
    category = request.args.get('category')

    query = Business.query.filter(Business.subscription_status != 'cancelled')
    if category and category != 'Todos':
        query = query.filter_by(category=category)

    results = []
    for biz in query.all():
        biz_text_match = (not q) or (q in biz.name.lower()) or (q in (biz.description or '').lower())
        for p in biz.products:
            prod_match = (not q) or (q in p.name.lower()) or (q in (p.description or '').lower())
            if biz_text_match or prod_match:
                item = p.to_dict()
                item['bizId'] = biz.id
                item['bizName'] = biz.name
                results.append(item)

    return jsonify(results)


# ---------- PANEL DEL NEGOCIO (dueño autenticado) ----------

@business_bp.route('/business/me', methods=['GET'])
@business_access_required
def get_my_business():
    business = Business.query.get(get_jwt_identity())
    return jsonify(business.to_owner_dict())


@business_bp.route('/business/me', methods=['PUT'])
@business_access_required
def update_my_business():
    business = Business.query.get(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    # Mapea el nombre que manda el frontend -> el atributo real del modelo
    field_map = {
        'address': 'address', 'phone': 'phone', 'whatsapp': 'whatsapp',
        'instagram': 'instagram', 'facebook': 'facebook',
        'description': 'description', 'category': 'category',
        'avatarUrl': 'avatar_url', 'coverUrl': 'cover_url',
    }
    for incoming_field, model_field in field_map.items():
        if incoming_field in data:
            value = data.get(incoming_field)
            setattr(business, model_field, value.strip() if isinstance(value, str) else value)

    db.session.commit()
    return jsonify(business.to_owner_dict())


@business_bp.route('/business/me/products', methods=['POST'])
@business_access_required
def add_product():
    business = Business.query.get(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    name = (data.get('name') or '').strip()
    price = data.get('price')
    if not name or price in (None, ''):
        return jsonify({'error': 'Completá el nombre y el precio.'}), 400

    try:
        price = float(price)
    except (TypeError, ValueError):
        return jsonify({'error': 'El precio no es válido.'}), 400

    product = Product(
        business_id=business.id, name=name, price=price,
        description=(data.get('desc') or '').strip(),
        image_url=data.get('image') or '',
    )
    db.session.add(product)
    db.session.commit()
    return jsonify(product.to_dict()), 201


@business_bp.route('/business/me/products/<product_id>', methods=['PUT'])
@business_access_required
def update_product(product_id):
    business = Business.query.get(get_jwt_identity())
    product = Product.query.filter_by(id=product_id, business_id=business.id).first()
    if not product:
        return jsonify({'error': 'No encontramos ese producto.'}), 404

    data = request.get_json(silent=True) or {}
    if 'name' in data:
        product.name = (data.get('name') or '').strip()
    if 'price' in data:
        try:
            product.price = float(data.get('price'))
        except (TypeError, ValueError):
            return jsonify({'error': 'El precio no es válido.'}), 400
    if 'desc' in data:
        product.description = (data.get('desc') or '').strip()
    if data.get('image'):
        product.image_url = data.get('image')

    db.session.commit()
    return jsonify(product.to_dict())


@business_bp.route('/business/me/products/<product_id>', methods=['DELETE'])
@business_access_required
def delete_product(product_id):
    business = Business.query.get(get_jwt_identity())
    product = Product.query.filter_by(id=product_id, business_id=business.id).first()
    if not product:
        return jsonify({'error': 'No encontramos ese producto.'}), 404
    db.session.delete(product)
    db.session.commit()
    return jsonify({'ok': True})
