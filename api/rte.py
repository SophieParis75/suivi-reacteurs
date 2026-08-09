import os
import json
import urllib.request
import urllib.parse
import urllib.error
import base64
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PARIS_TZ = ZoneInfo("Europe/Paris")
TOTAL_PARC_CAPACITY_MW = 62990.0

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
# CALCULATION RULES
# ==============================================================================
def parse_iso_date(dt_str):
    if not dt_str:
        return None
    return datetime.fromisoformat(dt_str).astimezone(PARIS_TZ)

def get_reactor_unavailability_at_instant(values, target_dt, installed_cap):
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
        return max(active_slots, key=lambda x: x[0])
    
    return 0, None, None

def get_reactor_daily_max_unavailability(values, day_date, installed_cap):
    day_start = datetime(day_date.year, day_date.month, day_date.day, 0, 0, 0, tzinfo=PARIS_TZ)
    day_end = day_start + timedelta(days=1)

    eligible_slots = []

    for v in values:
        v_start = parse_iso_date(v.get("start_date"))
        v_end = parse_iso_date(v.get("end_date"))

        if not v_start or not v_end:
            continue

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

    # Filter out entries lasting 30 minutes or less
    slots_over_30min = [s for s in eligible_slots if s["duration_minutes"] > 30]

    if slots_over_30min:
        best_slot = max(slots_over_30min, key=lambda x: x["unavail"])
        return best_slot["unavail"], best_slot["start_date"], best_slot["end_date"]

    return 0, None, None

# ==============================================================================
# VERCEL SERVERLESS ENTRYPOINT
# ==============================================================================
def app(environ, start_response):
    try:
        query_string = environ.get('QUERY_STRING', '')
        query_components = urllib.parse.parse_qs(query_string)
        
        now_paris = datetime.now(PARIS_TZ)
        t1_str = query_components.get("t1", [now_paris.isoformat()])[0]
        t2_str = query_components.get("t2", [now_paris.isoformat()])[0]

        t1_dt = datetime.fromisoformat(t1_str).astimezone(PARIS_TZ)
        t2_dt = datetime.fromisoformat(t2_str).astimezone(PARIS_TZ)

        client_id = os.environ.get("RTE_CLIENT_ID")
        client_secret = os.environ.get("RTE_CLIENT_SECRET")

        if not client_id or not client_secret:
            status = '500 Internal Server Error'
            headers = [('Content-Type', 'application/json')]
            start_response(status, headers)
            return [json.dumps({"status": "error", "message": "Missing RTE_CLIENT_ID or RTE_CLIENT_SECRET environment variables"}).encode('utf-8')]

        token = get_rte_token(client_id, client_secret)

        min_dt = min(t1_dt, t2_dt)
        max_dt = max(t1_dt, t2_dt)

        # Target range calculation in Paris time converted to UTC
        search_start_paris = datetime(min_dt.year, min_dt.month, min_dt.day, 0, 0, 0, tzinfo=PARIS_TZ)
        search_end_paris = datetime(max_dt.year, max_dt.month, max_dt.day, 0, 0, 0, tzinfo=PARIS_TZ) + timedelta(days=2)

        search_start_utc = search_start_paris.astimezone(timezone.utc)
        search_end_utc = search_end_paris.astimezone(timezone.utc)

        start_str = search_start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_str = search_end_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

        # Initial URL request with EVENT_DATE and last_version=true
        base_url = "https://digital.iservices.rte-france.com/open_api/unavailability_additional_information/v7/generation_unavailabilities"
        full_url = f"{base_url}?start_date={start_str}&end_date={end_str}&date_type=EVENT_DATE&last_version=true"

        unavailabilities = []
        next_url = full_url

        # Pagination loop handling HTTP 206 Partial Content responses
        while next_url:
            req_rte = urllib.request.Request(
                next_url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                method="GET"
            )

            with urllib.request.urlopen(req_rte, timeout=20) as resp:
                raw_data = json.loads(resp.read().decode('utf-8'))

            batch = raw_data.get("generation_unavailabilities", [])
            unavailabilities.extend(batch)

            # Check for continuation token across possible payload formats
            continuation_token = raw_data.get("continuation_token") or raw_data.get("pagination", {}).get("continuation_token")

            if continuation_token:
                next_url = f"{full_url}&continuation_token={urllib.parse.quote(continuation_token)}"
            else:
                next_url = None

        # Filter latest version per message identifier
        latest_by_identifier = {}
        for item in unavailabilities:
            identifier = item.get("identifier")
            version = int(item.get("version", 0))

            if identifier not in latest_by_identifier or version > latest_by_identifier[identifier]["version"]:
                latest_by_identifier[identifier] = item

        # Exclude cancelled / discarded message statuses
        active_latest_items = []
        for item in latest_by_identifier.values():
            msg_status = str(item.get("message_status") or "").upper()
            if "CANCEL" not in msg_status and "DISCARD" not in msg_status:
                active_latest_items.append(item)

        # Filter strictly by root word 'environ' and nuclear fuel 'nuc'
        filtered_items = []
        for item in active_latest_items:
            fuel_type = str(item.get("fuel_type") or "").lower()
            remarks = str(item.get("remarks") or "").lower()
            reason = str(item.get("reason") or "").lower()
            asset_name = str(item.get("affected_asset_or_unit_name") or "").lower()

            has_nuc = "nuc" in fuel_type or "nuc" in remarks or "nuc" in reason or "nuc" in asset_name
            has_env = "environ" in remarks or "environ" in reason

            if has_nuc and has_env:
                filtered_items.append(item)

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

            unavail_t1, f_t1, t_t1 = get_reactor_unavailability_at_instant(values, t1_dt, installed_cap)
            if unavail_t1 > 0:
                sum_t1 += unavail_t1
                list_t1.append({"reactor": unit_name, "unavailability_mw": unavail_t1, "from": f_t1, "to": t_t1})

            unavail_t2, f_t2, t_t2 = get_reactor_unavailability_at_instant(values, t2_dt, installed_cap)
            if unavail_t2 > 0:
                sum_t2 += unavail_t2
                list_t2.append({"reactor": unit_name, "unavailability_mw": unavail_t2, "from": f_t2, "to": t_t2})

            u_max_t1, f_m_t1, t_m_t1 = get_reactor_daily_max_unavailability(values, day_t1, installed_cap)
            if u_max_t1 > 0:
                sum_max_t1 += u_max_t1
                list_max_t1.append({"reactor": unit_name, "unavailability_mw": u_max_t1, "from": f_m_t1, "to": t_m_t1})

            u_max_t2, f_m_t2, t_m_t2 = get_reactor_daily_max_unavailability(values, day_t2, installed_cap)
            if u_max_t2 > 0:
                sum_max_t2 += u_max_t2
                list_max_t2.append({"reactor": unit_name, "unavailability_mw": u_max_t2, "from": f_m_t2, "to": t_m_t2})

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

        status = '200 OK'
        headers = [
            ('Content-Type', 'application/json'),
            ('Access-Control-Allow-Origin', '*')
        ]
        start_response(status, headers)
        return [json.dumps(payload).encode('utf-8')]

    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8', errors='ignore')
        status = f'{e.code} HTTP Error'
        headers = [('Content-Type', 'application/json')]
        start_response(status, headers)
        return [json.dumps({"status": "HTTPError", "code": e.code, "message": error_body}).encode('utf-8')]
    except Exception as e:
        status = '500 Internal Server Error'
        headers = [('Content-Type', 'application/json')]
        start_response(status, headers)
        return [json.dumps({"status": "Exception", "message": str(e)}).encode('utf-8')]

# Vercel entrypoint alias
handler = app
