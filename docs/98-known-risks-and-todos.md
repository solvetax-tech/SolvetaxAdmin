# Known Risks and Improvement TODOs

Owner: Engineering Team  
Last Verified On: 2026-04-07

This file captures practical risks observed from current code structure and documentation passes.

## High-priority risks

- **Large multi-concern files**
  - `app/sign_up/employee_edit.py`
  - `app/gst_registration_filing/gst_registation_filing.py`
  - Risk: harder testing, higher regression surface per change.

- **Inline SQL spread across many files**
  - Risk: schema/query drift and duplicated condition logic.
  - Improvement: centralize repeated SQL fragments and add query-level test coverage.

- **Trigger-dependent behavior visibility**
  - App logic relies on DB triggers/functions for some state sync behavior.
  - Risk: behavior can differ by environment if DB trigger DDL is not synchronized.

## Medium-priority risks

- **Permission and visibility coupling**
  - Visibility helpers in `app/utils.py` are critical and widely reused.
  - Risk: small changes can impact many endpoints unexpectedly.

- **Scheduler side effects**
  - `app/schedular/schedular.py` changes data periodically.
  - Risk: misconfiguration can silently alter statuses across large datasets.

- **Path naming inconsistency**
  - File name `gst_registation_filing.py` contains typo in codebase.
  - Risk: discoverability and onboarding confusion.

## Recommended TODOs

1. Add integration tests for:
   - auth middleware + session rotation
   - GST filing create/edit + return-detail regeneration
   - scheduler transitions (`NOT_FILED -> MISSED`, recurrence generation).
2. Split large modules into smaller service/route layers.
3. Introduce migration-managed SQL DDL tracking for triggers/functions.
4. Add a single permission matrix source for endpoint-to-feature mapping.
5. Add a smoke-test checklist for every production deploy.
