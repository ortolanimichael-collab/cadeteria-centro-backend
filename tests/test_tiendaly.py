import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['TIENDALY_URL'] = 'https://tiendaly.test'
os.environ['TIENDALY_CANAL_CLAVE'] = 'clave-de-prueba'
os.environ['JWT_SECRET_KEY'] = 'test'

import tiendaly_sync  # noqa: E402
from app import app as flask_app  # noqa: E402
from models import db, Business, Product, SiteEvent, Admin  # noqa: E402

NEGOCIOS = {'negocios': [{
    'id': 7, 'nombre': 'Pizzería Don Juan', 'slug': 'don-juan', 'url': 'https://tiendaly.ar/don-juan',
    'rubro': 'gastronomia', 'descripcion': 'Pizzas', 'whatsapp': '+54 9 3794 11-2233', 'telefono': '',
    'direccion': 'Junín 100', 'horarios': {'dias': {'0': [['09:00', '13:00'], ['17:00', '23:00']], '6': []}},
}]}
PRODUCTOS = {'productos': [{'id': 1, 'nombre': 'Pizza muzzarella', 'precio': 9000, 'descripcion': 'Grande', 'foto': ''}]}


@pytest.fixture
def cli(monkeypatch):
    flask_app.config['TESTING'] = True
    with flask_app.app_context():
        db.drop_all(); db.create_all()
    estado = {'neg': NEGOCIOS, 'prod': PRODUCTOS, 'code': 200}

    def falso_get(ruta):
        if estado['code'] != 200:
            return estado['code'], {}
        if '/productos' in ruta:
            return 200, estado['prod']
        if ruta.startswith('/api/canal/negocios'):
            return 200, estado['neg']
        return 200, {'mes': '2026-10', 'tiendas_activas': 1}
    monkeypatch.setattr(tiendaly_sync, '_get', falso_get)
    monkeypatch.setattr(tiendaly_sync, 'asegurar_al_dia', lambda app: None)
    c = flask_app.test_client()
    c.estado = estado
    return c


def test_sincroniza_y_se_ve_en_el_listado(cli):
    with flask_app.app_context():
        assert tiendaly_sync.sincronizar()['ok']
    lista = cli.get('/api/businesses').get_json()
    assert len(lista) == 1 and lista[0]['name'] == 'Pizzería Don Juan'
    assert lista[0]['tiendalyUrl'].endswith('/don-juan')
    r = cli.get('/api/products/search?q=pisa').get_json()   # tolera typos
    assert r and r[0]['name'] == 'Pizza muzzarella'


def test_403_apaga_el_espejo_y_error_conserva(cli):
    with flask_app.app_context():
        tiendaly_sync.sincronizar()
    cli.estado['code'] = 500
    with flask_app.app_context():
        tiendaly_sync.sincronizar()
    assert len(cli.get('/api/businesses').get_json()) == 1
    cli.estado['code'] = 403
    with flask_app.app_context():
        tiendaly_sync.sincronizar()
    assert cli.get('/api/businesses').get_json() == []


def test_negocio_que_sale_de_tiendaly_se_borra(cli):
    with flask_app.app_context():
        tiendaly_sync.sincronizar()
    cli.estado['neg'] = {'negocios': []}
    with flask_app.app_context():
        tiendaly_sync.sincronizar()
        assert Business.query.filter_by(source='tiendaly').count() == 0


def test_negocios_locales_viejos_no_se_muestran(cli):
    with flask_app.app_context():
        b = Business(name='Viejo', category='Pizzería', email='v@x.com'); b.set_password('123456')
        db.session.add(b); db.session.commit()
    assert cli.get('/api/businesses').get_json() == []


def test_registro_y_login_de_negocio_cerrados(cli):
    assert cli.post('/api/auth/register/business', json={}).status_code == 410
    with flask_app.app_context():
        b = Business(name='Viejo', category='Pizzería', email='v@x.com'); b.set_password('123456')
        db.session.add(b); db.session.commit()
    r = cli.post('/api/auth/login', json={'email': 'v@x.com', 'password': '123456'})
    assert r.status_code == 403 and 'Tiendaly' in r.get_json()['error']


def test_rutas_de_panel_de_negocio_ya_no_existen(cli):
    assert cli.get('/api/business/me').status_code == 404
    assert cli.post('/api/webhooks/membership-update', json={}).status_code == 404


def test_track_anonimo(cli):
    assert cli.post('/api/track', json={'kind': 'visit'}).status_code == 201
    assert cli.post('/api/track', json={'kind': 'hack'}).status_code == 400
    assert cli.post('/api/track', json={'kind': 'whatsapp_click', 'businessId': 'no-existe'}).status_code == 201
    with flask_app.app_context():
        assert SiteEvent.query.count() == 2
        assert SiteEvent.query.filter(SiteEvent.business_id.isnot(None)).count() == 0


def _admin(cli):
    with flask_app.app_context():
        a = Admin(email='a@x.com', name='A'); a.set_password('12345678'); db.session.add(a); db.session.commit()
    return {'Authorization': 'Bearer ' + cli.post('/api/auth/login', json={'email': 'a@x.com', 'password': '12345678'}).get_json()['token']}


def test_reporte_admin_y_sync(cli):
    h = _admin(cli)
    assert cli.get('/api/admin/reporte').status_code in (401, 403, 422)
    with flask_app.app_context():
        tiendaly_sync.sincronizar()
        bid = Business.query.first().id
    cli.post('/api/track', json={'kind': 'visit'})
    cli.post('/api/track', json={'kind': 'whatsapp_click', 'businessId': bid})
    rep = cli.get('/api/admin/reporte', headers=h).get_json()
    assert rep['sitio']['visitas'] == 1 and rep['sitio']['clics_whatsapp'] == 1
    assert rep['sitio']['por_negocio'][0]['negocio'] == 'Pizzería Don Juan'
    assert rep['tiendaly']['tiendas_activas'] == 1
    assert cli.post('/api/admin/sync-tiendaly', headers=h).get_json()['ok']
    st = cli.get('/api/admin/stats', headers=h).get_json()
    assert st['businesses'] == 1 and st['products'] == 1


def test_horarios_convertidos(cli):
    h = tiendaly_sync.convertir_horarios(NEGOCIOS['negocios'][0]['horarios'])
    assert h['lun']['ranges'] == [{'open': '09:00', 'close': '13:00'}, {'open': '17:00', 'close': '23:00'}]
    assert h['dom']['closed'] is True


def test_admin_desde_variables_de_entorno(cli, monkeypatch):
    import app as app_mod
    with flask_app.app_context():
        monkeypatch.delenv('ADMIN_EMAIL', raising=False); monkeypatch.delenv('ADMIN_PASSWORD', raising=False)
        assert app_mod.asegurar_admin_desde_entorno() is None
        monkeypatch.setenv('ADMIN_EMAIL', 'Yo@X.com'); monkeypatch.setenv('ADMIN_PASSWORD', 'corta')
        assert app_mod.asegurar_admin_desde_entorno() is None          # contraseña de menos de 8
        monkeypatch.setenv('ADMIN_PASSWORD', 'una-clave-larga')
        assert app_mod.asegurar_admin_desde_entorno() is True          # lo crea
        monkeypatch.setenv('ADMIN_PASSWORD', 'otra-clave-larga')
        assert app_mod.asegurar_admin_desde_entorno() is False         # el mismo email: cambia la contraseña
    r = cli.post('/api/auth/login', json={'email': 'yo@x.com', 'password': 'otra-clave-larga'})
    assert r.status_code == 200 and r.get_json()['type'] == 'admin'
    assert cli.post('/api/auth/login', json={'email': 'yo@x.com', 'password': 'una-clave-larga'}).status_code == 401
