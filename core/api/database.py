import os

from motor.motor_asyncio import AsyncIOMotorClient

# MongoDB connection URL — reads from environment variable or to localhost
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

# Database and collection names
DB_NAME = "shinttools"
COLLECTION_ANALYSIS = "analysis_results"

# Create the async MongoDB client
client = AsyncIOMotorClient(MONGO_URL)  # type: ignore[var-annotated]

# Reference to the shinttools database
database = client[DB_NAME]

# Reference to the analysis_results collection
analysis_results = database[COLLECTION_ANALYSIS]


async def ping_database() -> bool:
    """
    Checks if the MongoDB connection is alive.
    Returns True if connected, False otherwise.
    """
    try:
        await client.admin.command("ping")
        return True
    except Exception:
        return False
