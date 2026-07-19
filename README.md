# To-Do List App — Redesigned (v4)

## What changed in this version
The whole task-creation and task-detail flow now follows the layout you
shared (week-day strip, full-screen forms instead of pop-ups):

- **Home screen:** search bar, a "Daily Task" progress card, a **week
  strip** (Mon–Sun with dates, arrows to move between weeks) — tap any
  day to see that day's tasks. Task cards show a colored priority stripe
  and a circular checkmark.
- **Tapping "+"** opens a **full-screen "Create new task" page** — same
  week strip to pick the day, Name, Description, Start Time / End Time
  (clock-style pickers), Priority as outlined pills, and a "Get alert
  for this task" toggle.
- **Tapping an existing task** opens the same full-screen page, pre-filled,
  with **"Edit Task"** and **"Delete Task"** buttons at the bottom instead
  of "Create Task".
- The **Team tab** (create a team, add members by username, weekly/monthly
  progress) works exactly as before — assigning a task to a teammate now
  opens the same full-screen page too.

### One honest note about the "Get alert" toggle
This toggle is saved with the task (so you can see whether it's on or off
later), but this version does **not** actually send phone notifications —
building real push notifications needs extra infrastructure (a notification
service, and for a real phone app, background permissions) that's a
separate project on top of this. Right now it's there for visual/data
completeness, matching the design, but flipping it doesn't trigger an
alert yet. Let me know if you'd like that wired up next — it's very doable
as a follow-up.

## Run it locally
```
pip install fastapi uvicorn pyjwt
python app.py
```

## Deploying updates to Render
Upload the updated `app.py` and `index.html` to your GitHub repo
("Add file → Upload files" → Commit). Render auto-redeploys.

⚠️ Database structure changed again (new `alert` column) — same note as
before: on Render's free tier this doesn't matter since data resets on
redeploy anyway; locally, delete your old `tasks.db` before running this
version.