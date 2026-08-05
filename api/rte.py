import os
import json
import urllib.request
import urllib.parse
import urllib.error
from http.server import BaseHTTPRequestHandler

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
            query_components = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            start_date_raw = query_components.get('start_date', [None])[0]
            end_date_raw = query_components.get('end_date', [None])[0]

            if not start_date_raw or not end_date_raw:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing start_date or end_date"}).encode('utf-8'))
                return

            client_id = os.environ.get("RTE_CLIENT_ID")
            client_secret = os.environ.get("RTE_CLIENT_SECRET")

            if not client_id or not client_secret:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Variables d'environnement RTE_CLIENT_ID ou RTE_CLIENT_SECRET non définies sur Vercel"}).encode('utf-8'))
                return

            # Nettoyage et formatage strict ISO 8601 (+02:00) requis par l'API RTE
            start_clean = start_date_raw.split('.')[0] if '.' in start_date_raw else start_date_raw
            end_clean = end_date_raw.split('.')[0] if '.' in end_date_raw else end_date_raw
            
            if not start_clean.endswith('+02:00') and not start_clean.endswith('Z'):
                start_clean += "+02:00"
            else:
                start_clean = start_clean.replace('Z', '+02:00')

            if not end_clean.endswith('+02:00') and not end_clean.endswith('Z'):
                end_clean += "+02:00"
            else:
                end_clean = end_clean.replace('Z', '+02:00')

            # Obtenir le token d'accès OAuth
            token = get_rte_token(client_id, client_secret)

            # Requête vers l'API RTE
            rte_url = f"https://digital.iservices.rte-france.com/open_api/generation_unavailabilities/v4/generation_unavailabilities?start_date={urllib.parse.quote(start_clean)}&end_date={urllib.parse.quote(end_clean)}"
            
            req_rte = urllib.request.Request(
                rte_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json"
                },
                method="GET"
            )

            with urllib.request.urlopen(req_rte, timeout=15) as resp:
                body = resp.read()
                self.send_response(resp.status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='ignore')
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error_from_rte": error_body, "code": e.code}).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e), "type": type(e).__name__}).encode('utf-8'))
