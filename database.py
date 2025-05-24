import sqlite3
import os
from datetime import datetime

DB_PATH = "bot_database.db"

def init_db():
    """Initialize the database and create necessary tables."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 2,
            generations_used INTEGER DEFAULT 0,
            referred_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create transactions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            stars_spent INTEGER,
            points_received INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # Create referrals table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            points_awarded INTEGER DEFAULT 1,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (referrer_id) REFERENCES users (user_id),
            FOREIGN KEY (referred_id) REFERENCES users (user_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("Database initialized successfully!")

def get_user(user_id):
    """Get user data by user_id."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, points, generations_used, referred_by FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def create_user(user_id, referred_by=None):
    """Create a new user or update existing user."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if user already exists
    existing_user = cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,)).fetchone()
    
    if not existing_user:
        cursor.execute('''
            INSERT INTO users (user_id, points, generations_used, referred_by) 
            VALUES (?, 2, 0, ?)
        ''', (user_id, referred_by))
        
        # If user was referred, give referrer bonus points
        if referred_by:
            cursor.execute('UPDATE users SET points = points + 1 WHERE user_id = ?', (referred_by,))
            cursor.execute('''
                INSERT INTO referrals (referrer_id, referred_id, points_awarded) 
                VALUES (?, ?, 1)
            ''', (referred_by, user_id))
        
        conn.commit()
        print(f"Created new user: {user_id}")
    
    conn.close()

def update_generations(user_id):
    """Update user's generation count and deduct points."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET generations_used = generations_used + 1, points = points - 1 
        WHERE user_id = ?
    ''', (user_id,))
    conn.commit()
    conn.close()

def add_points(user_id, points):
    """Add points to user's account."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET points = points + ? WHERE user_id = ?', (points, user_id))
    conn.commit()
    conn.close()

def log_transaction(user_id, stars_spent, points_received):
    """Log a transaction to the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO transactions (user_id, stars_spent, points_received) 
        VALUES (?, ?, ?)
    ''', (user_id, stars_spent, points_received))
    conn.commit()
    conn.close()

def get_user_stats(user_id):
    """Get comprehensive user statistics."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get user data
    user_data = cursor.execute('''
        SELECT user_id, points, generations_used, created_at 
        FROM users WHERE user_id = ?
    ''', (user_id,)).fetchone()
    
    # Get referral count
    referral_count = cursor.execute('''
        SELECT COUNT(*) FROM users WHERE referred_by = ?
    ''', (user_id,)).fetchone()[0]
    
    # Get total stars spent
    total_stars = cursor.execute('''
        SELECT COALESCE(SUM(stars_spent), 0) FROM transactions WHERE user_id = ?
    ''', (user_id,)).fetchone()[0]
    
    conn.close()
    
    return {
        'user_data': user_data,
        'referrals': referral_count,
        'total_stars_spent': total_stars
    }

# Utility function to backup database
def backup_database():
    """Create a backup of the database."""
    if os.path.exists(DB_PATH):
        backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        os.system(f"copy {DB_PATH} {backup_name}")
        print(f"Database backed up as {backup_name}")
    else:
        print("No database found to backup")