import re

def validate_mobile(v):
    if v is not None and (not v.isdigit() or len(v) != 10):
        raise ValueError('Mobile number must be exactly 10 digits')
    return v

def validate_gstin(v):
    if v is not None and (len(v) != 15 or not v.isalnum()):
        raise ValueError('GSTIN must be exactly 15 alphanumeric characters')
    return v

def validate_pan(v):
    if v is not None:
        pattern = re.compile("^[A-Z]{5}[0-9]{4}[A-Z]$")
        if not pattern.match(v):
            raise ValueError('PAN must be 10 characters: 5 letters, 4 digits, 1 letter (e.g. ABCDE1234F)')
    return v

def validate_aadhaar(v):
    if v is not None:
        if not (v.isdigit() and len(v) == 12):
            raise ValueError('Aadhaar must be exactly 12 digits')
    return v

def validate_email(v):
    if v is not None:
        email_regex = r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)"
        if not re.match(email_regex, v):
            raise ValueError('Invalid email address')
    return v

def validate_url(v):
    if v is not None:
        url_regex = re.compile(
            r'^(https?://)'  # http:// or https://
            r'(([A-Za-z0-9-]+\.)+[A-Za-z]{2,6})'  # domain...
            r'(:\d+)?'  # optional port
            r'(/[A-Za-z0-9\-\._~:/?#\[\]@!$&\'()*+,;=%]*)?$'  # path and query string
        )
        if not url_regex.match(v):
            raise ValueError('Invalid URL format')
    return v
