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

The current project is configured in [database.py](/c:/Users/Acer/Downloads/lookfor-backend/database.py) to use:

- SQL Server
- server: `LAPTOP-2QGNEQVD\SQLEXPRESS`
- database: `LookForDB`
- Windows trusted connection

If your friend is using a different SQL Server instance or database name, they need to edit `database.py` and change:

- `server`
- `database`

They also need to make sure the `LookForDB` database exists before starting the app.

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
