import sqlite3

def upgrade_database():
    conn = sqlite3.connect('ai_screening.db')
    try:
        # 1. 增加专门的 abstract 字段
        conn.execute("ALTER TABLE literatures ADD COLUMN abstract TEXT")
        print("✅ 成功新增 abstract 字段！")
        # 2. 将之前挤在 reasoning 里的历史摘要，平滑迁移到新字段中
        conn.execute("UPDATE literatures SET abstract = reasoning WHERE ai_decision = 'Pending' AND reasoning LIKE 'Abstract:%'")
        print("✅ 成功迁移历史摘要数据！")
    except Exception as e:
        print("ℹ️ 字段可能已存在或发生错误:", e)
    conn.commit()
    conn.close()

if __name__ == '__main__':
    upgrade_database()