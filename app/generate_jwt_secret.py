import secrets

def generate_jwt_secret(length=64):
    """Generate a secure random JWT secret key."""
    return secrets.token_urlsafe(length)

def generate_public_api_key(length=48):
    """Generate a secure random public API key."""
    return secrets.token_urlsafe(length)

if __name__ == "__main__":
    jwt_secret = generate_jwt_secret()
    public_api_key = generate_public_api_key()
    print(f"Generated JWT_SECRET: {jwt_secret}")
    print(f"Generated PUBLIC_API_KEY: {public_api_key}")