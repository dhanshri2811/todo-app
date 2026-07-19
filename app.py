"""
To-Do List App — teams edition (v3)
- Signup/login is the same for everyone, no role picker.
- Any user can create a Team (becomes its manager).
- A manager adds teammates by typing their username.
- A user can belong to at most one team, either as its manager or as a
  member of someone else's team.
- Tasks assigned by a manager to a team member show up in that member's
  normal task list.
"""

import os
import sqlite3
import hashlib
import secrets
import datetime

import jwt
from fastapi import FastAPI, HTTPException, Depends, Header, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

APP_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(APP_DIR, "tasks.db")

SECRET_KEY = os.environ.get("SECRET_KEY", "local-dev-secret-change-me")
TOKEN_EXPIRY_HOURS = 24 * 7

app = FastAPI(title="To-Do List App (teams edition)")


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
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            manager_id INTEGER NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            FOREIGN KEY (manager_id) REFERENCES users (id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS team_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL UNIQUE,
            joined_at TEXT NOT NULL,
            FOREIGN KEY (team_id) REFERENCES teams (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            assigned_by INTEGER,
            text TEXT NOT NULL,
            description TEXT DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'Medium',
            start_datetime TEXT,
            end_datetime TEXT,
            completed INTEGER NOT NULL DEFAULT 0,
            alert INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (owner_id) REFERENCES users (id)
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
    description: Optional[str] = ""
    priority: Optional[str] = "Medium"
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    assigned_to: Optional[int] = None  # team member's user id
    alert: Optional[bool] = False


class TaskUpdateIn(BaseModel):
    text: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[str] = None
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    alert: Optional[bool] = None


class TeamCreateIn(BaseModel):
    name: str


class AddMemberIn(BaseModel):
    username: str


VALID_PRIORITIES = {"High", "Medium", "Low"}


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


# ---------- Team helpers ----------

def _team_managed_by(conn, user_id):
    return conn.execute("SELECT * FROM teams WHERE manager_id = ?", (user_id,)).fetchone()


def _team_membership_of(conn, user_id):
    row = conn.execute("SELECT * FROM team_members WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return None
    team = conn.execute("SELECT * FROM teams WHERE id = ?", (row["team_id"],)).fetchone()
    return team


# ---------- Team routes ----------

@app.get("/api/team/me")
def team_me(user=Depends(get_current_user)):
    conn = get_db()
    managed = _team_managed_by(conn, user["id"])
    if managed:
        members = conn.execute("""
            SELECT u.id, u.username FROM team_members tm
            JOIN users u ON u.id = tm.user_id
            WHERE tm.team_id = ?
            ORDER BY u.username
        """, (managed["id"],)).fetchall()
        conn.close()
        return {
            "status": "manager",
            "team": {"id": managed["id"], "name": managed["name"]},
            "members": [{"id": m["id"], "username": m["username"]} for m in members],
        }

    membership = _team_membership_of(conn, user["id"])
    if membership:
        manager = conn.execute("SELECT username FROM users WHERE id = ?", (membership["manager_id"],)).fetchone()
        conn.close()
        return {
            "status": "member",
            "team": {"id": membership["id"], "name": membership["name"], "manager_username": manager["username"]},
        }

    conn.close()
    return {"status": "none", "team": None}


@app.post("/api/team/create")
def create_team(data: TeamCreateIn, user=Depends(get_current_user)):
    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Team name cannot be empty.")

    conn = get_db()
    if _team_managed_by(conn, user["id"]) or _team_membership_of(conn, user["id"]):
        conn.close()
        raise HTTPException(status_code=400, detail="You're already part of a team.")

    cursor = conn.execute(
        "INSERT INTO teams (name, manager_id, created_at) VALUES (?, ?, ?)",
        (name, user["id"], datetime.datetime.utcnow().isoformat()),
    )
    conn.commit()
    team_id = cursor.lastrowid
    conn.close()
    return {"id": team_id, "name": name}


@app.post("/api/team/add-member")
def add_member(data: AddMemberIn, user=Depends(get_current_user)):
    username = data.username.strip()
    conn = get_db()

    team = _team_managed_by(conn, user["id"])
    if not team:
        conn.close()
        raise HTTPException(status_code=403, detail="You need to create a team first.")

    target = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if not target:
        conn.close()
        raise HTTPException(status_code=404, detail="No user found with that username.")

    if target["id"] == user["id"]:
        conn.close()
        raise HTTPException(status_code=400, detail="You can't add yourself.")

    if _team_managed_by(conn, target["id"]) or _team_membership_of(conn, target["id"]):
        conn.close()
        raise HTTPException(status_code=400, detail=f"{username} is already part of a team.")

    conn.execute(
        "INSERT INTO team_members (team_id, user_id, joined_at) VALUES (?, ?, ?)",
        (team["id"], target["id"], datetime.datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "username": username}


@app.delete("/api/team/members/{member_id}")
def remove_member(member_id: int, user=Depends(get_current_user)):
    conn = get_db()
    team = _team_managed_by(conn, user["id"])
    if not team:
        conn.close()
        raise HTTPException(status_code=403, detail="You don't manage a team.")
    conn.execute("DELETE FROM team_members WHERE team_id = ? AND user_id = ?", (team["id"], member_id))
    conn.commit()
    conn.close()
    return {"ok": True}


def _period_bounds():
    now = datetime.datetime.utcnow()
    start_of_week = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return start_of_week.isoformat(), start_of_month.isoformat()


@app.get("/api/team/progress")
def team_progress(user=Depends(get_current_user)):
    conn = get_db()
    team = _team_managed_by(conn, user["id"])
    if not team:
        conn.close()
        raise HTTPException(status_code=403, detail="You don't manage a team.")

    start_of_week, start_of_month = _period_bounds()
    members = conn.execute("""
        SELECT u.id, u.username FROM team_members tm
        JOIN users u ON u.id = tm.user_id
        WHERE tm.team_id = ?
        ORDER BY u.username
    """, (team["id"],)).fetchall()

    result = []
    for m in members:
        total = conn.execute("SELECT COUNT(*) c FROM tasks WHERE owner_id = ?", (m["id"],)).fetchone()["c"]
        completed_total = conn.execute(
            "SELECT COUNT(*) c FROM tasks WHERE owner_id = ? AND completed = 1", (m["id"],)
        ).fetchone()["c"]
        week_count = conn.execute(
            "SELECT COUNT(*) c FROM tasks WHERE owner_id = ? AND completed = 1 AND completed_at >= ?",
            (m["id"], start_of_week),
        ).fetchone()["c"]
        month_count = conn.execute(
            "SELECT COUNT(*) c FROM tasks WHERE owner_id = ? AND completed = 1 AND completed_at >= ?",
            (m["id"], start_of_month),
        ).fetchone()["c"]
        result.append({
            "id": m["id"], "username": m["username"], "total": total,
            "completed_total": completed_total, "pending": total - completed_total,
            "completed_this_week": week_count, "completed_this_month": month_count,
        })
    conn.close()
    return result


# ---------- Task routes ----------

def _task_row_to_dict(r):
    return {
        "id": r["id"], "owner_id": r["owner_id"], "assigned_by": r["assigned_by"],
        "text": r["text"], "description": r["description"] or "", "priority": r["priority"],
        "start_datetime": r["start_datetime"], "end_datetime": r["end_datetime"],
        "completed": bool(r["completed"]), "alert": bool(r["alert"]),
        "created_at": r["created_at"], "completed_at": r["completed_at"],
    }


@app.get("/api/tasks")
def get_tasks(
    user=Depends(get_current_user),
    date: Optional[str] = None,  # "YYYY-MM-DD"; matches start_datetime's day, falling back to created_at
):
    conn = get_db()
    query = "SELECT * FROM tasks WHERE owner_id = ?"
    params = [user["id"]]

    if date:
        query += " AND date(COALESCE(start_datetime, created_at)) = ?"
        params.append(date)

    query += " ORDER BY completed ASC, id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [_task_row_to_dict(r) for r in rows]


@app.get("/api/tasks/stats")
def get_stats(user=Depends(get_current_user)):
    conn = get_db()
    rows = conn.execute("SELECT completed FROM tasks WHERE owner_id = ?", (user["id"],)).fetchall()
    conn.close()
    total = len(rows)
    completed = sum(1 for r in rows if r["completed"])
    return {"total": total, "completed": completed, "pending": total - completed}


@app.post("/api/tasks")
def add_task(task: TaskIn, user=Depends(get_current_user)):
    text = task.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Task text cannot be empty.")
    priority = task.priority if task.priority in VALID_PRIORITIES else "Medium"

    owner_id = user["id"]
    assigned_by = None

    conn = get_db()
    if task.assigned_to is not None:
        team = _team_managed_by(conn, user["id"])
        if not team:
            conn.close()
            raise HTTPException(status_code=403, detail="You don't manage a team.")
        is_member = conn.execute(
            "SELECT 1 FROM team_members WHERE team_id = ? AND user_id = ?", (team["id"], task.assigned_to)
        ).fetchone()
        if not is_member:
            conn.close()
            raise HTTPException(status_code=400, detail="That person isn't in your team.")
        owner_id = task.assigned_to
        assigned_by = user["id"]

    now_iso = datetime.datetime.utcnow().isoformat()
    cursor = conn.execute(
        """INSERT INTO tasks
           (owner_id, assigned_by, text, description, priority, start_datetime, end_datetime, completed, alert, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (owner_id, assigned_by, text, task.description or "", priority,
         task.start_datetime, task.end_datetime, int(bool(task.alert)), now_iso),
    )
    conn.commit()
    new_id = cursor.lastrowid
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return _task_row_to_dict(row)


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, update: TaskUpdateIn, user=Depends(get_current_user)):
    conn = get_db()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found.")
    if row["owner_id"] != user["id"] and row["assigned_by"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Not allowed to edit this task.")

    fields = {
        "text": update.text.strip() if update.text is not None else row["text"],
        "description": update.description if update.description is not None else row["description"],
        "priority": update.priority if update.priority in VALID_PRIORITIES else row["priority"],
        "start_datetime": update.start_datetime if update.start_datetime is not None else row["start_datetime"],
        "end_datetime": update.end_datetime if update.end_datetime is not None else row["end_datetime"],
        "alert": int(update.alert) if update.alert is not None else row["alert"],
    }
    if not fields["text"]:
        conn.close()
        raise HTTPException(status_code=400, detail="Task text cannot be empty.")

    conn.execute(
        """UPDATE tasks SET text=?, description=?, priority=?, start_datetime=?, end_datetime=?, alert=?
           WHERE id=?""",
        (fields["text"], fields["description"], fields["priority"],
         fields["start_datetime"], fields["end_datetime"], fields["alert"], task_id),
    )
    conn.commit()
    updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return _task_row_to_dict(updated)


@app.patch("/api/tasks/{task_id}/toggle")
def toggle_task(task_id: int, user=Depends(get_current_user)):
    conn = get_db()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found.")
    if row["owner_id"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="You can only update your own tasks.")
    new_state = 0 if row["completed"] else 1
    completed_at = datetime.datetime.utcnow().isoformat() if new_state else None
    conn.execute("UPDATE tasks SET completed = ?, completed_at = ? WHERE id = ?", (new_state, completed_at, task_id))
    conn.commit()
    conn.close()
    return {"id": task_id, "completed": bool(new_state)}


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: int, user=Depends(get_current_user)):
    conn = get_db()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found.")
    if row["owner_id"] != user["id"] and row["assigned_by"] != user["id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Not allowed to delete this task.")
    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.delete("/api/tasks")
def delete_all_tasks(user=Depends(get_current_user)):
    conn = get_db()
    conn.execute("DELETE FROM tasks WHERE owner_id = ?", (user["id"],))
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