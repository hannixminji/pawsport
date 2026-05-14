# 🐾 PawsPort — System Description & Runtime Requirements

PawsPort is a smart digital pet passport platform combining:
- social graph (posts, comments, chats)
- AI-powered pet identification
- vector-based similarity search
- cloud-backed authentication and storage

The system is designed to run consistently across local and cloud environments using identical runtime dependencies.

---

# 🧠 Core Architecture

PawsPort consists of the following services:

## 1. API Service (FastAPI)
Main backend service responsible for:
- REST API endpoints
- authentication middleware (Firebase Admin SDK)
- business logic
- integration with ML service
- integration with Firestore and Qdrant

---

## 2. Worker Service
Background processing system responsible for:
- async tasks
- queue-based processing
- initialization scripts (bootstrap logic)
- database seeding and system setup tasks

---

## 3. ML Service
AI inference engine responsible for:
- pet image feature extraction
- embedding generation
- detection and classification tasks

Communicates with API service via HTTP.

---

## 4. Qdrant Vector Database
Used for:
- storing image embeddings
- similarity search
- pet identification matching

---

## 5. PostgreSQL (PostGIS enabled)
Used for:
- relational data storage
- geospatial queries
- transactional consistency

---

## 6. Redis
Used for:
- caching
- job queues
- session storage
- rate limiting

---

## 7. Firebase Services

### Authentication
Handles:
- user identity
- token validation
- session security

### Firestore
Used as:
- primary NoSQL document database
- real-time sync store

### Cloud Functions (Firestore triggers)
Used for:
- counter updates (likes, comments, replies)
- image aggregation updates
- reactive database consistency logic

---

## 8. Google Cloud Storage (GCS)
Used for:
- image uploads
- thumbnails
- media storage

Accessed through Google Service Account credentials.

---

# 🔐 Authentication & Identity Model

Authentication is handled via Firebase Authentication.

Backend services validate requests using Firebase Admin SDK with:

- Service Account JSON credentials
- Google Application Default Credentials (ADC style)

---

# 🔑 Required External Credentials

The system requires a service account JSON with permissions for:

### Firestore access
- read/write document operations

### Storage access
- upload/download objects in GCS

### Authentication
- verify Firebase ID tokens

### Logging
- write application logs

---

# 🧾 Firestore Data Model (High Level)

## users
- user profile data
- status flags (banned, muted, restrictions)

## posts
- social posts
- counters (likes, comments)
- media references

## nested collections:
- likes
- comments
- replies
- media/images

---

# 🔥 Firestore Security Model

Security rules enforce:

- authenticated access required for write operations
- ownership-based updates for user-owned resources
- restrictions for banned/muted users
- immutable system counters (managed by backend/functions)

---

# ⚡ Firebase Cloud Functions (Event System)

Cloud Functions are used to maintain data consistency:

## Post interactions
- increment/decrement likes
- update comment counters
- maintain reply counts

## Media system
- recompute image counts
- generate thumbnail references

All triggers are event-driven using Firestore document changes.

---

# 🧠 AI / ML Pipeline

### Flow:
1. Image uploaded to system
2. ML service generates embedding
3. Embedding stored in Qdrant
4. API performs similarity search
5. Matching results returned to client

---

# 📦 Containerized Runtime Model

The system is designed for containerized execution:

- API service container
- Worker service container
- ML service container
- PostgreSQL container
- Redis container
- Qdrant container

All services communicate via internal network DNS.

---

# 🌐 External Dependencies

The system requires:

- Firebase project (Auth + Firestore enabled)
- Google Cloud project (Storage enabled)
- Service Account credentials JSON
- Network access to Qdrant (local or remote)
- ML service runtime availability

---

# 🧩 Design Principles

- Event-driven consistency (Firestore triggers)
- Stateless API layer
- Externalized identity (Firebase Auth)
- Vector-first AI matching (Qdrant)
- Modular service separation (API / Worker / ML)
- Cloud-agnostic container runtime

---

# ⚠️ Operational Notes

- Firestore counters are not client-authoritative
- All counters must be updated via backend or Cloud Functions
- ML inference is stateless and horizontally scalable
- Service account must never be exposed to client applications
- Qdrant is the source of truth for embeddings
