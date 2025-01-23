from datetime import datetime
from pymongo import MongoClient
from typing import Dict, List, Optional

class Database:
    def __init__(self, uri: str):
        self.client = MongoClient(uri)
        self.db = self.client.dpdrbot
        
        # Colecciones
        self.users = self.db.users
        self.conversations = self.db.conversations
        self.usage_stats = self.db.usage_stats

    def get_user(self, user_id: int) -> Optional[Dict]:
        return self.users.find_one({"user_id": user_id})

    def update_user(self, user_id: int, data: Dict):
        return self.users.update_one(
            {"user_id": user_id},
            {"$set": data},
            upsert=True
        )

    def log_conversation(self, user_id: int, message: str, response: str):
        return self.conversations.insert_one({
            "user_id": user_id,
            "message": message,
            "response": response,
            "timestamp": datetime.now()
        })

    def update_usage(self, user_id: int):
        today = datetime.now().date()
        return self.usage_stats.update_one(
            {
                "user_id": user_id,
                "date": today
            },
            {
                "$inc": {"message_count": 1}
            },
            upsert=True
        ) # Forzar reinicio para MongoDB
