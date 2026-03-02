# database.py
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = 'ai_screening.db'

def init_database():
    """初始化数据库，创建所有表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 创建users表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建literatures表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS literatures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT DEFAULT '',
            journal TEXT DEFAULT '',
            year INTEGER,
            upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建projects表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            project_name TEXT NOT NULL,
            status TEXT DEFAULT 'PICO Setup',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')
    
    # 创建project_data表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS project_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            data_type TEXT NOT NULL,
            data_content TEXT,  -- SQLite没有JSON类型，用TEXT存储JSON字符串
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
            UNIQUE(project_id, data_type)
        )
    ''')
    
    # 创建触发器自动更新updated_at
    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS update_projects_timestamp 
        AFTER UPDATE ON projects
        BEGIN
            UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END;
    ''')
    
    cursor.execute('''
        CREATE TRIGGER IF NOT EXISTS update_project_data_timestamp 
        AFTER UPDATE ON project_data
        BEGIN
            UPDATE project_data SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END;
    ''')
    
    conn.commit()
    conn.close()
    print(f"数据库初始化完成：{os.path.abspath(DB_PATH)}")

def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 让返回的结果可以通过列名访问
    return conn

# 初始化数据库
if __name__ == '__main__':
    init_database()