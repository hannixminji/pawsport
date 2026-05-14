# 🐾 PawsPort: QR-Coded and AI-Powered Pet Identification System

> A mobile and AI-powered pet identification system designed to improve pet recovery, record management, and community-based reporting.

---

## 📌 Overview

PawsPort is a research-based system that integrates QR code technology, artificial intelligence, and cloud services to enhance pet identification and lost pet recovery.

The system allows pet owners to create digital pet profiles, generate QR-coded smart tags, and use AI-powered image recognition to verify and match pets.

A community feature supports reporting and tracking of lost and found pets in real time.

---

## ⚙️ Key Features

- 📱 Mobile pet profile management (Flutter)
- 🖥️ Admin dashboard (NestJS-based system)
- 🔳 QR-coded smart identification tags
- 🤖 AI-powered pet recognition system
- 📍 Lost & Found reporting with map visualization
- 💬 Community-driven pet network
- ☁️ Cloud-based backend and real-time data sync

---

## 🧠 AI System

The AI pipeline performs multi-stage pet identification:

- **YOLOv8s (Detection)**  
  Detects and localizes pet faces in images

- **YOLOv8s (Pose Validation)**  
  Ensures proper facial orientation using key landmarks

- **MegaDescriptor-L384 (Embedding Model)**  
  Extracts feature embeddings for identity matching

- **Vector Database Matching (Qdrant)**  
  Performs similarity search using a **60% confidence threshold**

---

## 🏗️ System Architecture

- **Mobile Frontend:** Flutter
- **Admin Panel:** NestJS
- **Backend API:** FastAPI
- **Authentication:** Firebase Authentication
- **Databases:**
  - PostgreSQL (Neon)
  - Firestore (real-time features)
  - Redis (caching)
- **AI Models:** YOLOv8s + MegaDescriptor-L384
- **Vector Search:** Qdrant
- **Storage:** Google Cloud Storage
- **Deployment:** Google Cloud Run / Firebase

---

## 📊 Dataset & Training

- PetFaceDetection dataset (Kaggle)
- Animals10 dataset (background augmentation)
- Over 25,000 images used for training and evaluation

### Training Pipeline:
- Two-stage YOLOv8s training process
- Image preprocessing (resize, filtering, validation)
- Background class inclusion for robustness

---

## 📱 Application Modules

- Home: Pet profiles, QR scanning, AI identification
- Lost & Found: Reports and map-based tracking
- Community: Posts, discussions, and engagement
- Profile: User settings and account management
- Admin Panel: User moderation, system monitoring, and report management

---

## 🎯 Objective

The system aims to improve traditional pet identification methods by providing:

- Faster and more accessible pet identification
- Improved lost pet recovery success rate
- Centralized digital pet records
- Community-assisted reporting system

---

## ⚠️ Limitations

- Currently supports only cats and dogs
- Requires internet connectivity
- AI performance depends on image quality
- Not a replacement for official microchip systems
- Android-only mobile implementation

---

## 👨‍💻 Authors & Contributions

- **Bargola, Yrvihn D.** – Frontend Development (Flutter mobile application) & Admin Dashboard (NestJS)
- **Calvis, Edmar A.** – Research Documentation & AI Detection Model Training
- **Dalida, Marc Lester S.** – Backend Development, API Design, and System Integration

---

## 🧠 System Type

Research-based AI-assisted pet identification and recovery platform integrating mobile, web admin, and cloud-based services.
