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
        raise Exception("RTE_CLIENT_ID ou RTE_CLIENT_SECRET manquant dans les variables d'environnement Vercel.")

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
                self.wfile.write(json.dumps({"error": "Missing start_date or end_date"}).encode('utf-8'))
                return

            # Fuseau horaire Paris été (+02:00) défini via timedelta standard
            paris_tz = timezone(timedelta(hours=2))

            # Conversion des dates d'entrée
            start_dt = datetime.fromisoformat(start_date_raw.replace('Z', '+00:00')).astimezone(paris_tz)
            end_dt = datetime.fromisoformat(end_date_raw.replace('Z', '+00:00')).astimezone(paris_tz)

            # Format ISO 8601 strict exigé par l'API RTE : YYYY-MM-DDTHH:mm:ss+02:00
            rte_start = start_dt.strftime('%Y-%m-%dT%H:%M:%S%z')
            rte_end = end_dt.strftime('%Y-%m-%dT%H:%M:%S%z')

            # Formattage du décalage UTC avec les deux-points (+0200 -> +02:00)
            if rte_start[-2:] != ':00' and (rte_start.endswith('+0200') or rte_start.endswith('+0100')):
                rte_start = rte_start[:-2] + ':' + rte_start[-2:]
            if rte_end[-2:] != ':00' and (rte_end.endswith('+0200') or rte_end.endswith('+0100')):
                rte_end = rte_end[:-2] + ':' + rte_end[-2:]

            # Token OAuth RTE
            token = get_rte_token()

            # Appel API RTE
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
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
