from ..schemas import CommonTicket

# For the scaffold, web_form simply validates payload; heavier parsing lives upstream

def parse_web_form_payload(payload: dict) -> CommonTicket:
    # In practice you'd normalize field names, validate attachments, etc.
    return CommonTicket(**payload)
