# app.py
import os
import sys

from flask import Flask, request, jsonify
from flask_cors import CORS
import hashlib
import json
# === 路径注入核心代码 开始 ===
# 1. 获取上一级根目录 (GRP-MULTIAGENT)
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, parent_dir)

# 2. 获取 Screening 目录，并加入 Python 搜索路径
# 这样 AbstractScreening.py 里面直接 import ThreeAgnets 就能找到了
screening_dir = os.path.join(parent_dir, 'Screening')
sys.path.insert(0, screening_dir)


from database import get_db  # 只导入get_db，不导入init_database
# app.py 顶部引入
from Screening.AbstractScreening import search_pubmed


app = Flask(__name__)
CORS(app, supports_credentials=True, resources={r"/api/*": {"origins": "*"}})

# 注意：这里不要调用 init_database()
# 数据库初始化应该在第一次运行database.py时完成

# 测试数据库连接
@app.route('/api/test', methods=['GET', 'OPTIONS'])
def test():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        return response
    return jsonify({'success': True, 'message': 'Python后端运行正常！'})

# 登录接口
@app.route('/api/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password cannot be empty'})
    
    md5_password = hashlib.md5(password.encode()).hexdigest()
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id, email FROM users WHERE email = ? AND password = ?', (email, md5_password))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return jsonify({
                'success': True, 
                'message': 'Login successful',
                'user_id': user['id']
            })
        else:
            return jsonify({'success': False, 'message': 'Incorrect email or password'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Server error: {str(e)}'})

# 注册接口
@app.route('/api/register', methods=['POST', 'OPTIONS'])
def register():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    email = data.get('email')
    password = data.get('password')
    
    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required!'})
    
    if len(password) < 6:
        return jsonify({'success': False, 'message': 'Password must be at least 6 characters!'})
    
    md5_password = hashlib.md5(password.encode()).hexdigest()
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': False, 'message': 'Email already registered!'})
        
        cursor.execute('INSERT INTO users (email, password) VALUES (?, ?)', (email, md5_password))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Register success!'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Register failed: {str(e)}'})

# 上传文献接口
# ==========================================
# 修改：本地上传文献接口（增加去重拦截）
# ==========================================
@app.route('/api/upload-literature', methods=['POST', 'OPTIONS'])
def upload_literature():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    project_id = data.get('project_id')
    title = data.get('title')
    author = data.get('author', '')
    journal = data.get('journal', '')
    year = data.get('year')
    
    if not project_id or not title:
        return jsonify({'success': False, 'message': 'Project ID and Literature title cannot be empty!'})
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 【核心修复】：查重 - 检查当前项目中是否已经存在相同标题的文献
        cursor.execute('SELECT id FROM literatures WHERE project_id = ? AND title = ?', (project_id, title))
        if cursor.fetchone():
            conn.close()
            # 发现重复：返回 success=True 防止前端报错，但通过 inserted=False 告诉前端这是重复数据
            return jsonify({'success': True, 'inserted': False, 'message': 'Duplicate literature skipped.'})
            
        # 没有重复，正常插入
        cursor.execute(
            '''INSERT INTO literatures (project_id, title, author, journal, year, ai_decision, reasoning) 
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (project_id, title, author, journal, year, 'Pending', 'Waiting for AI screening...')
        )
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'inserted': True, 'message': 'Literature uploaded successfully!'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to save literature: {str(e)}'})

    
# 在 app.py 中新增：PubMed 自动检索并保存接口
@app.route('/api/search-pubmed', methods=['POST', 'OPTIONS'])
def api_search_pubmed():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    project_id = data.get('project_id')
    keywords = data.get('keywords')
    max_papers = data.get('max_papers', 200)
    
    if not project_id or not keywords:
        return jsonify({'success': False, 'message': 'Project ID and keywords are required'})
    
    try:
        # 1. 调用 AbstractScreening.py 中的函数去 PubMed 抓取数据
        papers = search_pubmed(keywords, max_papers)
        
        if not papers:
            return jsonify({'success': True, 'message': 'No literatures found for these keywords.', 'count': 0})
            
        # 2. 将抓取到的数据批量存入 SQLite 数据库（新增去重逻辑）
        conn = get_db()
        cursor = conn.cursor()
        inserted_count = 0
        duplicate_count = 0  # 新增：记录重复跳过的文献数量
        
        for paper in papers:
            if not paper['title']: 
                continue # 跳过没有标题的无效数据
                
            # 【核心修复】：查重 - 检查当前项目中是否已经存在相同标题的文献
            cursor.execute('SELECT id FROM literatures WHERE project_id = ? AND title = ?', (project_id, paper['title']))
            if cursor.fetchone():
                duplicate_count += 1
                continue # 发现重复，直接跳过，不插入数据库
                
            cursor.execute('''
                INSERT INTO literatures 
                (project_id, title, author, journal, year, ai_decision, reasoning) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                project_id, 
                paper['title'], 
                paper['author'], 
                paper['journal'], 
                paper['year'], 
                'Pending', 
                'Abstract:\n' + paper['abstract']
            ))
            inserted_count += 1
            
        conn.commit()
        conn.close()
        
        # 优化返回信息，告知用户去重情况
        msg = f'Successfully saved {inserted_count} new papers.'
        if duplicate_count > 0:
            msg += f' (Skipped {duplicate_count} duplicate papers).'
            
        return jsonify({
            'success': True, 
            'message': msg, 
            'count': inserted_count
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Search failed: {str(e)}'})
    

# 获取文献列表接口
@app.route('/api/get-literatures', methods=['POST', 'OPTIONS'])
def get_literatures():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    project_id = data.get('project_id')
    
    if not project_id:
        return jsonify({'success': False, 'message': 'Project ID required'})
        
    try:
        conn = get_db()
        cursor = conn.cursor()
        # 核心修改：只查询当前项目下的文献
        cursor.execute('''
            SELECT id, title, author, journal, year, ai_decision, user_decision, reasoning 
            FROM literatures 
            WHERE project_id = ? 
            ORDER BY upload_time DESC
        ''', (project_id,))
        rows = cursor.fetchall()
        literatures = [dict(row) for row in rows]
        conn.close()
        
        return jsonify({'success': True, 'data': literatures})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to get literatures: {str(e)}'})
    

@app.route('/api/update-literature-decision', methods=['POST', 'OPTIONS'])
def update_literature_decision():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    literature_id = data.get('literature_id')
    user_decision = data.get('user_decision')
    reasoning = data.get('reasoning')
    
    if not literature_id:
        return jsonify({'success': False, 'message': 'Literature ID required'})
        
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 动态构建更新语句，支持单独更新decision或reasoning
        updates = []
        params = []
        if user_decision is not None:
            updates.append("user_decision = ?")
            params.append(user_decision)
        if reasoning is not None:
            updates.append("reasoning = ?")
            params.append(reasoning)
            
        if not updates:
            return jsonify({'success': False, 'message': 'Nothing to update'})
            
        params.append(literature_id)
        query = f"UPDATE literatures SET {', '.join(updates)} WHERE id = ?"
        
        cursor.execute(query, tuple(params))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Decision updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to update decision: {str(e)}'})


# 获取用户的所有项目
@app.route('/api/get-projects', methods=['POST', 'OPTIONS'])
def get_projects():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({'success': False, 'message': 'User ID required'})
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, project_name, status, created_at 
            FROM projects 
            WHERE user_id = ? 
            ORDER BY updated_at DESC
            LIMIT 5
        ''', (user_id,))
        
        rows = cursor.fetchall()
        projects = []
        for row in rows:
            project = dict(row)
            if project['created_at']:
                project['created_at'] = str(project['created_at'])[:10]
            projects.append(project)
        
        conn.close()
        return jsonify({'success': True, 'data': projects})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to get projects: {str(e)}'})

# 创建新项目
@app.route('/api/create-project', methods=['POST', 'OPTIONS'])
def create_project():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    user_id = data.get('user_id')
    project_name = data.get('project_name')
    
    if not user_id or not project_name:
        return jsonify({'success': False, 'message': 'User ID and project name required'})
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO projects (user_id, project_name, status) 
            VALUES (?, ?, ?)
        ''', (user_id, project_name, 'PICO Setup'))
        
        project_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': 'Project created successfully',
            'project_id': project_id
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to create project: {str(e)}'})

# 保存项目数据
@app.route('/api/save-project-data', methods=['POST', 'OPTIONS'])
def save_project_data():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    project_id = data.get('project_id')
    data_type = data.get('data_type')
    data_content = data.get('data_content')
    
    if not project_id or not data_type or data_content is None:
        return jsonify({'success': False, 'message': 'Missing required fields'})
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO project_data (project_id, data_type, data_content) 
            VALUES (?, ?, ?)
        ''', (project_id, data_type, json.dumps(data_content)))
        
        cursor.execute('''
            UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?
        ''', (project_id,))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Data saved successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to save data: {str(e)}'})

# 获取项目数据
@app.route('/api/get-project-data', methods=['POST', 'OPTIONS'])
def get_project_data():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    project_id = data.get('project_id')
    data_type = data.get('data_type')
    
    if not project_id:
        return jsonify({'success': False, 'message': 'Project ID required'})
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        if data_type:
            cursor.execute('''
                SELECT data_content FROM project_data 
                WHERE project_id = ? AND data_type = ?
            ''', (project_id, data_type))
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return jsonify({'success': True, 'data': json.loads(result['data_content'])})
            else:
                return jsonify({'success': True, 'data': None})
        else:
            cursor.execute('''
                SELECT data_type, data_content FROM project_data 
                WHERE project_id = ?
            ''', (project_id,))
            
            data_dict = {}
            for row in cursor.fetchall():
                data_dict[row['data_type']] = json.loads(row['data_content'])
            
            conn.close()
            return jsonify({'success': True, 'data': data_dict})
            
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to get data: {str(e)}'})

# 更新项目状态
@app.route('/api/update-project-status', methods=['POST', 'OPTIONS'])
def update_project_status():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    project_id = data.get('project_id')
    status = data.get('status')
    
    if not project_id or not status:
        return jsonify({'success': False, 'message': 'Project ID and status required'})
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE projects SET status = ? WHERE id = ?
        ''', (status, project_id))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Status updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to update status: {str(e)}'})

# 修改项目名称
@app.route('/api/update-project-name', methods=['POST', 'OPTIONS'])
def update_project_name():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    project_id = data.get('project_id')
    project_name = data.get('project_name')
    
    if not project_id or not project_name:
        return jsonify({'success': False, 'message': 'Project ID and name required'})
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE projects SET project_name = ? WHERE id = ?
        ''', (project_name, project_id))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Project name updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to update name: {str(e)}'})


# 删除项目接口
@app.route('/api/delete-project', methods=['POST', 'OPTIONS'])
def delete_project():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    project_id = data.get('project_id')
    
    if not project_id:
        return jsonify({'success': False, 'message': 'Project ID required'})
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 因为数据库表设置了 ON DELETE CASCADE，删除项目会自动删除关联的 project_data 和 literatures
        cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Project deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to delete project: {str(e)}'})
    

if __name__ == '__main__':
    print('=' * 50)
    print('Python后端服务器启动在 http://localhost:3000')
    print('数据库文件: ai_screening.db')
    print('=' * 50)
    app.run(host='127.0.0.1', port=3000, debug=True)