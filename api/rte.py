import os
import json
import urllib.request
import urllib.parse
import urllib.error
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta

def get_rte_token(client_id, client_secret):
    url = "https://digital.iservices.rte-france.com/token/oauth/"
    auth_str = f"{client_id}:{client_secret}"
    import base64
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = "grant_type=client_credentials".encode('utf-8')
    
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        res_data = json.loads(resp.read().decode())
        return res_data.get("access_token")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            client_id = os.environ.get("RTE_CLIENT_ID")
            client_secret = os.environ.get("RTE_CLIENT_SECRET")

            if not client_id or not client_secret:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "RTE_CLIENT_ID ou RTE_CLIENT_SECRET manquant sur Vercel"}).encode('utf-8'))
                return

            token = get_rte_token(client_id, client_secret)

            # Dates sur 24h avec fuseau +02:00 tel que requis par RTE (API v7.0)
            now = datetime.now()
            start_dt = now - timedelta(days=1)
            
            # Format ex: 2026-08-04T00:00:00+02:00
            start_str = start_dt.strftime('%Y-%m-%dT00:00:00+02:00')
            end_str = now.strftime('%Y-%m-%dT23:59:59+02:00')

            # URL V7 exacte selon la documentation officielle
            rte_base_url = "https://digital.iservices.rte-france.com/open_api/unavailability_additional_information/v7/generation_unavailabilities"
            
            # Paramètres conformes V7
            params = urllib.parse.urlencode({
                "start_date": start_str,
                "end_date": end_str,
                "date_type": "created_date"
            })

            full_url = f"{rte_base_url}?{params}"

            req_rte = urllib.request.Request(
                full_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json"
                },
                method="GET"
            )

            with urllib.request.urlopen(req_rte, timeout=15) as resp:
                body = resp.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='ignore')
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "HTTPError",
                "code": e.code,
                "requested_url": full_url if 'full_url' in locals() else None,
                "rte_response": error_body
            }).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "Exception",
                "message": str(e),
                "type": type(e).__name__
            }).encode('utf-8'))
