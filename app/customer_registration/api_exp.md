# 📘 Create Customer API — Complete Documentation

---

## 🔹 Endpoint Details

- **Method:** POST  
- **URL:** `/api/v1/customers`  
- **Access Control:** Requires `EMPLOYEE WRITE` permission  
- **Success Response Code:** `201 Created`  
- **Response Model:** `CustomerOut`

This API is responsible for securely creating a new customer in the system using proper validation, logging, transaction handling, and database integrity enforcement.

---

# 🏗 Architectural Responsibilities

The API follows clean separation of responsibilities across layers:

---

## 1️⃣ FastAPI Layer (Framework Level)

Handled automatically by FastAPI:

- Parses incoming JSON request
- Validates request body type
- Injects authenticated user via dependency
- Enforces permission using RBAC

If authentication fails → `401 / 403` returned automatically.

---

## 2️⃣ Schema-Level Validation (Pydantic)

Handled inside `CustomerIn` model:

- Email format validation
- Mobile number regex validation
- Field length constraints
- Required field enforcement
- Optional field handling

If validation fails → `422 Unprocessable Entity`.

---

## 3️⃣ Authorization (RBAC)

The API requires:

```
EMPLOYEE WRITE
```

Only authorized employees can create customers.

The authenticated `emp_id` is extracted and attached to structured logs.

---

# 🔐 Security & Production Features

---

## ✅ Structured Logging

Each request generates:

- `request_id` (UUID)
- `emp_id` (who performed the action)

This enables:
- Traceability
- Audit tracking
- Production debugging
- Incident investigation

---

## ✅ Sensitive Data Masking

Sensitive fields such as:

- Email
- Mobile number

are masked before being written to logs.

This prevents sensitive data exposure in log files.

---

## ✅ SQL Injection Protection

The API uses parameterized SQL:

```
$1, $2, $3 ...
```

No direct string interpolation of values.

This prevents SQL injection attacks.

---

## ✅ Transaction Safety

Database insert runs inside:

```
async with conn.transaction()
```

This ensures:

- Atomic operation
- Automatic rollback on failure
- No partial writes
- Data consistency

---

# 🗄 Database-Level Integrity

Database enforces the following constraints:

---

## 🔹 UNIQUE Constraints

- `email`
- `mobile`

If violated → API returns:

```
409 Conflict
```

---

## 🔹 FOREIGN KEY Constraints

- `rm_id`
- `op_id`

If invalid → API returns:

```
400 Bad Request
```

---

## 🔹 NOT NULL Constraints

Ensures required DB fields cannot be empty.

---

# 📤 Response Handling

After successful insertion:

- Only fields defined in `CustomerOut` are returned.
- Extra DB columns are filtered out.
- A success message is attached:

```
"Customer created successfully."
```

Datetime fields are converted to JSON-safe format.

---

# 🚨 Error Handling Strategy

The API categorizes errors clearly:

| Scenario | HTTP Code | Meaning |
|----------|-----------|----------|
| Duplicate email/mobile | 409 | Customer already exists |
| Invalid rm_id/op_id | 400 | Foreign key invalid |
| Database failure | 500 | DB-level issue |
| Unexpected error | 500 | Internal server error |

Each error is logged with `request_id`.

---

# 🔄 End-to-End Flow

1. Client sends POST request  
2. FastAPI validates input type  
3. Pydantic validates schema  
4. RBAC checks permission  
5. Sensitive data masked in logs  
6. Insert query executed in transaction  
7. Database enforces constraints  
8. Clean structured response returned  

---

# 🎯 Why This API Is Production-Ready

- Async architecture (scalable)
- Structured logging
- Proper validation separation
- Secure parameterized SQL
- Transaction-safe writes
- Defensive error handling
- Role-based access control
- Audit-friendly logging
- Clean response filtering

---

# 🧠 Key Learning for Interns

This API demonstrates:

- Clean backend architecture
- Secure coding practices
- Enterprise logging standards
- Defensive programming
- Database-first integrity enforcement
- Proper HTTP error mapping
- Production-grade CRUD design

---

This is not just a simple insert API —  
it is a structured, secure, production-ready backend implementation.
