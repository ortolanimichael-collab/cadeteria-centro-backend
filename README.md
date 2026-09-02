# Cadetería Centro — Backend

API en Flask + SQLAlchemy para Cadetería Centro: cuentas de negocios y clientes
de verdad (con contraseñas hasheadas), productos, viajes particulares,
configuración del sitio, y un webhook de ida y vuelta con el panel de
membresías para activar/suspender el acceso de cada negocio.

## Estructura

```
cadeteria-centro-backend/
  app.py              -> arma la app, registra todo, comando `flask create-admin`
  models.py           -> tablas: Business, Product, Client, Admin, TripRequest, SiteSettings
  auth.py             -> decoradores de permisos (@role_required, @business_access_required)
  webhooks.py          -> aviso saliente al panel de membresías + endpoint entrante
  routes_auth.py       -> registro (negocio/cliente) y login
  routes_business.py   -> listado público, búsqueda, panel del negocio (perfil y productos)
  routes_trips.py      -> pedir/cancelar/listar viajes particulares
  routes_admin.py      -> configuración del sitio y estadísticas (solo admin)
  requirements.txt
  Procfile             -> comando de arranque para Render
  .env.example         -> plantilla de variables de entorno
```

## 1. Correrlo en tu máquina (Windows)

```bat
cd C:\src
mkdir cadeteria-centro-backend
cd cadeteria-centro-backend
:: copiá todos estos archivos acá adentro

python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

copy .env.example .env
:: abrí .env y completá los valores (para probar local, DATABASE_URL puede
:: quedar como sqlite:///cadeteria_centro.db, no hace falta Postgres todavía)

set FLASK_APP=app.py
flask db init
flask db migrate -m "inicial"
flask db upgrade

flask create-admin
:: te va a pedir el email y la contraseña del admin por consola

python app.py
:: queda corriendo en http://localhost:5000
```

Probalo con `http://localhost:5000/api/health` — tiene que devolver `{"status":"ok"}`.

## 2. Subir el código a GitHub

Igual que hiciste con el frontend: creá un repo nuevo (por ejemplo
`cadeteria-centro-backend`) en tu cuenta `ortolanimichael-collab`, y subí
todos estos archivos. **Importante:** no subas el archivo `.env` real, solo
`.env.example` — el `.env` con tus claves reales se carga directo en Render
(paso siguiente).

## 3. Crear la base de datos en Render

1. En el dashboard de Render: **New → PostgreSQL**.
2. Ponele un nombre (ej. `cadeteria-centro-db`), dejá la región y el plan Free.
3. Cuando esté lista, copiá el valor de **Internal Database URL** — lo vas a
   pegar como `DATABASE_URL` en el paso siguiente.

## 4. Crear el Web Service en Render

A diferencia del frontend (que es un **Static Site**), esto es un
**Web Service** — corre código de verdad, no son archivos fijos.

1. **New → Web Service**, conectá el repo `cadeteria-centro-backend`.
2. **Build Command:** `pip install -r requirements.txt`
3. **Start Command:** `gunicorn app:app`
4. En la sección **Environment**, cargá estas variables (con tus valores reales):
   - `DATABASE_URL` → la Internal Database URL que copiaste en el paso 3
   - `JWT_SECRET_KEY` → una clave larga y random (podés generarla con
     `python -c "import secrets; print(secrets.token_hex(32))"`)
   - `CORS_ORIGINS` → la URL de tu frontend en Render, ej.
     `https://cadeteria-centro.onrender.com`
   - `PANEL_MEMBRESIAS_URL` → la URL de tu panel de membresías
   - `PANEL_MEMBRESIAS_API_KEY` → una clave que definas vos y configures
     también del lado del panel de membresías, para autenticar el aviso
     saliente
   - `MEMBERSHIP_WEBHOOK_SECRET` → otra clave que definas vos y configures
     también del lado del panel de membresías, para autenticar los avisos
     que **el panel te manda a vos**
5. **Create Web Service.** Cuando termine el primer deploy, Render te da una
   URL como `https://cadeteria-centro-backend.onrender.com`.

## 5. Crear las tablas y el admin en Render

Render te deja abrir una consola (Shell) del servicio ya desplegado, desde su
dashboard. Ahí corrés, una sola vez:

```bash
flask db upgrade
flask create-admin
```

## 6. El webhook con el panel de membresías

**Cuando se registra un negocio nuevo acá**, este backend le avisa
automáticamente al panel de membresías con un POST a:

```
POST {PANEL_MEMBRESIAS_URL}/api/webhooks/new-subscriber
Authorization: Bearer {PANEL_MEMBRESIAS_API_KEY}

{
  "product": "cadeteria-centro",
  "external_id": "<id del negocio>",
  "business_name": "...",
  "email": "...",
  "created_at": "..."
}
```

Tu panel de membresías necesita tener ese endpoint (o uno con ese contrato)
para poder recibirlo. Si Facturea ya le avisa al panel de una forma parecida,
lo más prolijo es que este endpoint siga el mismo patrón — avisame cómo es
el de Facturea y lo ajusto para que hablen igual.

**Cuando cambia el estado de pago de un negocio**, tu panel de membresías
tiene que avisarle a este backend con:

```
POST {tu backend}/api/webhooks/membership-update
X-Webhook-Secret: {MEMBERSHIP_WEBHOOK_SECRET}

{
  "external_id": "<id del negocio>",
  "status": "active"   // o "trial" | "suspended" | "cancelled"
}
```

En cuanto llega ese webhook, el negocio queda con ese estado:
- `trial` / `active` → puede entrar a su panel y editar todo con normalidad.
- `suspended` → sigue apareciendo en las búsquedas, pero **no puede** entrar
  a su panel ni editar nada, hasta que se reactive.
- `cancelled` → **desaparece del todo** de las búsquedas y de su página
  pública (dio de baja el servicio).

Si preferís cambiar el estado a mano sin pasar por el panel de membresías,
también hay un endpoint para eso: `PUT /api/admin/businesses/<id>/subscription`
(solo accesible logueado como admin).

## 7. Lo que todavía queda pendiente

- **Reconectar el frontend** (el archivo `index.html`) para que llame a esta
  API en vez de usar el guardado del chat — eso lo hacemos en el próximo
  paso, una vez que confirmes que esto ya está desplegado y funcionando.
- **Imágenes:** por ahora siguen viajando como texto (base64) dentro de la
  base de datos, igual que antes, pero ahora en Postgres, que aguanta mucho
  más que el límite de 5 MB que tenías. El día que se sienta pesado, el
  siguiente paso natural es mover las imágenes a un storage de archivos de
  verdad (S3, Cloudinary, o Firebase Storage) y guardar acá solo el link.
