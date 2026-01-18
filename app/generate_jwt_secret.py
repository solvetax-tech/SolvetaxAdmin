import secrets

def generate_jwt_secret(length=64):
    """Generate a secure random JWT secret key."""
    return secrets.token_urlsafe(length)

if __name__ == "__main__":
    secret = generate_jwt_secret()
    print(f"Generated JWT_SECRET: {secret}")