import os

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.server_api import ServerApi

load_dotenv()

DB_NAME = "io-scraper"
COLLECTION_NAME = os.environ.get("LISTINGS_COLLECTION", "listings")

def get_client() -> MongoClient:
    uri = os.environ.get("MONGODB_URI")

    if not uri:
        raise RuntimeError("MONGODB_URI is not set (check .env or environment)")
    return MongoClient(uri, server_api=ServerApi("1"))


def get_collection() -> Collection:
    return get_client()[DB_NAME][COLLECTION_NAME]
