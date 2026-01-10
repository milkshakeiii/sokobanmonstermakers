#!/usr/bin/env python3
"""Quick migration script to add missing columns."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "monster_workshop.db")

def run_migrations():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check existing columns
    cursor.execute("PRAGMA table_info(monsters)")
    columns = [col[1] for col in cursor.fetchall()]
    print(f"Existing columns: {columns}")

    # Add last_upkeep_paid if missing
    if "last_upkeep_paid" not in columns:
        try:
            cursor.execute("ALTER TABLE monsters ADD COLUMN last_upkeep_paid TIMESTAMP")
            conn.commit()
            print("Added last_upkeep_paid column")
        except Exception as e:
            print(f"Error adding last_upkeep_paid: {e}")
    else:
        print("last_upkeep_paid column already exists")

    # Add skill_last_used if missing
    if "skill_last_used" not in columns:
        try:
            cursor.execute("ALTER TABLE monsters ADD COLUMN skill_last_used TEXT DEFAULT '{}'")
            conn.commit()
            print("Added skill_last_used column")
        except Exception as e:
            print(f"Error adding skill_last_used: {e}")
    else:
        print("skill_last_used column already exists")

    conn.close()
    print("Migration complete!")

if __name__ == "__main__":
    run_migrations()
