# 📘 Production-Ready FastAPI – Customer Module Documentation

---

# 1️⃣ Overview

This document explains the architecture and implementation of a production-ready FastAPI Customer module.

It covers:

- `schemas.py` (Validation Layer)
- `logger.py` (Logging Layer)
- `customer.py` (API Layer)
- Best practices used
- How to build production-ready APIs

This structure follows:

- Clean separation of concerns
- Strict validation
- Secure logging
- Safe database handling
- Enterprise-level best practices

---

# 🏗️ Project Structure

```
app/
│
├── schemas.py
├── logger.py
├── routers/
│     └── customer.py
├── database.py
├── dependencies.py
├── utils.py
└── config.py
```

---

# 2️⃣ schemas.py – Data Validation Layer

## 🎯 Purpose

The `schemas.py` file defines:

- What data the API accepts (request models)
- What data the API returns (response models)
- Validation rules
- Business rules
- Security rules

It ensures:

> Only valid and clean data enters the system.

---

## 🔹 BaseSchema

```python
class BaseSchema(BaseModel):
    model_config = {
        "extra": "forbid",
        "str_strip_whitespace": True,
        "validate_assignment": True,
        "from_attributes": True,
    }
```

### What This Does

| Setting | Meaning |
|----------|----------|
| `extra="forbid"` | Reject unknown fields |
| `str_strip_whitespace=True` | Auto-trims all string inputs |
| `validate_assignment=True` | Re-validates fields on update |
| `from_attributes=True` | Allows parsing ORM objects |

### Why It Matters

- Prevents injection of unexpected fields
- Ensures consistent input cleaning
- Makes APIs safer and predictable

---

## 🔹 CustomerIn (Request Schema)

Defines:

- Required fields
- Optional fields
- Field length limits
- Regex validation
- Business rules

Example:

```python
full_name: str = Field(..., min_length=2, max_length=100)
```

Ensures:
- Required field
- Minimum 2 characters
- Maximum 100 characters

Other validations include:

- Email format (`EmailStr`)
- Mobile regex validation
- URL validation (`HttpUrl`)
- Positive integer validation (`gt=0`)

---

## 🔹 Field Validators

### `mode="before"`

```python
@field_validator("email", mode="before")
```

Runs **before type validation**.

Used for:
- Lowercasing email
- Stripping whitespace
- Sanitizing strings

Flow example:

1. Raw input → `"  TEST@GMAIL.COM  "`
2. Normalize → `"test@gmail.com"`
3. Validate as EmailStr

---

### `mode="after"`

```python
@model_validator(mode="after")
```

Runs **after all fields are validated**.

Used for:

- Cross-field validation
- Business rules

Example rule:

```
Either email or mobile must be provided
```

---

## 🔹 CustomerOut (Response Schema)

Defines:

- What the client receives
- Structured output format
- Safe field exposure

Ensures:
> API never exposes unintended or internal fields.

---

# 3️⃣ logger.py – Logging Layer

## 🎯 Purpose

The logging layer ensures:

- All requests are traceable
- Logs are saved to file
- Logs rotate automatically
- Logs contain request context
- Sensitive data is protected

---

## 🔹 Key Features

### Rotating Logs

```python
RotatingFileHandler(maxBytes=10MB, backupCount=5)
```

Ensures:

- Log file capped at 10MB
- Keeps 5 backup files
- Prevents disk overflow

---

### Automatic Log Folder Creation

```python
os.makedirs("logs", exist_ok=True)
```

Ensures:

- No crash if folder doesn't exist

---

### Context Logging

Each log contains:

- Timestamp (`asctime`)
- Log level
- `request_id`
- `emp_id`

Example log:

```
2026-02-12 10:45:32 | INFO | request_id=abc123 | emp_id=101 | Customer created successfully id=501
```

---

## 🔹 Why Context Logging Is Important

- Helps trace specific API calls
- Helps debug production issues
- Enables audit tracking
- Prevents confusion during incident analysis

---

# 4️⃣ customer.py – API Business Logic Layer

## 🎯 Purpose

This file handles:

- API endpoint definition
- Database operations
- Business logic
- Logging
- Exception handling

It does NOT handle:

- Input validation (handled in schemas)
- Logging setup (handled in logger.py)

---

## 🔹 What the API Contains

### 1. Request ID Generation

```python
request_id = uuid.uuid4()
```

Used for:

- Log tracing
- Debugging
- Correlating logs

---

### 2. Role-Based Access Control

```python
Depends(require_permission("EMPLOYEE", "WRITE"))
```

Ensures only authorized users can create customers.

---

### 3. Duplicate Check

Prevents duplicate active customers.

---

### 4. Database Transaction

```python
async with conn.transaction()
```

Ensures:

- Atomic database operations
- No partial inserts
- Data consistency

---

### 5. Structured Exception Handling

Handles:

- Unique constraint errors
- Foreign key violations
- Database failures
- Unexpected runtime errors

Ensures predictable API behavior.

---

# 5️⃣ Masking vs Response Filtering

## Response Filtering (Pydantic)

Controls what the client sees.

Example:

```python
model_dump(exclude={"mobile"})
```

Prevents exposing unnecessary data in response.

---

## Masking (Logging Protection)

Protects sensitive data inside logs.

Example:

Instead of:
```
mobile=9876543210
```

Log:
```
mobile=98******10
```

---

## Difference Summary

| Feature | Response Filtering | Masking |
|----------|------------------|----------|
| Controls API output | Yes | No |
| Protects logs | No | Yes |
| Prevents internal leaks | No | Yes |
| Prevents client exposure | Yes | No |

Both are required in production systems.

---

# 6️⃣ How to Build a Production-Ready API

## Step 1 – Define Strict Schemas

- Add type validation
- Add length limits
- Add regex validation
- Add business rules
- Forbid unknown fields

---

## Step 2 – Separate Concerns

- Schema → Validation
- API → Business logic
- Logger → Observability
- DB Layer → Database handling

Never mix responsibilities.

---

## Step 3 – Implement Secure Logging

- Always log request_id
- Log user/emp_id
- Mask sensitive fields
- Use rotating file handler

---

## Step 4 – Use Database Best Practices

- Always use transactions
- Catch specific DB exceptions
- Use parameterized queries
- Avoid dynamic SQL injection

---

## Step 5 – Protect Sensitive Data

- Mask logs
- Restrict response fields
- Never log raw PII
- Enforce strict schema validation

---

# 7️⃣ Responsibilities of Each Layer

| Layer | Responsibility |
|--------|----------------|
| schemas.py | Data validation & business rules |
| logger.py | Logging & observability |
| customer.py | Business logic & DB operations |
| dependencies.py | Authentication & RBAC |
| utils.py | Helper utilities |

---

# 8️⃣ Why This Architecture Is Production-Ready

- Strict validation
- Clean separation of concerns
- Structured logging
- Transaction-safe DB operations
- Controlled response models
- Secure logging practices
- Scalable structure

---

# 9️⃣ Conclusion

This module demonstrates:

- Clean backend architecture
- Secure API design
- Maintainable structure
- Enterprise-level standards
- Audit-friendly implementation

A fresher reviewing this should understand:

- Where validation belongs
- Where business logic belongs
- Why logging is important
- How to structure production-grade APIs
- How to prevent mixing responsibilities

---

End of Documentation.
