# File-Level Doc: `app/gst_registration/gst_blob.py`

Owner: Engineering Team  
Last Verified On: 2026-04-07

## Purpose

Provides blob-storage utility endpoints for GST documents: upload, view URL generation, and download URL generation.

## Router

- Prefix: `/api/v1/gst-blob`
- Tag: `GST Registration Blob`

## Endpoints in this file

- `POST /api/v1/gst-blob/upload`
- `GET /api/v1/gst-blob/view`
- `GET /api/v1/gst-blob/download`

## Permission usage

- Upload: `EMPLOYEE:WRITE`
- View/download: `EMPLOYEE:READ`

## Core behaviors

- Upload validates file constraints and pushes to Azure Blob storage.
- View/download generate SAS URLs with intended content-disposition behavior.
- Returns URL metadata to caller; document-row persistence happens in other modules.

## Main integrations/tables

- External storage integration (Azure Blob).
- No primary transactional table writes in this file.
