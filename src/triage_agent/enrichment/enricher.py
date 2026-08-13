from ..schemas import CommonTicket, EnrichmentContext

# Mock enricher. Replace with real directory/CMDB/history lookups.

def enrich(ticket: CommonTicket) -> EnrichmentContext:
    # Simple mock: mark VIP if requester email in a small list
    vip_list = {"ceo@example.com", "cto@example.com"}
    requester = ticket.requester_identifier.lower()
    requester_context = {
        "department": "Engineering",
        "title": "Software Engineer",
        "manager": "manager@example.com",
        "location": "HQ",
        "employment_status": "active",
        "is_vip": requester in vip_list
    }
    asset_context = {"device_id": None, "os": None, "last_checkin": None, "open_incidents": []}
    history_context = {"open_tickets_last_30d": 0, "similar_open_ticket_ids": [], "is_likely_duplicate": False}
    return EnrichmentContext(requester_context=requester_context, asset_context=asset_context, history_context=history_context)
