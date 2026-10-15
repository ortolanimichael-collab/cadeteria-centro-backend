"""Lee de Tiendaly los negocios y productos que se muestran en Cadetería Centro.

Tiendaly es la dueña de los datos: los negocios se registran y cargan sus productos allá. Este sitio solo LEE lo
público de los que se registraron por Cadetería Centro y aceptaron aparecer (la clave del canal lo garantiza del
otro lado). Lo leído se guarda como copia local (`Business` / `Product` con `source = 'tiendaly'`), así el buscador
que tolera errores de tipeo y todo lo demás siguen funcionando igual y el sitio anda aunque Tiendaly tarde.

Variables de entorno:
  TIENDALY_URL           https://tiendaly.ar
  TIENDALY_CANAL_CLAVE   la clave que genera Tiendaly en Administración > Canales (no la subas al repo)
  TIENDALY_SYNC_MINUTOS  cada cuánto se refresca la copia (por defecto 10)

Si Tiendaly no responde, se conserva la última copia. Si Tiendaly informa que el canal está suspendido, se oculta
la vitrina (la copia no se borra del todo: vuelve cuando el canal se reactive).
"""
import logging
import os
import threading
import time

import requests

from models import db, Business, Product, SUBSCRIPTION_STATUSES

log = logging.getLogger(__name__)

DIAS = ('lun', 'mar', 'mie', 'jue', 'vie', 'sab', 'dom')
# Rubros de Tiendaly -> cómo se muestran acá (los que no están, salen con su nombre)
RUBROS = {
    'gastronomia': 'Gastronomía', 'reposteria': 'Panadería y pastelería', 'cafeteria': 'Cafetería y bar',
    'polleria': 'Pollería', 'carniceria': 'Carnicería', 'verduleria': 'Verdulería', 'almacen': 'Almacén y kiosco',
    'mascotas': 'Mascotas', 'ropa': 'Ropa y accesorios', 'ferreteria': 'Ferretería', 'peluqueria': 'Peluquería',
    'lavanderia': 'Lavandería', 'lavadero': 'Lavadero de autos', 'taller': 'Taller mecánico', 'servicios': 'Servicios',
    'oficios': 'Oficios', 'costura': 'Costura y arreglos', 'impresion3d': 'Impresiones 3D', 'general': 'Comercio',
    'otro': 'Otro',
}

_estado = {'ultima': 0.0, 'corriendo': False}
_lock = threading.Lock()


def configurado():
    return bool(os.environ.get('TIENDALY_URL') and os.environ.get('TIENDALY_CANAL_CLAVE'))


def _intervalo():
    try:
        return max(1, int(os.environ.get('TIENDALY_SYNC_MINUTOS', '10'))) * 60
    except ValueError:
        return 600


def _get(ruta):
    url = os.environ['TIENDALY_URL'].rstrip('/') + ruta
    r = requests.get(url, headers={'X-Canal-Clave': os.environ['TIENDALY_CANAL_CLAVE']}, timeout=20)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def convertir_horarios(h):
    """Horarios de Tiendaly ({'dias': {'0': [['08:00','13:00'], ...]}}, 0 = lunes) al formato de este sitio."""
    out = {}
    dias = (h or {}).get('dias') or {}
    for i, dia in enumerate(DIAS):
        franjas = [f for f in (dias.get(str(i)) or []) if isinstance(f, (list, tuple)) and len(f) == 2 and f[0] and f[1]]
        out[dia] = {'closed': False, 'ranges': [{'open': a, 'close': b} for a, b in franjas]} if franjas else {'closed': True}
    return out if any(not v.get('closed') for v in out.values()) else {}


def _aplicar_negocio(b, d):
    b.source = 'tiendaly'
    b.tiendaly_id = d['id']
    b.tiendaly_slug = d.get('slug')
    b.tiendaly_url = d.get('url') or ''
    b.name = (d.get('nombre') or '')[:120]
    b.rubro_tiendaly = d.get('rubro')
    b.category = RUBROS.get(d.get('rubro') or '', (d.get('rubro') or 'Otro').title())
    b.email = f"tiendaly-{d['id']}@tiendaly.invalid"      # no es un email real: esta cuenta no puede iniciar sesión
    b.password_hash = '!'
    b.address = d.get('direccion') or ''
    b.whatsapp = d.get('whatsapp') or ''
    b.phone = b.whatsapp
    b.instagram = d.get('instagram') or ''
    b.description = d.get('descripcion') or ''
    b.avatar_url = d.get('logo') or ''
    b.cover_url = d.get('portada') or ''
    b.hours = convertir_horarios(d.get('horarios'))
    b.lat, b.lng = d.get('lat'), d.get('lng')
    b.subscription_status = 'active'


def _aplicar_productos(b, items):
    actuales = {p.tiendaly_id: p for p in b.products if p.tiendaly_id is not None}
    vistos = set()
    for it in items:
        p = actuales.get(it['id'])
        if p is None:
            p = Product(business_id=b.id, tiendaly_id=it['id'])
            db.session.add(p)
        p.name = (it.get('nombre') or '')[:150]
        p.price = it.get('precio') or 0
        p.description = it.get('descripcion') or ''
        foto = it.get('foto') or ''
        p.image_url, p.images = foto, ([foto] if foto else [])
        if p.variant_groups is None:
            p.variant_groups = []
        vistos.add(it['id'])
    for tid, p in actuales.items():
        if tid not in vistos:
            db.session.delete(p)


def sincronizar():
    """Refresca la copia local. Devuelve {'ok', 'negocios', 'productos', 'error'}. Nunca levanta excepciones."""
    if not configurado():
        return {'ok': False, 'error': 'Falta configurar TIENDALY_URL y TIENDALY_CANAL_CLAVE.'}
    try:
        estado, data = _get('/api/canal/negocios')
        if estado == 403:
            # el canal está suspendido en Tiendaly: se oculta la vitrina, sin borrar la copia
            for b in Business.query.filter_by(source='tiendaly').all():
                b.subscription_status = 'cancelled'
            db.session.commit()
            return {'ok': False, 'error': 'El canal está suspendido en Tiendaly.'}
        if estado != 200:
            return {'ok': False, 'error': f'Tiendaly respondió {estado}: se conserva la última copia.'}
        remotos = {d['id']: d for d in data.get('negocios', [])}
        locales = {b.tiendaly_id: b for b in Business.query.filter_by(source='tiendaly').all()}
        total_prod = 0
        for tid, d in remotos.items():
            b = locales.get(tid)
            if b is None:
                b = Business(source='tiendaly', tiendaly_id=tid, name=d.get('nombre') or '', category='Otro',
                             email=f'tiendaly-{tid}@tiendaly.invalid', password_hash='!')
                db.session.add(b)
                db.session.flush()
            _aplicar_negocio(b, d)
            est, prods = _get(f'/api/canal/negocios/{tid}/productos')
            if est == 200:
                items = prods.get('productos', [])
                _aplicar_productos(b, items)
                total_prod += len(items)
            else:
                total_prod += len(b.products)
        for tid, b in locales.items():
            if tid not in remotos:       # ya no aparece (retiró el consentimiento, se ocultó, se dio de baja)
                db.session.delete(b)
        db.session.commit()
        return {'ok': True, 'negocios': len(remotos), 'productos': total_prod}
    except requests.RequestException as exc:
        db.session.rollback()
        log.warning('No se pudo leer Tiendaly: %s', exc)
        return {'ok': False, 'error': 'No se pudo conectar con Tiendaly: se conserva la última copia.'}
    except Exception:
        db.session.rollback()
        log.exception('Falló la sincronización con Tiendaly')
        return {'ok': False, 'error': 'Falló la sincronización.'}


def asegurar_al_dia(app):
    """Se llama antes de mostrar negocios. Si la copia está vieja, la refresca en segundo plano (sin hacer esperar a
    nadie); si todavía no hay ninguna, espera la primera lectura."""
    if not configurado():
        return
    ahora = time.time()
    if ahora - _estado['ultima'] < _intervalo() or _estado['corriendo']:
        return
    with _lock:
        if ahora - _estado['ultima'] < _intervalo() or _estado['corriendo']:
            return
        _estado['corriendo'] = True

    def tarea():
        try:
            with app.app_context():
                sincronizar()
        finally:
            _estado['ultima'] = time.time()
            _estado['corriendo'] = False

    vacia = Business.query.filter_by(source='tiendaly').first() is None
    if vacia:
        tarea()                      # primera vez: se espera, para no mostrar un listado vacío
    else:
        threading.Thread(target=tarea, daemon=True).start()
