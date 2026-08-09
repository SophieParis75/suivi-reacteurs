# Filter latest version per message identifier
        latest_by_identifier = {}
        for item in unavailabilities:
            identifier = item.get("identifier")
            version = int(item.get("version", 0))

            if identifier not in latest_by_identifier or version > latest_by_identifier[identifier]["version"]:
                latest_by_identifier[identifier] = item

        # Filter strictly by root word 'environ', nuclear fuel 'nuc', AND active message status
        filtered_items = []
        for item in latest_by_identifier.values():
            # Check status and message_status fields
            msg_status = str(item.get("message_status") or "").upper()
            status_field = str(item.get("status") or "").upper()
            combined_status = f"{msg_status} {status_field}"

            # Exclude any cancelled, inactive, withdrawn or dismissed status
            if any(term in combined_status for term in ["CANCEL", "DISCARD", "WITHDRAW", "INACTIVE", "DISMISSED"]):
                continue

            fuel_type = str(item.get("fuel_type") or "").lower()
            remarks = str(item.get("remarks") or "").lower()
            reason = str(item.get("reason") or "").lower()
            asset_name = str(item.get("affected_asset_or_unit_name") or "").lower()

            has_nuc = "nuc" in fuel_type or "nuc" in remarks or "nuc" in reason or "nuc" in asset_name
            has_env = "environ" in remarks or "environ" in reason

            if has_nuc and has_env:
                filtered_items.append(item)
