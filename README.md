# FaceRealTimeDect 👁️🚀

A comprehensive, microservices-based Real-Time Face Detection and Recognition platform. This project leverages the power of deep learning for highly accurate facial recognition, while keeping inference lightweight enough to run efficiently on CPUs. 

Designed with a modern full-stack architecture, it seamlessly handles live video streams, automatic registration of unknown faces, and persistent data storage.

---

## ✨ Features

- **Real-Time Video Matching**: Low-latency face tracking and recognition over WebSockets.
- **CPU-Optimized AI Engine**: Uses `InsightFace` (antelopev2) and ONNXRuntime configured for fast CPU execution, eliminating the strict requirement for high-end GPUs.
- **Automatic Stranger Enrollment**: 
  - Unknown faces are tracked continuously.
  - After aggregating 20 high-quality frames of an unknown person, the system calculates an averaged centroid embedding for high accuracy and robust matching.
  - Automatically registers the person (e.g., "Stranger 1") in the database and saves a cropped profile image.
- **Microservices Architecture**: Cleanly separated into Frontend (React), Backend (.NET API), and AI Services (Python/FastAPI).
- **Persistent Data Store**: SQL Server database integration via Entity Framework Core to store user identities and facial embeddings.

---

## 🏗️ Architecture Stack

### 1. AI Service (`/ai-services`)
- **Language/Framework**: Python, FastAPI
- **AI/CV Tools**: InsightFace, OpenCV, NumPy, ONNXRuntime
- **Responsibilities**: WebSockets for streaming video frames, facial landmark extraction (5-point alignment), computing 512-d embeddings, and calculating cosine similarity. Connects directly to the database for caching and real-time syncing.

### 2. Backend API (`/Backend`)
- **Language/Framework**: C#, ASP.NET Core 10 (.NET 10)
- **Tools**: Entity Framework Core (SQL Server), MathNet.Numerics, OpenCvSharp4
- **Responsibilities**: Provides robust CRUD API endpoints for user management, serves enrolled facial images, manages migrations, and handles business logic.

### 3. Frontend UI (`/Frontend`)
- **Language/Framework**: React 19, Vite
- **Styling**: Tailwind CSS v4
- **Responsibilities**: Responsive, modern, and sleek user interface for monitoring the camera feed, managing stored users, and viewing recognition metrics.

---

## 🚀 Getting Started

### Prerequisites
- Node.js (v18+)
- .NET 10 SDK
- Python 3.10+
- SQL Server (LocalDB or Express)

### 1. Setup the Database
Ensure your SQL Server instance is running. The Backend will apply EF Core migrations, and the AI service expects the database (`VideoFaceDetect`) to be accessible.

### 2. Start the AI Service
```bash
cd ai-services
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
