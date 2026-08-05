from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
import base64
import os

# Récupération des secrets depuis les variables d'environnement Vercel (ou valeurs par défaut)
RTE_CLIENT_ID = os.environ.get("RTE_CLIENT_ID", "7ed7653e-c820-4cbd-8cc9-dbbebca19fce")
RTE_CLIENT_SECRET = os.environ.get("RTE_CLIENT_SECRET", "b5c4687c-9639-4bdc-a9af-5a16898f4476")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed_path.query)
        
        start_date = params.get('start_date', [''])[0]
        end_date = params.get('end_date', [''])[0]

        try:
            # 1. Authentification auprès de RTE
            credentials = f"{RTE_CLIENT_ID}:{RTE_CLIENT_SECRET}"
            encoded_credentials = base64.b64encode(credentials.encode()).decode()
            
            token_req = urllib.request.Request(
                "https://digital.iservices.rte-france.com/token/oauth/",
                headers={
                    "Authorization": f"Basic {encoded_credentials}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                method="POST"
            )
            
            with urllib.request.urlopen(token_req) as token_res:
                token_data = json.loads(token_res.read().decode())
                access_token = token_data.get("access_token")

            # 2. Requête API RTE Unavailabilities
            rte_url = f"https://digital.iservices.rte-france.com/open_api/unavailability/v4/generation_unavailabilities?start_date={urllib.parse.quote(start_date)}&end_date={urllib.parse.quote(end_date)}"
            data_req = urllib.request.Request(
                rte_url,
                headers={"Authorization": f"Bearer {access_token}"}
            )

            with urllib.request.urlopen(data_req) as data_res:
                response_data = data_res.read().decode()

            # 3. Réponse JSON au navigateur sans blocage CORS
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(response_data.encode())

        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())
