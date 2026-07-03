import os
import urllib
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

driver = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")
server = os.getenv("DB_SERVER", r"LAPTOP-2QGNEQVD\SQLEXPRESS")
database = os.getenv("DB_NAME", "LookForDB")
username = os.getenv("DB_USERNAME", "").strip()
password = os.getenv("DB_PASSWORD", "").strip()
encrypt = os.getenv("DB_ENCRYPT", "no")
trust_server_certificate = os.getenv("DB_TRUST_SERVER_CERTIFICATE", "yes")

connection_parts = [
    f"DRIVER={{{driver}}}",
    f"SERVER={server}",
    f"DATABASE={database}",
    f"Encrypt={encrypt}",
    f"TrustServerCertificate={trust_server_certificate}",
]

if username and password:
    connection_parts.extend([f"UID={username}", f"PWD={password}"])
else:
    connection_parts.append("Trusted_Connection=yes")

params = urllib.parse.quote_plus(";".join(connection_parts) + ";")
SQLALCHEMY_DATABASE_URL = f"mssql+pyodbc:///?odbc_connect={params}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,  # Checks if connection is alive before using it
    pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "900")),
    pool_size=int(os.getenv("DB_POOL_SIZE", "15")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "15")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "30")),
    pool_use_lifo=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
