# 1. Dédoublonnage strict par identifiant : ne garder QUE la version la plus récente absolue (ex. v11)
latest_by_identifier = {}
for item in unavailabilities:
    identifier = item.get("identifier")
    version = int(item.get("version", 0))

    if identifier not in latest_by_identifier or version > latest_by_identifier[identifier]["version"]:
        latest_by_identifier[identifier] = item

# 2. Filtrage : exclure uniquement les messages annulés/jetés (DISMISSED, CANCEL, ANNULE)
# On CONSERVE les messages INACTIVE car leurs dates reflètent la fin réelle de l'événement
filtered_items = []
exclusion_terms = ["DISMISSED", "CANCEL", "CANCELLED", "ANNULE"]

for item in latest_by_identifier.values():
    event_status = str(item.get("event_status") or "").upper()
    msg_status = str(item.get("message_status") or item.get("status") or "").upper()
    combined_status = remove_accents(f"{event_status} {msg_status}")

    # Si la version est annulée ou rejetée, on l'ignore
    if any(term in combined_status for term in exclusion_terms):
        continue

    # Filtrage environnemental (racine "environ")
    full_item_text = json.dumps(item).lower()
    if "environ" in full_item_text:
        filtered_items.append(item)
