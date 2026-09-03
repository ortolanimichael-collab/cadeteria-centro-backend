import uuid
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def gen_uuid():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


# Estados posibles de la membresía de un negocio.
# 'trial'     -> recién registrado, todavía no pagó, pero tiene acceso (período de prueba)
# 'active'    -> membresía al día, el panel de membresías confirmó el pago
# 'suspended' -> se le cortó el acceso (dejó de pagar), no puede entrar a su panel
# 'cancelled' -> dio de baja el servicio por su cuenta o se lo dieron de baja definitivamente
SUBSCRIPTION_STATUSES = ('trial', 'active', 'suspended', 'cancelled')


class Business(db.Model):
    __tablename__ = 'businesses'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(60), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)

    address = db.Column(db.String(200), default='')
    phone = db.Column(db.String(40), default='')
    whatsapp = db.Column(db.String(40), default='')
    instagram = db.Column(db.String(150), default='')
    facebook = db.Column(db.String(150), default='')
    website = db.Column(db.String(300), default='')
    description = db.Column(db.Text, default='')
    avatar_url = db.Column(db.Text, default='')
    cover_url = db.Column(db.Text, default='')

    # Ubicación real, para mostrarla en un mapa. Se calculan solos a partir
    # de "address" cuando el negocio guarda su perfil (ver geocoding.py).
    lat = db.Column(db.Float, nullable=True)
    lng = db.Column(db.Float, nullable=True)

    # Horarios de atención: {"lun": {"closed": false, "open": "09:00", "close": "20:00"}, ...}
    hours = db.Column(db.JSON, default=dict)

    subscription_status = db.Column(db.String(20), default='trial', nullable=False)
    subscription_updated_at = db.Column(db.DateTime, default=utcnow)

    created_at = db.Column(db.DateTime, default=utcnow)

    products = db.relationship(
        'Product', backref='business', cascade='all, delete-orphan',
        order_by='Product.created_at'
    )

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_access_allowed(self):
        """False si el negocio no puede entrar a su panel (le cortaron el acceso)."""
        return self.subscription_status in ('trial', 'active')

    @property
    def is_publicly_visible(self):
        """False si la página pública del negocio no debe mostrarse (dio de baja)."""
        return self.subscription_status != 'cancelled'

    def is_open_now(self):
        """True/False según el horario cargado. None si no cargó horarios
        (para que el frontend no muestre nada, en vez de "cerrado" por error)."""
        if not self.hours:
            return None
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            tz = ZoneInfo('America/Argentina/Cordoba')
            now = datetime.now(tz)
            dias = ['lun', 'mar', 'mie', 'jue', 'vie', 'sab', 'dom']
            cfg = self.hours.get(dias[now.weekday()])
            if not cfg or cfg.get('closed'):
                return False
            open_t = datetime.strptime(cfg['open'], '%H:%M').time()
            close_t = datetime.strptime(cfg['close'], '%H:%M').time()
            current_t = now.time()
            if open_t <= close_t:
                return open_t <= current_t <= close_t
            return current_t >= open_t or current_t <= close_t
        except Exception:
            return None

    def to_public_dict(self, include_products=True):
        data = {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'address': self.address,
            'phone': self.phone,
            'whatsapp': self.whatsapp,
            'instagram': self.instagram,
            'facebook': self.facebook,
            'website': self.website,
            'description': self.description,
            'avatarUrl': self.avatar_url,
            'coverUrl': self.cover_url,
            'lat': self.lat,
            'lng': self.lng,
            'hours': self.hours or {},
            'isOpenNow': self.is_open_now(),
            'createdAt': self.created_at.isoformat() if self.created_at else None,
        }
        if include_products:
            data['products'] = [p.to_dict() for p in self.products]
        return data

    def to_owner_dict(self):
        """Igual que to_public_dict pero incluye datos privados (email, estado de membresía)."""
        data = self.to_public_dict()
        data['email'] = self.email
        data['subscriptionStatus'] = self.subscription_status
        return data


class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    business_id = db.Column(db.String(36), db.ForeignKey('businesses.id'), nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.Text, default='')
    image_url = db.Column(db.Text, default='')  # legado: una sola imagen (versión vieja)
    images = db.Column(db.JSON, default=list)   # lista de imágenes (varias fotos por producto)

    # Grupos de opciones para variar el producto, ej:
    # [{"name": "¿Con papas?", "type": "single", "options": [
    #     {"name": "Con papas", "price": 800}, {"name": "Sin papas", "price": 0}
    # ]}]
    # type: "single" (elegí una) o "multiple" (elegí una o más)
    variant_groups = db.Column(db.JSON, default=list)

    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        imgs = self.images if self.images else ([self.image_url] if self.image_url else [])
        return {
            'id': self.id,
            'name': self.name,
            'price': float(self.price),
            'desc': self.description,
            'image': imgs[0] if imgs else '',
            'images': imgs,
            'variantGroups': self.variant_groups or [],
        }


class Client(db.Model):
    """Cuenta de un cliente particular (no dueño de negocio)."""
    __tablename__ = 'clients'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    google_id = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'email': self.email}


class Admin(db.Model):
    __tablename__ = 'admins'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(120), default='Administrador')
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    # Controlado por panel-membresías vía webhook: si se pone en False,
    # el login de admin queda bloqueado hasta que se reactive desde ahí.
    activo = db.Column(db.Boolean, default=True, nullable=False)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)


class TripRequest(db.Model):
    """Pedido de 'viaje particular' (envío que no pasa por ningún negocio)."""
    __tablename__ = 'trip_requests'

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    origin = db.Column(db.String(200), nullable=False)
    destination = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(20), default='pendiente')  # pendiente | cancelado | entregado

    # Quién completa el formulario respecto del envío en sí.
    solicitante_rol = db.Column(db.String(20), default='emisor')  # 'emisor' | 'destinatario'
    # Quién se hace cargo del costo del viaje.
    quien_paga = db.Column(db.String(20), default='emisor')  # 'emisor' | 'destinatario'
    # Si el cadete tiene que pagar algo de su bolsillo al retirar (para
    # después cobrárselo a quien lo recibe), y cuánto aproximadamente.
    requiere_efectivo = db.Column(db.Boolean, default=False)
    monto_efectivo = db.Column(db.String(40), nullable=True)

    # Quién lo pidió, si estaba logueado. owner_type: 'client' | 'business' | None (anónimo)
    owner_type = db.Column(db.String(20), nullable=True)
    owner_id = db.Column(db.String(36), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'origin': self.origin,
            'dest': self.destination,
            'description': self.description,
            'phone': self.phone,
            'status': self.status,
            'solicitanteRol': self.solicitante_rol,
            'quienPaga': self.quien_paga,
            'requiereEfectivo': bool(self.requiere_efectivo),
            'montoEfectivo': self.monto_efectivo,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
        }


class SiteSettings(db.Model):
    """Fila única con la configuración general del sitio (banner, anuncio, whatsapp)."""
    __tablename__ = 'site_settings'

    id = db.Column(db.Integer, primary_key=True)
    hero_title = db.Column(db.String(200), default='')
    hero_subtitle = db.Column(db.Text, default='')
    hero_images = db.Column(db.JSON, default=list)
    logo_url = db.Column(db.Text, default='')
    promo_enabled = db.Column(db.Boolean, default=False)
    promo_text = db.Column(db.String(300), default='')
    cadeteria_whatsapp = db.Column(db.String(40), default='')

    @staticmethod
    def get_singleton():
        settings = SiteSettings.query.get(1)
        if not settings:
            settings = SiteSettings(id=1, hero_images=[])
            db.session.add(settings)
            db.session.commit()
        return settings

    def to_dict(self):
        return {
            'heroTitle': self.hero_title or '',
            'heroSubtitle': self.hero_subtitle or '',
            'heroImages': self.hero_images or [],
            'logoUrl': self.logo_url or '',
            'promoEnabled': bool(self.promo_enabled),
            'promoText': self.promo_text or '',
            'cadeteriaWhatsapp': self.cadeteria_whatsapp or '',
        }
