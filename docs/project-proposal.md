# Estate Car Theft Detection System

## 1. Introduction

Vehicle theft and unauthorized vehicle movement remain security concerns within gated residential estates. Traditional security procedures often depend on manual vehicle registration checks and security personnel visually inspecting vehicles at entry and exit points.

These procedures can be vulnerable to human error, inadequate recordkeeping, unauthorized vehicle movement and difficulties verifying whether a vehicle leaving an estate was legitimately admitted.

The proposed Estate Car Theft Detection System is an intelligent vehicle monitoring and verification platform designed to improve vehicle security within residential estates.

## 2. Problem Statement

Residential estates require reliable mechanisms for monitoring vehicles entering and leaving their premises. Manual verification processes may fail to identify suspicious movements, mismatched registration plates, unauthorized exits and vehicles leaving without corresponding entry records.

There is a need for an integrated system capable of maintaining vehicle records, monitoring entry and exit events, verifying vehicle authorization and generating alerts when suspicious activities occur.

## 3. Project Aim

To design and develop an intelligent vehicle security system that monitors, verifies and records vehicle movements within gated residential estates, helping security personnel detect and respond to potential vehicle theft.

## 4. Project Objectives

1. Develop a centralized database for registered residents, vehicles, visitors and gate records.
2. Implement automatic number plate recognition using computer vision and OCR.
3. Develop vehicle entry and exit verification mechanisms.
4. Implement visitor registration and host approval workflows.
5. Integrate Apache Kafka for real-time vehicle event processing.
6. Detect suspicious vehicle movements and generate security alerts.
7. Develop a dashboard for monitoring vehicle activities and managing security incidents.
8. Provide manual verification mechanisms when automated recognition is unavailable or unreliable.

## 5. Proposed Solution

The system will combine a centralized backend, computer vision, event streaming and a web-based security dashboard.

At entry, a vehicle is captured through an image or video source. Its registration plate is extracted and checked against estate records. Registered vehicles can proceed through the authorized entry workflow, while unregistered vehicles follow visitor registration and host approval.

Each successful entry creates a vehicle movement session. At exit, the system verifies the vehicle against its active entry session and applicable authorization.

Suspicious movements, including plate mismatches, missing entry sessions and reported stolen vehicles, generate security alerts for investigation by authorized personnel.

## 6. Project Scope

The project will focus on a residential estate with one or more controlled gates.

The prototype will support:
- Resident and vehicle registration.
- Gate and CCTV event management.
- Number plate recognition.
- Visitor registration and approval.
- Vehicle entry and exit sessions.
- Real-time event streaming.
- Suspicious movement detection.
- Security alerts and incident management.
- Security monitoring dashboard.
- Manual recognition and verification fallback.

Physical gate automation and production CCTV hardware integration are outside the initial prototype scope.

## 7. Expected Outcomes

A functional prototype demonstrating how computer vision, backend services, event streaming and database-driven verification can improve vehicle security and accountability within gated residential estates.

## 8. Proposed Technologies

Python, Django REST Framework, FastAPI, PostgreSQL, Apache Kafka, Redis, MinIO, OpenCV, YOLO, PaddleOCR, Next.js, TypeScript and Docker.