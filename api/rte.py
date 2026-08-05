import os
import json
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from datetime import datetime
import zoneinfo

def get_rte_token():
    # Récupération des identifiants stockés dans Vercel
    client_id = os.environ.get("RTE_CLIENT_ID")
    client_secret = os.environ.get("RTE_CLIENT_SECRET")
    
    # Authentification OAuth RTE (Basic Auth)
    url = "https://digital.iservices.rte-france.com/token/oauth/"
    response = requests.post(
        url,
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    response.raise_for_status()
    return response.json().get("access_token")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query_components = parse_qs(urlparse(self.path).query)
        start_date_raw = query_components.get('start_date', [None])[0]
        end_date_raw = query_components.get('end_date', [None])[0]

        if not start_date_raw or not end_date_raw:
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Missing start_date or end_date"}).encode('utf-8'))
            return

        try:
            # 1. Conversion et formatage strict pour le fuseau heure d'été de Paris (+02:00)
            # Accepte le format ISO transmis par le front et force le décalage RTE attendu
            paris_tz = zoneinfo.ZoneInfo("Europe/Paris")
            
            # Nettoyage des ISO passés en paramètre
            start_dt = datetime.fromisoformat(start_date_raw.replace('Z', '+00:00')).astimezone(paris_tz)
            end_dt = datetime.fromisoformat(end_date_raw.replace('Z', '+00:00')).astimezone(paris_tz)

            # Format requis par RTE: YYYY-MM-DDTHH:mm:ss+02:00
            formatted_start = start_dt.strftime('%Y-%m-%d T%H:%M:%S%z')
            formatted_start = formatted_start.replace(' ', '').replace('00', ':00') if formatted_start.endswith('00') else formatted_start
            # Utilisation du formateur ISO standard
            rte_start = start_dt.isoformat(timespec='seconds')
            rte_end = end_dt.isoformat(timespec='seconds')

            # 2. Obtention du token OAuth
            token = get_rte_token()

            # 3. Appel de l'API RTE Generation Unavailabilities
            rte_url = "https://digital.iservices.rte-france.com/open_api/generation_unavailabilities/v4/generation_unavailabilities"
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }
            
            params = {
                "start_date": rte_start,
                "end_date": rte_end
            }

            rte_res = requests.get(rte_url, headers=headers, params=params)
            
            self.send_response(rte_res.status_code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(rte_res.content)

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
