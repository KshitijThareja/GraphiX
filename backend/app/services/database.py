import logging
import motor.motor_asyncio
import os
from ..models.base import settings

logger = logging.getLogger(__name__)

# MongoDB client instance (initialized lazily)
_client = None
_db = None

# Check if MongoDB URI is provided in environment or config
def get_mongodb_uri():
    # First try environment variable
    mongo_uri = os.environ.get("MONGODB_URI")
    if mongo_uri:
        return mongo_uri
        
    # Try settings
    mongo_uri = getattr(settings, "MONGODB_URI", None)
    if mongo_uri:
        return mongo_uri
        
    # Fallback: use localhost with the app name as db
    return "mongodb://localhost:27017/graphix"

async def get_database():
    """
    Get a MongoDB database instance for storing callgraph data.
    
    This is a singleton factory that initializes the MongoDB connection
    on first call and returns the database instance on subsequent calls.
    
    Returns:
        Motor AsyncIOMotorDatabase instance
    """
    global _client, _db
    
    if _db is None:
        mongo_uri = get_mongodb_uri()
        db_name = os.environ.get("MONGODB_DB_NAME", "graphix")
        
        # Extract database name from URI if present in the URI itself
        if "/" in mongo_uri.split("://")[-1] and not mongo_uri.endswith("/"):
            uri_parts = mongo_uri.split("/")
            if len(uri_parts) > 3:  # protocol://host:port/dbname
                db_name = uri_parts[-1].split("?")[0]  # Remove query parameters if any
                mongo_uri = "/".join(uri_parts[:-1])  # Remove dbname from URI
        
        try:
            logger.info(f"Connecting to MongoDB for callgraph data storage")
            _client = motor.motor_asyncio.AsyncIOMotorClient(mongo_uri)
            _db = _client[db_name]
            
            # Verify connection
            await _db.command("ping")
            logger.info(f"Connected to MongoDB database: {db_name}")
            
            # Create necessary indexes for callgraph data if they don't exist
            await _db["callgraph_data"].create_index("repository_id", unique=True)
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {str(e)}")
            logger.error("Using in-memory fallback for callgraph data. This is not suitable for production!")
            
            # Create an in-memory database for development/testing
            # This is a proper async-compatible mock
            class AsyncMockCollection:
                def __init__(self, name):
                    self.name = name
                    self.data = {}
                
                async def find_one(self, query):
                    # Simple implementation that checks repository_id
                    repo_id = query.get("repository_id")
                    return self.data.get(repo_id)
                
                async def insert_one(self, document):
                    # Store by repository_id
                    class MockResult:
                        def __init__(self, id_value):
                            self.inserted_id = id_value
                    
                    doc_id = str(len(self.data) + 1)  # Simple ID generation
                    repo_id = document.get("repository_id")
                    if repo_id:
                        document["_id"] = doc_id
                        self.data[repo_id] = document
                    return MockResult(doc_id)
                
                async def update_one(self, query, update):
                    # Simple implementation that updates by repository_id
                    class MockResult:
                        def __init__(self, count):
                            self.modified_count = count
                    
                    repo_id = query.get("repository_id")
                    if repo_id in self.data:
                        # Apply updates
                        if "$set" in update:
                            for key, value in update["$set"].items():
                                self.data[repo_id][key] = value
                        return MockResult(1)
                    return MockResult(0)
                
                async def delete_one(self, query):
                    # Simple implementation that deletes by repository_id
                    class MockResult:
                        def __init__(self, count):
                            self.deleted_count = count
                    
                    repo_id = query.get("repository_id")
                    if repo_id in self.data:
                        del self.data[repo_id]
                        return MockResult(1)
                    return MockResult(0)
                
                async def create_index(self, field_name, unique=False):
                    # Mock index creation
                    return field_name
            
            class AsyncMockDatabase:
                def __init__(self):
                    self.collections = {}
                
                def __getitem__(self, collection_name):
                    if collection_name not in self.collections:
                        self.collections[collection_name] = AsyncMockCollection(collection_name)
                    return self.collections[collection_name]
                
                async def command(self, command_name):
                    # Mock ping command
                    if command_name == "ping":
                        return {"ok": 1}
                    return {"ok": 0}
            
            _db = AsyncMockDatabase()
            logger.warning("Using in-memory mock database - data will not persist!")
    
    return _db
