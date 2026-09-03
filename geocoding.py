import logging

import requests

logger = logging.getLogger(__name__)

NOMINATIM_URL = 'https://nominatim.openstreetmap.org/search'


def geocode_address(address):
    """Convierte una dirección de texto en (lat, lng), usando OpenStreetMap
    (gratis, sin API key). Devuelve (None, None) si no encuentra nada o si
    el servicio falla -- nunca lanza una excepción, para no romper el
    guardado del perfil del negocio por esto."""
    if not address or not address.strip():
        return None, None

    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={'q': address, 'format': 'json', 'limit': 1, 'countrycodes': 'ar'},
            headers={'User-Agent': 'CadeteriaCentro/1.0 (contacto@cadeteriacentro.com)'},
            timeout=8,
        )
        resp.raise_for_status()
        results = resp.json()
        if not results:
            return None, None
        return float(results[0]['lat']), float(results[0]['lon'])
    except Exception as exc:
        logger.warning('No se pudo geocodificar "%s": %s', address, exc)
        return None, None
