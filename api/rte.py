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
            client_id = os.environ.get("RTE_CLIENT_ID")
            client_secret = os.environ.get("RTE_CLIENT_SECRET")

            if not client_id or not client_secret:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Variables d'environnement manquantes"}).encode('utf-8'))
                return

            token = get_rte_token(client_id, client_secret)

            start_date_val = "2026-08-04T00:00:00+02:00"
            end_date_val = "2026-08-05T23:59:59+02:00"

            query_string = f"start_date={urllib.parse.quote(start_date_val)}&end_date={urllib.parse.quote(end_date_val)}&date_type=created_date"
            full_url = f"https://digital.iservices.rte-france.com/open_api/unavailability_additional_information/v7/generation_unavailabilities?{query_string}"

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
