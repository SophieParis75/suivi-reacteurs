import os
import json
import urllib.request
import urllib.parse
import base64

def app(environ, start_response):
    try:
        client_id = os.environ.get("RTE_CLIENT_ID")
        client_secret = os.environ.get("RTE_CLIENT_SECRET")

        if not client_id or not client_secret:
            start_response('500 Internal Server Error', [('Content-Type', 'text/plain; charset=utf-8')])
            return ["Erreur : Clés RTE_CLIENT_ID ou RTE_CLIENT_SECRET manquantes sur Vercel".encode('utf-8')]

        # 1. OAuth RTE
        url_token = "https://digital.iservices.rte-france.com/token/oauth/"
        auth_str = f"{client_id}:{client_secret}"
        b64_auth = base64.b64encode(auth_str.encode()).decode()

        req = urllib.request.Request(
            url_token, 
            data="grant_type=client_credentials".encode(), 
            headers={"Authorization": f"Basic {b64_auth}", "Content-Type": "application/x-www-form-urlencoded"}, 
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=10) as resp:
            token = json.loads(resp.read().decode())["access_token"]

        # 2. Requête brute à RTE du 9 au 11 août 2026
        url_api = "https://digital.iservices.rte-france.com/open_api/unavailability_additional_information/v7/generation_unavailabilities?start_date=2026-08-09T00:00:00Z&end_date=2026-08-11T23:59:59Z&date_type=EVENT_DATE&last_version=true"

        req_rte = urllib.request.Request(url_api, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        with urllib.request.urlopen(req_rte, timeout=20) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        items = data.get("generation_unavailabilities", [])

        # Déduplication par version la plus récente
        latest = {}
        for item in items:
            ident = item.get("identifier")
            ver = int(item.get("version", 0))
            if ident not in latest or ver > latest[ident]["version"]:
                latest[ident] = item

        # Filtrage ciblé sur les 3 réacteurs
        results = []
        for item in latest.values():
            name = str(item.get("affected_asset_or_unit_name") or "")
            if any(target in name.upper() for target in ["ST ALBAN 1", "ST ALBAN 2", "TRICASTIN 4"]):
                results.append({
                    "reactor": name,
                    "identifier": item.get("identifier"),
                    "version": item.get("version"),
                    "event_status": item.get("event_status"),
                    "message_status": item.get("message_status"),
                    "fuel_type": item.get("fuel_type"),
                    "remarks": item.get("remarks"),
                    "reason": item.get("reason"),
                    "type": item.get("type"),
                    "values": item.get("values")
                })

        output = {
            "nombre_de_reacteurs_trouves": len(results),
            "donnees_brutes_rte": results
        }

        start_response('200 OK', [('Content-Type', 'application/json; charset=utf-8')])
        return [json.dumps(output, indent=2, ensure_ascii=False).encode('utf-8')]

    except Exception as e:
        start_response('500 Internal Server Error', [('Content-Type', 'text/plain; charset=utf-8')])
        return [f"Erreur pendant le test : {str(e)}".encode('utf-8')]

handler = app
