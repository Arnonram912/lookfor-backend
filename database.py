# database.py
import urllib
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Your exact server name from SSMS
server = r'LAPTOP-2QGNEQVD\SQLEXPRESS' 
database = 'LookForDB'

# Safely encode the connection parameters
params = urllib.parse.quote_plus(
    f"DRIVER={{ODBC Driver 17 for SQL Server}};"
    f"SERVER={server};"
    f"DATABASE={database};"
    f"trusted_connection=yes;"
)

SQLALCHEMY_DATABASE_URL = f"mssql+pyodbc:///?odbc_connect={params}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,  # Checks if connection is alive before using it
    pool_recycle=3600    # Refreshes the connection every hour
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()