import sqlite3

def init_db():
    conn=sqlite3.connect("../database/db.sqlite3")
    cur=conn.cursor()
    
    cur.execute("""
                CREATE TABLE IF NOT EXISTS apps(
                    id TEXT,
                    repo TEXT,
                    url TEXT,
                    status TEXT,
                    instance_id TEXT
                )
                """)
    conn.commit()
    conn.close()

def save_app(app_id, repo, url, instance_id):
    conn=sqlite3.connect("../database/db.sqlite3")
    cur=conn.cursor()
    
    cur.execute(
                "INSERT INTO apps VALUES (?, ?, ?, ?, ?)",
                (app_id, repo, url, "RUNNING", instance_id)
    )
    conn.commit()
    conn.close()

def get_apps():
    conn=sqlite3.connect("../database/db.sqlite3")
    cur=conn.cursor()
    
    cur.execute("SELECT * FROM apps")
    data = cur.fetchall()
    conn.close()
    return data

def update_status(instance_id, status):
    conn = sqlite3.connect("../database/db.sqlite3")
    cur = conn.cursor()

    cur.execute(
        "UPDATE apps SET status=? WHERE instance_id=?",
        (status, instance_id)
    )

    conn.commit()
    conn.close()