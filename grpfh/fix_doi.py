import sqlite3

def fix_database():
    conn = sqlite3.connect('ai_screening.db')
    try:
        conn.execute("ALTER TABLE literatures ADD COLUMN doi TEXT")
        print("✅ 成功新增 doi 字段！前端可以正常显示了。")
    except Exception as e:
        print("ℹ️ 字段可能已存在或发生错误:", e)
    conn.commit()
    conn.close()

if __name__ == '__main__':
    fix_database()