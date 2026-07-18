"""
To-Do List App — multi-user backend
- SQLite database (tasks.db) so every user's tasks are stored separately
- Signup / login with hashed passwords (pbkdf2, no extra native deps)
- JWT token issued on login, required for all /api/tasks routes
- Serves the frontend (index.html) at "/"
"""

import os
import sqlite3
import hashlib
import secrets
import datetime

import jwt
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel

APP_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(APP_DIR, "tasks.db")

# Reads SECRET_KEY from the environment (set this in Render's dashboard).
# Falls back to a default only for local testing.
SECRET_KEY = os.environ.get("SECRET_KEY", "local-dev-secret-change-me")
TOKEN_EXPIRY_HOURS = 24 * 7  # tokens last a week

app = FastAPI(title="To-Do List App (multi-user)")


# ---------- Database setup ----------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            salt TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            completed INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    conn.commit()
    conn.close()


init_db()


# ---------- Password hashing ----------

def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()


def verify_password(password: str, salt: str, stored_hash: str) -> bool:
    return hash_password(password, salt) == stored_hash


# ---------- JWT helpers ----------

def create_token(user_id: int, username: str) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=TOKEN_EXPIRY_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def get_current_user(authorization: str = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not logged in.")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired, please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session.")
    return {"id": payload["user_id"], "username": payload["username"]}


# ---------- Request models ----------

class AuthIn(BaseModel):
    username: str
    password: str


class TaskIn(BaseModel):
    text: str


# ---------- Auth routes ----------

@app.post("/api/auth/signup")
def signup(data: AuthIn):
    username = data.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters.")
    if len(data.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")

    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="That username is already taken.")

    salt = secrets.token_hex(16)
    password_hash = hash_password(data.password, salt)
    cursor = conn.execute(
        "INSERT INTO users (username, salt, password_hash, created_at) VALUES (?, ?, ?, ?)",
        (username, salt, password_hash, datetime.datetime.utcnow().isoformat()),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()

    token = create_token(user_id, username)
    return {"token": token, "username": username}


@app.post("/api/auth/login")
def login(data: AuthIn):
    username = data.username.strip()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()

    if not user or not verify_password(data.password, user["salt"], user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password.")

    token = create_token(user["id"], user["username"])
    return {"token": token, "username": user["username"]}


# ---------- Task routes (all require a valid token) ----------

@app.get("/api/tasks")
def get_tasks(user=Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, text, completed FROM tasks WHERE user_id = ? ORDER BY id", (user["id"],)
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "text": r["text"], "completed": bool(r["completed"])} for r in rows]


@app.get("/api/tasks/stats")
def get_stats(user=Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("SELECT completed FROM tasks WHERE user_id = ?", (user["id"],)).fetchall()
    conn.close()
    total = len(rows)
    completed = sum(1 for r in rows if r["completed"])
    return {"total": total, "completed": completed, "pending": total - completed}


@app.post("/api/tasks")
def add_task(task: TaskIn, user=Depends(get_current_user)):
    text = task.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Task text cannot be empty.")
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO tasks (user_id, text, completed) VALUES (?, ?, 0)", (user["id"], text)
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return {"id": new_id, "text": text, "completed": False}


@app.patch("/api/tasks/{task_id}/toggle")
def toggle_task(task_id: int, user=Depends(get_current_user)):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, user["id"])
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found.")
    new_state = 0 if row["completed"] else 1
    conn.execute("UPDATE tasks SET completed = ? WHERE id = ?", (new_state, task_id))
    conn.commit()
    conn.close()
    return {"id": task_id, "completed": bool(new_state)}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int, user=Depends(get_current_user)):
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM tasks WHERE id = ? AND user_id = ?", (task_id, user["id"])
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found.")
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/tasks")
def delete_all_tasks(user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM tasks WHERE user_id = ?", (user["id"],))
    conn.commit()
    conn.close()
    return {"ok": True}


# ---------- Serve frontend ----------

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(APP_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)