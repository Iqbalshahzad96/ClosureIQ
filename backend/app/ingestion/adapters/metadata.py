import re

def extract_title_metadata(title_values, options):
    """
    Extracts financial metadata from a title row and updates options in-place.
    """
    row_text = " ".join(str(v).strip() for v in title_values if v).lower()
    
    if "account" in row_text and not options.get("bank_account_id"):
        match = re.search(r'(?:account|acct)(?:\s+(?:number|num|no))?[\s#:]+([a-z0-9-]+)', row_text)
        if match:
            options["bank_account_id"] = match.group(1).upper()
            
    if "account" in row_text and not options.get("account_name_raw"):
        match = re.search(r'(?:account|ledger)[\s:]*([a-z0-9-\s]+)', row_text)
        if match:
            val = match.group(1).strip()
            if len(val) > 2:
                options["account_name_raw"] = val.title()
                
    if not options.get("bank_name"):
        if "diamond trust" in row_text or "dtb" in row_text:
            options["bank_name"] = "Diamond Trust Bank Kenya Limited"
        elif "prime bank" in row_text:
            options["bank_name"] = "Prime Bank Limited"
            
    if not options.get("currency_code"):
        match = re.search(r'(?:currency|curr)[\s:]*([a-z]{3})', row_text)
        if match:
            options["currency_code"] = match.group(1).upper()
            
    if not options.get("fiscal_period"):
        match = re.search(r'(?:period|month|for the period ended)[\s:]*([a-z0-9-\s]+)', row_text)
        if match:
            val = match.group(1).strip()
            if len(val) > 3:
                options["fiscal_period"] = val
