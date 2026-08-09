import os
import json
import urllib.request
import urllib.parse
import urllib.error
import base64
from http.server import BaseHTTPRequestHandler
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PARIS_TZ = ZoneInfo("Europe/Paris")
TOTAL_PARC_CAPACITY_MW = 62990.0  # Total capacity of the French nuclear fleet in MW

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


# ==============================================================================
# START OF CALCULATION RULE - NUCLEAR & ENVIRONMENTAL DEDUPLICATION RULES
# ==============================================================================
def parse_iso_date(dt_str):
    if not dt_str:
        return None
    return datetime.fromisoformat(dt_str).astimezone(PARIS_TZ)

def get_reactor_unavailability_at_instant(values, target_dt, installed_cap):
    """
    Returns the maximum unavailable capacity (MW) and its corresponding time interval
    for a specific timestamp (target_dt) across all values.
    """
    active_slots = []
    for v in values:
        v_start = parse_iso_date(v.get("start_date"))
        v_end = parse_iso_date(v.get("end_date"))
        if v_start and v_end and (v_start <= target_dt < v_end):
            unavail = v.get("unavailable_capacity")
            if unavail is None:
                avail = v.get("available_capacity", installed_cap)
                unavail = installed_cap - avail
            unavail = max(0, unavail)
            active_slots.append((unavail, v.get("start_date"), v.get("end_date")))
    
    if active_slots:
        # Deduplication: retain max unavailable capacity if multiple messages cover target_dt
        return max(active_slots, key=lambda x: x[0])
    
    return 0, None, None

def get_reactor_daily_max_unavailability(values, day_date, installed_cap):
    """
    Calculates the retained unavailability for a full day (day_date).
    Rule applied:
    Retains the largest unavailability among time slots that last
    STRICTLY MORE THAN 30 MINUTES (> 30 min) during that day.
    If no slot lasts strictly more than 30 minutes, returns 0 MW.
    """
    day_start = datetime(day_date.year, day_date.month, day_date.day, 0, 0, 0, tzinfo=PARIS_TZ)
    day_end = day_start + timedelta(days=1)

    eligible_slots = []

    for v in values:
        v_start = parse_iso_date(v.get("start_date"))
        v_end = parse_iso_date(v.get("end_date"))

        if not v_start or not v_end:
            continue

        # Check overlap with target day
        overlap_start = max(v_start, day_start)
        overlap_end = min(v_end, day_end)

        if overlap_start < overlap_end:
            duration_minutes = (overlap_end - overlap_start).total_seconds() / 60.0
            
            unavail = v.get("unavailable_capacity")
            if unavail is None:
                avail = v.get("available_capacity", installed_cap)
                unavail = installed_cap - avail
            unavail = max(0, unavail)

            eligible_slots.append({
                "unavail": unavail,
                "duration_minutes": duration_minutes,
                "start_date": v.get("start_date"),
                "end_date": v.get("end_date")
            })

    # Filter: retain ONLY slots strictly greater than 30 minutes
    slots_over_30min = [s for s in eligible_slots if s["duration_minutes"] > 30]

    if slots_over_30min:
        best_slot = max(slots_over_30min, key=lambda x: x["unavail"])
        return best_slot["unavail"], best_slot["start_date"], best_slot["end_date"]

    return 0, None, None
# ==============================================================================
# END OF CALCULATION RULE
# ==============================================================================


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            query_components = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            
            now_paris = datetime.now(PARIS_TZ)
            t1_str = query_components.get("t1", [now_paris.isoformat()])[0]
            t2_str = query_components.get("t2", [now_paris.isoformat()])[0]

            t1_dt = datetime.fromisoformat(t1_str).astimezone(PARIS_TZ)
            t2_dt = datetime.fromisoformat(t2_str).astimezone(PARIS_TZ)

            client_id = os.environ.get("RTE_CLIENT_ID")
            client_secret = os.environ.get("RTE_CLIENT_SECRET")

            if not client_id or not client_secret:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Missing RTE_CLIENT_ID or RTE_CLIENT_SECRET environment variables"}).encode('utf-8'))
                return

            token = get_rte_token(client_id, client_secret)

            min_dt = min(t1_dt, t2_dt)
            max_dt = max(t1_dt, t2_dt)

            search_start = datetime(min_dt.year, min_dt.month, min_dt.day, 0, 0, 0, tzinfo=PARIS_TZ)
            search_end = datetime(max_dt.year, max_dt.month, max_dt.day, 0, 0, 0, tzinfo=PARIS_TZ) + timedelta(days=2)

            params = urllib.parse.urlencode({
                "start_date": search_start.strftime('%Y-%m-%dT%H:%M:%S%z'),
                "end_date": search_end.strftime('%Y-%m-%dT%H:%M:%S%z')
            })

            base_url = "https://digital.iservices.rte-france.com/open_api/unavailability_additional_information/v7/generation_unavailabilities"
            req_rte = urllib.request.Request(
                f"{base_url}?{params}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                method="GET"
            )

            with urllib.request.urlopen(req_rte, timeout=20) as resp:
                raw_data = json.loads(resp.read().decode('utf-8'))

            unavailabilities = raw_data.get("generation_unavailabilities", [])

            # 1. Keep only the latest version for each message identifier
            latest_by_identifier = {}
            for item in unavailabilities:
                identifier = item.get("identifier")
                version = int(item.get("version", 0))

                if identifier not in latest_by_identifier or version > latest_by_identifier[identifier]["version"]:
                    latest_by_identifier[identifier] = item

            # 2. Filter messages matching both "nuc" and "environ" roots
            filtered_items = []
            for item in latest_by_identifier.values():
                fuel_type = str(item.get("fuel_type") or "").lower()
                remarks = str(item.get("remarks") or "").lower()
                reason = str(item.get("reason") or "").lower()
                asset_name = str(item.get("affected_asset_or_unit_name") or "").lower()

                has_nuc = "nuc" in fuel_type or "nuc" in remarks or "nuc" in reason or "nuc" in asset_name
                has_env = "environ" in remarks or "environ" in reason

                if has_nuc and has_env:
                    filtered_items.append(item)

            # 3. Group all values by reactor (affected_asset_or_unit_name) to avoid duplicate additions
            reactors_data = {}
            for item in filtered_items:
                unit_name = item.get("affected_asset_or_unit_name", "Unknown")
                installed_cap = item.get("affected_asset_or_unit_installed_capacity", 0)
                values = item.get("values", [])

                if unit_name not in reactors_data:
                    reactors_data[unit_name] = {
                        "installed_capacity": installed_cap,
                        "values": []
                    }
                reactors_data[unit_name]["values"].extend(values)

            # 4. Compute deduplicated values per reactor for T1, T2, Day T1 Max, Day T2 Max, Next Day T2 Max
            day_t1 = t1_dt.date()
            day_t2 = t2_dt.date()
            day_t2_next = day_t2 + timedelta(days=1)

            list_t1, list_t2 = [], []
            list_max_t1, list_max_t2, list_max_t2_next = [], [], []

            sum_t1 = sum_t2 = 0
            sum_max_t1 = sum_max_t2 = sum_max_t2_next = 0

            for unit_name, r_info in reactors_data.items():
                installed_cap = r_info["installed_capacity"]
                values = r_info["values"]

                # T1 Instant
                unavail_t1, f_t1, t_t1 = get_reactor_unavailability_at_instant(values, t1_dt, installed_cap)
                if unavail_t1 > 0:
                    sum_t1 += unavail_t1
                    list_t1.append({"reactor": unit_name, "unavailability_mw": unavail_t1, "from": f_t1, "to": t_t1})

                # T2 Instant
                unavail_t2, f_t2, t_t2 = get_reactor_unavailability_at_instant(values, t2_dt, installed_cap)
                if unavail_t2 > 0:
                    sum_t2 += unavail_t2
                    list_t2.append({"reactor": unit_name, "unavailability_mw": unavail_t2, "from": f_t2, "to": t_t2})

                # Day T1 Max
                u_max_t1, f_m_t1, t_m_t1 = get_reactor_daily_max_unavailability(values, day_t1, installed_cap)
                if u_max_t1 > 0:
                    sum_max_t1 += u_max_t1
                    list_max_t1.append({"reactor": unit_name, "unavailability_mw": u_max_t1, "from": f_m_t1, "to": t_m_t1})

                # Day T2 Max
                u_max_t2, f_m_t2, t_m_t2 = get_reactor_daily_max_unavailability(values, day_t2, installed_cap)
                if u_max_t2 > 0:
                    sum_max_t2 += u_max_t2
                    list_max_t2.append({"reactor": unit_name, "unavailability_mw": u_max_t2, "from": f_m_t2, "to": t_m_t2})

                # Next Day T2 Max
                u_max_t2_next, f_m_t2_next, t_m_t2_next = get_reactor_daily_max_unavailability(values, day_t2_next, installed_cap)
                if u_max_t2_next > 0:
                    sum_max_t2_next += u_max_t2_next
                    list_max_t2_next.append({"reactor": unit_name, "unavailability_mw": u_max_t2_next, "from": f_m_t2_next, "to": t_m_t2_next})

            payload = {
                "status": "success",
                "t1_iso": t1_dt.isoformat(),
                "t2_iso": t2_dt.isoformat(),
                "summary": {
                    "t1_unavailability_mw": sum_t1,
                    "t1_percent": round((sum_t1 / TOTAL_PARC_CAPACITY_MW) * 100, 2),
                    "t1_day_max_mw": sum_max_t1,
                    "t1_day_max_percent": round((sum_max_t1 / TOTAL_PARC_CAPACITY_MW) * 100, 2),
                    "t2_unavailability_mw": sum_t2,
                    "t2_percent": round((sum_t2 / TOTAL_PARC_CAPACITY_MW) * 100, 2),
                    "t2_day_max_mw": sum_max_t2,
                    "t2_day_max_percent": round((sum_max_t2 / TOTAL_PARC_CAPACITY_MW) * 100, 2),
                    "t2_next_day_max_mw": sum_max_t2_next,
                    "t2_next_day_max_percent": round((sum_max_t2_next / TOTAL_PARC_CAPACITY_MW) * 100, 2)
                },
                "list_t1": list_t1,
                "list_t2": list_t2,
                "list_max_day_t1": list_max_t1,
                "list_max_day_t2": list_max_t2,
                "list_max_next_day_t2": list_max_t2_next
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))

        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='ignore')
            self.send_response(e.code)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "HTTPError", "code": e.code, "message": error_body}).encode('utf-8'))
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "Exception", "message": str(e)}).encode('utf-8'))
