# app.py
import os
import sys

from flask import Flask, request, jsonify
from flask_cors import CORS
import hashlib
import json

import pandas as pd
import asyncio
import csv
from io import StringIO
from flask import make_response

# === 路径注入核心代码 开始 ===
# 1. 获取上一级根目录 (GRP-MULTIAGENT)
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, parent_dir)

# 2. 获取 Screening 目录，并加入 Python 搜索路径
# 这样 AbstractScreening.py 里面直接 import ThreeAgnets 就能找到了
screening_dir = os.path.join(parent_dir, 'Screening')
sys.path.insert(0, screening_dir)


from database import get_db  # 只导入get_db，不导入init_database
# app.py 顶部导入区域，更新这一行
from Screening.AbstractScreening import literature_search_all, run_ai_screening_sync
import Screening.ThreeAgnets
from Screening.download import ImprovedPaperDownloader
from flask import Flask, request, jsonify, make_response, send_file # 新增 send_file
# ...
from Screening.WebFullText import run_fulltext_ai_sync # 新增引入口
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
    # === 将获取参数和 INSERT 语句替换为以下内容 ===
    year = data.get('year')
    doi = data.get('doi', '') # 新增：提取 DOI
    abstract = data.get('abstract', '') # 【新增】：获取摘要

    if not project_id or not title:
        return jsonify({'success': False, 'message': 'Project ID and Literature title cannot be empty!'})
    
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute('SELECT id FROM literatures WHERE project_id = ? AND title = ?', (project_id, title))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success': True, 'inserted': False, 'message': 'Duplicate literature skipped.'})
            
        # 新增：插入 doi 字段
        cursor.execute(
            '''INSERT INTO literatures (project_id, title, author, journal, year, doi, abstract, ai_decision, reasoning) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (project_id, title, author, journal, year, doi, abstract, 'Pending', 'Waiting for AI screening...')
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
        papers = literature_search_all(keywords, max_papers)
        
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
                
            # === 将原来的 INSERT 语句替换为以下内容 ===
            # 【修改】：加入 abstract 字段并保存真实摘要，而 reasoning 只是显示等待中
            cursor.execute('''
                INSERT INTO literatures 
                (project_id, title, author, journal, year, doi, abstract, ai_decision, reasoning) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                project_id, 
                paper['title'], 
                paper['author'], 
                paper['journal'], 
                paper['year'], 
                paper.get('doi', ''), 
                paper.get('abstract', ''), # <--- 专门保存摘要
                'Pending', 
                'Waiting for AI screening...' # <--- reasoning 不再充当摘要的临时仓库
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
        # 核心修改：查询增加了 doi 和全文筛选阶段的新字段
        # 【修改】：SELECT 语句中加入 abstract
        cursor.execute('''
            SELECT id, title, author, journal, year, doi, abstract, ai_decision, user_decision, reasoning,
                   pdf_status, pdf_path, full_text_decision, pico_evidence
            FROM literatures 
            WHERE project_id = ? 
            ORDER BY id ASC
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


# ==========================================
# 触发 AI 摘要筛查接口 (完美对接 ThreeAgnets)
# ==========================================
@app.route('/api/run-ai-screening', methods=['POST', 'OPTIONS'])
def run_ai_screening_api():
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
        
        # 1. 获取该项目的 PICO 设定并解析为字典
        cursor.execute("SELECT data_content FROM project_data WHERE project_id = ? AND data_type = 'pico'", (project_id,))
        pico_row = cursor.fetchone()
        if not pico_row:
            return jsonify({'success': False, 'message': 'PICO data not found. Please setup PICO first.'})
            
        pico_data = json.loads(pico_row['data_content']) # 这是一个字典，包含 population, intervention 等
        
        # 2. 获取所有 Pending 状态的文献（上传时摘要暂存在了 reasoning 里）
        cursor.execute("SELECT id, title, abstract, reasoning FROM literatures WHERE project_id = ? AND ai_decision = 'Pending'", (project_id,))
        pending_rows = cursor.fetchall()
        
        if not pending_rows:
            return jsonify({'success': True, 'message': 'No pending literatures to screen.', 'count': 0})
            
        papers_to_screen = []
        for row in pending_rows:
            papers_to_screen.append({
                'id': row['id'],
                'title': row['title'],
                # 兼容历史数据：如果 abstract 为空，去 reasoning 里找
                'abstract': row['abstract'] if row['abstract'] else row['reasoning'] 
            })
            
        # 3. 将 PICO 字典和文献列表传给我们的同步包装函数
        screen_results = run_ai_screening_sync(pico_data, papers_to_screen)
        
        # 4. 将 AI 智能体跑出的结果批量覆盖写回数据库
        for res in screen_results:
            cursor.execute('''
                UPDATE literatures 
                SET ai_decision = ?, reasoning = ? 
                WHERE id = ?
            ''', (res['ai_decision'], res['reasoning'], res['id']))
            
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'Successfully screened {len(screen_results)} papers using Multi-Agent workflow!', 
            'count': len(screen_results)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'AI Screening failed: {str(e)}'})

# ==========================================
# 新增：动态导出 CSV 文件接口
# ==========================================
@app.route('/api/export-csv', methods=['GET', 'OPTIONS'])
def export_csv():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        return response

    # 注意：下载文件通常用 GET 请求，参数放在 URL 里
    project_id = request.args.get('project_id')
    
    if not project_id:
        return jsonify({'success': False, 'message': 'Project ID required'}), 400
        
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 获取项目名称，用于生成文件名
        cursor.execute("SELECT project_name FROM projects WHERE id = ?", (project_id,))
        project_row = cursor.fetchone()
        project_name = project_row['project_name'] if project_row else "project"
        
        # 查询该项目下的所有文献记录
        cursor.execute('''
            SELECT id, title, author, journal, year, ai_decision, user_decision, reasoning 
            FROM literatures 
            WHERE project_id = ? 
            ORDER BY id ASC
        ''', (project_id,))
        rows = cursor.fetchall()
        conn.close()

        # 在内存中创建 CSV 字符串
        si = StringIO()
        cw = csv.writer(si)
        
        # 写入表头 (综合了搜索结果和筛查结果的所有列)
        cw.writerow(['Database_ID', 'Title', 'Authors', 'Journal', 'Publication_Year', 'AI_Decision', 'User_Decision', 'Reasoning/Abstract'])
        
        # 写入数据
        for row in rows:
            cw.writerow([
                row['id'], 
                row['title'], 
                row['author'], 
                row['journal'], 
                row['year'], 
                row['ai_decision'], 
                row['user_decision'], 
                row['reasoning']
            ])

        # 将内存中的 CSV 数据转换为响应对象，强制浏览器下载
        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = f"attachment; filename=screening_results_{project_name.replace(' ', '_')}.csv"
        output.headers["Content-type"] = "text/csv; charset=utf-8-sig" # 使用 utf-8-sig 确保 Excel 打开中文不乱码
        
        # 处理跨域
        output.headers['Access-Control-Allow-Origin'] = '*'
        return output

    except Exception as e:
        return jsonify({'success': False, 'message': f'Export failed: {str(e)}'}), 500
    
# ==========================================
# 触发 全文 PDF 自动下载接口 (对接 download.py)
# ==========================================
@app.route('/api/fetch-pdfs', methods=['POST', 'OPTIONS'])
def fetch_pdfs_api():
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
        
        # 1. 筛选出所有在摘要阶段被“纳入(Included)”的文献
        # 逻辑：用户手动设为Include，或者(用户未手动排除 且 AI判定为Included)
        cursor.execute('''
            SELECT id, title, doi FROM literatures 
            WHERE project_id = ? 
            AND (user_decision = 'Include' OR (COALESCE(user_decision, 'Keep') = 'Keep' AND ai_decision = 'Included'))
            AND (pdf_status = 'Pending' OR pdf_status IS NULL)
        ''', (project_id,))
        papers = cursor.fetchall()
        
        if not papers:
            return jsonify({'success': True, 'message': 'No new included papers require PDF download.', 'count': 0})
            
        # 2. 初始化下载器和存储路径
        downloader = ImprovedPaperDownloader()
        output_dir = os.path.join(parent_dir, 'resources') # 统一存放在项目的 resources 文件夹
        os.makedirs(output_dir, exist_ok=True)
        
        success_count = 0
        
        # 3. 遍历下载并更新数据库状态
        for paper in papers:
            doi = paper['doi']
            if not doi:
                cursor.execute("UPDATE literatures SET pdf_status = 'Failed (No DOI)' WHERE id = ?", (paper['id'],))
                continue
                
            # 调用你们的强力下载器
            ok = downloader.download_paper(doi, output_dir=output_dir)
            if ok:
                filepath = os.path.join(output_dir, doi.replace("/", "_") + ".pdf")
                cursor.execute("UPDATE literatures SET pdf_status = 'Downloaded', pdf_path = ? WHERE id = ?", (filepath, paper['id']))
                success_count += 1
            else:
                cursor.execute("UPDATE literatures SET pdf_status = 'Failed (Paywalled/Error)' WHERE id = ?", (paper['id'],))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': f'Attempted {len(papers)} downloads. Successfully fetched {success_count} Open-Access PDFs.',
            'count': success_count
        })
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'Fetch PDFs failed: {str(e)}'})


@app.route('/api/upload-pdf', methods=['POST'])
def upload_pdf():

    paper_id = request.form.get('paper_id')
    file = request.files.get('file')

    if not file:
        return jsonify({'success': False, 'message': 'No file uploaded'})

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT doi FROM literatures WHERE id = ?",
        (paper_id,)
    )
    paper = cursor.fetchone()

    if not paper:
        return jsonify({'success': False, 'message': 'Paper not found'})

    doi = paper['doi']
    # 兜底：如果没有 DOI，就用文献的 ID 命名，防止 replace 报错
    if not doi:
        filename = f"manual_upload_{paper_id}.pdf"
    else:
        filename = doi.replace("/", "_") + ".pdf"

    save_dir = os.path.join(parent_dir, "resources")
    os.makedirs(save_dir, exist_ok=True)

    filepath = os.path.join(save_dir, filename)

    file.save(filepath)

    cursor.execute("""
        UPDATE literatures
        SET pdf_status = 'Downloaded',
            pdf_path = ?
        WHERE id = ?
    """, (filepath, paper_id))

    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'message': 'PDF uploaded successfully'
    })

# ==========================================
# 触发 AI 全文多模态筛选与高亮接口
# ==========================================
@app.route('/api/run-fulltext-ai', methods=['POST', 'OPTIONS'])
def run_fulltext_ai_api():
    if request.method == 'OPTIONS':
        response = jsonify({'success': True})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
        
    data = request.json
    project_id = data.get('project_id')
    if not project_id: return jsonify({'success': False, 'message': 'Project ID required'})
        
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT data_content FROM project_data WHERE project_id = ? AND data_type = 'pico'", (project_id,))
        pico_row = cursor.fetchone()
        pico_data = json.loads(pico_row['data_content']) if pico_row else {}
        
        # 只取出成功下载了 PDF 且还未被判定过的文献
        cursor.execute('''
            SELECT id, title, pdf_path FROM literatures 
            WHERE project_id = ? AND pdf_status = 'Downloaded' AND (full_text_decision = 'Pending' OR full_text_decision IS NULL)
        ''', (project_id,))
        papers = cursor.fetchall()
        
        if not papers:
            return jsonify({'success': True, 'message': 'No pending downloaded papers to screen.', 'count': 0})
            
        papers_to_screen = [{'id': p['id'], 'title': p['title'], 'pdf_path': p['pdf_path']} for p in papers]
        
        # 调用大模型多模态阅片与高亮
        results = run_fulltext_ai_sync(papers_to_screen, pico_data)
        
        # 将判决结果、抽取的 JSON 证据，以及带有颜色高亮的 PDF 路径写回数据库
        success_count = 0
        for res in results:
            if res['decision'] != 'Error':
                # 如果高亮成功，就用高亮版的 PDF 替换原来的普通 PDF 路径
                final_pdf_path = res['hl_path'] if res['hl_path'] else papers_to_screen[success_count]['pdf_path']
                cursor.execute('''
                    UPDATE literatures 
                    SET full_text_decision = ?, pico_evidence = ?, pdf_path = ?
                    WHERE id = ?
                ''', (res['decision'], res['evidence'], final_pdf_path, res['id']))
                success_count += 1
                
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'AI Processed {success_count} full-text papers.', 'count': success_count})
        
    except Exception as e:
        return jsonify({'success': False, 'message': f'AI Screening failed: {str(e)}'})

# ==========================================
# 预览高亮 PDF 文件的路由
# ==========================================
@app.route('/api/view-pdf', methods=['GET'])
def view_pdf():
    pdf_path = request.args.get('path')
    if pdf_path and os.path.exists(pdf_path):
        return send_file(pdf_path, mimetype='application/pdf')
    return "PDF not found on server", 404


if __name__ == '__main__':
    print('=' * 50)
    print('Python后端服务器启动在 http://localhost:3000')
    print('数据库文件: ai_screening.db')
    print('=' * 50)
    app.run(host='127.0.0.1', port=3000, debug=True)