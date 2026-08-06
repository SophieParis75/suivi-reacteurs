import os
import json
import urllib.request
import urllib.error
import base64
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta, timezone

def get_rte_token(client_id, client_secret):
    url = "https://digital.iservices.rte-france.com/token/oauth/"
    auth_str = f"{client_id}:{client_secret}"
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

            # Plage temporelle : 24h glissantes
            now_utc = datetime.now(timezone.utc)
            start_utc = now_utc - timedelta(days=1)

            start_str = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
            end_str = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

            base_url = "https://digital.iservices.rte-france.com/open_api/unavailability_additional_information/v7/generation_unavailabilities"
            full_url = f"{base_url}?start_date={start_str}&end_date={end_str}"

            req_rte = urllib.request.Request(
                full_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json"
                },
                method="GET"
            )

            with urllib.request.urlopen(req_rte, timeout=15) as resp:
                raw_data = json.loads(resp.read().decode('utf-8'))

            unavailabilities = raw_data.get("generation_unavailabilities", [])

            # 1. Regroupement par identifier pour ne garder que la version la plus récente
            latest_by_identifier = {}
            for item in unavailabilities:
                # Filtrage filière : recherche de la racine "nucl"
                fuel_type = str(item.get("fuel_type", "")).lower()
                if "nucl" not in fuel_type:
                    continue

                identifier = item.get("identifier")
                version = int(item.get("version", 0))

                if identifier not in latest_by_identifier or version > latest_by_identifier[identifier]["version"]:
                    latest_by_identifier[identifier] = item

            # 2. Filtrage et structuration des données nettoyées
            clean_list = []
            total_env_loss_mw = 0

            for item in latest_by_identifier.values():
                remarks = str(item.get("remarks", "")).lower()
                reason = str(item.get("reason", "")).lower()
                
                # Vérification de la contrainte environnementale (racine "environ")
                is_environmental = "environ" in remarks or "environ" in reason

                # Calcul des capacités
                installed_cap = item.get("affected_asset_or_unit_installed_capacity", 0)
               values = item.get("values", [])
if values:
    # On calcule la perte max parmi les tranches du message
    unavailable_cap = max(
        v.get("unavailable_capacity", installed_cap - v.get("available_capacity", installed_cap)) 
        for v in values
    )
    available_cap = installed_cap - unavailable_cap
else:
    available_cap = installed_cap
    unavailable_cap = 0

                if is_environmental:
                    total_env_loss_mw += unavailable_cap

                clean_list.append({
                    "identifier": item.get("identifier"),
                    "unit_name": item.get("affected_asset_or_unit_name"),
                    "eic_code": item.get("affected_asset_or_unit_eic_code"),
                    "version": item.get("version"),
                    "event_status": item.get("event_status"),
                    "unavailability_type": item.get("unavailability_type"),
                    "start_date": item.get("start_date"),
                    "end_date": item.get("end_date"),
                    "installed_capacity_mw": installed_cap,
                    "available_capacity_mw": available_cap,
                    "unavailable_capacity_mw": unavailable_cap,
                    "is_environmental": is_environmental,
                    "remarks": item.get("remarks"),
                    "reason": item.get("reason")
                })

            response_payload = {
                "status": "success",
                "count": len(clean_list),
                "total_environmental_loss_mw": total_env_loss_mw,
                "data": clean_list
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(response_payload).encode('utf-8'))

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='ignore')
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "HTTPError",
                "code": e.code,
                "rte_response": error_body
            }).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "Exception",
                "message": str(e)
            }).encode('utf-8'))
