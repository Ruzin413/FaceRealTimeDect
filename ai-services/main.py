import os
import json
import numpy as np
import cv2
import pyodbc
from typing import List, Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
import insightface
from insightface.app import FaceAnalysis
from datetime import datetime
import time
app = FastAPI(title="Face Detection CPU-Friendly Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
print("Initializing FaceAnalysis...")
# Set root to current directory to use local ./models/antelopev2 folder
face_app = FaceAnalysis(name='antelopev2', root='.', providers=['CPUExecutionProvider'])
# Increased from 640 to 800 to significantly improve detection accuracy for small/distant faces on the new 720p feed
face_app.prepare(ctx_id=0, det_size=(800, 800))
print("FaceAnalysis Ready!")
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

stranger_counter = 0
users_cache = []
recent_enrollments = []
pending_strangers = []
ENROLLMENT_COOLDOWN = 10.0

def get_initial_stranger_count():
    global stranger_counter
    conn = get_db_connection()
    if conn:
        cursor = conn.cursor()
        try:
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
get_initial_stranger_count()
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_UPLOADS_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "Backend", "Backend", "Uploads"))
def save_new_stranger(name, embedding_np, face_img):
    if not os.path.exists(BACKEND_UPLOADS_DIR):
        os.makedirs(BACKEND_UPLOADS_DIR, exist_ok=True)
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
async def extract_embedding(file: bytes = File(...)):
    """Receives an image, detects the largest face, and returns its 512-d embedding as JSON.
    Uses 'bytes' to avoid Starlette's automatic temporary file spooling for large uploads.
    """
    nparr = np.frombuffer(file, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image file.")
    faces = face_app.get(img)
    if len(faces) == 0:
        raise HTTPException(status_code=400, detail="No face detected in the image.")
    largest_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
    embedding_list = largest_face.normed_embedding.tolist()
    return {"embedding": embedding_list}

@app.delete("/user_cache/{user_id}")
async def delete_user_cache(user_id: int, request: Request):
    """Notify the AI service that a user was deleted from the DB to sync the in-memory cache."""
    name = request.query_params.get("name")
    
    global users_cache
    original_len = len(users_cache)
    
    if name:
        users_cache = [u for u in users_cache if u.get("id") != user_id and u.get("name") != name]
    else:
        users_cache = [u for u in users_cache if u.get("id") != user_id]
    
    if len(users_cache) < original_len:
        print(f"User ID {user_id} (Name: {name}) removed from AI cache.")
        return {"status": "success", "message": f"User removed from cache."}
    else:
        print(f"User ID {user_id} (Name: {name}) not found in AI cache.")
        return {"status": "not_found", "message": "User not in cache."}

@app.put("/user_cache/rename")
async def rename_user_cache(request: Request):
    data = await request.json()
    old_name = data.get("old_name")
    new_name = data.get("new_name")
    
    global users_cache
    global recent_enrollments
    updated = False
    
    for u in users_cache:
        if u["name"] == old_name:
            u["name"] = new_name
            updated = True
            
    for e in recent_enrollments:
        if e["name"] == old_name:
            e["name"] = new_name
            
    if updated:
        print(f"Renamed {old_name} to {new_name} in AI cache.")
        return {"status": "success"}
    return {"status": "not_found"}
@app.websocket("/match_frame")
async def match_frame(websocket: WebSocket):
    """WebSocket endpoint to receive frames, process matching, and return results."""
    await websocket.accept()
    
    global recent_enrollments
    global users_cache
    global stranger_counter
    global pending_strangers
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
    
    # Benchmarking variables
    frame_count = 0
    total_time = 0.0
    
    try:
        while True:
            data = await websocket.receive_bytes()
            start_time = time.perf_counter() # Start Benchmark
            nparr = np.frombuffer(data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                continue
            faces = face_app.get(img)
            results = []
            for face in faces:
                best_match_name = "Unknown"
                best_match_score = 0.0
                for user in users_cache:
                    sim = compute_similarity(face.normed_embedding, user["embedding"])
                    if sim > best_match_score:
                        best_match_score = sim
                        # Lowered to 0.30 to increase tolerance for face masks and poor lighting
                        if sim > 0.30:  
                            best_match_name = user["name"]
                if best_match_name == "Unknown":
                    current_time = time.time()
                    recent_enrollments = [e for e in recent_enrollments if current_time - e["timestamp"] < ENROLLMENT_COOLDOWN]
                    for r_enroll in recent_enrollments:
                        sim = compute_similarity(face.normed_embedding, r_enroll["embedding"])
                        # Lowered to 0.30 to increase tolerance for face masks and poor lighting
                        if sim > 0.30: 
                            best_match_name = r_enroll["name"]
                            best_match_score = sim
                            break
                if best_match_name == "Unknown":
                    current_time = time.time()
                    
                    # Clean up expired pending stranger scans (e.g. person left frame for 30 seconds)
                    pending_strangers = [p for p in pending_strangers if current_time - p["timestamp"] < 30.0]
                    
                    matched_pending = None
                    for p in pending_strangers:
                        # Compare against the rolling average of collected embeddings so far
                        curr_avg = np.mean(p["embeddings"], axis=0)
                        curr_avg = curr_avg / np.linalg.norm(curr_avg)
                        sim = compute_similarity(face.normed_embedding, curr_avg)
                        if sim > 0.30:
                            matched_pending = p
                            break
                            
                    if matched_pending is not None:
                        matched_pending["embeddings"].append(face.normed_embedding)
                        matched_pending["timestamp"] = current_time
                        best_match_name = f"Scanning {len(matched_pending['embeddings'])}/20"
                        best_match_score = sim
                        
                        # Once we collect 20 templates, average them and commit to DB!
                        if len(matched_pending["embeddings"]) >= 20:
                            stranger_counter += 1
                            new_name = f"Stranger {stranger_counter}"
                            
                            # Create a highly robust averaged centroid embedding
                            final_avg = np.mean(matched_pending["embeddings"], axis=0)
                            final_avg = final_avg / np.linalg.norm(final_avg)
                            
                            if save_new_stranger(new_name, final_avg, matched_pending["face_crop"]):
                                users_cache.append({
                                    "id": -1, 
                                    "name": new_name,
                                    "embedding": final_avg
                                })
                                recent_enrollments.append({
                                    "name": new_name,
                                    "embedding": final_avg,
                                    "timestamp": time.time()
                                })
                            pending_strangers.remove(matched_pending)
                            best_match_name = new_name
                    else:
                        # Encountering a brand new unknown face. Start aggregating!
                        # Use the 5 keypoints to perform a professional affine alignment crop
                        if hasattr(face, 'kps') and face.kps is not None:
                            from insightface.utils import face_align
                            # Standard 112x112 aligned face crop used by ArcFace
                            face_crop = face_align.norm_crop(img, landmark=face.kps, image_size=112)
                        else:
                            # Fallback to simple bbox crop if no keypoints
                            x1, y1, x2, y2 = map(int, face.bbox)
                            h, w = img.shape[:2]
                            x1, y1 = max(0, x1), max(0, y1)
                            x2, y2 = min(w, x2), min(h, y2)
                            face_crop = img[y1:y2, x1:x2]

                        pending_strangers.append({
                            "embeddings": [face.normed_embedding],
                            "face_crop": face_crop,
                            "timestamp": current_time
                        })
                        best_match_name = f"Scanning 1/20"
                        best_match_score = 1.0
                
                # Extract 5 facial keypoints if available
                landmarks = []
                if hasattr(face, 'kps') and face.kps is not None:
                    landmarks = face.kps.tolist()

                results.append({
                    "bbox": face.bbox.tolist(),
                    "name": best_match_name,
                    "score": float(best_match_score),
                    "landmarks": landmarks
                })
            await websocket.send_json({"matches": results})

            # Benchmarking logic
            frame_count += 1
            elapsed = time.perf_counter() - start_time
            total_time += elapsed
            if frame_count % 10 == 0:
                avg_time = (total_time / 10) * 1000 # in ms
                fps = 1.0 / (total_time / 10)
                print(f"BENCHMARK: Avg Inference: {avg_time:.2f}ms | Est. Max FPS: {fps:.1f}")
                total_time = 0.0
            
    except Exception as e:
        print(f"WebSocket closed or error: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
