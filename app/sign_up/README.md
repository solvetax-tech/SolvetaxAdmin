# Signup Folder API Documentation

This document provides detailed information about the Signup backend APIs, including signup, login, session management, employee editing, and related data schemas. This guide is intended for frontend developers integrating these APIs.

---

## Base API Path

- All APIs are served under `/app/v1` prefix.

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
| ------------ | -------- | -------- | -------------------------------------------- | ------------------------------------------------- |
| username     | string   | Yes      | Desired username                             | Non-empty, max length 50, trimmed                  |
| email        | string   | Yes      | User's email address                         | Valid email format                                 |
| password     | string   | Yes      | User's password                             | Minimum 8 characters, must be strong (checked on server) |
| first_name   | string   | No       | User's first name                           | Trimmed, 1-100 characters                           |
| last_name    | string   | No       | User's last name                            | Trimmed, 1-100 characters                           |
| phone_number | string   | No       | Phone number (10 digits expected)           | Exactly 10 digits, digits only                      |
| role         | string   | No       | User role (default: "customer")              |                                                   |

#### Responses

- `200 OK` - Successfully registered, returns newly assigned `emp_id` and message.
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

### 4. Employee Edit API

**POST** `/api/v1/employees/{emp_id}/edit`

- Edits provided fields for an employee by employee ID.

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

### 5. Employee List and Filter APIs

- **GET** `/api/v1/employees` - List employees with pagination and optional inclusion of inactive users.

- **GET** `/api/v1/employees/search` - Filter employees by multiple optional query parameters including `emp_id`, `full_name`, `email`, `phone_number`, `role`, `is_active`, and date ranges `from_date` and `to_date` (ISO 8601 datetime).

---

## Common Points for Frontend

- Always include `Authorization: Bearer <token>` header for protected endpoints.
- For filtering by dates, use ISO 8601 formatted datetimes in `from_date` and `to_date` query parameters.
- Pagination is controlled via `limit` and `offset` query parameters.
- All responses contain key fields plus a `message` for success context.
- Error responses use consistent status codes and error structures.

---

## Example: Signup Request

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

## Example: Login Request

```json
{
  "email": "alice@example.com",
  "password": "StrongPass!2024"
}
```

## Example: Logout Request

```json
{
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5..."
}
```

## Example: Employee Edit Request

```json
{
  "email": "alice.new@example.com",
  "role": "admin",
  "is_active": true
}
```

---

For additional details on pagination used across APIs, refer to `pagination.md` in this folder.

This documentation will help frontend development teams understand API requirements, expected responses, and handle authentication/session workflows correctly.
