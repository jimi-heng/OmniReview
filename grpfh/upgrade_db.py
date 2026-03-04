import sqlite3
import os

def upgrade_database():
    db_path = 'ai_screening.db'
    
    if not os.path.exists(db_path):
        print(f"❌ 找不到数据库文件 {db_path}，请确保在正确的目录下运行此脚本。")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 我们需要为 Full-Text Screening 新增的 4 个字段
    columns_to_add = [
        # 记录全文 PDF 的下载状态 (Pending, Downloaded, Failed)
        ("pdf_status", "TEXT DEFAULT 'Pending'"), 
        # 记录下载到本地的 PDF 文件路径
        ("pdf_path", "TEXT DEFAULT NULL"),        
        # 记录 AI 对全文的最终判决 (Pending, Included, Excluded)
        ("full_text_decision", "TEXT DEFAULT 'Pending'"), 
        # 记录 AI 提取的 PICO 原句证据（我们将存为 JSON 格式的字符串）
        ("pico_evidence", "TEXT DEFAULT NULL")    
    ]

    print("开始升级数据库表结构...")
    
    for col_name, col_type in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE literatures ADD COLUMN {col_name} {col_type}")
            print(f"✅ 成功新增字段: {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print(f"ℹ️ 字段已存在，跳过: {col_name}")
            else:
                print(f"❌ 添加字段 {col_name} 时发生错误: {e}")

    conn.commit()
    conn.close()
    print("🎉 数据库升级完成！你的系统现在支持全文筛查功能了。")

if __name__ == '__main__':
    upgrade_database()