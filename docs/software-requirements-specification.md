# Software Requirements Specification (SRS)

## 1. Purpose

This document defines the functional and non-functional requirements of the Estate Car Theft Detection System.

## 2. System Users

| User | Responsibilities |
|---|---|
| System Administrator | Manage system configuration, users and estate records |
| Security Officer | Monitor gates, verify vehicles and investigate alerts |
| Estate Manager | Manage residents, registered vehicles and visitor permissions |
| Resident | Register vehicles and authorize visitors |

## 3. Functional Requirements

### FR-01: User Authentication
The system shall provide secure authentication and role-based access control.

### FR-02: Resident Management
The system shall allow authorized administrators to register and manage estate residents.

### FR-03: Vehicle Registration
The system shall store vehicle registration numbers, vehicle types, descriptions and associated owners.

### FR-04: Vehicle Recognition
The system shall process images or video frames to detect vehicles and extract registration plates.

### FR-05: Vehicle Entry Verification
The system shall determine whether a detected vehicle is registered or has an approved visitor authorization.

### FR-06: Visitor Management
The system shall allow visitors to be registered and associated with a resident host. Visitor entry shall require the configured approval process.

### FR-07: Entry Session Management
The system shall create an active movement session when a vehicle is successfully admitted.

### FR-08: Exit Verification
The system shall verify an exiting vehicle against its active entry session, authorization and recorded registration plate.

### FR-09: Suspicious Movement Detection
The system shall identify:
- Vehicles reported stolen.
- Vehicles attempting to exit without an active entry session.
- Registration plate mismatches.
- Unauthorized or expired visitor permissions.
- Other configured suspicious movements.

### FR-10: Event Streaming
The system shall publish relevant vehicle and gate events through Apache Kafka for asynchronous processing.

### FR-11: Alert Management
The system shall generate, record and expose security alerts to authorized personnel.

### FR-12: Audit Trail
The system shall maintain records of vehicle movements, verification decisions and security actions.

### FR-13: Manual Verification
The system shall support manual plate entry and security officer verification when automated recognition fails.

## 4. Non-Functional Requirements

### Performance
- Vehicle verification should be designed for near-real-time responses.
- Gate authorization decisions must not depend on delayed analytical processing.
- Kafka events must be processed reliably without creating duplicate movement sessions.

### Security
- Passwords must be securely hashed.
- APIs must enforce authentication and authorization.
- CCTV evidence must be protected from unauthorized access.
- Sensitive configuration must be stored outside source code.

### Reliability
- Failed event processing must be recoverable.
- Invalid or unprocessable events must be handled through a dead-letter queue.
- Database transactions must protect entry and exit session consistency.

### Scalability
- The architecture should support multiple gates.
- Recognition and verification services should be independently scalable.

### Maintainability
- Services should have clear responsibilities.
- APIs should be documented.
- Automated tests should cover critical verification workflows.

## 5. Business Rules

1. A registered vehicle must be associated with an estate resident.
2. A visitor must have a valid authorization before being admitted.
3. A successful vehicle entry must create an active movement session.
4. An exit must reference an existing active session.
5. A vehicle reported stolen must be flagged for investigation.
6. A plate mismatch must trigger additional verification rather than automatic approval.
7. Failed automated recognition must permit manual review.
8. A security officer's override must be recorded in the audit trail.
9. Repeated delivery of the same event must not create duplicate entry or exit records.
10. A vehicle must not have multiple conflicting active movement sessions within the same estate.

## 6. System Constraints

- The prototype will initially use simulated CCTV input and uploaded media.
- Automated number plate recognition depends on image quality and lighting conditions.
- The system will not physically control boom barriers in the initial implementation.
- Human security personnel retain responsibility for investigating suspicious events.

## 7. Acceptance Criteria

The prototype will be considered successful when:

- Residents and vehicles can be registered.
- Vehicle plates can be extracted from supported images.
- Registered vehicles can be verified.
- Visitors can be registered and approved.
- Entry and exit sessions are maintained correctly.
- Unauthorized movements generate alerts.
- Kafka events are processed reliably.
- Security officers can review vehicle movements and alerts through the dashboard.