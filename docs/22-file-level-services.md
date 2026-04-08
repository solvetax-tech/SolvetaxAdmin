# File-Level Doc: `app/customer_registration/services.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Manages customer-service operational records: filtering, activation, deactivation, dashboard stats, and pending queues.

## Router

- Prefix: `/api/v1/services`
- Tag: `services`

## Endpoints in this file

- `GET /api/v1/services/customer-services/filter`
- `POST /api/v1/services/customer-services/{service_id}/activate`
- `POST /api/v1/services/customer-services/{service_id}/deactivate`
- `GET /api/v1/services/services/dashboard/stats`
- `GET /api/v1/services/services/pending`

## Permission usage

- Reads: `EMPLOYEE:READ`
- Mutations: `EMPLOYEE:WRITE`

## Core behaviors

- Dynamic filters over service/customer/entity/status dimensions.
- Enforces state guards when activating/deactivating service rows.
- Deactivation is blocked if dependent pending followups exist.
- Returns aggregate counts for dashboard and operational pending views.
- Writes operation audits to `versions` where applicable.

## Main tables touched

- `customer_services`
- `service_config`
- `customers`
- `customer_service_followups`
- `versions`
