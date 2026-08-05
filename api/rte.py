import os
import json
import requests
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timezone, timedelta

def get_rte_token():
    client_id = os.environ.get("RTE_CLIENT_ID")
    client_secret = os.environ.get("RTE_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        raise Exception("RTE_CLIENT_ID ou RTE_CLIENT_SECRET manquant dans les variables Vercel.")

    url = "https://digital.iservices.rte-france.com/token/oauth/"
    response = requests.post(
        url,
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10
    )
    response.raise_for_status()
    return response.json().get("access_token")

def parse_iso_date(date_str):
    """ Parse la date de façon tolérante aux formats JS/ISO """
    clean_str = date_str.replace('Z', '+00:00')
    if '.' in clean_str:
        # Supprime les millisecondes si présent pour éviter les erreurs de parsing
        main_part, rest = clean_str.split('.', 1)
        if '+' in rest:
            tz_part = '+' + rest.split('+', 1)[1]
        elif '-' in rest:
            tz_part = '-' + rest.split('-', 1)[1]
        else:
            tz_part = ''
        clean_str = main_part + tz_part

    return datetime.fromisoformat(clean_str)

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            query_components = parse_qs(urlparse(self.path).query)
            start_date_raw = query_components.get('start_date', [None])[0]
            end_date_raw = query_components.get('end_date', [None])[0]

            if not start_date_raw or not end_date_raw:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Paramètres start_date ou end_date manquants"}).encode('utf-8'))
                return

            # Fuseau horaire Europe/Paris en été (+02:00)
            paris_tz = timezone(timedelta(hours=2))

            # Parsing sécurisé et conversion vers le fuseau Paris
            start_dt = parse_iso_date(start_date_raw).astimezone(paris_tz)
            end_dt = parse_iso_date(end_date_raw).astimezone(paris_tz)

            # Formatage strict ISO 8601 pour RTE (ex: 2026-08-02T00:00:00+02:00)
            rte_start = start_dt.strftime('%Y-%m-%dT%H:%M:%S+02:00')
            rte_end = end_dt.strftime('%Y-%m-%dT%H:%M:%S+02:00')

            # Token et appel à RTE
            token = get_rte_token()
            rte_url = "https://digital.iservices.rte-france.com/open_api/generation_unavailabilities/v4/generation_unavailabilities"
            
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json"
            }
            params = {
                "start_date": rte_start,
                "end_date": rte_end
            }

            rte_res = requests.get(rte_url, headers=headers, params=params, timeout=15)

            self.send_response(rte_res.status_code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(rte_res.content)

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            # Renvoie le détail exact de l'exception pour voir exactement ce qui plante en cas de souci
            self.wfile.write(json.dumps({"error": str(e), "type": type(e).__name__}).encode('utf-8'))
