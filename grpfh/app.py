# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import hashlib
import json
from database import get_db  # 只导入get_db，不导入init_database

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
@app.route('/api/upload-literature', methods=['POST', 'OPTIONS'])
def upload_literature():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
    data = request.json
    title = data.get('title')
    author = data.get('author')
    journal = data.get('journal')
    year = data.get('year')
    
    if not title:
        return jsonify({'success': False, 'message': 'Literature title cannot be empty!'})
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO literatures (title, author, journal, year) VALUES (?, ?, ?, ?)',
            (title, author, journal, year)
        )
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Literature uploaded successfully!'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to save literature: {str(e)}'})

# 获取文献列表接口
@app.route('/api/get-literatures', methods=['GET', 'OPTIONS'])
def get_literatures():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        return response
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT id, title, author, journal, year FROM literatures ORDER BY upload_time DESC')
        rows = cursor.fetchall()
        literatures = [dict(row) for row in rows]
        conn.close()
        
        return jsonify({'success': True, 'data': literatures})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to get literatures: {str(e)}'})

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

if __name__ == '__main__':
    print('=' * 50)
    print('Python后端服务器启动在 http://localhost:3000')
    print('数据库文件: ai_screening.db')
    print('=' * 50)
    app.run(host='127.0.0.1', port=3000, debug=True)