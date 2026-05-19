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
uvicorn main:app --reload
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
uvicorn main:app --host 0.0.0.0 --port $PORT
```

A `Procfile` is included for hosts that support it:

```Procfile
web: uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Uploads are stored under `static/uploads/`. On hosts with temporary filesystems, use persistent disk storage or move uploads to cloud storage.

## Notes

- On first run, the app may download the CLIP model from Hugging Face because `clip_test.py` loads `openai/clip-vit-base-patch32`.
- Email-based MFA and password reset only work if the `.env` Gmail credentials are valid.
- Uploaded files, local database contents, and local `.env` secrets are not included in the repo.

## Share Safely

Your friend should:

- use their own `.env`
- use their own Gmail app password
- keep `.env` out of GitHub

They should not use your personal secret values.
