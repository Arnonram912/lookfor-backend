# LookFor Backend

FastAPI backend for the LookFor lost-and-found system.

## What Your Friend Needs

- Python 3.10 or newer
- SQL Server running locally or on a reachable machine
- ODBC Driver 17 for SQL Server installed on Windows
- Their own `.env` file values

## Setup

1. Clone the repository:

```powershell
git clone https://github.com/Arnonram912/lookfor-backend.git
cd lookfor-backend
```

2. Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

3. Install dependencies:

```powershell
pip install -r requirements.txt
```

4. Create a `.env` file from the example:

```powershell
copy .env.example .env
```

5. Update `.env` with their own values:

```env
SECRET_KEY=replace-with-your-secret-key
GMAIL_SENDER_EMAIL=your-email@example.com
GMAIL_APP_PASSWORD=your-gmail-app-password
MFA_CODE_EXPIRE_MINUTES=10
LOOKFOR_LOGIN_URL=http://127.0.0.1:8000/login
LOOKFOR_BASE_URL=http://127.0.0.1:8000
ACCOUNT_EMAIL_QUEUE_SIZE=10000
```

## Database Setup

The project reads its SQL Server settings from `.env`.

Local default values are:

- SQL Server
- server: `LAPTOP-2QGNEQVD\SQLEXPRESS`
- database: `LookForDB`
- Windows trusted connection

For a different SQL Server instance, update these values in `.env`:

```env
DB_DRIVER=ODBC Driver 17 for SQL Server
DB_SERVER=LAPTOP-2QGNEQVD\SQLEXPRESS
DB_NAME=LookForDB
DB_USERNAME=
DB_PASSWORD=
DB_ENCRYPT=no
DB_TRUST_SERVER_CERTIFICATE=yes
```

If `DB_USERNAME` and `DB_PASSWORD` are empty, the app uses Windows trusted connection.

For Azure SQL or another hosted SQL Server, set:

```env
DB_SERVER=your-server.database.windows.net
DB_NAME=your-database-name
DB_USERNAME=your-database-user
DB_PASSWORD=your-database-password
DB_ENCRYPT=yes
DB_TRUST_SERVER_CERTIFICATE=no
```

Make sure the database exists before starting the app.

## Run The App

Start the server with:

```powershell
python main.py
```

Or with uvicorn:

```powershell
python -m uvicorn main:app --reload --reload-exclude=.venv/**
```

Then open:

- `http://127.0.0.1:8000`

## Hosting

Recommended setup:

- App hosting: Azure App Service, Render, Railway, or a VPS
- Database: Azure SQL Database or another reachable SQL Server
- Environment variables: copy the values from `.env.example` into the hosting provider's settings
- Start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1 --limit-concurrency 20 --backlog 64 --timeout-keep-alive 5
```

A `Procfile` is included for hosts that support it:

```Procfile
web: uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --limit-concurrency 20 --backlog 64 --timeout-keep-alive 5
```

Uploads are stored under `static/uploads/`. On hosts with temporary filesystems, use persistent disk storage or move uploads to cloud storage.

### Azure App Service B1

The Docker image uses B1-safe defaults: one Uvicorn worker, bounded request
concurrency, a small SQL connection pool, and low-memory CLIP inference. In the
App Service configuration:

- set the Health check path to `/healthz`;
- set `WEBSITES_ENABLE_APP_SERVICE_STORAGE=true` so the model cache under
  `/home/data/huggingface` survives restarts;
- configure Cloudinary for uploaded images, or set `UPLOAD_FOLDER` to a
  persistent `/home/data/...` directory;
- do not override the worker count above `1` on B1;
- use the resource settings shown in `.env.example`.

## Notes

- On first run, the app may download the CLIP model from Hugging Face because `clip_test.py` loads `openai/clip-vit-base-patch32`.
- Email-based MFA and password reset only work if the `.env` Gmail credentials are valid.
- Uploaded files, local database contents, and local `.env` secrets are not included in the repo.

## Vercel Deployment

This repo includes an experimental Vercel entrypoint:

- `app.py` exposes the FastAPI `app` from `main.py`
- `vercel.json` routes all requests to that FastAPI app

To try it:

```powershell
npm install -g vercel
vercel login
vercel
```

Then add the same environment variables from `.env.example` in the Vercel project settings.

Important: Vercel is not the recommended production host for this backend right now. This app uses SQL Server through `pyodbc`, which needs Microsoft ODBC system drivers, and it also installs large AI dependencies like `torch` and `transformers`. Vercel's Python runtime is serverless and does not run the included Dockerfile, so these dependencies may exceed Vercel's function limits or fail because the ODBC driver is unavailable.

For this project, Azure App Service with the included `Dockerfile` is a better fit because the container can install the SQL Server ODBC driver and run the backend as a normal long-running web app.

## Share Safely

Your friend should:

- use their own `.env`
- use their own Gmail app password
- keep `.env` out of GitHub

They should not use your personal secret values.
