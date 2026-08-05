from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.parse
import urllib.error
import base64

class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        # Récupération des paramètres d'URL (ex: ?start_date=...&end_date=...)
        parsed_path = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed_path.query)
        
        start_date = params.get('start_date', [None])[0]
        end_date = params.get('end_date', [None])[0]

        # Clés API RTE (à configurer dans les variables d'environnement Vercel)
        client_id = os.environ.get('RTE_CLIENT_ID', '')
        client_secret = os.environ.get('RTE_CLIENT_SECRET', '')

        if not client_id or not client_secret:
            self._send_json(500, {
                "error": "Configuration manquante",
                "details": "RTE_CLIENT_ID ou RTE_CLIENT_SECRET absent des variables d'environnement Vercel."
            })
            return

        try:
            # 1. Obtention du token OAuth2 RTE
            auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            token_url = "https://digital.iservices.rte-france.com/token/oauth/"
            
            token_req = urllib.request.Request(
                token_url,
                data=b"grant_type=client_credentials",
                headers={
                    "Authorization": f"Basic {auth_header}",
                    "Content-Type": "application/x-www-form-urlencoded"
                },
                method="POST"
            )
            
            with urllib.request.urlopen(token_req) as resp:
                token_data = json.loads(resp.read().decode())
                access_token = token_data.get("access_token")

            # 2. Appel de l'API Unavailabilities RTE
            api_url = "https://digital.iservices.rte-france.com/open_api/unavailability_additional_information/v4/generation_unavailabilities"
            
            query_params = {}
            if start_date: query_params['start_date'] = start_date
            if end_date: query_params['end_date'] = end_date
            
            if query_params:
                api_url += "?" + urllib.parse.urlencode(query_params)

            api_req = urllib.request.Request(
                api_url,
                headers={"Authorization": f"Bearer {access_token}"},
                method="GET"
            )

            with urllib.request.urlopen(api_req) as resp:
                data = json.loads(resp.read().decode())
                self._send_json(200, data)

        except urllib.error.HTTPError as e:
            # Traitement spécifique RTE 404 = Pas d'indisponibilité sur la période
            if e.code == 404:
                self._send_json(200, {"generation_unavailabilities": []})
            else:
                try:
                    error_body = e.read().decode('utf-8')
                except Exception:
                    error_body = str(e)
                self._send_json(e.code, {
                    "error": f"RTE API HTTP {e.code}",
                    "details": error_body
                })

        except Exception as e:
            self._send_json(500, {
                "error": "Erreur serveur interne",
                "details": str(e)
            })

    def _send_json(self, status_code, data):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
