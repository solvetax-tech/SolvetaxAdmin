def validate_mobile(v):
    if v is not None and (not v.isdigit() or len(v) != 10):
        raise ValueError('Mobile number must be exactly 10 digits')
    return v

def validate_gstin(v):
    if v is not None and (len(v) != 15 or not v.isalnum()):
        raise ValueError('GSTIN must be exactly 15 alphanumeric characters')
    return v
