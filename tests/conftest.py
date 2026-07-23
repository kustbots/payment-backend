import os

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB_NAME", "payments_app_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENV", "test")

import pytest_asyncio
from mongomock_motor import AsyncMongoMockClient

from app.db import indexes, mongo


@pytest_asyncio.fixture(autouse=True)
async def mock_mongo():
    client = AsyncMongoMockClient()
    mongo.set_client_override(client)
    await indexes.create_indexes()
    yield client
    mongo.set_client_override(None)


@pytest_asyncio.fixture
def db():
    return mongo.get_db()
