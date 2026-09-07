# wallet.py - Basic wallet functionality
import json
import os
from datetime import datetime

DATA_DIR = "data"
USER_FILE = os.path.join(DATA_DIR, "users.json")

def init_data_dir():
    """Initialize data directory"""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(USER_FILE):
        with open(USER_FILE, 'w') as f:
            json.dump({}, f)

def load_users():
    """Load all users"""
    try:
        with open(USER_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_users(users):
    """Save users"""
    with open(USER_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def get_balance(user_id):
    """Get user balance"""
    users = load_users()
    return users.get(str(user_id), {}).get("balance", 0)

def add_balance(user_id, amount, note=""):
    """Add balance to user"""
    users = load_users()
    user_id = str(user_id)
    
    if user_id not in users:
        users[user_id] = {
            "balance": 0,
            "games_played": 0,
            "wins": 0,
            "joined": datetime.now().isoformat()
        }
    
    users[user_id]["balance"] += amount
    save_users(users)
    return True

def deduct_balance(user_id, amount, note=""):
    """Deduct balance from user"""
    users = load_users()
    user_id = str(user_id)
    
    if user_id not in users:
        return False
    
    if users[user_id]["balance"] < amount:
        return False
    
    users[user_id]["balance"] -= amount
    save_users(users)
    return True

# Initialize on import
init_data_dir()
