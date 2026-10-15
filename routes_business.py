import re
import unicodedata
import difflib

from flask import Blueprint, request, jsonify, current_app

import tiendaly_sync
from models import Business

business_bp = Blueprint('business', __name__, url_prefix='/api')


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


# ---------- PÚBLICO ----------

def _visibles():
    """Solo se muestran los negocios que vienen de Tiendaly (la copia local) y no están dados de baja."""
    return Business.query.filter(Business.source == 'tiendaly', Business.subscription_status != 'cancelled')


@business_bp.route('/businesses', methods=['GET'])
def list_businesses():
    """Listado público. Filtros opcionales: ?category=Pizzería o
    ?category=Rotisería,Pizzería,Panadería (varios rubros a la vez, para
    los chips agrupados del frontend, ej. "Comidas")."""
    tiendaly_sync.asegurar_al_dia(current_app._get_current_object())
    categorias = _categorias_del_filtro(request.args.get('category'))
    query = _visibles()
    if categorias:
        query = query.filter(Business.category.in_(categorias))
    businesses = query.order_by(Business.created_at.desc()).all()
    return jsonify([b.to_public_dict() for b in businesses])


@business_bp.route('/businesses/<business_id>', methods=['GET'])
def get_business(business_id):
    business = _visibles().filter(Business.id == business_id).first()
    if not business:
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
    tiendaly_sync.asegurar_al_dia(current_app._get_current_object())
    categorias = _categorias_del_filtro(request.args.get('category'))

    query = _visibles()
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
