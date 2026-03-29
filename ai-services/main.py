import os
import json
import numpy as np
import cv2
import pyodbc
from typing import List, Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import insightface
from insightface.app import FaceAnalysis
from datetime import datetime
import time

app = FastAPI(title="Face Detection CPU-Friendly Service")

# Allow CORS for Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize InsightFace
# Using antelopev2 requires the model to be downloaded.
# It automatically downloads to ~/.insightface/models/antelopev2
print("Initializing FaceAnalysis...")
face_app = FaceAnalysis(name='antelopev2', providers=['CPUExecutionProvider'])
face_app.prepare(ctx_id=0, det_size=(640, 640))
print("FaceAnalysis Ready!")

# --- Database Connection Logic ---
# DB Connection Details from appsettings.json
DB_CONNECTION_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=DESKTOP-6E3VAT1\\SQLEXPRESS;"
    "DATABASE=VideoFaceDetect;"
    "Trusted_Connection=yes;"
)

def get_db_connection():
    try:
        conn = pyodbc.connect(DB_CONNECTION_STRING)
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None
# ---------------------------------

# Global stranger counter and local user cache
stranger_counter = 0
users_cache = []
# Cache for very recently enrolled strangers to prevent double-enrollment [ {embedding: np.array, name: str, timestamp: float} ]
recent_enrollments = []
ENROLLMENT_COOLDOWN = 10.0 # seconds

def get_initial_stranger_count():
    global stranger_counter
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            # Find the highest Number in "Stranger {Number}"
            # Check if table exists first for robustness
            cursor.execute("IF OBJECT_ID('Users', 'U') IS NOT NULL SELECT Name FROM Users WHERE Name LIKE 'Stranger %'")
            rows = cursor.fetchall()
            max_num = 0
            for row in rows:
                try:
                    parts = row.Name.split(' ')
                    if len(parts) >= 2:
                        num = int(parts[1])
                        if num > max_num:
                            max_num = num
                except:
                    continue
            stranger_counter = max_num
            print(f"Synced stranger_counter from DB: {stranger_counter}")
        except Exception as e:
            print(f"Error initializing stranger counter: {e}")
        finally:
            conn.close()

# Call sync on server startup
get_initial_stranger_count()

# Shared Uploads Path (Backend folder)
# Get absolute path relative to this script's location for robustness
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_UPLOADS_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "Backend", "Backend", "Uploads"))

def save_new_stranger(name, embedding_np, face_img):
    # Ensure directory exists
    if not os.path.exists(BACKEND_UPLOADS_DIR):
        os.makedirs(BACKEND_UPLOADS_DIR, exist_ok=True)
    
    # Save image first
    img_filename = f"{name.replace(' ', '_')}.jpg"
    img_path = os.path.join(BACKEND_UPLOADS_DIR, img_filename)
    cv2.imwrite(img_path, face_img)
    print(f"Saved face image to {img_path}")

    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
            emb_json = json.dumps(embedding_np.tolist())
            now = datetime.now()
            cursor.execute(
                "INSERT INTO Users (Name, Embedding, ImagePath, CreatedAt) VALUES (?, ?, ?, ?)",
                (name, emb_json, img_filename, now)
            )
            conn.commit()
            print(f"Saved new face entry as {name} with image {img_filename}")
            return True
        except Exception as e:
            print(f"Error saving stranger to DB: {e}")
            return False
        finally:
            conn.close()
    return False

def compute_similarity(embedding1, embedding2):
    return np.dot(embedding1, embedding2) / (np.linalg.norm(embedding1) * np.linalg.norm(embedding2))

@app.post("/extract_embedding")
async def extract_embedding(file: UploadFile = File(...)):
    """Receives an image, detects the largest face, and returns its 512-d embedding as JSON."""
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image file.")

    faces = face_app.get(img)
    if len(faces) == 0:
        raise HTTPException(status_code=400, detail="No face detected in the image.")

    # Get the largest face
    largest_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
    
    # Returning as list of floats
    embedding_list = largest_face.normed_embedding.tolist()
    return {"embedding": embedding_list}

@app.websocket("/match_frame")
async def match_frame(websocket: WebSocket):
    """WebSocket endpoint to receive frames, process matching, and return results."""
    await websocket.accept()
    
    global recent_enrollments
    global users_cache
    global stranger_counter
    
    # IMPORTANT: Clear local temporary cache on every new tab switch/connection
    # This forces the AI to look at the database (which has the new edited name)
    recent_enrollments = [] 

    # Preload embeddings from DB
    get_initial_stranger_count()
    conn = get_db_connection()
    users_cache = []
    if conn:
        cursor = conn.cursor()
        try:
            cursor.execute("IF OBJECT_ID('Users', 'U') IS NOT NULL SELECT Id, Name, Embedding FROM Users WHERE Embedding IS NOT NULL")
            rows = cursor.fetchall()
            for row in rows:
                try:
                    emb_list = json.loads(row.Embedding)
                    emb_np = np.array(emb_list, dtype=np.float32)
                    users_cache.append({"id": row.Id, "name": row.Name, "embedding": emb_np})
                except Exception as e:
                    print(f"Error parsing embedding for user {row.Name}: {e}")
        except Exception as e:
            print(f"Error fetching users: {e}")
        finally:
            conn.close()
    
    print(f"Loaded {len(users_cache)} users from database.")
    
    try:
        while True:
            # Receive frame as bytes
            data = await websocket.receive_bytes()
            nparr = np.frombuffer(data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                continue
            faces = face_app.get(img)
            results = []
            for face in faces:
                best_match_name = "Unknown"
                best_match_score = 0.0
                # Compare against all users
                for user in users_cache:
                    sim = compute_similarity(face.normed_embedding, user["embedding"])
                    if sim > best_match_score:
                        best_match_score = sim
                        if sim > 0.4:  # Threshold for ArcFace
                            best_match_name = user["name"]
                if best_match_name == "Unknown":
                    current_time = time.time()
                    recent_enrollments = [e for e in recent_enrollments if current_time - e["timestamp"] < ENROLLMENT_COOLDOWN]
                    
                    for r_enroll in recent_enrollments:
                        sim = compute_similarity(face.normed_embedding, r_enroll["embedding"])
                        if sim > 0.4: # Same threshold
                            best_match_name = r_enroll["name"]
                            best_match_score = sim
                            break
                if best_match_name == "Unknown":
                    stranger_counter += 1
                    new_name = f"Stranger {stranger_counter}"
                    x1, y1, x2, y2 = map(int, face.bbox)
                    h, w = img.shape[:2]
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)
                    face_crop = img[y1:y2, x1:x2]

                    if save_new_stranger(new_name, face.normed_embedding, face_crop):
                        best_match_name = new_name
                        # Add to local cache for immediate recognition in next frame
                        users_cache.append({
                            "id": -1, # Temporary ID
                            "name": new_name,
                            "embedding": face.normed_embedding
                        })
                        # Add to recent enrollments to prevent duplicates within the cooldown
                        recent_enrollments.append({
                            "name": new_name,
                            "embedding": face.normed_embedding,
                            "timestamp": time.time()
                        })
                
                results.append({
                    "bbox": face.bbox.tolist(),
                    "name": best_match_name,
                    "score": float(best_match_score)
                })
            await websocket.send_json({"matches": results})
            
    except Exception as e:
        print(f"WebSocket closed or error: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
