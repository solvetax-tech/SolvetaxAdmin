# Signup Folder API Documentation

This document provides detailed information about the Signup backend APIs, including signup, login, logout, forgot password, employee editing, and related data schemas. This guide is intended for frontend developers integrating these APIs.

---

## Base API Path

- All APIs are served under `/app/v1` prefix for user authentication and signup flows.
- Employee management APIs are served under `/api/v1/employees` prefix.

---

## Authentication

- Most endpoints require an OAuth2 Bearer token in the `Authorization` header.
- The token is obtained via the login API.
- Token validation is enforced for protected routes.

---

## Endpoints

### 1. Signup API

**POST** `/app/v1/signup`

- Registers a new employee/user.

#### Request Payload (`SignupRequest`)

| Field        | Type     | Required | Description                                  | Validation                                         |
| ------------ | -------- | -------- | ------------------------------------------- | ------------------------------------------------- |
| username     | string   | Yes      | Desired username                            | Non-empty, max length 50, trimmed                  |
| email        | string   | Yes      | User's email address                        | Valid email format                                 |
| password     | string   | Yes      | User's password                            | Minimum 8 characters, must be strong (checked on server) |
| first_name   | string   | No       | User's first name                          | Trimmed, 1-100 characters                           |
| last_name    | string   | No       | User's last name                           | Trimmed, 1-100 characters                           |
| phone_number | string   | No       | Phone number (10 digits expected)          | Exactly 10 digits, digits only                      |
| role         | string   | No       | User role (default: "SE")                   |                                                   |

#### Responses

- `201 Created` - Successfully registered, returns newly assigned `emp_id` and message.
- `400 Bad Request` - Validation failed (e.g., weak password).
- `409 Conflict` - Username or email already exists.
- `503 Service Unavailable` - Temporary service issue.

---

### 2. Login API

**POST** `/app/v1/login`

- Authenticates the user and issues a JWT token plus a session token.

#### Request Payload (`LoginRequest`)

| Field    | Type   | Required | Description         |
| -------- | ------ | -------- | ------------------- |
| email    | string | Yes      | User's email        |
| password | string | Yes      | User's password     |

#### Responses

- `200 OK` - Returns an access token (`token`), session token (`session_token`), expiration time, and employee profile.
- `400 Bad Request` - Missing credentials.
- `401 Unauthorized` - Invalid credentials.
- `503 Service Unavailable` - Temporary service issue.

#### Notes

- The `token` should be sent as `Authorization: Bearer <token>` in further API requests.
- Multiple concurrent sessions per user are supported.
- Session info including device and IP are stored in DB.

---

### 3. Logout API

**POST** `/app/v1/logout`

- Revokes a session token, ending a session.

#### Request Headers

- `Authorization: Bearer <token>` (JWT token from login)

#### Request Payload (`LogoutRequest`)

| Field         | Type   | Required | Description                |
| ------------- | ------ | -------- | --------------------------|
| session_token | string | Yes      | JWT session token to revoke |

#### Responses

- `200 OK` - Session revoked successfully.
- `400 Bad Request` - Session token invalid or already inactive.
- `401 Unauthorized` - Missing or invalid authorization.
- `503 Service Unavailable` - Temporary issue.

---

### 4. Forgot Password APIs

**POST** `/app/v1/forgot-password/request`

- Request an OTP for password reset sent via SMS to the registered phone number.

#### Request Payload (`ForgotPasswordRequest`)

| Field | Type   | Required | Description           |
|-------|--------|----------|-----------------------|
| email | string | Yes      | Registered email ID   |

#### Responses

- `200 OK` - OTP sent to registered phone number.
- `400 Bad Request` - Validation errors.
- `404 Not Found` - Email not registered.

---

**POST** `/app/v1/forgot-password/verify`

- Verify OTP and set a new password.

#### Request Payload (`ForgotPasswordVerify`)

| Field           | Type   | Required | Description                          |
|-----------------|--------|----------|------------------------------------|
| email           | string | Yes      | Registered email ID                 |
| otp             | string | Yes      | 4-digit OTP received via SMS        |
| new_password    | string | Yes      | New password (must be strong)       |
| confirm_password| string | Yes      | Confirmation of new password        |

#### Responses

- `200 OK` - Password reset successful.
- `400 Bad Request` - OTP invalid/expired or password validation failed.
- `404 Not Found` - Email not registered.

---

### 5. Employee Edit API

**POST** `/api/v1/employees/{emp_id}/edit`

- Edit provided fields for an employee by employee ID.

#### Request Payload (`EmployeeEditIn`)

All fields optional; include any subset to update.

| Field              | Type   | Description                    |
| ------------------ | ------ | ------------------------------|
| username           | string | Username                      |
| email              | string | Email address                 |
| first_name         | string | First name                   |
| last_name          | string | Last name                    |
| phone_number       | string | Phone number (validated)      |
| role               | string | User role                    |
| is_active          | bool   | Active status                |
| employee_image_url | string | URL for employee image       |

#### Validations

- Email must be valid format.
- Phone number must be valid format.
- username/email/phone uniqueness is checked.
- `employee_image_url` must be valid URL if provided.

#### Responses

- `200 OK` - Employee updated successfully with updated fields.
- `400 Bad Request` - Validation failure or no fields to update.
- `404 Not Found` - Employee not found.

---

### 6. Employee List and Filter API

**GET** `/api/v1/employees/filter`

- Filter employees by multiple optional query parameters including:

| Query Parameter   | Type      | Description                        |
|-------------------|-----------|----------------------------------|
| emp_id            | int       | Employee ID                      |
| full_name         | string    | Matches first_name + last_name   |
| email             | string    | Partial match                    |
| phone_number      | string    | Exact match                     |
| role              | string    | Exact match                     |
| is_active         | bool      | Active status                   |
| include_inactive  | bool      | Include inactive users if true  |
| from_date         | datetime  | Filter created_at from           |
| to_date           | datetime  | Filter created_at to             |
| limit             | int       | Pagination limit (default 20)    |
| offset            | int       | Pagination offset (default 0)    |

#### Responses

- `200 OK` - List of filtered employees.
- `400 Bad Request` - Validation errors.

---

## Schemas and Validation

- Most request and response schemas are defined using Pydantic models in `app/sign_up/schemas.py`.
- Key validation includes:
  - Password strength enforcement.
  - Email and phone format validation.
  - Uniqueness constraints for usernames, emails, and phones.
  - URL format validation for image URLs.

---

## Pagination

- Pagination is controlled via `limit` and `offset` query parameters.
- For detailed pagination rules and recommendations, see `pagination.md` in this folder.

---

## Error Handling

- Error responses follow consistent status codes:
  - `400` for validation errors.
  - `401` for unauthorized or missing authentication.
  - `404` for not found resources.
  - `409` for conflicts like duplicate usernames/emails.
  - `500` or `503` for server errors.

---

## Example Requests

### Signup

```json
{
  "username": "alice123",
  "email": "alice@example.com",
  "password": "StrongPass!2024",
  "first_name": "Alice",
  "last_name": "Doe",
  "phone_number": "1234567890",
  "role": "employee"
}
```

### Login

```json
{
  "email": "alice@example.com",
  "password": "StrongPass!2024"
}
```

### Logout

```json
{
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5..."
}
```

### Forgot Password Request

```json
{
  "email": "alice@example.com"
}
```

### Forgot Password Verify

```json
{
  "email": "alice@example.com",
  "otp": "1234",
  "new_password": "NewStrongPass!2024",
  "confirm_password": "NewStrongPass!2024"
}
```

### Employee Edit

```json
{
  "email": "alice.new@example.com",
  "role": "admin",
  "is_active": true
}
```

---

This documentation will help frontend development teams understand API requirements, expected responses, and handle authentication/session workflows correctly.