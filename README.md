# To-Do List App — Multi-user Edition

## Run it locally
```
pip install fastapi uvicorn pyjwt
python app.py
```
Then open http://localhost:8000 — you'll see a signup/login screen. Each
person creates their own account; every account only sees its own tasks.

Data is stored in `tasks.db` (SQLite), created automatically next to
`app.py` the first time you run it.

## Let people on your phone / other devices use it (same Wi-Fi)
1. On the computer running the server, find its local IP address
   (Windows: `ipconfig`, look for "IPv4 Address", e.g. `192.168.1.14`).
2. On your phone (same Wi-Fi network), open a browser and go to:
   `http://192.168.1.14:8000`
3. Each person can sign up with their own username/password from their
   own phone, as long as they're on the same network and your computer
   stays on and running the server.

This works for testing with people nearby, but it stops working the
moment your computer is off, asleep, or off that Wi-Fi network.

## Making it available to anyone, anywhere (real deployment)
For a link that works for anyone on the internet, all the time, you need
to host the backend on a server that's always on — your own laptop isn't
enough for that. Common free/low-cost options:
- **Render** (render.com) — free tier, deploys a FastAPI app directly
  from a GitHub repo.
- **Railway** (railway.app) — similar, simple GitHub-based deploys.
- **PythonAnywhere** — good for small Python apps.

General steps for any of these:
1. Push this project (`app.py`, `index.html`) to a GitHub repository.
2. Connect that repo to Render/Railway and point it at `app.py`.
3. Set the `SECRET_KEY` in `app.py` as an environment variable instead
   of a hardcoded string (important for real security).
4. The host gives you a public URL (e.g. `https://your-todo.onrender.com`)
   — share that link with anyone, and it'll work on any phone or computer,
   any time.

Note: SQLite works fine for a small number of users, but if this ever
needs to support many people at once, moving to a hosted database like
Supabase or Postgres is a natural next step — the backend code would
only need the `get_db()` function changed, everything else stays the same.