import os
import getpass

import click
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from sqlalchemy import inspect, text
from dotenv import load_dotenv

from models import db, Admin

load_dotenv()


def _sql_literal(valor):
    """Convierte un valor por defecto de Python (True, 5, 'texto', etc.) al
    literal SQL equivalente, para poder incluirlo en un ALTER TABLE."""
    if isinstance(valor, bool):
        return 'true' if valor else 'false'
    if isinstance(valor, (int, float)):
        return str(valor)
    return "'" + str(valor).replace("'", "''") + "'"


def _sync_missing_columns(app):
    """
    Agrega automáticamente, al arrancar, cualquier columna que exista en los
    modelos (models.py) pero todavía no en la base de datos real -- pasa
    cuando se agrega un campo nuevo a un modelo (ej: "activo" en Admin) y la
    tabla ya existía de antes con filas, así que create_all() no la vuelve a
    crear desde cero (create_all solo agrega TABLAS que faltan, no columnas
    nuevas en una que ya existe).

    - Si la columna es nullable, se agrega tal cual.
    - Si es NOT NULL y el modelo le definió un default fijo (ej. default=True),
      se agrega con ese mismo default a nivel de base de datos, así las filas
      que ya existen se completan solas sin quedar inválidas.
    - Si es NOT NULL sin default y la tabla ya tiene filas, se salta (no hay
      forma segura de agregarla sola sin arriesgar romper datos existentes).
    """
    with app.app_context():
        inspector = inspect(db.engine)
        for table in db.metadata.tables.values():
            if not inspector.has_table(table.name):
                continue
            existing_cols = {c['name'] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue

                tiene_default_fijo = col.default is not None and not callable(getattr(col.default, 'arg', None))
                default_sql = _sql_literal(col.default.arg) if tiene_default_fijo else None

                if not col.nullable and default_sql is None:
                    with db.engine.connect() as conn:
                        cantidad_filas = conn.execute(text(f'SELECT COUNT(*) FROM "{table.name}"')).scalar()
                    if cantidad_filas > 0:
                        print(f'[aviso] columna {table.name}.{col.name} es NOT NULL sin default y la tabla tiene {cantidad_filas} filas -- no se puede agregar sola.')
                        continue

                col_type = col.type.compile(db.engine.dialect)
                partes = [col_type]
                if default_sql is not None:
                    partes.append(f'DEFAULT {default_sql}')
                if not col.nullable:
                    partes.append('NOT NULL')

                with db.engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {" ".join(partes)}'))
                print(f'[info] columna agregada automáticamente: {table.name}.{col.name}')


def create_app():
    app = Flask(__name__)

    db_url = os.environ.get('DATABASE_URL', 'sqlite:///cadeteria_centro.db')
    # Render entrega DATABASE_URL como "postgres://...". SQLAlchemy necesita "postgresql://...",
    # y le indicamos que use el driver psycopg (v3), que sí tiene soporte para versiones
    # nuevas de Python (a diferencia de psycopg2, que se quedó atrás).
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql+psycopg://', 1)
    elif db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+psycopg://', 1)

    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET_KEY', 'cambiar-en-produccion')
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = 60 * 60 * 24 * 30  # 30 días

    db.init_app(app)
    Migrate(app, db)
    JWTManager(app)

    origins = [o.strip() for o in os.environ.get('CORS_ORIGINS', '*').split(',') if o.strip()]
    CORS(app, resources={r'/api/*': {'origins': origins or '*'}})

    from routes_auth import auth_bp
    from routes_business import business_bp
    from routes_trips import trips_bp
    from routes_admin import admin_bp
    from routes_banners import banners_bp
    from webhooks import webhooks_bp
    from routes_setup import setup_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(business_bp)
    app.register_blueprint(trips_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(banners_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(setup_bp)

    # El plan gratuito de Render no da acceso a una consola (Shell), así que
    # en vez de depender de "flask db upgrade" a mano, creamos las tablas
    # que falten automáticamente cada vez que arranca la app. Es seguro:
    # create_all() nunca borra ni pisa tablas que ya existen, solo agrega
    # las que faltan.
    with app.app_context():
        db.create_all()
    _sync_missing_columns(app)

    @app.route('/api/health', methods=['GET'])
    def health():
        return jsonify({'status': 'ok'})

    @app.cli.command('create-admin')
    def create_admin():
        """Uso: flask create-admin  (te pregunta email y contraseña por consola)"""
        email = input('Email del admin: ').strip().lower()
        if Admin.query.filter_by(email=email).first():
            click.echo('Ya existe un admin con ese email.')
            return
        password = getpass.getpass('Contraseña: ')
        password2 = getpass.getpass('Repetí la contraseña: ')
        if password != password2:
            click.echo('Las contraseñas no coinciden.')
            return
        if len(password) < 8:
            click.echo('Usá una contraseña de al menos 8 caracteres.')
            return
        admin = Admin(email=email, name='Administrador')
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        click.echo(f'Admin creado: {email}')

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
