# Database Design – Estate Car Theft Detection System

## 1. Introduction

This document describes the database design for the Estate Car Theft Detection System. It defines the entities, relationships, constraints and data management strategy required to support vehicle registration, visitor authorization, vehicle entry and exit monitoring, number plate recognition and security incident management.

The system uses PostgreSQL as its primary relational database.

Django REST Framework acts as the primary owner of database operations. Other services access business data through the backend APIs rather than independently modifying the database.

## 2. Database Design Objectives

The database is designed to:

- Maintain centralized records of estates, gates, residents and registered vehicles.
- Support visitor registration and authorization.
- Track vehicle movements through entry and exit sessions.
- Store number plate recognition results.
- Record suspicious vehicle movements and security incidents.
- Maintain an auditable history of system activities.
- Support multiple estates and multiple gates.
- Prevent duplicate or conflicting vehicle movement sessions.

## 3. Database Technology

| Component | Technology |
|---|---|
| Primary database | PostgreSQL |
| ORM | Django ORM |
| Database identifier | UUID |
| Primary backend | Django REST Framework |
| Event processing | Apache Kafka |
| Evidence storage | MinIO |

## 4. Entity Descriptions

### 4.1 Estate

Represents a residential estate registered within the system.

| Field | Data Type | Constraint |
|---|---|---|
| id | UUID | Primary Key |
| name | VARCHAR(150) | NOT NULL |
| address | TEXT | NOT NULL |
| description | TEXT | NULL |
| created_at | TIMESTAMP | NOT NULL |
| updated_at | TIMESTAMP | NOT NULL |

Relationships:
- One estate can have multiple gates.
- One estate can have multiple residents.
- One estate can manage multiple vehicles.
- One estate can receive multiple visitors.

### 4.2 Gate

Represents an entrance or exit point within an estate.

| Field | Data Type | Constraint |
|---|---|---|
| id | UUID | Primary Key |
| estate_id | UUID | Foreign Key |
| name | VARCHAR(100) | NOT NULL |
| gate_type | VARCHAR(20) | NOT NULL |
| location_description | TEXT | NULL |
| is_active | BOOLEAN | DEFAULT TRUE |
| created_at | TIMESTAMP | NOT NULL |

Gate types:
- ENTRY
- EXIT
- BOTH

### 4.3 User

Represents an authenticated system user.

The implementation will use Django's custom user model.

| Field | Data Type | Constraint |
|---|---|---|
| id | UUID | Primary Key |
| username | VARCHAR(150) | UNIQUE |
| email | VARCHAR(254) | UNIQUE |
| password | VARCHAR | Hashed |
| role | VARCHAR(30) | NOT NULL |
| is_active | BOOLEAN | DEFAULT TRUE |
| created_at | TIMESTAMP | NOT NULL |

Supported roles:
- SYSTEM_ADMIN
- ESTATE_MANAGER
- SECURITY_OFFICER
- RESIDENT

### 4.4 Resident

Represents an individual registered within an estate.

| Field | Data Type | Constraint |
|---|---|---|
| id | UUID | Primary Key |
| estate_id | UUID | Foreign Key |
| user_id | UUID | Foreign Key |
| apartment_number | VARCHAR(50) | NOT NULL |
| phone_number | VARCHAR(30) | NULL |
| created_at | TIMESTAMP | NOT NULL |

A resident belongs to one estate and is associated with an authenticated user account.

### 4.5 Vehicle

Represents a vehicle registered to an estate resident.

| Field | Data Type | Constraint |
|---|---|---|
| id | UUID | Primary Key |
| estate_id | UUID | Foreign Key |
| resident_id | UUID | Foreign Key |
| registration_number | VARCHAR(20) | NOT NULL |
| vehicle_type | VARCHAR(50) | NULL |
| make | VARCHAR(100) | NULL |
| model | VARCHAR(100) | NULL |
| color | VARCHAR(50) | NULL |
| is_reported_stolen | BOOLEAN | DEFAULT FALSE |
| is_active | BOOLEAN | DEFAULT TRUE |
| created_at | TIMESTAMP | NOT NULL |
| updated_at | TIMESTAMP | NOT NULL |

Business rules:
- Registration numbers should be normalized before comparison.
- Registration numbers should be unique within an estate for active vehicle records.
- A vehicle must belong to a resident within the same estate.
- Reported stolen vehicles must be flagged during verification.

### 4.6 Visitor

Represents a person visiting a resident within an estate.

| Field | Data Type | Constraint |
|---|---|---|
| id | UUID | Primary Key |
| estate_id | UUID | Foreign Key |
| full_name | VARCHAR(150) | NOT NULL |
| identification_reference | VARCHAR(100) | NULL |
| phone_number | VARCHAR(30) | NULL |
| created_at | TIMESTAMP | NOT NULL |

Visitor records are separate from permanent resident records.

### 4.7 VisitorPass

Represents permission granted to a visitor to access an estate.

| Field | Data Type | Constraint |
|---|---|---|
| id | UUID | Primary Key |
| visitor_id | UUID | Foreign Key |
| resident_id | UUID | Foreign Key |
| registration_number | VARCHAR(20) | NULL |
| status | VARCHAR(30) | NOT NULL |
| valid_from | TIMESTAMP | NOT NULL |
| valid_until | TIMESTAMP | NOT NULL |
| approved_at | TIMESTAMP | NULL |
| created_at | TIMESTAMP | NOT NULL |

Supported statuses:
- PENDING
- APPROVED
- REJECTED
- EXPIRED
- REVOKED

A visitor pass must be approved by the resident or an authorized estate manager before admission.

### 4.8 VehicleSession

Represents a vehicle's period of presence inside the estate.

This is one of the most important entities in the system because it connects vehicle entry and exit activities.

| Field | Data Type | Constraint |
|---|---|---|
| id | UUID | Primary Key |
| estate_id | UUID | Foreign Key |
| vehicle_id | UUID | Nullable Foreign Key |
| visitor_pass_id | UUID | Nullable Foreign Key |
| observed_registration | VARCHAR(20) | NOT NULL |
| entry_gate_id | UUID | Foreign Key |
| exit_gate_id | UUID | Nullable Foreign Key |
| entry_time | TIMESTAMP | NOT NULL |
| exit_time | TIMESTAMP | NULL |
| status | VARCHAR(30) | NOT NULL |
| created_at | TIMESTAMP | NOT NULL |
| updated_at | TIMESTAMP | NOT NULL |

Supported statuses:
- ACTIVE
- COMPLETED
- FLAGGED
- CANCELLED

Business rules:
- Every successful entry creates a vehicle session.
- A vehicle session must have an entry timestamp.
- An exit timestamp is recorded when the vehicle successfully exits.
- Only one active session per vehicle registration number per estate is allowed.
- A visitor vehicle may have no permanent Vehicle record.
- The observed registration number must be preserved even if the registered vehicle information changes.

### 4.9 GateEvent

Represents an event recorded at an estate gate.

| Field | Data Type | Constraint |
|---|---|---|
| id | UUID | Primary Key |
| gate_id | UUID | Foreign Key |
| session_id | UUID | Nullable Foreign Key |
| event_id | UUID | UNIQUE |
| event_type | VARCHAR(30) | NOT NULL |
| occurred_at | TIMESTAMP | NOT NULL |
| processing_status | VARCHAR(30) | NOT NULL |
| created_at | TIMESTAMP | NOT NULL |

Event types:
- VEHICLE_DETECTED
- ENTRY_REQUESTED
- ENTRY_AUTHORIZED
- ENTRY_DENIED
- EXIT_REQUESTED
- EXIT_AUTHORIZED
- EXIT_DENIED

The unique event_id supports idempotent event processing.

### 4.10 RecognitionRecord

Stores the results of automatic number plate recognition.

| Field | Data Type | Constraint |
|---|---|---|
| id | UUID | Primary Key |
| gate_event_id | UUID | Foreign Key |
| vehicle_id | UUID | Nullable Foreign Key |
| detected_plate | VARCHAR(20) | NOT NULL |
| confidence | DECIMAL(5,4) | NOT NULL |
| image_reference | TEXT | NULL |
| recognition_status | VARCHAR(30) | NOT NULL |
| created_at | TIMESTAMP | NOT NULL |

The original detected plate must be retained for auditing even if the recognition result is incorrect.

### 4.11 SecurityAlert

Stores suspicious activities identified by the system.

| Field | Data Type | Constraint |
|---|---|---|
| id | UUID | Primary Key |
| estate_id | UUID | Foreign Key |
| vehicle_id | UUID | Nullable Foreign Key |
| session_id | UUID | Nullable Foreign Key |
| gate_event_id | UUID | Nullable Foreign Key |
| alert_type | VARCHAR(50) | NOT NULL |
| severity | VARCHAR(20) | NOT NULL |
| description | TEXT | NOT NULL |
| status | VARCHAR(30) | NOT NULL |
| assigned_to_id | UUID | Nullable Foreign Key |
| created_at | TIMESTAMP | NOT NULL |
| resolved_at | TIMESTAMP | NULL |

Alert types:
- REPORTED_STOLEN_VEHICLE
- UNAUTHORIZED_EXIT
- MISSING_ENTRY_SESSION
- REGISTRATION_MISMATCH
- INVALID_VISITOR_PASS
- DUPLICATE_ACTIVE_SESSION
- RECOGNITION_FAILURE

Severity levels:
- LOW
- MEDIUM
- HIGH
- CRITICAL

Alert statuses:
- OPEN
- INVESTIGATING
- RESOLVED
- DISMISSED

### 4.12 AuditLog

Records important activities performed by users and system services.

| Field | Data Type | Constraint |
|---|---|---|
| id | UUID | Primary Key |
| user_id | UUID | Nullable Foreign Key |
| action | VARCHAR(100) | NOT NULL |
| entity_type | VARCHAR(100) | NOT NULL |
| entity_id | UUID | NULL |
| details | JSONB | NULL |
| created_at | TIMESTAMP | NOT NULL |

Examples:
- Vehicle registered.
- Visitor pass approved.
- Vehicle entry authorized.
- Vehicle exit denied.
- Security alert resolved.

## 5. Entity Relationships

| Relationship | Cardinality |
|---|---|
| Estate → Gate | One-to-Many |
| Estate → Resident | One-to-Many |
| Estate → Vehicle | One-to-Many |
| User → Resident | One-to-One |
| Resident → Vehicle | One-to-Many |
| Resident → VisitorPass | One-to-Many |
| Visitor → VisitorPass | One-to-Many |
| Vehicle → VehicleSession | One-to-Many |
| VisitorPass → VehicleSession | One-to-Many |
| Gate → GateEvent | One-to-Many |
| VehicleSession → GateEvent | One-to-Many |
| GateEvent → RecognitionRecord | One-to-Many |
| Vehicle → SecurityAlert | One-to-Many |

## 6. Database Integrity Rules

1. All primary identifiers use UUIDs.
2. Foreign key relationships must be enforced.
3. Vehicle registration numbers must be normalized.
4. Resident and vehicle estate ownership must be consistent.
5. Visitor passes must have valid time windows.
6. An active vehicle session must not have an exit timestamp.
7. Completed sessions must have both entry and exit timestamps.
8. An event ID must be unique.
9. Duplicate Kafka events must not produce duplicate business records.
10. Security decisions and manual overrides must be auditable.

## 7. Indexing Strategy

Recommended indexes:

- `Vehicle(estate_id, registration_number)`
- `VehicleSession(estate_id, observed_registration, status)`
- `GateEvent(event_id)`
- `GateEvent(gate_id, occurred_at)`
- `RecognitionRecord(detected_plate)`
- `SecurityAlert(estate_id, status, severity)`
- `VisitorPass(visitor_id, status, valid_from, valid_until)`

A partial unique index should prevent multiple active sessions for the same normalized registration number within an estate.

## 8. Data Storage Strategy

PostgreSQL:
- Residents
- Vehicles
- Visitor permissions
- Vehicle sessions
- Gate events
- Recognition results
- Security alerts
- Audit records

MinIO:
- CCTV snapshots
- Captured vehicle images
- Number plate evidence
- Relevant video clips

Kafka:
- Vehicle recognition events
- Entry and exit events
- Verification events
- Security alerts

Kafka is an event transport mechanism and is not the authoritative source of business records.

## 9. Security and Privacy

- Restrict database access to authorized backend services.
- Apply role-based access control.
- Avoid storing unnecessary personal identification information.
- Encrypt sensitive information where appropriate.
- Restrict access to CCTV evidence.
- Define evidence retention and deletion policies.
- Record access to sensitive security records.

## 10. Conclusion

The database design provides a relational foundation for the Estate Car Theft Detection System. It supports multiple estates, residents, visitors, gates and vehicle movement sessions while maintaining the historical evidence required for security monitoring and incident investigation.