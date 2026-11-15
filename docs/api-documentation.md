# API Documentation – Estate Car Theft Detection System

## 1. Introduction

This document describes the REST API for the Estate Car Theft Detection System.

The API provides access to estate management, resident registration, vehicle management, visitor authorization, vehicle movement verification and security monitoring.

The primary backend is implemented using Django REST Framework.

FastAPI provides a dedicated verification interface for recognition and gate-processing services.

## 2. API Architecture

| Service | Technology | Responsibility |
|---|---|---|
| Core API | Django REST Framework | Main business operations |
| Verification API | FastAPI | Vehicle verification |
| Recognition Service | Python | Number plate extraction |
| Event Streaming | Apache Kafka | Asynchronous event distribution |

## 3. Base URLs

Development:

```text
Django API: http://localhost:8000/api/v1/
FastAPI:    http://localhost:8001/
```

These are proposed endpoints and will be implemented progressively.

## 4. Authentication

The API uses token-based authentication.

Protected endpoints require an authorization header.

```http
Authorization: Bearer <access_token>
```

Authentication endpoints:

| Method | Endpoint | Description |
|---|---|---|
| POST | /api/v1/auth/login/ | Authenticate user |
| POST | /api/v1/auth/refresh/ | Refresh access token |
| GET | /api/v1/auth/me/ | Get authenticated user |

### Login

Request:

```json
{
  "username": "security_officer",
  "password": "password"
}
```

Response:

```json
{
  "access": "access-token",
  "refresh": "refresh-token"
}
```

Production deployments must use HTTPS and secure token handling.

## 5. Estate Management API

Base endpoint:

```text
/api/v1/estates/
```

| Method | Endpoint | Description |
|---|---|---|
| GET | /estates/ | List estates |
| POST | /estates/ | Create estate |
| GET | /estates/{id}/ | Retrieve estate |
| PATCH | /estates/{id}/ | Update estate |
| DELETE | /estates/{id}/ | Delete estate |

Only authorized administrators can create or modify estate records.

## 6. Gate Management API

Base endpoint:

```text
/api/v1/gates/
```

| Method | Endpoint | Description |
|---|---|---|
| GET | /gates/ | List gates |
| POST | /gates/ | Register gate |
| GET | /gates/{id}/ | Retrieve gate |
| PATCH | /gates/{id}/ | Update gate |
| GET | /gates/{id}/events/ | Retrieve gate events |

Example request:

```json
{
  "estate_id": "estate-uuid",
  "name": "Main Entrance",
  "gate_type": "BOTH",
  "is_active": true
}
```

## 7. Resident Management API

Base endpoint:

```text
/api/v1/residents/
```

| Method | Endpoint | Description |
|---|---|---|
| GET | /residents/ | List residents |
| POST | /residents/ | Register resident |
| GET | /residents/{id}/ | Retrieve resident |
| PATCH | /residents/{id}/ | Update resident |
| GET | /residents/{id}/vehicles/ | List resident vehicles |

Example request:

```json
{
  "estate_id": "estate-uuid",
  "username": "resident01",
  "email": "resident@example.com",
  "apartment_number": "A-101",
  "phone_number": "+254700000000"
}
```

Resident creation and user account creation should be handled within one database transaction.

## 8. Vehicle Management API

Base endpoint:

```text
/api/v1/vehicles/
```

| Method | Endpoint | Description |
|---|---|---|
| GET | /vehicles/ | List vehicles |
| POST | /vehicles/ | Register vehicle |
| GET | /vehicles/{id}/ | Retrieve vehicle |
| PATCH | /vehicles/{id}/ | Update vehicle |
| DELETE | /vehicles/{id}/ | Deactivate vehicle |
| POST | /vehicles/{id}/report-stolen/ | Report stolen vehicle |
| POST | /vehicles/{id}/clear-stolen-report/ | Clear stolen report |

Example registration:

```json
{
  "estate_id": "estate-uuid",
  "resident_id": "resident-uuid",
  "registration_number": "KDA123A",
  "vehicle_type": "SUV",
  "make": "Toyota",
  "model": "RAV4",
  "color": "Black"
}
```

Example stolen vehicle report:

```json
{
  "description": "Vehicle reported stolen by registered owner"
}
```

The stolen vehicle report must be auditable and accessible only to authorized roles.

## 9. Visitor Management API

Base endpoint:

```text
/api/v1/visitors/
```

| Method | Endpoint | Description |
|---|---|---|
| GET | /visitors/ | List visitors |
| POST | /visitors/ | Register visitor |
| GET | /visitors/{id}/ | Retrieve visitor |
| PATCH | /visitors/{id}/ | Update visitor |
| GET | /visitors/{id}/passes/ | List visitor passes |

Example request:

```json
{
  "estate_id": "estate-uuid",
  "full_name": "John Doe",
  "phone_number": "+254700000000"
}
```

## 10. Visitor Pass API

Base endpoint:

```text
/api/v1/visitor-passes/
```

| Method | Endpoint | Description |
|---|---|---|
| GET | /visitor-passes/ | List passes |
| POST | /visitor-passes/ | Create visitor pass |
| GET | /visitor-passes/{id}/ | Retrieve pass |
| POST | /visitor-passes/{id}/approve/ | Approve pass |
| POST | /visitor-passes/{id}/reject/ | Reject pass |
| POST | /visitor-passes/{id}/revoke/ | Revoke pass |

Example request:

```json
{
  "visitor_id": "visitor-uuid",
  "resident_id": "resident-uuid",
  "registration_number": "KCA456B",
  "valid_from": "2026-11-16T08:00:00Z",
  "valid_until": "2026-11-16T18:00:00Z"
}
```

A visitor pass must be approved before entry authorization.

## 11. Vehicle Recognition API

FastAPI endpoint:

```text
POST /api/v1/recognition/process/
```

Purpose:

Receive recognition results from the computer vision service.

Request:

```json
{
  "estate_id": "estate-uuid",
  "gate_id": "gate-uuid",
  "registration_number": "KDA123A",
  "confidence": 0.97,
  "image_reference": "evidence/entry/image.jpg",
  "event_type": "ENTRY"
}
```

Response:

```json
{
  "success": true,
  "registration_number": "KDA123A",
  "recognition_status": "SUCCESS",
  "verification_required": true
}
```

The endpoint should be protected using service-to-service authentication.

## 12. Vehicle Verification API

FastAPI endpoint:

```text
POST /api/v1/verification/
```

Purpose:

Determine whether a recognized vehicle is authorized to enter or exit an estate.

Request:

```json
{
  "estate_id": "estate-uuid",
  "gate_id": "gate-uuid",
  "registration_number": "KDA123A",
  "event_type": "ENTRY",
  "confidence": 0.97,
  "event_id": "unique-event-uuid"
}
```

Possible responses:

### Authorized vehicle

```json
{
  "decision": "AUTHORIZED",
  "reason": "REGISTERED_VEHICLE",
  "registration_number": "KDA123A",
  "session_id": "session-uuid"
}
```

### Visitor vehicle

```json
{
  "decision": "AUTHORIZED",
  "reason": "APPROVED_VISITOR_PASS",
  "registration_number": "KCA456B",
  "session_id": "session-uuid"
}
```

### Unauthorized vehicle

```json
{
  "decision": "DENIED",
  "reason": "NO_VALID_AUTHORIZATION",
  "registration_number": "KDB789C"
}
```

### Reported stolen vehicle

```json
{
  "decision": "DENIED",
  "reason": "REPORTED_STOLEN",
  "alert_generated": true
}
```

### Manual verification required

```json
{
  "decision": "REVIEW_REQUIRED",
  "reason": "LOW_RECOGNITION_CONFIDENCE",
  "manual_verification_required": true
}
```

## 13. Vehicle Session API

Base endpoint:

```text
/api/v1/sessions/
```

| Method | Endpoint | Description |
|---|---|---|
| GET | /sessions/ | List vehicle sessions |
| GET | /sessions/{id}/ | Retrieve session |
| GET | /sessions/active/ | List active sessions |
| GET | /sessions/completed/ | List completed sessions |
| GET | /sessions/{id}/events/ | Retrieve session events |

Vehicle sessions should normally be created and closed by the verification workflow rather than arbitrary frontend requests.

## 14. Gate Event API

Base endpoint:

```text
/api/v1/gate-events/
```

| Method | Endpoint | Description |
|---|---|---|
| GET | /gate-events/ | List gate events |
| GET | /gate-events/{id}/ | Retrieve event |
| GET | /gate-events/recent/ | Retrieve recent events |
| GET | /gate-events/by-gate/{gate_id}/ | Events by gate |

Example event:

```json
{
  "event_id": "unique-event-uuid",
  "gate_id": "gate-uuid",
  "event_type": "ENTRY_AUTHORIZED",
  "registration_number": "KDA123A",
  "occurred_at": "2026-11-16T08:30:00Z"
}
```

## 15. Security Alert API

Base endpoint:

```text
/api/v1/alerts/
```

| Method | Endpoint | Description |
|---|---|---|
| GET | /alerts/ | List alerts |
| GET | /alerts/{id}/ | Retrieve alert |
| POST | /alerts/{id}/assign/ | Assign alert |
| POST | /alerts/{id}/investigate/ | Start investigation |
| POST | /alerts/{id}/resolve/ | Resolve alert |
| POST | /alerts/{id}/dismiss/ | Dismiss alert |

Example response:

```json
{
  "id": "alert-uuid",
  "alert_type": "UNAUTHORIZED_EXIT",
  "severity": "HIGH",
  "description": "Vehicle attempted to exit without a valid active entry session.",
  "status": "OPEN",
  "created_at": "2026-11-16T08:30:00Z"
}
```

Alert resolution and dismissal must record the responsible user and resolution details.

## 16. Dashboard Analytics API

Base endpoint:

```text
/api/v1/analytics/
```

| Method | Endpoint | Description |
|---|---|---|
| GET | /analytics/overview/ | Dashboard summary |
| GET | /analytics/vehicle-movements/ | Movement statistics |
| GET | /analytics/daily-activity/ | Daily vehicle activity |
| GET | /analytics/alert-statistics/ | Alert statistics |
| GET | /analytics/gate-performance/ | Gate activity statistics |

Example overview response:

```json
{
  "registered_vehicles": 150,
  "vehicles_inside": 42,
  "vehicles_exited_today": 86,
  "visitors_today": 24,
  "open_alerts": 3,
  "active_gates": 4
}
```

Analytics must be scoped to the authenticated user's authorized estate.

## 17. Audit Log API

Base endpoint:

```text
/api/v1/audit-logs/
```

| Method | Endpoint | Description |
|---|---|---|
| GET | /audit-logs/ | List audit records |
| GET | /audit-logs/{id}/ | Retrieve audit record |

Audit records should be immutable through normal application APIs.

## 18. Standard HTTP Status Codes

| Status | Meaning |
|---|---|
| 200 | Successful request |
| 201 | Resource created |
| 202 | Accepted for asynchronous processing |
| 204 | Successful request without response body |
| 400 | Invalid request |
| 401 | Authentication required |
| 403 | Permission denied |
| 404 | Resource not found |
| 409 | Business rule conflict |
| 422 | Validation failure |
| 429 | Too many requests |
| 500 | Internal server error |
| 503 | Service temporarily unavailable |

## 19. Standard Error Response

Example:

```json
{
  "error": {
    "code": "VEHICLE_ALREADY_INSIDE",
    "message": "The vehicle already has an active session in this estate.",
    "details": {}
  }
}
```

## 20. API Security

- Authentication is required for protected endpoints.
- Role-based permissions must be enforced.
- Estate-level data isolation must be applied.
- Service-to-service requests must be authenticated.
- Input validation must be enforced.
- Rate limiting must be applied where appropriate.
- CCTV evidence must not be publicly accessible.
- Sensitive operations must be recorded in audit logs.

## 21. API Versioning

The initial API version is:

```text
/api/v1/
```

Breaking API changes should be introduced through a new version.

## 22. API Testing

The API should be tested using:

- Postman.
- Django REST Framework APIClient.
- Pytest.
- FastAPI TestClient.

Important test scenarios include:

1. Registering a vehicle.
2. Verifying a registered vehicle.
3. Rejecting an unauthorized vehicle.
4. Approving and rejecting visitor passes.
5. Creating a vehicle entry session.
6. Closing a valid vehicle session.
7. Rejecting an exit without an active session.
8. Detecting reported stolen vehicles.
9. Handling duplicate Kafka events.
10. Preventing unauthorized access to estate records.

## 23. API Documentation Tools

Recommended documentation tools:

- Django REST Framework.
- drf-spectacular for OpenAPI schema generation.
- Swagger UI.
- ReDoc.
- FastAPI automatic OpenAPI documentation.

## 24. Conclusion

The API provides a structured interface between the frontend, core backend, computer vision services and event-processing infrastructure.

It separates estate management, vehicle verification, event processing and security monitoring while maintaining consistent authorization and audit requirements.
