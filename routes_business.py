import re
import unicodedata
import difflib

from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity

from models import db, Business, Product
from auth import business_access_required, role_required
from geocoding import geocode_address

business_bp = Blueprint('business', __name__, url_prefix='/api')

DIAS_SEMANA = ('lun', 'mar', 'mie', 'jue', 'vie', 'sab', 'dom')


def _categorias_del_filtro(param):
    """El querystring de categoría puede traer un solo rubro (ej.
    "Pizzería") o varios separados por coma -- así arma el filtro el
    frontend para los chips agrupados (ej. "Comidas" manda
    "Rotisería,Pizzería,Panadería,..."). Devuelve la lista lista para un
    IN(), o None si no hay filtro (vacío o "Todos")."""
    if not param or param == 'Todos':
        return None
    return [c.strip() for c in param.split(',') if c.strip()]


def _normalizar_texto(s):
    """Minúsculas y sin acentos, para que "rotisería"/"rotiseria" (con o
    sin tilde) se traten como lo mismo al buscar."""
    s = (s or '').lower()
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def _texto_coincide(query_norm, texto):
    """True si "texto" coincide con la búsqueda, tolerando errores de
    tipeo -- ej. "pisa" encuentra "pizza", "anburgesa" encuentra
    "hamburguesa". Primero prueba substring exacto (rápido, sin falsos
    positivos); si no aparece, compara palabra por palabra con similitud
    de texto para tolerar una letra de más/de menos/cambiada. Con
    palabras muy cortas (menos de 4 letras) no compara por similitud --
    ahí cualquier letra de diferencia ya cambia el significado, así que
    solo cuenta el substring exacto de arriba."""
    if not query_norm:
        return True
    texto_norm = _normalizar_texto(texto)
    if query_norm in texto_norm:
        return True
    if len(query_norm) < 4:
        return False
    for palabra in re.findall(r'\w+', texto_norm):
        if len(palabra) < 4:
            continue
        if difflib.SequenceMatcher(None, query_norm, palabra).ratio() >= 0.65:
            return True
    return False


def _clean_hours(raw):
    """Valida y limpia el objeto de horarios que manda el frontend, para no
    guardar cualquier cosa. Ignora días con formato raro en vez de fallar.

    Cada día puede tener varios turnos ("ranges") -- por ejemplo, negocios
    que cierran al mediodía por la siesta y reabren a la tarde. También
    acepta el formato viejo de un solo {open, close} suelto (sin "ranges"),
    por si una pestaña del navegador quedó con el código anterior, y lo
    guarda ya convertido a la lista nueva.
    """
    if not isinstance(raw, dict):
        return {}
    cleaned = {}
    for dia in DIAS_SEMANA:
        cfg = raw.get(dia)
        if not isinstance(cfg, dict):
            continue
        if cfg.get('closed'):
            cleaned[dia] = {'closed': True}
            continue
        ranges_in = cfg.get('ranges')
        if not isinstance(ranges_in, list):
            open_t = (cfg.get('open') or '').strip()
            close_t = (cfg.get('close') or '').strip()
            ranges_in = [{'open': open_t, 'close': close_t}] if open_t and close_t else []
        ranges = []
        for r in ranges_in:
            if not isinstance(r, dict):
                continue
            open_t = (r.get('open') or '').strip()
            close_t = (r.get('close') or '').strip()
            if open_t and close_t:
                ranges.append({'open': open_t, 'close': close_t})
        if ranges:
            cleaned[dia] = {'closed': False, 'ranges': ranges}
    return cleaned


def _clean_variant_groups(raw):
    """Valida y limpia los grupos de opciones de un producto."""
    if not isinstance(raw, list):
        return []
    cleaned = []
    for group in raw:
        if not isinstance(group, dict):
            continue
        name = (group.get('name') or '').strip()
        gtype = group.get('type') if group.get('type') in ('single', 'multiple') else 'single'
        options = []
        for opt in (group.get('options') or []):
            if not isinstance(opt, dict):
                continue
            opt_name = (opt.get('name') or '').strip()
            if not opt_name:
                continue
            try:
                opt_price = float(opt.get('price') or 0)
            except (TypeError, ValueError):
                opt_price = 0
            options.append({'name': opt_name, 'price': opt_price})
        if name and options:
            cleaned.append({'name': name, 'type': gtype, 'options': options})
    return cleaned


# ---------- PÚBLICO ----------

@business_bp.route('/businesses', methods=['GET'])
def list_businesses():
    """Listado público. Filtros opcionales: ?category=Pizzería o
    ?category=Rotisería,Pizzería,Panadería (varios rubros a la vez, para
    los chips agrupados del frontend, ej. "Comidas")."""
    categorias = _categorias_del_filtro(request.args.get('category'))
    query = Business.query.filter(Business.subscription_status != 'cancelled')
    if categorias:
        query = query.filter(Business.category.in_(categorias))
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
    """Busca productos por nombre/descripción, o negocios por
    nombre/descripción (en cuyo caso devuelve todos sus productos). La
    búsqueda tolera errores de tipeo (ver _texto_coincide). ?q=pisa
    encuentra productos de "pizza" igual. category admite uno o varios
    rubros separados por coma: ?q=milanesa&category=Rotisería"""
    q_norm = _normalizar_texto((request.args.get('q') or '').strip())
    categorias = _categorias_del_filtro(request.args.get('category'))

    query = Business.query.filter(Business.subscription_status != 'cancelled')
    if categorias:
        query = query.filter(Business.category.in_(categorias))

    results = []
    for biz in query.all():
        biz_text_match = _texto_coincide(q_norm, biz.name) or _texto_coincide(q_norm, biz.description)
        for p in biz.products:
            prod_match = _texto_coincide(q_norm, p.name) or _texto_coincide(q_norm, p.description)
            if biz_text_match or prod_match:
                item = p.to_dict()
                item['bizId'] = biz.id
                item['bizName'] = biz.name
                item['bizIsOpenNow'] = biz.is_open_now()
                results.append(item)

    return jsonify(results)


# ---------- PANEL DEL NEGOCIO (dueño autenticado) ----------

@business_bp.route('/business/me', methods=['GET'])
@role_required('business')
def get_my_business():
    """A diferencia de editar, DEJAMOS ver el negocio aunque la membresía
    esté suspendida — así el dueño no queda completamente a ciegas, solo
    no puede guardar cambios hasta regularizar el pago."""
    business = Business.query.get(get_jwt_identity())
    data = business.to_owner_dict()
    data['canEdit'] = business.is_access_allowed
    return jsonify(data)


@business_bp.route('/business/me', methods=['PUT'])
@business_access_required
def update_my_business():
    business = Business.query.get(get_jwt_identity())
    data = request.get_json(silent=True) or {}

    # Mapea el nombre que manda el frontend -> el atributo real del modelo
    field_map = {
        'address': 'address', 'phone': 'phone', 'whatsapp': 'whatsapp',
        'instagram': 'instagram', 'facebook': 'facebook', 'website': 'website',
        'description': 'description', 'category': 'category',
        'avatarUrl': 'avatar_url', 'coverUrl': 'cover_url',
    }
    old_address = business.address
    for incoming_field, model_field in field_map.items():
        if incoming_field in data:
            value = data.get(incoming_field)
            setattr(business, model_field, value.strip() if isinstance(value, str) else value)

    if 'hours' in data:
        business.hours = _clean_hours(data.get('hours'))

    # Volvemos a ubicar en el mapa si cambió la dirección, O si la dirección
    # ya está cargada pero todavía no tiene coordenadas (por ejemplo, porque
    # el intento anterior falló por un límite de pedidos del servicio de
    # mapas) -- así el próximo guardado reintenta solo, sin que dependas de
    # cambiar algo en el texto para forzarlo. Si falla, no rompe el resto.
    direccion_cambio = 'address' in data and business.address and business.address != old_address
    sin_coordenadas_todavia = business.address and (business.lat is None or business.lng is None)
    if direccion_cambio or sin_coordenadas_todavia:
        lat, lng = geocode_address(business.address)
        if lat is not None:
            business.lat = lat
            business.lng = lng

    db.session.commit()
    return jsonify(business.to_owner_dict())


@business_bp.route('/business/me', methods=['DELETE'])
@business_access_required
def delete_my_business():
    """El propio negocio se da de baja desde su panel. No borra sus datos
    de la base -- pasa la membresía a 'cancelled', el mismo estado que ya
    usa el sistema para "dio de baja el servicio por su cuenta" (ver
    SUBSCRIPTION_STATUSES en models.py). Con eso alcanza para que:
    - desaparezca de la búsqueda pública al instante (is_publicly_visible)
    - no pueda volver a entrar a su panel con esta cuenta (is_access_allowed)
    Se guarda el historial en vez de borrarlo de verdad porque sirve para
    la facturación/membresías propias, y porque así, si se dio de baja por
    error, un administrador lo puede reactivar sin que el negocio tenga
    que cargar todo el catálogo de nuevo desde cero.
    """
    business = Business.query.get(get_jwt_identity())
    if not business:
        return jsonify({'error': 'No encontramos tu negocio.'}), 404
    business.subscription_status = 'cancelled'
    db.session.commit()
    return jsonify({'ok': True})


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

    images = data.get('images')
    if not isinstance(images, list):
        images = [data.get('image')] if data.get('image') else []
    images = [img for img in images if img]

    product = Product(
        business_id=business.id, name=name, price=price,
        description=(data.get('desc') or '').strip(),
        images=images,
        image_url=images[0] if images else '',
        variant_groups=_clean_variant_groups(data.get('variantGroups')),
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
    if 'images' in data and isinstance(data.get('images'), list):
        images = [img for img in data.get('images') if img]
        product.images = images
        product.image_url = images[0] if images else ''
    elif data.get('image'):
        product.images = [data.get('image')]
        product.image_url = data.get('image')
    if 'variantGroups' in data:
        product.variant_groups = _clean_variant_groups(data.get('variantGroups'))

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
