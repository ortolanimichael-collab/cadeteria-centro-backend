import os
import getpass

import click
from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from dotenv import load_dotenv

from models import db, Admin

load_dotenv()


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
