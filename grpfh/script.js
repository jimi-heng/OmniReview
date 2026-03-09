// 全局变量：存储当前编辑的行数据（用于推理编辑）
let currentEditRow = null;
// 在文件开头添加全局变量
let currentUser = null; // 存储当前登录用户信息
let currentProject = null; // 存储当前正在进行的项目


// 1. 更新顶部进度导航激活状态
// 1. 更新顶部进度导航激活状态
function updateProgressStep(activeStepId) {
    // 【核心修改】：加入了 'step-fulltext'
    const steps = ['step-login', 'step-home', 'step-pico', 'step-import', 'step-abstract', 'step-fulltext', 'step-data'];
    steps.forEach(id => {
        const step = document.getElementById(id);
        if(step) {
            step.classList.remove('active');
            step.classList.add('disabled');
        }
    });
    const activeEl = document.getElementById(activeStepId);
    if(activeEl) {
        activeEl.classList.add('active');
        activeEl.classList.remove('disabled');
    }
}

// 2. 通用页面切换函数（所有按钮跳转核心）
// 2. 通用页面切换函数（所有按钮跳转核心）
function showPage(pageId) {
    // 【核心修改】：加入了 'full-text-screen-page'
    const allPages = ['login-page', 'register-page', 'home-page', 'pico-page', 'import-search-page', 'abstract-screen-page', 'full-text-screen-page', 'data-extraction-page'];
    allPages.forEach(id => {
        const el = document.getElementById(id);
        if(el) el.style.display = 'none';
    });
    
    const targetEl = document.getElementById(pageId);
    if(targetEl) targetEl.style.display = 'block';
    
    switch (pageId) {
        case 'login-page':
        case 'register-page': updateProgressStep('step-login'); break;
        case 'home-page':
            updateProgressStep('step-home');
            if (currentUser) loadUserProjects();
            break;
        case 'pico-page': updateProgressStep('step-pico'); break;
        case 'import-search-page':
            updateProgressStep('step-import');
            setTimeout(loadLiteratureList, 100);
            break;
        case 'abstract-screen-page': updateProgressStep('step-abstract'); break;
        // 【新增】：当跳转到 Full-Text 时更新导航栏
        case 'full-text-screen-page': 
            updateProgressStep('step-fulltext'); 
            setTimeout(loadFullTextScreening, 100); // 留好坑位，后续接入后端用
            break;
        case 'data-extraction-page': updateProgressStep('step-data'); break;
    }
}


document.getElementById('login-btn').addEventListener('click', async () => {
  // 1. 获取用户输入
  const inputEmail = document.getElementById('email').value.trim();
  const inputPwd = document.getElementById('password').value.trim();
  const errorTip = document.getElementById('login-error');

  // 2. 空值校验
  if (!inputEmail || !inputPwd) {
    errorTip.textContent = 'Email and password cannot be empty';
    errorTip.style.display = 'block';
    return;
  }

  try {
    // 3. 调用后端登录接口
    const response = await fetch('http://localhost:3000/api/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ email: inputEmail, password: inputPwd })
    });

    const result = await response.json();
    
    // 4. 根据后端结果处理
    if (result.success) {
      errorTip.style.display = 'none';
      
      // 保存用户信息（现在后端会返回user_id）
      currentUser = {
        id: result.user_id,
        email: inputEmail
      };
      
      // 保存到sessionStorage以便页面刷新后保留
      sessionStorage.setItem('currentUser', JSON.stringify(currentUser));
      
      showPage('home-page');
      loadUserProjects(); // 加载用户的项目
    } else {
      errorTip.textContent = result.message;
      errorTip.style.display = 'block';
      document.getElementById('password').value = ''; // 清空密码
    }
  } catch (error) {
    // 网络/服务器错误
    errorTip.textContent = 'Failed to connect to the server! Please check if the backend is running.';
    errorTip.style.display = 'block';
  }
});


// 退出登录
document.getElementById('logout-btn').addEventListener('click', () => {
  // 清空表单
  document.getElementById('email').value = '';
  document.getElementById('password').value = '';
  document.getElementById('login-error').style.display = 'none';
  
  // 清空用户信息
  currentUser = null;
  currentProject = null;
  sessionStorage.removeItem('currentUser');
  sessionStorage.removeItem('currentProject');
  
  showPage('login-page');
});


document.addEventListener('DOMContentLoaded', () => {
  // 添加导航监听器
  addNavigationListeners();
  
  // 检查是否有保存的用户信息
  const savedUser = sessionStorage.getItem('currentUser');
  if (savedUser) {
    currentUser = JSON.parse(savedUser);
    // 如果是在登录状态，直接显示首页并加载项目
    showPage('home-page');
    loadUserProjects();
  }
});


// 4. 注册相关逻辑
// 跳转到注册页
document.getElementById('to-register').addEventListener('click', (e) => {
    e.preventDefault(); // 阻止链接默认跳转
    showPage('register-page'); // 显示注册页
    updateProgressStep('step-login'); // 进度条仍显示login
});

// 跳回登录页
document.getElementById('to-login').addEventListener('click', (e) => {
    e.preventDefault();
    showPage('login-page');
    updateProgressStep('step-login');
});

// 注册按钮点击事件
document.getElementById('register-btn').addEventListener('click', async () => {
    // 1. 获取注册输入
    const regEmail = document.getElementById('reg-email').value.trim();
    const regPwd = document.getElementById('reg-password').value.trim();
    const regConfirmPwd = document.getElementById('reg-confirm-pwd').value.trim();
    const regErrorTip = document.getElementById('register-error');

    // 2. 前端校验
    if (!regEmail || !regPwd || !regConfirmPwd) {
        regErrorTip.textContent = 'All fields are required!';
        regErrorTip.style.display = 'block';
        return;
    }
    if (regPwd !== regConfirmPwd) {
        regErrorTip.textContent = 'Passwords do not match!';
        regErrorTip.style.display = 'block';
        return;
    }
    if (regPwd.length < 6) {
        regErrorTip.textContent = 'Password must be at least 6 characters!';
        regErrorTip.style.display = 'block';
        return;
    }

    try {
        // 3. 调用后端注册接口
        const response = await fetch('http://localhost:3000/api/register', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ email: regEmail, password: regPwd })
        });

        const result = await response.json();
        if (result.success) {
            // 注册成功，提示并跳登录页
            regErrorTip.style.display = 'none';
            alert('Register success! Please log in.');
            // 清空注册输入框
            document.getElementById('reg-email').value = '';
            document.getElementById('reg-password').value = '';
            document.getElementById('reg-confirm-pwd').value = '';
            // 跳登录页
            showPage('login-page');
        } else {
            // 注册失败，显示错误
            regErrorTip.textContent = result.message;
            regErrorTip.style.display = 'block';
        }
    } catch (error) {
        regErrorTip.textContent = 'Server connection failed!';
        regErrorTip.style.display = 'block';
    }
});




// 4. 文献导入页标签切换（还原Figure12标签功能）
function switchImportTab(type) {
    const tabs = document.querySelectorAll('.tabs')[0].querySelectorAll('.tab');
    tabs[0].classList.toggle('active', type === 'import');
    tabs[1].classList.toggle('active', type === 'search');
    document.getElementById('import-section').style.display = type === 'import' ? 'block' : 'none';
    document.getElementById('search-section').style.display = type === 'search' ? 'block' : 'none';
}

// 5. 数据提取页标签切换
function switchDataTab(type) {
    const tabs = document.querySelectorAll('.tabs')[1].querySelectorAll('.tab');
    tabs.forEach(tab => tab.classList.remove('active'));
    // 隐藏所有内容区
    ['outcome-section', 'characteristics-section', 'pico-evidence-section'].forEach(id => {
        document.getElementById(id).style.display = 'none';
    });
    // 激活对应标签和内容
    if (type === 'outcome') {
        tabs[0].classList.add('active');
        document.getElementById('outcome-section').style.display = 'block';
    } else if (type === 'characteristics') {
        tabs[1].classList.add('active');
        document.getElementById('characteristics-section').style.display = 'block';
    } else if (type === 'pico') {
        tabs[2].classList.add('active');
        document.getElementById('pico-evidence-section').style.display = 'block';
    }
}

// 6. 核心功能：AI推理查看/编辑（实现Figure13的edit reasoning需求）
const reasonModal = document.getElementById('reasonModal');
const reasonText = document.getElementById('reasonText');
const closeModal = document.getElementById('closeModal');
const cancelEdit = document.getElementById('cancelEdit');
const saveReason = document.getElementById('saveReason');

// 点击View/Edit按钮打开弹窗，加载当前行的推理内容
document.querySelectorAll('.edit-reason-btn').forEach(btn => {
    btn.addEventListener('click', function() {
        currentEditRow = this.closest('tr'); // 获取当前点击的行
        const originalReason = currentEditRow.getAttribute('data-reason'); // 获取原始推理内容
        reasonText.value = originalReason; // 加载到编辑框
        reasonModal.style.display = 'flex'; // 打开弹窗
    });
});

// 关闭弹窗（取消/叉号）
function closeReasonModal() {
    reasonModal.style.display = 'none';
    currentEditRow = null; // 清空当前编辑行
}
closeModal.addEventListener('click', closeReasonModal);
cancelEdit.addEventListener('click', closeReasonModal);

// 保存编辑后的推理内容
saveReason.addEventListener('click', function() {
    if (!currentEditRow) return;
    const newReason = reasonText.value.trim();
    if (newReason) {
        // 更新行的data-reason属性和表格显示内容
        currentEditRow.setAttribute('data-reason', newReason);
        // 表格内显示截取的短内容（完整内容在弹窗）
        const shortReason = newReason.length > 80 ? newReason.substring(0, 80) + '...' : newReason;
        currentEditRow.cells[3].textContent = shortReason;
        closeReasonModal(); // 保存后关闭弹窗
        alert('Reasoning updated successfully!'); // 提示保存成功
    } else {
        alert('Reasoning content cannot be empty!');
    }
});

// 点击遮罩层关闭弹窗（优化体验）
reasonModal.addEventListener('click', function(e) {
    if (e.target === reasonModal) closeReasonModal();
});





// ========== 文献上传+渲染逻辑（完整新增） ==========
// 1. 解析.bib文件的核心函数
function parseBibFile(text) {
  const literatures = [];
  // 分割多个文献条目
  const entries = text.split('@').filter(entry => entry.trim());

  entries.forEach(entry => {
    // 提取核心字段（正则匹配bib格式）
    const titleMatch = entry.match(/title\s*=\s*\{([^}]+)\}/i);
    const authorMatch = entry.match(/author\s*=\s*\{([^}]+)\}/i);
    const journalMatch = entry.match(/journal\s*=\s*\{([^}]+)\}/i);
    const yearMatch = entry.match(/year\s*=\s*\{([0-9]+)\}/i);
    const doiMatch = entry.match(/doi\s*=\s*\{([^}]+)\}/i); // 新增：匹配 DOI
    const abstractMatch = entry.match(/abstract\s*=\s*\{([^}]+)\}/i); // 【新增】匹配摘要

    if (titleMatch) {
      literatures.push({
        title: titleMatch[1].trim().replace(/[\{\}]/g, ''),
        author: authorMatch ? authorMatch[1].trim().replace(/[\{\}]/g, '') : '',
        journal: journalMatch ? journalMatch[1].trim().replace(/[\{\}]/g, '') : '',
        year: yearMatch ? parseInt(yearMatch[1]) : null,
        doi: doiMatch ? doiMatch[1].trim().replace(/[\{\}]/g, '') : '', // 注意这里末尾加了逗号！
        abstract: abstractMatch ? abstractMatch[1].trim().replace(/[\{\}]/g, '') : '' // 【新增】保存摘要
      });
    }
  });
  return literatures;
}

// 2. 多文件上传处理逻辑
document.addEventListener('DOMContentLoaded', () => {
  // 绑定上传按钮点击事件
  const uploadBtn = document.getElementById('upload-btn');
  if (uploadBtn) {
    uploadBtn.addEventListener('click', async () => {
      const fileInput = document.getElementById('file-upload');
      const uploadError = document.getElementById('upload-error');
      const files = fileInput.files;

      // 清空之前的错误提示
      uploadError.style.display = 'none';
      uploadError.textContent = '';

      // 校验是否选择文件
      if (files.length === 0) {
        uploadError.textContent = 'Please select at least one citation file!';
        uploadError.style.display = 'block';
        return;
      }

      let totalSuccess = 0;    // 成功上传的新文献数
      let totalDuplicates = 0; // 记录被拦截的重复文献数
      let errorFiles = [];     // 处理失败的文件

      // 批量处理每个文件
      for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const fileExt = file.name.split('.').pop().toLowerCase();

        // 校验文件格式
        if (!['bib', 'ris', 'txt'].includes(fileExt)) {
          errorFiles.push(`${file.name} (unsupported format)`);
          continue;
        }

        // 读取文件内容
        const fileContent = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = (e) => resolve(e.target.result);
          reader.onerror = (e) => reject(e);
          reader.readAsText(file);
        });

        // 解析文件（仅完善bib解析，ris/txt暂提示）
        let literatures = [];
        if (fileExt === 'bib') {
          literatures = parseBibFile(fileContent);
        } else {
          errorFiles.push(`${file.name} (.ris/.txt not fully supported yet)`);
          continue;
        }

        if (literatures.length === 0) {
          errorFiles.push(`${file.name} (no valid literature found)`);
          continue;
        }

        // 批量上传到后端
        try {
          if (!currentProject || !currentProject.id) {
             alert('Error: No active project found. Please select or create a project first.');
             return;
          }
          
          for (let lit of literatures) {
            lit.project_id = currentProject.id;
            
            const response = await fetch('http://localhost:3000/api/upload-literature', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(lit)
            });
            const result = await response.json();
            
            // 根据后端的 inserted 标志判断是成功插入还是重复跳过
            if (result.success) {
                if (result.inserted) {
                    totalSuccess++;
                } else {
                    totalDuplicates++; // 命中去重逻辑
                }
            }
          }
        } catch (err) {
          errorFiles.push(`${file.name} (upload failed)`);
        }
      }

      // 优化处理完成后的提示框信息
      let message = `Upload Task Completed!\n`;
      message += `- Successfully saved: ${totalSuccess} new papers.\n`;
      if (totalDuplicates > 0) {
          message += `- Skipped duplicates: ${totalDuplicates} papers.\n`;
      }
      if (errorFiles.length > 0) {
          message += `- Failed files: ${errorFiles.join(', ')}`;
      }
      alert(message);

      // 清空文件选择框 + 刷新列表
      fileInput.value = '';
      loadLiteratureList();

      // 显示错误提示（如有）
      if (errorFiles.length > 0) {
        uploadError.textContent = `Failed to process ${errorFiles.length} files!`;
        uploadError.style.display = 'block';
      }
    });
  }

  // 3. 加载文献列表并渲染到表格
  // 3. 加载文献列表并渲染到表格 (核心修改：只请求当前项目的文献)
// 3. 加载文献列表并渲染到表格 (核心修改：只请求当前项目的文献)
  window.loadLiteratureList = async function() {
    const tableBody = document.getElementById('literature-table-body');
    if (!tableBody) return;
    
    if (!currentProject || !currentProject.id) return;

    try {
      const response = await fetch('http://localhost:3000/api/get-literatures', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: currentProject.id })
      });
      const result = await response.json();

      if (result.success && result.data.length > 0) {
        // 有数据，渲染表格
        tableBody.innerHTML = '';
        
        // 【核心修复】：加上 index 参数，用于生成独立的显示序号
        result.data.forEach((lit, index) => {
          const displayId = index + 1; // 生成 1, 2, 3... 的独立序号
          
          const tr = document.createElement('tr');
          // 注意：我们在标签上保存真实的数据库ID (data-id)，但页面上显示的是 displayId
          tr.setAttribute('data-id', lit.id);
          tr.innerHTML = `
            <td style="border: 1px solid #ddd; padding: 8px; text-align: center;">${displayId}</td>
            <td style="border: 1px solid #ddd; padding: 8px;">${lit.title || '-'}</td>
            <td style="border: 1px solid #ddd; padding: 8px;">${lit.author || '-'}</td>
            <td style="border: 1px solid #ddd; padding: 8px;">${lit.journal || '-'}</td>
            <td style="border: 1px solid #ddd; padding: 8px;">${lit.year || '-'}</td>
          `;
          tableBody.appendChild(tr);
        });
      } else {
        tableBody.innerHTML = `
          <tr>
            <td colspan="5" class="empty-data">No literature data yet - Upload or search to view results</td>
          </tr>
        `;
      }
    } catch (error) {
      tableBody.innerHTML = `
        <tr>
          <td colspan="5" class="empty-data" style="color: red;">
            Failed to load literatures! Please check backend server.
          </td>
        </tr>
      `;
      console.error('加载文献列表失败：', error);
    }
  };

  // 4. 扩展showPage函数，进入各个页面时加载对应数据
  const originalShowPage = window.showPage;
  window.showPage = function(pageId) {
    originalShowPage(pageId);
    
    // 进入文献导入页时加载列表
    if (pageId === 'import-search-page') {
      setTimeout(loadLiteratureList, 100); 
    }
    // 进入摘要筛选页面时加载筛查列表
    else if (pageId === 'abstract-screen-page') {
      setTimeout(loadAbstractScreening, 100);
    }
  };

  // 5. 标签页切换函数（如果原有代码没有，补充）
  window.switchImportTab = function(tabName) {
    // 隐藏所有标签内容
    document.getElementById('import-section').style.display = 'none';
    document.getElementById('search-section').style.display = 'none';
    // 移除所有标签的active类
    document.querySelectorAll('.tabs .tab').forEach(tab => tab.classList.remove('active'));
    // 显示选中的标签
    document.getElementById(`${tabName}-section`).style.display = 'block';
    // 激活选中的标签
    event.target.classList.add('active');
  };
});

// ====== 新增：处理 PubMed 在线检索逻辑 ======
// ====== 处理 PubMed 在线检索逻辑 ======
document.addEventListener('DOMContentLoaded', () => {
    const searchPubmedBtn = document.getElementById('search-pubmed-btn');
    if (searchPubmedBtn) {
        searchPubmedBtn.addEventListener('click', async () => {
            const keywords = document.getElementById('search-keywords').value.trim();
            const maxPapers = document.getElementById('max-papers').value;
            
            if (!keywords) {
                alert('Please enter search keywords!');
                return;
            }
            if (!currentProject || !currentProject.id) {
                alert('Error: No active project found.');
                return;
            }

            // 1. 按钮变为 Loading 状态
            const originalText = searchPubmedBtn.textContent;
            searchPubmedBtn.textContent = 'Searching PubMed... Please wait...';
            searchPubmedBtn.disabled = true;

            // 2. 【核心修复】：立即清空下方表格，显示正在加载的状态
            const tableBody = document.getElementById('literature-table-body');
            if (tableBody) {
                tableBody.innerHTML = `
                    <tr>
                        <td colspan="6" class="empty-data" style="color: #2c6ecb; font-weight: bold;">
                            Searching PubMed database... This might take a few seconds...
                        </td>
                    </tr>
                `;
            }

            try {
                // 3. 发送请求给后端
                const response = await fetch('http://localhost:3000/api/search-pubmed', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        project_id: currentProject.id,
                        keywords: keywords,
                        max_papers: parseInt(maxPapers)
                    })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    alert(result.message);
                    // 4. 搜索成功后，重新从数据库拉取该项目的最新文献列表并覆盖表格
                    loadLiteratureList(); 
                } else {
                    alert('Search Error: ' + result.message);
                    // 如果失败了，恢复空状态或者显示原来的文献
                    loadLiteratureList();
                }
            } catch (error) {
                console.error('Search request failed:', error);
                alert('Network error. Is the Python backend running?');
                loadLiteratureList();
            } finally {
                // 5. 恢复按钮状态
                searchPubmedBtn.textContent = originalText;
                searchPubmedBtn.disabled = false;
            }
        });
    }
});


// 加载用户的项目列表
async function loadUserProjects() {
    if (!currentUser) return;
    
    try {
        const response = await fetch('http://localhost:3000/api/get-projects', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ user_id: currentUser.id })
        });
        
        const result = await response.json();
        
        if (result.success) {
            renderProjects(result.data);
        }
    } catch (error) {
        console.error('Failed to load projects:', error);
    }
}

// 渲染项目列表到页面
// 渲染项目列表到页面
function renderProjects(projects) {
    const homePage = document.getElementById('home-page');
    const projectsContainer = homePage.querySelector('.card');
    
    if (!projectsContainer) return;
    
    if (projects.length === 0) {
        // 没有项目时显示空状态
        projectsContainer.innerHTML = `
            <h3>Recent Projects</h3>
            <div class="no-projects">
                No projects yet. Click "Create New Project" to start.
            </div>
            <div style="margin-top: 20px;">
                <button class="btn btn-primary" id="create-project-btn">Create New Project</button>
                <button class="btn btn-secondary" style="margin-left: 10px;">Browse All Projects</button>
            </div>
        `;
    } else {
        // 有项目时渲染列表
        let projectsHtml = '<h3>Recent Projects</h3>';
        
        projects.forEach(project => {
            projectsHtml += `
                <div class="project-item" data-project-id="${project.id}">
                    <div>
                        <p>
                            <strong class="project-name">${project.project_name}</strong>
                            <button class="btn btn-sm btn-secondary" style="margin-left: 10px;" onclick="editProjectName(${project.id}, this)">✎</button>
                        </p>
                        <p><small>Status: ${project.status} | Created: ${project.created_at}</small></p>
                    </div>
                    <div>
                        <button class="btn btn-secondary btn-sm" onclick="continueProject(${project.id})">Continue</button>
                        <button class="btn btn-sm" style="background-color: #dc3545; color: white; margin-left: 5px; border: none;" onclick="deleteProject(${project.id}, '${project.project_name}')">Delete</button>
                    </div>
                </div>
            `;
        });
        
        projectsHtml += `
            <div style="margin-top: 20px;">
                <button class="btn btn-primary" id="create-project-btn">Create New Project</button>
                <button class="btn btn-secondary" style="margin-left: 10px;">Browse All Projects</button>
            </div>
        `;
        
        projectsContainer.innerHTML = projectsHtml;
    }
    
    // 重新绑定创建项目按钮事件
    const createBtn = document.getElementById('create-project-btn');
    if (createBtn) {
        createBtn.replaceWith(createBtn.cloneNode(true));
        const newCreateBtn = document.getElementById('create-project-btn');
        newCreateBtn.addEventListener('click', () => {
            const projectName = prompt('Enter project name:');
            if (projectName && projectName.trim()) {
                createNewProject(projectName.trim());
            }
        });
    }
}

// 创建新项目
async function createNewProject(projectName) {
    if (!currentUser) return;
    
    try {
        const response = await fetch('http://localhost:3000/api/create-project', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: currentUser.id,
                project_name: projectName
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            currentProject = {
                id: result.project_id,
                name: projectName,
                status: 'PICO Setup'
            };
            sessionStorage.setItem('currentProject', JSON.stringify(currentProject));
            
            // 【核心修复】：新建项目时，先清空上一个项目遗留的输入！
            clearAllInputs();
            
            showPage('pico-page');
        } else {
            alert('Failed to create project: ' + result.message);
        }
    } catch (error) {
        alert('Failed to create project');
    }
}

// 继续项目
async function continueProject(projectId) {
    try {
        // 【核心修复】：加载项目前，先清空面板，防止上一个项目的数据串号！
        clearAllInputs();

        const response = await fetch('http://localhost:3000/api/get-project-data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: projectId })
        });
        
        const result = await response.json();
        
        if (result.success) {
            currentProject = { id: projectId };
            
            // 加载 PICO 数据
            if (result.data.pico) {
                document.getElementById('population').value = result.data.pico.population || '';
                document.getElementById('intervention').value = result.data.pico.intervention || '';
                document.getElementById('comparison').value = result.data.pico.comparison || '';
                document.getElementById('study_design').value = result.data.pico.study_design || '';
            }
            
            // 加载 Protocol 数据
            if (result.data.protocol) {
                document.getElementById('research-objective').value = result.data.protocol.objective || '';
                document.getElementById('inclusion-criteria').value = result.data.protocol.inclusion || '';
                document.getElementById('exclusion-criteria').value = result.data.protocol.exclusion || '';
            }

            // 【核心修复】：加载 Search 阶段的数据（隔离各项目的搜索参数）
            if (result.data.search_params) {
                document.getElementById('search-keywords').value = result.data.search_params.keywords || '';
                document.getElementById('max-papers').value = result.data.search_params.maxPapers || 200;
            }
            
            const projectResponse = await fetch('http://localhost:3000/api/get-projects', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: currentUser.id })
            });
            
            const projectResult = await projectResponse.json();
            const project = projectResult.data.find(p => p.id === projectId);
            
            if (project) {
                currentProject.name = project.project_name;
                sessionStorage.setItem('currentProject', JSON.stringify(currentProject));
                
                switch(project.status) {
                    case 'PICO Setup': showPage('pico-page'); break;
                    case 'Import/Search': showPage('import-search-page'); break;
                    case 'Abstract Screening': showPage('abstract-screen-page'); break;
                    case 'Full-Text Screening': showPage('full-text-screen-page'); break; // 新增：全文筛选的跳转
                    case 'Data Extraction': showPage('data-extraction-page'); break;
                    default: showPage('pico-page');
                }
            }
        }
    } catch (error) {
        alert('Failed to load project data');
    }
}

// 编辑项目名称
async function editProjectName(projectId, buttonElement) {
    const projectItem = buttonElement.closest('.project-item');
    const nameElement = projectItem.querySelector('.project-name');
    const oldName = nameElement.textContent;
    
    const newName = prompt('Edit project name:', oldName);
    if (newName && newName.trim() && newName.trim() !== oldName) {
        try {
            const response = await fetch('http://localhost:3000/api/update-project-name', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    project_id: projectId,
                    project_name: newName.trim()
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                nameElement.textContent = newName.trim();
            } else {
                alert('Failed to update project name');
            }
        } catch (error) {
            alert('Failed to update project name');
        }
    }
}

// 新增：删除项目逻辑
async function deleteProject(projectId, projectName) {
    // 增加二次确认，防止用户误删
    if (!confirm(`Are you sure you want to permanently delete the project "${projectName}"?\nThis will erase all PICO data, imported literatures, and AI reasoning. This action cannot be undone.`)) {
        return; 
    }

    try {
        const response = await fetch('http://localhost:3000/api/delete-project', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: projectId })
        });
        
        const result = await response.json();
        
        if (result.success) {
            // 如果用户删除的正好是他们当前正在操作的项目，清空当前项目缓存防干扰
            if (currentProject && currentProject.id === projectId) {
                currentProject = null;
                sessionStorage.removeItem('currentProject');
                clearAllInputs();
            }
            // 重新拉取并渲染最新的项目列表
            loadUserProjects();
        } else {
            alert('Failed to delete project: ' + result.message);
        }
    } catch (error) {
        console.error('Failed to delete project:', error);
        alert('Network error occurred while trying to delete the project.');
    }
}

// 保存PICO数据
async function savePicoData() {
    if (!currentProject || !currentProject.id) return;
    
    const picoData = {
        population: document.getElementById('population').value,
        intervention: document.getElementById('intervention').value,
        comparison: document.getElementById('comparison').value,
        study_design: document.getElementById('study_design').value
    };
    
    try {
        await fetch('http://localhost:3000/api/save-project-data', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                project_id: currentProject.id,
                data_type: 'pico',
                data_content: picoData
            })
        });
    } catch (error) {
        console.error('Failed to save PICO data:', error);
    }
}

// 保存Protocol数据
async function saveProtocolData() {
    if (!currentProject || !currentProject.id) return;
    
    const protocolData = {
        objective: document.getElementById('research-objective').value,
        inclusion: document.getElementById('inclusion-criteria').value,
        exclusion: document.getElementById('exclusion-criteria').value
    };
    
    try {
        await fetch('http://localhost:3000/api/save-project-data', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                project_id: currentProject.id,
                data_type: 'protocol',
                data_content: protocolData
            })
        });
    } catch (error) {
        console.error('Failed to save protocol data:', error);
    }
}

// 更新项目状态
async function updateProjectStatus(status) {
    if (!currentProject || !currentProject.id) return;
    
    try {
        await fetch('http://localhost:3000/api/update-project-status', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                project_id: currentProject.id,
                status: status
            })
        });
    } catch (error) {
        console.error('Failed to update project status:', error);
    }
}

// 修改后的 addNavigationListeners 函数
function addNavigationListeners() {
    // PICO页面的 Import Papers 按钮
    const importBtn = document.getElementById('import-papers-btn');
    if (importBtn) {
        importBtn.onclick = async () => {
            await savePicoData();
            await saveProtocolData();
            await updateProjectStatus('Import/Search');
            showPage('import-search-page');
        };
    }
    
    // Import/Search页面的 Proceed to Abstract Screening 按钮
    // Import/Search页面的 Proceed to Abstract Screening 按钮
    const proceedBtn = document.getElementById('proceed-to-abstract-btn');
    if (proceedBtn) {
        proceedBtn.onclick = async () => {
            // 【核心修复】：离开搜索界面前，将关键词等输入内容保存进该项目的数据库中
            await saveSearchData();
            
            await updateProjectStatus('Abstract Screening');
            showPage('abstract-screen-page');
        };
    }
    
    // Abstract Screening页面的 Proceed to Full-Text Screening 按钮
    // Abstract Screening页面的 Proceed 按钮
    const abstractProceedBtn = document.getElementById('proceed-to-data-btn');
    if (abstractProceedBtn) {
        abstractProceedBtn.onclick = async () => {
            await updateProjectStatus('Full-Text Screening');
            showPage('full-text-screen-page'); // 【修改】：现在跳到全文筛选页
        };
    }
    
    // 【新增】：Full-Text Screening 页面跳往 Data Extraction 的按钮
    const fulltextProceedBtn = document.getElementById('proceed-to-data-from-fulltext-btn');
    if (fulltextProceedBtn) {
        fulltextProceedBtn.onclick = async () => {
            await updateProjectStatus('Data Extraction');
            showPage('data-extraction-page');
        };
    }
    // ========== 调试代码 ==========
console.log('=== 调试信息开始 ===');
console.log('1. currentUser:', currentUser);
console.log('2. sessionStorage currentUser:', sessionStorage.getItem('currentUser'));
console.log('3. currentProject:', currentProject);

// 检查 create-project-btn 按钮
setTimeout(() => {
    const btn = document.getElementById('create-project-btn');
    console.log('4. create-project-btn 元素:', btn);
    
    if (btn) {
        console.log('5. 按钮文本:', btn.textContent);
        console.log('6. 按钮事件监听器:', btn.onclick);
        
        // 临时添加点击测试
        btn.addEventListener('click', function(e) {
            console.log('7. 按钮被点击了！');
            alert('按钮点击测试成功！');
        });
    } else {
        console.log('5. 未找到 create-project-btn 按钮！');
    }
}, 3000);

// 检查是否调用了 addNavigationListeners
console.log('8. addNavigationListeners 函数是否存在:', typeof addNavigationListeners);
console.log('=== 调试信息结束 ===');
}

// ========== Abstract Screening 动态渲染与保存逻辑 ==========

// 加载当前项目文献至摘要筛选表格
// 加载当前项目文献至摘要筛选表格
window.loadAbstractScreening = async function() {
    const screenTableBody = document.getElementById('screenTableBody');
    if (!screenTableBody || !currentProject || !currentProject.id) return;

    try {
        const response = await fetch('http://localhost:3000/api/get-literatures', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: currentProject.id })
        });
        const result = await response.json();

        if (result.success && result.data.length > 0) {
            screenTableBody.innerHTML = '';
            
            // 【核心修改】：在 forEach 中加入 index，用来生成显示的序号
            result.data.forEach((lit, index) => {
                const displayId = index + 1; // 生成从 1 开始的显示序号
                
                // 根据 AI 决定设置颜色
                let aiColor = lit.ai_decision === 'Included' ? 'green' : (lit.ai_decision === 'Excluded' ? 'red' : '#6c757d');
                let shortReason = lit.reasoning && lit.reasoning.length > 80 ? lit.reasoning.substring(0, 80) + '...' : (lit.reasoning || 'No reasoning provided yet');
                
                const tr = document.createElement('tr');
                // 真实数据库 ID 保存在 DOM 属性里
                // 【核心修改】：绑定 abstract 数据
                tr.setAttribute('data-id', lit.id);
                tr.setAttribute('data-reason', lit.reasoning || '');
                tr.setAttribute('data-abstract', lit.abstract || 'No abstract available.');
                
                tr.innerHTML = `
                    <td>${displayId}</td>
                    <td>${lit.title}</td>
                    <td style="color: ${aiColor}; font-weight: 600;">${lit.ai_decision}</td>
                    <td>
                        <select class="user-decision-select" style="font-size: 12px; padding: 6px;" onchange="updateDecision(${lit.id}, this.value)">
                            <option value="Keep" ${lit.user_decision === 'Keep' ? 'selected' : ''}>Keep AI Decision</option>
                            <option value="Include" ${lit.user_decision === 'Include' ? 'selected' : ''}>Manually Include</option>
                            <option value="Exclude" ${lit.user_decision === 'Exclude' ? 'selected' : ''}>Manually Exclude</option>
                        </select>
                    </td>
                    <td class="reason-display" style="cursor: pointer; color: #2c6ecb; text-decoration: underline;" onclick="openEditModal(this)" title="Click to view/edit full reasoning">${shortReason}</td>
                    <td>
                        <button class="btn btn-secondary btn-sm" onclick="openAbstractModal(this)">View Abstract</button>
                    </td>
                `;
                screenTableBody.appendChild(tr);
            });
        } else {
             screenTableBody.innerHTML = `<tr><td colspan="6" class="empty-data">No literatures found. Please import some papers first.</td></tr>`;
        }
    } catch (error) {
        console.error('Failed to load abstract screening data:', error);
    }
};


// 更新用户的Include/Exclude决定
window.updateDecision = async function(literatureId, decision) {
    try {
        await fetch('http://localhost:3000/api/update-literature-decision', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                literature_id: literatureId,
                user_decision: decision
            })
        });
    } catch (error) {
        console.error('Failed to update decision:', error);
    }
};

// 打开编辑推理弹窗（替换原本固定的事件绑定）
window.openEditModal = function(btnElement) {
    currentEditRow = btnElement.closest('tr');
    const originalReason = currentEditRow.getAttribute('data-reason');
    document.getElementById('reasonText').value = originalReason;
    document.getElementById('reasonModal').style.display = 'flex';
};

// 改写 Save Reason 按钮逻辑（添加后端调用）
document.getElementById('saveReason').addEventListener('click', async function() {
    if (!currentEditRow) return;
    const newReason = document.getElementById('reasonText').value.trim();
    const litId = currentEditRow.getAttribute('data-id'); // 获取文献ID
    
    if (newReason) {
        try {
            // 调用我们刚才在 app.py 里写的接口保存到数据库
            const response = await fetch('http://localhost:3000/api/update-literature-decision', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    literature_id: litId,
                    reasoning: newReason
                })
            });
            const result = await response.json();
            
            if (result.success) {
                // 更新前端 DOM
                currentEditRow.setAttribute('data-reason', newReason);
                const shortReason = newReason.length > 80 ? newReason.substring(0, 80) + '...' : newReason;
                currentEditRow.querySelector('.reason-display').textContent = shortReason;
                closeReasonModal();
                alert('Reasoning updated successfully!');
            } else {
                alert('Failed to save reasoning to database.');
            }
        } catch (error) {
            console.error('Save reasoning error:', error);
        }
    } else {
        alert('Reasoning content cannot be empty!');
    }
});

function clearAllInputs() {
    // 1. 清空 PICO 和 Protocol 输入框
    const textInputs = [
        'population', 'intervention', 'comparison', 'study_design',
        'research-objective', 'inclusion-criteria', 'exclusion-criteria',
        'search-keywords' // 连同搜索界面的关键字一起清空
    ];
    textInputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });

    // 2. 恢复 Search 界面的 Max Papers 默认值
    const maxPapers = document.getElementById('max-papers');
    if (maxPapers) maxPapers.value = 200;

    // 3. 清空文件上传框
    const fileUpload = document.getElementById('file-upload');
    if (fileUpload) fileUpload.value = '';
}


// ====== 新增：保存 Search 界面的数据 ======
async function saveSearchData() {
    if (!currentProject || !currentProject.id) return;
    
    const searchData = {
        keywords: document.getElementById('search-keywords').value,
        maxPapers: document.getElementById('max-papers').value
    };
    
    try {
        await fetch('http://localhost:3000/api/save-project-data', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                project_id: currentProject.id,
                data_type: 'search_params',  // 存入数据库时的类型标识
                data_content: searchData
            })
        });
    } catch (error) {
        console.error('Failed to save search data:', error);
    }
}

// ====== 新增：触发 AI 摘要筛查 ======
document.addEventListener('DOMContentLoaded', () => {
    const runAiBtn = document.getElementById('run-ai-screening-btn');
    if (runAiBtn) {
        runAiBtn.addEventListener('click', async () => {
            if (!currentProject || !currentProject.id) {
                alert('Error: No active project found.');
                return;
            }

            // 防抖与 Loading 提示
            const originalText = runAiBtn.innerHTML;
            runAiBtn.innerHTML = '⏳ AI is reading and screening... Please do not close the page.';
            runAiBtn.disabled = true;
            runAiBtn.style.backgroundColor = '#6c757d';

            try {
                const response = await fetch('http://localhost:3000/api/run-ai-screening', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ project_id: currentProject.id })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    alert(result.message);
                    // 运行完毕，重新加载带有全新 Include/Exclude 状态的表格
                    loadAbstractScreening(); 
                } else {
                    alert('Screening Error: ' + result.message);
                }
            } catch (error) {
                console.error('AI Screening request failed:', error);
                alert('Network error. Check if the Python backend is running properly.');
            } finally {
                // 恢复按钮状态
                runAiBtn.innerHTML = originalText;
                runAiBtn.disabled = false;
                runAiBtn.style.backgroundColor = '#28a745';
            }
        });
    }
});

// ====== 新增：处理导出 CSV 逻辑 ======
document.addEventListener('DOMContentLoaded', () => {
    const exportCsvBtn = document.getElementById('export-csv-btn');
    if (exportCsvBtn) {
        exportCsvBtn.addEventListener('click', () => {
            if (!currentProject || !currentProject.id) {
                alert('Error: No active project found.');
                return;
            }
            
            // 对于文件下载，最简单的方式是直接让浏览器打开带有参数的 GET 请求 URL
            const downloadUrl = `http://localhost:3000/api/export-csv?project_id=${currentProject.id}`;
            window.open(downloadUrl, '_blank');
        });
    }
});

// ====== 新增：处理非线性 Maximum Papers 预设跳跃逻辑 ======
document.addEventListener('DOMContentLoaded', () => {
    const maxPapersInput = document.getElementById('max-papers');
    const btnUp = document.getElementById('max-papers-up');
    const btnDown = document.getElementById('max-papers-down');
    
    // 你要求的预设档位
    const steps = [10, 30, 50, 100, 200];
    
    if (maxPapersInput && btnUp && btnDown) {
        btnUp.addEventListener('click', () => {
            let currentVal = parseInt(maxPapersInput.value) || 0;
            // 找到数组中第一个大于当前值的数，如果都比它小，就取最大值 200
            let nextVal = steps.find(s => s > currentVal) || steps[steps.length - 1];
            maxPapersInput.value = nextVal;
        });
        
        btnDown.addEventListener('click', () => {
            let currentVal = parseInt(maxPapersInput.value) || 0;
            // 把数组反转，找第一个小于当前值的数，如果都比它大，就取最小值 10
            let prevVal = [...steps].reverse().find(s => s < currentVal) || steps[0];
            maxPapersInput.value = prevVal;
        });
    }
});

// ==========================================
// Full-Text Screening 专属逻辑
// ==========================================

// 1. 自动下载 PDF 按钮事件
document.addEventListener('DOMContentLoaded', () => {
    const fetchPdfsBtn = document.getElementById('fetch-pdfs-btn');
    if (fetchPdfsBtn) {
        fetchPdfsBtn.addEventListener('click', async () => {
            if (!currentProject || !currentProject.id) return;
            
            const originalText = fetchPdfsBtn.innerHTML;
            fetchPdfsBtn.innerHTML = '⏳ Crawler is downloading PDFs... Please wait...';
            fetchPdfsBtn.disabled = true;
            fetchPdfsBtn.style.backgroundColor = '#6c757d';
            
            try {
                const response = await fetch('http://localhost:3000/api/fetch-pdfs', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ project_id: currentProject.id })
                });
                const result = await response.json();
                
                if (result.success) {
                    alert(result.message);
                    loadFullTextScreening(); // 刷新表格，显示已下载/失败状态
                } else {
                    alert('Error: ' + result.message);
                }
            } catch (e) {
                console.error(e);
                alert('Network error while fetching PDFs.');
            } finally {
                fetchPdfsBtn.innerHTML = originalText;
                fetchPdfsBtn.disabled = false;
                fetchPdfsBtn.style.backgroundColor = '#17a2b8';
            }
        });
    }
});

// 2. 加载 Full-Text 阶段文献列表
window.loadFullTextScreening = async function() {
    const tbody = document.getElementById('fulltextTableBody');
    if (!tbody || !currentProject) return;
    
    try {
        const response = await fetch('http://localhost:3000/api/get-literatures', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: currentProject.id })
        });
        const result = await response.json();
        
        if (result.success) {
            // 核心逻辑：只挑出被判定为 Included 的文献进入全文筛选！
            const includedPapers = result.data.filter(lit => {
                return lit.user_decision === 'Include' || 
                       ((!lit.user_decision || lit.user_decision === 'Keep') && lit.ai_decision === 'Included');
            });
            
            if (includedPapers.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" class="empty-data">No included papers found. Please review Abstract Screening first.</td></tr>`;
                return;
            }
            
            tbody.innerHTML = '';
            includedPapers.forEach((lit, index) => {
                let statusColor = '#6c757d'; 
                if (lit.pdf_status === 'Downloaded') statusColor = 'green';
                if (lit.pdf_status && lit.pdf_status.includes('Failed')) statusColor = 'red';
                
                let evidenceText = 'Waiting for AI Analysis...';
                if (lit.pico_evidence && lit.pico_evidence !== '{}') {
                    try {
                        const ev = JSON.parse(lit.pico_evidence);
                        evidenceText = `💡 <b>AI Conclusion:</b> ${ev.conclusion || 'Extracted'}`;
                    } catch(e) {
                        evidenceText = '✅ Extracted by AI';
                    }
                }
                
                // 给灰色不可点按钮也加上相同的 div 占位和 width: 100% 样式
                let pdfBtn = `
                    <div style="position: sticky; top: 120px; z-index: 10;">
                        <button class="btn btn-sm btn-secondary" disabled style="width: 100%; font-weight: bold;">View PDF</button>
                    </div>
                `;
                if (lit.pdf_path) {
                    const safePath = encodeURIComponent(lit.pdf_path);
                    pdfBtn = `
                        <div style="position: sticky; top: 120px; z-index: 10;">
                            <button id="view-pdf-btn-${lit.id}" class="btn btn-sm btn-primary" onclick="togglePdfView(${lit.id}, '${safePath}')" style="width: 100%; font-weight: bold; transition: all 0.3s;">View PDF</button>
                        </div>
                    `;
                }
                
                let decisionColor = lit.full_text_decision === 'Included' ? 'green' : (lit.full_text_decision === 'Excluded' ? 'red' : '#333');

                // 1. 生成主信息行
                const mainTr = document.createElement('tr');
                mainTr.id = `main-row-${lit.id}`;
                mainTr.innerHTML = `
                    <td>${index + 1}</td>
                    <td>${lit.title}</td>
                    <td style="color: ${statusColor}; font-weight: bold; font-size: 13px;">${lit.pdf_status || 'Pending'}</td>
                    <td style="color: ${decisionColor}; font-weight: bold;">${lit.full_text_decision || 'Pending'}</td>
                    <td style="font-size: 13px; color: #555;">${evidenceText}</td>
                    <td style="vertical-align: top; ">
                        <input type="file"
                            id="upload-${lit.id}"
                            accept="application/pdf"
                            style="font-size:12px; margin-bottom:4px;">
                    
                        <button class="btn btn-sm btn-warning"
                            onclick="uploadPDF(${lit.id})"
                            style="font-weight:bold;">
                            Upload PDF
                        </button>
                    </td>
                    <td id="action-cell-${lit.id}" style="vertical-align: top; background-color: #fff; border-left: 1px solid #eee;">${pdfBtn}</td>
                `;
                tbody.appendChild(mainTr);

                // 2. 生成紧跟在下方的隐藏 PDF 渲染行
                if (lit.pdf_path) {
                    const pdfTr = document.createElement('tr');
                    pdfTr.id = `pdf-row-${lit.id}`;
                    pdfTr.style.display = 'none'; // 初始隐藏
                    // 【核心魔法2】注意这里 colspan 是 6！因为第6列(Action列)会被上面的主行通过 rowspan 霸占下来
                    pdfTr.innerHTML = `
                        <td colspan="6" style="padding: 0; border-bottom: 3px solid #17a2b8;">
                            <div id="pdf-container-${lit.id}" style="width: 100%; background: #e9ecef; position: relative;">
                                </div>
                        </td>
                    `;
                    tbody.appendChild(pdfTr);
                }
            });
        }
    } catch (e) {
        console.error("Failed to load full-text screening data:", e);
    }
};

window.uploadPDF = function(paperId) {

    const fileInput = document.getElementById(`upload-${paperId}`);
    const file = fileInput.files[0];

    if (!file) {
        alert("Please select a PDF first.");
        return;
    }

    const formData = new FormData();
    formData.append("paper_id", paperId);
    formData.append("file", file);

    fetch("http://localhost:3000/api/upload-pdf", {
        method: "POST",
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            alert("Upload successful!");
            loadFullTextScreening();   // 重新加载表格
        } else {
            alert(data.message);
        }
    })
    .catch(err => {
        console.error(err);
        alert("Upload failed");
    });
};

// 3. 触发 AI 多模态全文阅片与高亮
document.addEventListener('DOMContentLoaded', () => {
    const runAiBtn = document.getElementById('run-fulltext-ai-btn');
    if (runAiBtn) {
        runAiBtn.addEventListener('click', async () => {
            if (!currentProject || !currentProject.id) return;
            
            const originalText = runAiBtn.innerHTML;
            runAiBtn.innerHTML = '⏳ Multimodal AI is reading and highlighting PDFs...';
            runAiBtn.disabled = true;
            runAiBtn.style.backgroundColor = '#6c757d';
            
            try {
                const response = await fetch('http://localhost:3000/api/run-fulltext-ai', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ project_id: currentProject.id })
                });
                const result = await response.json();
                
                if (result.success) {
                    alert(result.message);
                    loadFullTextScreening(); 
                } else {
                    alert('AI Error: ' + result.message);
                }
            } catch (e) {
                console.error(e);
                alert('Network error while running AI.');
            } finally {
                runAiBtn.innerHTML = originalText;
                runAiBtn.disabled = false;
                runAiBtn.style.backgroundColor = '#28a745';
            }
        });
    }
});


// ====== Full-Text: 展开/关闭行内 PDF 视图 ======
window.togglePdfView = function(litId, safePath) {
    const pdfRow = document.getElementById(`pdf-row-${litId}`);
    const pdfContainer = document.getElementById(`pdf-container-${litId}`);
    const actionCell = document.getElementById(`action-cell-${litId}`);
    const btn = document.getElementById(`view-pdf-btn-${litId}`);

    if (pdfRow.style.display === 'none') {
        // 【展开逻辑】
        pdfRow.style.display = 'table-row';
        // 让 Action 列动态跨越两行，包裹住上方摘要和下方巨幅 PDF
        actionCell.rowSpan = 2; 
        
        // 懒加载：只有第一次点击才生成 iframe 获取文件，避免页面加载时同时请求几十个PDF卡死服务器
        if (!pdfContainer.innerHTML.trim()) {
            pdfContainer.innerHTML = `<iframe src="http://localhost:3000/api/view-pdf?path=${safePath}" style="width: 100%; height: 800px; border: none; display: block;"></iframe>`;
        }
        
        // 按钮变红，文字变为关闭
        btn.innerHTML = 'Close PDF';
        btn.classList.remove('btn-primary');
        btn.classList.add('btn-danger');
    } else {
        // 【关闭逻辑】
        pdfRow.style.display = 'none';
        // Action 列恢复单行模式
        actionCell.rowSpan = 1; 
        
        // 按钮变蓝，文字恢复
        btn.innerHTML = 'View PDF';
        btn.classList.remove('btn-danger');
        btn.classList.add('btn-primary');
    }
};


// ====== 新增：打开查看摘要的弹窗 ======
const abstractModal = document.getElementById('abstractModal');
const abstractText = document.getElementById('abstractText');

window.openAbstractModal = function(btnElement) {
    const row = btnElement.closest('tr');
    const abstractContent = row.getAttribute('data-abstract');
    abstractText.textContent = abstractContent;
    abstractModal.style.display = 'flex';
};

function closeAbstractModalFunc() {
    abstractModal.style.display = 'none';
}
if(document.getElementById('closeAbstractModal')) {
    document.getElementById('closeAbstractModal').addEventListener('click', closeAbstractModalFunc);
    document.getElementById('closeAbstractBtn').addEventListener('click', closeAbstractModalFunc);
}

// 点击遮罩层关闭摘要弹窗
abstractModal.addEventListener('click', function(e) {
    if (e.target === abstractModal) closeAbstractModalFunc();
});