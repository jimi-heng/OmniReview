// 全局变量：存储当前编辑的行数据（用于推理编辑）
let currentEditRow = null;
// 在文件开头添加全局变量
let currentUser = null; // 存储当前登录用户信息
let currentProject = null; // 存储当前正在进行的项目
// ====== 核心配置：自动环境识别 ======
// 如果当前网址是 localhost，就请求本地后端的 3000 端口；否则请求云服务器的后端
const API_BASE_URL = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:3000'
    : 'http://47.102.222.252:3000';
    
// ====== 新增：处理 Apple 风格登录页入场动画逻辑 ======
// ====== 新增：处理 Apple 风格登录页入场动画逻辑 ======
function playLoginEntranceAnimation() {
    // 隐藏导航栏，直到登录成功 (确保和 showPage 守卫同步)
    const navbar = document.querySelector('.navbar');
    if (navbar) navbar.style.display = 'none';

    // 1. 给动画元素加上基础的动画准备类 (删除了 .login-background)
    document.getElementById('login-title')?.classList.add('animate-item');
    document.getElementById('login-subtitle')?.classList.add('animate-item');
    document.getElementById('feature-1')?.classList.add('animate-item');
    document.getElementById('feature-2')?.classList.add('animate-item');
    document.getElementById('feature-3')?.classList.add('animate-item');
    document.getElementById('login-card')?.classList.add('animate-item');

    // 2. 瞬间清除，触发重新计算 (Triggers reflow)
    void document.body.offsetWidth;

    // 3. 加上触发关键帧播放的类 (删除了 .login-background)
    document.getElementById('login-title')?.classList.add('play-animation');
    document.getElementById('login-subtitle')?.classList.add('play-animation');
    document.getElementById('feature-1')?.classList.add('play-animation');
    document.getElementById('feature-2')?.classList.add('play-animation');
    document.getElementById('feature-3')?.classList.add('play-animation');
    document.getElementById('login-card')?.classList.add('play-animation');
}


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
// 2. 通用页面切换函数（所有按钮跳转核心）
// ====== 新增：记录页面层级，用于苹果风滑动动画 ======
let activePageId = 'login-page';
const pageLevel = {
    'home-page': 1,
    'profile-page': 2,
    'pico-page': 2,
    'import-search-page': 3,
    'abstract-screen-page': 4,
    'full-text-screen-page': 5,
    'data-extraction-page': 6
};

// 2. 通用页面切换函数（所有按钮跳转核心）
function showPage(pageId) {
    // 🌟 核心拦截：如果切回主页，就把导航栏名字重置为通用的 Criteria Setup
    if (pageId === 'home-page') {
        const navPico = document.getElementById('step-pico');
        if (navPico) navPico.textContent = '2. Criteria Setup';
    }

    // ========== 导航路由守卫 ==========
    if (!currentUser && pageId !== 'login-page' && pageId !== 'register-page') {
        alert('Access denied. Please log in first.');
        return;
    }
    if (currentUser && (pageId === 'login-page' || pageId === 'register-page')) {
        return; 
    }
    const projectPages = ['pico-page', 'import-search-page', 'abstract-screen-page', 'full-text-screen-page', 'data-extraction-page'];
    if (currentUser && !currentProject && projectPages.includes(pageId)) {
        alert('Please select "Continue" or "Create New Project" from the Home dashboard first.');
        return;
    }
    // ===================================

    // 🌟 核心动效：判断滑动方向 (Forward: 从右向左滑; Backward: 从左向右滑)
    let isForward = true;
    if (pageLevel[pageId] !== undefined && pageLevel[activePageId] !== undefined) {
        isForward = pageLevel[pageId] >= pageLevel[activePageId];
    }
    // 强制规定：只要是回到 home-page，必定是后退
    if (pageId === 'home-page') isForward = false;

    // 隐藏所有页面，并清除旧的动画类
    const allPages = ['login-page', 'register-page', 'home-page', 'profile-page', 'pico-page', 'import-search-page', 'abstract-screen-page', 'full-text-screen-page', 'data-extraction-page'];
    allPages.forEach(id => {
        const el = document.getElementById(id);
        if (el && id !== pageId) {
            el.style.display = 'none';
            el.classList.remove('ios-slide-in-forward', 'ios-slide-in-backward');
        }
    });
    
    // 显示目标页面 (兼容全新平移空间架构)
    if (pageId === 'login-page' || pageId === 'register-page') {
        const megaWrapper = document.getElementById('auth-mega-wrapper');
        if (megaWrapper) {
            megaWrapper.style.display = 'block';
            megaWrapper.className = 'state-cover';
            document.body.classList.add('hide-nav');
        }
    } else {
        const targetEl = document.getElementById(pageId);
        if (targetEl) {
            targetEl.style.display = 'block';
            
            // 🌟 触发苹果风滑入动画 (排除从封面刚进来的第一次，保持原样)
            if (activePageId !== 'login-page' && activePageId !== 'register-page') {
                targetEl.classList.remove('ios-slide-in-forward', 'ios-slide-in-backward');
                void targetEl.offsetWidth; // 魔法：瞬间触发重绘，重启 CSS 动画
                targetEl.classList.add(isForward ? 'ios-slide-in-forward' : 'ios-slide-in-backward');
            }
        }
        
        const megaWrapper = document.getElementById('auth-mega-wrapper');
        if (megaWrapper) megaWrapper.style.display = 'none';
        document.body.classList.remove('hide-nav');
    }

    activePageId = pageId; // 更新当前所处页面的记忆

    // 智能底图隔离逻辑
    const loginBg = document.querySelector('.login-background');
    if (loginBg) {
        loginBg.style.display = (pageId === 'login-page' || pageId === 'register-page') ? 'block' : 'none';
    }

    // 检查数据提取结果
    if (pageId === 'data-extraction-page' && currentProject) {
        checkExtractionStatus();
    }
    
    // 根据页面执行对应的初始化和导航高亮
    switch (pageId) {
        case 'login-page':
        case 'register-page': updateProgressStep('step-login'); break;
        case 'home-page':
            updateProgressStep('step-home');
            currentProject = null;
            sessionStorage.removeItem('currentProject');
            if (currentUser) loadUserProjects();
            break;
        case 'pico-page': updateProgressStep('step-pico'); break;
        case 'import-search-page':
            updateProgressStep('step-import');
            setTimeout(loadLiteratureList, 100);
            break;
        case 'abstract-screen-page': updateProgressStep('step-abstract'); break;
        case 'full-text-screen-page': 
            updateProgressStep('step-fulltext'); 
            setTimeout(loadFullTextScreening, 100);
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
    const response = await fetch(`${API_BASE_URL}/api/login`, {
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

      // 1. 获取当前格式化的时间 (例如：Mar 15, 17:30)
      const now = new Date();
      const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const dateStr = now.toLocaleDateString([], { month: 'short', day: 'numeric' });

      // 2. 保存用户信息 (加入了时间)
      currentUser = {
        id: result.user_id,
        email: inputEmail, // 你的代码直接拿到了输入邮箱，完美！
        loginTime: `${dateStr}, ${timeStr}`
      };

      // 3. 动态渲染到 HTML 界面上 (苹果风悬浮窗和个人主页)
      const emailDisplays = [document.getElementById('profile-email-display'), document.getElementById('tooltip-email')];
      emailDisplays.forEach(el => { 
          if (el) el.textContent = currentUser.email; 
      });
      const timeDisplay = document.getElementById('tooltip-time');
      if (timeDisplay) timeDisplay.textContent = `Logged in: ${currentUser.loginTime}`;

      // 4. 保存到sessionStorage以便页面刷新后保留
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
  playLoginEntranceAnimation(); // 【核心新增】：点击退出登录回到主页时，也播放一次入场动画
});


document.addEventListener('DOMContentLoaded', () => {
  // 添加导航监听器
  addNavigationListeners();

  // 检查是否有保存的用户信息
  const savedUser = sessionStorage.getItem('currentUser');
  if (savedUser) {
    currentUser = JSON.parse(savedUser);
    
    // 🔄 恢复页面刷新后的悬浮窗和账号显示
    const emailDisplays = [document.getElementById('profile-email-display'), document.getElementById('tooltip-email')];
    emailDisplays.forEach(el => { if (el) el.textContent = currentUser.email; });
    const timeDisplay = document.getElementById('tooltip-time');
    if (timeDisplay && currentUser.loginTime) timeDisplay.textContent = `Logged in: ${currentUser.loginTime}`;

    // 如果是在登录状态，直接显示首页并加载项目
    showPage('home-page');
    loadUserProjects();
  } else {
    // 【核心新增】：如果没有登录，确保显示登录页，并瞬间触发绝美的开场动画
    showPage('login-page');
    playLoginEntranceAnimation();
  }
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
        const response = await fetch(`${API_BASE_URL}/api/register`, {
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

// 6. 核心功能：AI推理查看/编辑弹窗控制（仅保留关闭逻辑，保存和打开逻辑已移至底部）
function closeReasonModal() {
    document.getElementById('reasonModal').style.display = 'none';
    currentEditRow = null;
}
// 删掉了绑定 closeModal 的那行
document.getElementById('cancelEdit').addEventListener('click', closeReasonModal);
document.getElementById('reasonModal').addEventListener('click', function(e) {
    if (e.target === this) closeReasonModal();
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
// ====== 新增：解析 .ris 和 .txt (标准标签格式) 的核心函数 ======
function parseRisFile(text) {
  const literatures = [];
  // RIS 格式以 "ER  - " 作为每条文献的结束标记
  const entries = text.split(/ER\s+-/);

  entries.forEach(entry => {
    if (!entry.trim()) return;

    const lines = entry.split(/\n|\r\n/);
    let lit = { title: '', author: [], journal: '', year: null, doi: '', abstract: '' };
    let currentTag = '';

    lines.forEach(line => {
      // 匹配标准的 "TAG  - Value" 格式 (如 TI  - 文章标题)
      const match = line.match(/^([A-Z0-9]{2})\s+-\s+(.*)$/);
      if (match) {
        currentTag = match[1];
        const val = match[2].trim();
        
        // 解析各类标签 (兼容不同文献管理软件的微小差异)
        if (currentTag === 'TI' || currentTag === 'T1') lit.title = val;
        else if (currentTag === 'AU' || currentTag === 'A1') lit.author.push(val);
        else if (currentTag === 'JO' || currentTag === 'T2' || currentTag === 'JF') lit.journal = val;
        else if (currentTag === 'PY' || currentTag === 'Y1') {
          const yearMatch = val.match(/\d{4}/);
          if (yearMatch) lit.year = parseInt(yearMatch[0]);
        }
        else if (currentTag === 'DO') lit.doi = val;
        else if (currentTag === 'AB' || currentTag === 'N2') lit.abstract = val;
      } else if (currentTag === 'AB' || currentTag === 'N2') {
         // 处理摘要中可能存在换行符的情况
         lit.abstract += ' ' + line.trim();
      }
    });

    // 只要成功提取到标题，就视为有效文献
    if (lit.title) {
      literatures.push({
        title: lit.title,
        author: lit.author.join('; '), // 将多个作者用分号拼接
        journal: lit.journal,
        year: lit.year,
        doi: lit.doi,
        abstract: lit.abstract
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

        // 校验文件格式 (严防死守，仅放行标准文献格式)
        if (!['bib', 'ris'].includes(fileExt)) {
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

        // 🌟 核心解析：安全拆分 bib 和 ris 文件
        let literatures = [];
        if (fileExt === 'bib') {
          literatures = parseBibFile(fileContent);
        } else if (fileExt === 'ris') {
          literatures = parseRisFile(fileContent); // 专注于解析纯正的 ris
        } else {
          errorFiles.push(`${file.name} (unsupported format)`);
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

            const response = await fetch(`${API_BASE_URL}/api/upload-literature`, {
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
      const response = await fetch(`${API_BASE_URL}/api/get-literatures`, {
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

    if (pageId === 'import-search-page') {
      setTimeout(loadLiteratureList, 100);
    } else if (pageId === 'abstract-screen-page') {
      setTimeout(loadAbstractScreening, 100);
    } else if (pageId === 'data-extraction-page') {
      // 新增：进入数据提取页面时加载统计数据
      setTimeout(window.loadDataExtraction, 100);
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
            
            // 🌟 核心修复 1：提取当前所有处于 active 状态的胶囊按钮
            const activeChips = document.querySelectorAll('.db-chip.active');
            const selectedDBs = Array.from(activeChips).map(chip => chip.getAttribute('data-db'));

            if (!keywords) {
                alert('Please enter search keywords.');
                return;
            }
            if (!currentProject || !currentProject.id) {
                alert('Please create or select a project first.');
                return;
            }

            const btn = document.getElementById('search-pubmed-btn');
            const originalText = btn.textContent;
            btn.textContent = 'Searching... (May take a while)';
            btn.disabled = true;

            try {
                const response = await fetch(`${API_BASE_URL}/api/search-pubmed`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        project_id: currentProject.id,
                        keywords: keywords,
                        max_papers: parseInt(maxPapers),
                        databases: selectedDBs // 👈 核心修复 2：把选中的数据库数组发给后端
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

// ==========================================
// 🌓 昼夜主题切换核心逻辑
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
    const themeBtn = document.getElementById('theme-toggle-btn');
    const themeIcon = document.getElementById('theme-icon');
    
    // 初始化时根据 body 是否有 dark-theme 来设置图标
    if (document.body.classList.contains('dark-theme')) {
        themeIcon.textContent = '☀️'; // 当前是黑夜，提示可切白天
    } else {
        themeIcon.textContent = '🌙'; // 当前是白天，提示可切黑夜
    }

    themeBtn.addEventListener('click', () => {
        document.body.classList.toggle('dark-theme');
        const isDark = document.body.classList.contains('dark-theme');
        
        if (isDark) {
            themeIcon.textContent = '☀️';
            localStorage.setItem('app-theme', 'dark'); // 记住用户的夜间偏好
        } else {
            themeIcon.textContent = '🌙';
            localStorage.setItem('app-theme', 'light'); // 记住用户的白天偏好
        }
        
        // 💡 下一步：如果你想让 3D DNA 在白天变成另外一种颜色，可以在这里触发修改
    });
});



// 加载用户的项目列表
async function loadUserProjects() {
    if (!currentUser) return;

    try {
        const response = await fetch(`${API_BASE_URL}/api/get-projects`, {
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
// 渲染项目列表到页面
// 渲染项目列表到页面 (修复按钮丢失问题)
function renderProjects(projects) {
    const homePage = document.getElementById('home-page');
    const projectsContainer = homePage.querySelector('.card');
    if (!projectsContainer) return;

    // 🌟 核心修复：把顶部标题和 Create 按钮的结构单独提出来，保证每次渲染都在
    const headerHtml = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
            <h3 style="margin: 0;">Recent Projects</h3>
            <button class="btn btn-primary" id="create-project-btn">Create New Project</button>
        </div>
    `;

    if (projects.length === 0) {
        // 没有项目时显示空状态
        projectsContainer.innerHTML = headerHtml + `
            <div class="empty-data">No projects yet. Click "Create New Project" to start.</div>
        `;
    } else {
        // 有项目时渲染列表
        let projectsHtml = headerHtml;
        
        projects.forEach(project => {
            // 解析后端传来的类型并渲染正确的角标 (拦截并强制显示为 SPICO)
            let pType = project.project_type ? project.project_type.replace(/"/g, '') : 'SPICO';
            if (pType === 'PICOS') pType = 'SPICO';
            let badgeClass = pType.toLowerCase();

            projectsHtml += `
                <div class="project-item" data-project-id="${project.id}">
                    <div>
                        <p style="display: flex; align-items: center; margin-bottom: 4px;">
                            <strong class="project-name" style="font-size: 16px;">${project.project_name}</strong>
                            <span class="type-badge ${badgeClass}">${pType}</span>
                            <button class="btn btn-sm btn-secondary" style="margin-left: 10px; padding: 2px 8px;" onclick="editProjectName(${project.id}, this)">✎</button>
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
        projectsContainer.innerHTML = projectsHtml;
    }

    // 🌟 核心修复：每次重新渲染 HTML 后，必须重新给按钮绑定点击事件！
    const createBtn = document.getElementById('create-project-btn');
    if (createBtn) {
        // 为了防止重复绑定，先克隆再替换，然后再绑定绝对安全的事件
        createBtn.replaceWith(createBtn.cloneNode(true));
        const newCreateBtn = document.getElementById('create-project-btn');
        newCreateBtn.addEventListener('click', openCreateProjectModal);
    }
}

// 创建新项目
// 创建新项目
async function createNewProject(projectName) {
    if (!currentUser) return;
    try {
        // 抓取用户选中的类型
        const activeOption = document.querySelector('.type-option.active');
        const projectType = activeOption ? activeOption.getAttribute('data-type') : 'SPICO';

        const response = await fetch(`${API_BASE_URL}/api/create-project`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: currentUser.id, project_name: projectName })
        });
        const result = await response.json();

        if (result.success) {
            currentProject = { id: result.project_id, name: projectName, status: 'PICO Setup', type: projectType };
            sessionStorage.setItem('currentProject', JSON.stringify(currentProject));

            // 立刻将类型存入 project_data 供后端 AI 和首页角标读取
            await fetch(`${API_BASE_URL}/api/save-project-data`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: currentProject.id, data_type: 'project_type', data_content: projectType })
            });

            clearAllInputs();
            renderPicoPageByType(projectType);
            showPage('pico-page');
        } else {
            alert('Failed to create project: ' + result.message);
        }
    } catch (error) { alert('Failed to create project'); }
}

// 继续项目
async function continueProject(projectId) {
    try {
        clearAllInputs(); // 安全清空

        const response = await fetch(`${API_BASE_URL}/api/get-project-data`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: projectId })
        });
        const result = await response.json();

        if (result.success) {
            currentProject = { id: projectId };
            
            // 1. 读取项目类型并恢复界面形态
            if (result.data.project_type) {
                currentProject.type = result.data.project_type;
            } else {
                currentProject.type = 'SPICO'; // 默认采用新版 SPICO
            }
            // 🛡️ 核心兼容：不管后端原来存的是什么，前端一律按 SPICO 渲染
            if (currentProject.type === 'PICOS') {
                currentProject.type = 'SPICO';
            }
            renderPicoPageByType(currentProject.type);

            // 2. 将数据安全填入对应的输入框
            if (result.data.pico) {
                if (currentProject.type === 'SPICO') {
                    document.getElementById('spico-s').value = result.data.pico.s || '';
                    document.getElementById('spico-p').value = result.data.pico.p || '';
                    document.getElementById('spico-i').value = result.data.pico.i || '';
                    document.getElementById('spico-c').value = result.data.pico.c || '';
                    document.getElementById('spico-o').value = result.data.pico.o || '';
                } else if (currentProject.type === 'PECO') {
                    document.getElementById('peco-p').value = result.data.pico.p || '';
                    document.getElementById('peco-e').value = result.data.pico.e || '';
                    document.getElementById('peco-c').value = result.data.pico.c || '';
                    document.getElementById('peco-o').value = result.data.pico.o || '';
                } else if (currentProject.type === 'PIRO') {
                    document.getElementById('piro-p').value = result.data.pico.p || '';
                    document.getElementById('piro-i').value = result.data.pico.i || '';
                    document.getElementById('piro-r').value = result.data.pico.r || '';
                    document.getElementById('piro-o').value = result.data.pico.o || '';
                }
            }

            // 加载 Protocol 数据
            if (result.data.protocol) {
                if (result.data.protocol.criteria !== undefined) {
                    document.getElementById('additional-criteria').value = result.data.protocol.criteria;
                }
            }
            // 加载 Search 数据
            if (result.data.search_params) {
                document.getElementById('search-keywords').value = result.data.search_params.keywords || '';
                document.getElementById('max-papers').value = result.data.search_params.maxPapers || 200;
            }

            const projectResponse = await fetch(`${API_BASE_URL}/api/get-projects`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: currentUser.id })
            });
            const project = (await projectResponse.json()).data.find(p => p.id === projectId);
            if (project) {
                currentProject.name = project.project_name;
                sessionStorage.setItem('currentProject', JSON.stringify(currentProject));
                switch(project.status) {
                    case 'PICO Setup': showPage('pico-page'); break;
                    case 'Import/Search': showPage('import-search-page'); break;
                    case 'Abstract Screening': showPage('abstract-screen-page'); break;
                    case 'Full-Text Screening': showPage('full-text-screen-page'); break;
                    case 'Data Extraction': showPage('data-extraction-page'); break;
                    default: showPage('pico-page');
                }
            }
        }
    } catch (error) { console.error(error); alert('Failed to load project data'); }
}



// 编辑项目名称
async function editProjectName(projectId, buttonElement) {
    const projectItem = buttonElement.closest('.project-item');
    const nameElement = projectItem.querySelector('.project-name');
    const oldName = nameElement.textContent;

    const newName = prompt('Edit project name:', oldName);
    if (newName && newName.trim() && newName.trim() !== oldName) {
        try {
            const response = await fetch(`${API_BASE_URL}/api/update-project-name`, {
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

// ====== 重构：Apple 风格删除项目逻辑 ======
let projectToDeleteId = null; // 临时存储要删除的项目 ID

// 1. 点击 Delete 按钮时，只打开弹窗，不直接删
function deleteProject(projectId, projectName) {
    projectToDeleteId = projectId;
    document.getElementById('deleteProjectNameDisplay').textContent = `"${projectName}"`;
    document.getElementById('deleteProjectModal').style.display = 'flex';
}

// 2. 关闭弹窗逻辑
function closeDeleteModal() {
    document.getElementById('deleteProjectModal').style.display = 'none';
    projectToDeleteId = null;
}

document.getElementById('cancelDeleteBtn')?.addEventListener('click', closeDeleteModal);
document.getElementById('deleteProjectModal')?.addEventListener('click', function(e) {
    if (e.target === this) closeDeleteModal();
});

// 3. 点击弹窗里的红色 Delete 按钮时，真正执行删除
document.getElementById('confirmDeleteBtn')?.addEventListener('click', async () => {
    if (!projectToDeleteId) return;
    const projectId = projectToDeleteId;

    // 先立刻关闭弹窗
    closeDeleteModal();

    try {
        const response = await fetch(`${API_BASE_URL}/api/delete-project`, {
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
});

// 保存PICO数据
// 保存PICO数据 (更新为 PICOS 结构)
// 动态保存针对该类型的输入
async function savePicoData() {
    if (!currentProject || !currentProject.id) return;
    const type = currentProject.type || 'SPICO';
    let picoData = {};

    if (type === 'SPICO') {
        picoData = {
            s: document.getElementById('spico-s').value, p: document.getElementById('spico-p').value,
            i: document.getElementById('spico-i').value, c: document.getElementById('spico-c').value, o: document.getElementById('spico-o').value
        };
    } else if (type === 'PECO') {
        picoData = {
            p: document.getElementById('peco-p').value, e: document.getElementById('peco-e').value,
            c: document.getElementById('peco-c').value, o: document.getElementById('peco-o').value
        };
    } else if (type === 'PIRO') {
        picoData = {
            p: document.getElementById('piro-p').value, i: document.getElementById('piro-i').value,
            r: document.getElementById('piro-r').value, o: document.getElementById('piro-o').value
        };
    }

    try {
        await fetch(`${API_BASE_URL}/api/save-project-data`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: currentProject.id, data_type: 'pico', data_content: picoData })
        });
    } catch (error) { console.error('Failed to save PICO data:', error); }
}

// 保存Protocol数据 (合并纳排标准)
async function saveProtocolData() {
    if (!currentProject || !currentProject.id) return;

    const protocolData = {
        criteria: document.getElementById('additional-criteria').value // 统一合并为 criteria
    };

    try {
        await fetch(`${API_BASE_URL}/api/save-project-data`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
        await fetch(`${API_BASE_URL}/api/update-project-status`, {
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
}

// ========== Abstract Screening 动态渲染与保存逻辑 ==========

// 加载当前项目文献至摘要筛选表格
// 加载当前项目文献至摘要筛选表格
window.loadAbstractScreening = async function() {
    const screenTableBody = document.getElementById('screenTableBody');
    if (!screenTableBody || !currentProject || !currentProject.id) return;

    try {
        const response = await fetch(`${API_BASE_URL}/api/get-literatures`, {
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

                // 根据 AI 决定设置颜色 (新增 Error 状态的苹果风色彩支持)
                let aiColor = '#6c757d'; // 默认灰
                if (lit.ai_decision === 'Included') aiColor = '#34c759'; // 苹果绿
                else if (lit.ai_decision === 'Excluded') aiColor = '#ff3b30'; // 苹果红
                else if (lit.ai_decision === 'Error') aiColor = '#ff9500'; // 苹果警告橙
                let shortReason = lit.reasoning && lit.reasoning.length > 80 ? lit.reasoning.substring(0, 80) + '...' : (lit.reasoning || 'No reasoning provided yet');

                const tr = document.createElement('tr');
                tr.setAttribute('data-id', lit.id);
                tr.setAttribute('data-reason', lit.reasoning || '');
                tr.setAttribute('data-abstract', lit.abstract || 'No abstract available.');

                // 【新增】：根据当前状态计算苹果风按钮的初始外观
                let currentAction = lit.user_decision || 'Keep';
                let btnText = 'Keep AI';
                let btnBg = '#f2f2f7';
                let btnColor = '#1d1d1f';

                if (currentAction === 'Include') {
                    btnText = 'Included';
                    btnBg = '#34c759';
                    btnColor = '#ffffff';
                } else if (currentAction === 'Exclude') {
                    btnText = 'Excluded';
                    btnBg = '#ff3b30';
                    btnColor = '#ffffff';
                }

                tr.innerHTML = `
                    <td>${displayId}</td>
                    <td>${lit.title}</td>
                    <td style="color: ${aiColor}; font-weight: 600;">${lit.ai_decision}</td>
                    <td>
                        <button class="btn" 
                            style="font-size: 12px; padding: 6px 14px; border-radius: 14px; font-weight: 600; border: none; transition: all 0.2s cubic-bezier(0.25, 0.8, 0.25, 1); background-color: ${btnBg}; color: ${btnColor}; box-shadow: 0 2px 6px rgba(0,0,0,0.06);" 
                            onclick="toggleUserDecision(this, ${lit.id}, '${currentAction}', '${lit.ai_decision}')">
                            ${btnText}
                        </button>
                    </td>
                    <td class="reason-display" 
                        style="cursor: pointer; color: #555; text-decoration: none; transition: color 0.2s ease; line-height: 1.5;" 
                        onmouseover="this.style.color='#0071e3'" 
                        onmouseout="this.style.color='#555'" 
                        onclick="openEditModal(this)" 
                        title="Click to view/edit full reasoning">
                        ${shortReason}
                    </td>
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
        await fetch(`${API_BASE_URL}/api/update-literature-decision`, {
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
            const response = await fetch(`${API_BASE_URL}/api/update-literature-decision`, {
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

// ====== 统一且唯一的清空输入框函数 ======
function clearAllInputs() {
    const textInputs = [
        // SPICO 字段
        'spico-s', 'spico-p', 'spico-i', 'spico-c', 'spico-o',
        // PECO 字段
        'peco-p', 'peco-e', 'peco-c', 'peco-o',
        // PIRO 字段
        'piro-p', 'piro-i', 'piro-r', 'piro-o',
        // Protocol 与 Search 字段 (已移除废弃的 research-objective)
        'additional-criteria', 'search-keywords'
    ];
    
    textInputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });

    // 恢复 Search 界面的 Max Papers 默认值
    const maxPapers = document.getElementById('max-papers');
    if (maxPapers) maxPapers.value = 200;

    // 清空文件上传框
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
        await fetch(`${API_BASE_URL}/api/save-project-data`, {
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
                const response = await fetch(`${API_BASE_URL}/api/run-ai-screening`, {
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
            const downloadUrl = `${API_BASE_URL}/api/export-csv?project_id=${currentProject.id}`;
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
                const response = await fetch(`${API_BASE_URL}/api/fetch-pdfs`, {
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
        const response = await fetch(`${API_BASE_URL}/api/get-literatures`, {
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
                // 【全量果化】1. PDF 下载状态颜色升级
                let statusColor = '#86868b'; // 苹果默认灰
                let displayStatus = lit.pdf_status || 'Pending';

                if (displayStatus === 'Downloaded') {
                    statusColor = '#34c759'; // 苹果系统绿
                } else if (displayStatus.includes('Failed')) {
                    statusColor = '#ff3b30'; // 苹果系统红
                    // 【神来之笔】：把 "Failed (Paywalled)" 变成两行："Failed" 加粗，原因变细变小换行显示！
                    displayStatus = displayStatus.replace(' (', '<br><span style="font-size: 11px; font-weight: normal; opacity: 0.8;">(') + '</span>';
                }

                let evidenceText = 'Waiting for AI Analysis...';
                if (lit.pico_evidence && lit.pico_evidence !== '{}') {
                    try {
                        const ev = JSON.parse(lit.pico_evidence);
                        evidenceText = `💡 <b>AI Conclusion:</b> ${ev.conclusion || 'Extracted'}`;
                    } catch(e) {
                        evidenceText = '✅ Extracted by AI';
                    }
                }

                // 【全量果化】2. AI 全文判决状态颜色升级 (同步加入 Error 的橙色预警)
                let decisionColor = '#86868b'; // 苹果默认灰
                if (lit.full_text_decision === 'Included') decisionColor = '#34c759'; // 苹果系统绿
                else if (lit.full_text_decision === 'Excluded') decisionColor = '#ff3b30'; // 苹果系统红
                else if (lit.full_text_decision === 'Error') decisionColor = '#ff9500'; // 苹果警告橙

                let actionContent = '';
                const rawStatus = lit.pdf_status || 'Pending';

                // 【核心逻辑】：根据下载状态，动态决定 Action 列显示什么
                if (rawStatus === 'Downloaded' && lit.pdf_path) {
                    const safePath = encodeURIComponent(lit.pdf_path);
                    actionContent = `
                        <div style="display: flex; flex-direction: column; align-items: center; gap: 8px; position: sticky; top: 120px; z-index: 10;">
                            <button id="view-pdf-btn-${lit.id}" class="btn btn-primary" onclick="togglePdfView(${lit.id}, '${safePath}')" 
                                style="font-size: 13px; padding: 8px 20px; border-radius: 20px; font-weight: 600; transition: all 0.3s; box-shadow: 0 4px 12px rgba(0,113,227,0.3); border: none;">
                                View PDF
                            </button>
                            <label style="font-size: 11px; color: #86868b; text-align: center; cursor: pointer; margin: 0; transition: color 0.2s;" onmouseover="this.style.color='#0071e3'" onmouseout="this.style.color='#86868b'">
                                <input type="file" accept="application/pdf" style="display: none;" onchange="autoUploadPDF(${lit.id}, this)">
                                Replace file
                            </label>
                        </div>
                    `;
                } else if (rawStatus.includes('Failed')) {
                    // 【新增】：智能生成外部跳转链接 (优先使用 DOI，没有则用 Google Scholar 搜索)
                    let sourceLinkHtml = '';
                    if (lit.doi) {
                        let cleanDoi = lit.doi.replace('https://doi.org/', '').trim();
                        sourceLinkHtml = `
                            <a href="https://doi.org/${cleanDoi}" target="_blank" style="font-size: 11px; color: #0071e3; text-decoration: none; font-weight: 500; display: flex; align-items: center; gap: 2px; transition: opacity 0.2s;" onmouseover="this.style.opacity='0.6'" onmouseout="this.style.opacity='1'">
                                Open Source <span style="font-size: 14px; margin-bottom: 2px;">↗</span>
                            </a>
                        `;
                    } else {
                        let searchUrl = `https://scholar.google.com/scholar?q=${encodeURIComponent(lit.title)}`;
                        sourceLinkHtml = `
                            <a href="${searchUrl}" target="_blank" style="font-size: 11px; color: #0071e3; text-decoration: none; font-weight: 500; display: flex; align-items: center; gap: 2px; transition: opacity 0.2s;" onmouseover="this.style.opacity='0.6'" onmouseout="this.style.opacity='1'">
                                Search Scholar <span style="font-size: 14px; margin-bottom: 2px;">↗</span>
                            </a>
                        `;
                    }

                    actionContent = `
                        <div style="display: flex; flex-direction: column; align-items: center; gap: 8px; position: sticky; top: 120px; z-index: 10;">
                            <label class="btn" style="font-size: 13px; padding: 8px 18px; border-radius: 20px; font-weight: 600; background-color: #ff3b30; color: white; border: none; cursor: pointer; text-align: center; margin: 0; box-shadow: 0 4px 12px rgba(255,59,48,0.3); transition: all 0.3s;" onmouseover="this.style.transform='scale(1.04)'" onmouseout="this.style.transform='scale(1)'">
                                <input type="file" accept="application/pdf" style="display: none;" onchange="autoUploadPDF(${lit.id}, this)">
                                ⇧ Upload
                            </label>
                            ${sourceLinkHtml}
                        </div>
                    `;
                } else {
                    actionContent = `
                        <div style="display: flex; flex-direction: column; align-items: center; position: sticky; top: 120px; z-index: 10;">
                            <button class="btn btn-secondary" disabled style="font-size: 13px; padding: 8px 20px; border-radius: 20px; font-weight: 600; border: none;">Waiting...</button>
                        </div>
                    `;
                }

                // 【新增】：全文筛选的 User Action 苹果风按钮逻辑
                let fullTextUserAction = lit.full_text_user_decision || 'Keep';
                let btnText = 'Keep AI';
                let btnBg = '#f2f2f7';
                let btnColor = '#1d1d1f';

                if (fullTextUserAction === 'Include') {
                    btnText = 'Included';
                    btnBg = '#34c759';
                    btnColor = '#ffffff';
                } else if (fullTextUserAction === 'Exclude') {
                    btnText = 'Excluded';
                    btnBg = '#ff3b30';
                    btnColor = '#ffffff';
                }

                let userActionContent = `
                    <button class="btn" 
                        style="font-size: 12px; padding: 6px 14px; border-radius: 14px; font-weight: 600; border: none; transition: all 0.2s cubic-bezier(0.25, 0.8, 0.25, 1); background-color: ${btnBg}; color: ${btnColor}; box-shadow: 0 2px 6px rgba(0,0,0,0.06);" 
                        onclick="toggleFullTextUserDecision(this, ${lit.id}, '${fullTextUserAction}', '${lit.full_text_decision || 'Pending'}')">
                        ${btnText}
                    </button>
                `;
                // 1. 生成主信息行 (彻底去掉了那丑陋的独立 Upload 列，现在只有 6 列)
                const mainTr = document.createElement('tr');
                mainTr.id = `main-row-${lit.id}`;
                mainTr.innerHTML = `
                    <td>${index + 1}</td>
                    <td>${lit.title}</td>
                    <td style="color: ${statusColor}; font-weight: bold; font-size: 13px; line-height: 1.4;">${displayStatus}</td>
                    <td style="color: ${decisionColor}; font-weight: bold;">${lit.full_text_decision || 'Pending'}</td>
                    <td>${userActionContent}</td> <td style="font-size: 13px; color: #555;">${evidenceText}</td>
                    <td id="action-cell-${lit.id}" style="vertical-align: top;">${actionContent}</td>
                `;
                tbody.appendChild(mainTr);

                // 2. 生成紧跟在下方的隐藏 PDF 渲染行
                if (lit.pdf_path) {
                    const pdfTr = document.createElement('tr');
                    pdfTr.id = `pdf-row-${lit.id}`;
                    pdfTr.style.display = 'none'; // 初始隐藏
                    // 【修改为 colspan=6】因为加了 User Action 列，下面需要横跨 6 列
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

// 极客感拉满的“即选即传”无缝上传函数
window.autoUploadPDF = function(paperId, inputElement) {
    const file = inputElement.files[0];
    if (!file) return;

    // 获取到包裹着 input 的按钮(label)，将它的文字变为 Loading 状态
    const label = inputElement.parentElement;
    const originalHtml = label.innerHTML;
    label.innerHTML = '⏳ Uploading...';
    label.style.pointerEvents = 'none'; // 防止用户连续狂点

    const formData = new FormData();
    formData.append("paper_id", paperId);
    formData.append("file", file);

    fetch(`${API_BASE_URL}/api/upload-pdf`, {
        method: "POST",
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            // 上传成功后，不再弹窗打断用户，直接丝滑刷新表格！
            loadFullTextScreening();
        } else {
            alert(data.message);
            label.innerHTML = originalHtml;
            label.style.pointerEvents = 'auto';
        }
    })
    .catch(err => {
        console.error(err);
        alert("Upload failed. Please check network.");
        label.innerHTML = originalHtml;
        label.style.pointerEvents = 'auto';
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
                const response = await fetch(`${API_BASE_URL}/api/run-fulltext-ai`, {
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

        // 懒加载：只有第一次点击才生成 iframe 获取文件
        if (!pdfContainer.innerHTML.trim()) {
            pdfContainer.innerHTML = `<iframe src="${API_BASE_URL}/api/view-pdf?path=${safePath}" style="width: 100%; height: 800px; border: none; display: block;"></iframe>`;
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
if(document.getElementById('closeAbstractBtn')) {
    // 删掉了绑定 closeAbstractModal 的那行
    document.getElementById('closeAbstractBtn').addEventListener('click', closeAbstractModalFunc);
}

// 点击遮罩层关闭摘要弹窗
abstractModal.addEventListener('click', function(e) {
    if (e.target === abstractModal) closeAbstractModalFunc();
});

// ==========================================
// Data Extraction 专属逻辑
// ==========================================



// ====== 新增：处理 Abstract Screening 一键智能切换按钮逻辑 ======
window.toggleUserDecision = async function(btn, litId, currentAction, aiDecision) {
    let nextAction = 'Keep';

    // 智能推断下一个状态：如果是Keep，则切换为与AI相反的操作；如果是其他，则切回Keep
    if (currentAction === 'Keep' || !currentAction) {
        nextAction = (aiDecision === 'Included') ? 'Exclude' : 'Include';
    } else {
        nextAction = 'Keep';
    }

    // 提前在前端计算出 Apple 风格的外观并瞬间更新（极其丝滑）
    let btnText = 'Keep AI';
    let btnBg = '#f2f2f7';
    let btnColor = '#1d1d1f';

    if (nextAction === 'Include') {
        btnText = 'Included';
        btnBg = '#34c759';
        btnColor = '#ffffff';
    } else if (nextAction === 'Exclude') {
        btnText = 'Excluded';
        btnBg = '#ff3b30';
        btnColor = '#ffffff';
    }

    // 更新按钮 UI 和 点击事件里的参数
    btn.textContent = btnText;
    btn.style.backgroundColor = btnBg;
    btn.style.color = btnColor;
    // 添加一点点击的微动效反馈
    btn.style.transform = 'scale(0.92)';
    setTimeout(() => { btn.style.transform = 'scale(1)'; }, 150);

    btn.setAttribute('onclick', `toggleUserDecision(this, ${litId}, '${nextAction}', '${aiDecision}')`);

    // 后台静默发送请求保存结果
    try {
        await fetch(`${API_BASE_URL}/api/update-literature-decision`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                literature_id: litId,
                user_decision: nextAction
            })
        });
    } catch (error) {
        console.error('Failed to update decision:', error);
        alert("Network error, decision might not be saved!");
    }
};

// ====== 新增：Apple 风格“新建项目”弹窗交互逻辑 ======
const createProjectModal = document.getElementById('createProjectModal');
const newProjectNameInput = document.getElementById('newProjectNameInput');

window.openCreateProjectModal = function() {
    newProjectNameInput.value = ''; // 每次打开清空上一次的输入
    createProjectModal.style.display = 'flex';
    newProjectNameInput.focus(); // 自动聚焦输入框，方便用户直接打字
};

function closeCreateProjectModal() {
    createProjectModal.style.display = 'none';
}

document.getElementById('cancelCreateProjectBtn')?.addEventListener('click', closeCreateProjectModal);

document.getElementById('confirmCreateProjectBtn')?.addEventListener('click', () => {
    const projectName = newProjectNameInput.value.trim();
    if (projectName) {
        createNewProject(projectName);
        closeCreateProjectModal();
    } else {
        alert('Project name cannot be empty!');
    }
});

// 贴心小细节：允许用户打完字后直接按回车键 (Enter) 确认创建
newProjectNameInput?.addEventListener('keypress', function (e) {
    if (e.key === 'Enter') {
        document.getElementById('confirmCreateProjectBtn').click();
    }
});

// 点击弹窗外的暗色遮罩层也可以关闭弹窗
createProjectModal?.addEventListener('click', function(e) {
    if (e.target === createProjectModal) closeCreateProjectModal();
});

// ====== 新增：处理 Full-Text Screening 一键智能切换按钮逻辑 ======
window.toggleFullTextUserDecision = async function(btn, litId, currentAction, aiDecision) {
    let nextAction = 'Keep';

    // 智能推断下一个状态
    if (currentAction === 'Keep' || !currentAction) {
        nextAction = (aiDecision === 'Included') ? 'Exclude' : 'Include';
    } else {
        nextAction = 'Keep';
    }

    let btnText = 'Keep AI';
    let btnBg = '#f2f2f7';
    let btnColor = '#1d1d1f';

    if (nextAction === 'Include') {
        btnText = 'Included';
        btnBg = '#34c759';
        btnColor = '#ffffff';
    } else if (nextAction === 'Exclude') {
        btnText = 'Excluded';
        btnBg = '#ff3b30';
        btnColor = '#ffffff';
    }

    // 瞬间更新UI
    btn.textContent = btnText;
    btn.style.backgroundColor = btnBg;
    btn.style.color = btnColor;
    btn.style.transform = 'scale(0.92)';
    setTimeout(() => { btn.style.transform = 'scale(1)'; }, 150);

    btn.setAttribute('onclick', `toggleFullTextUserDecision(this, ${litId}, '${nextAction}', '${aiDecision}')`);

    // 后台静默发送请求保存结果到新的全文字段
    try {
        await fetch(`${API_BASE_URL}/api/update-literature-decision`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                literature_id: litId,
                full_text_user_decision: nextAction
            })
        });
    } catch (error) {
        console.error('Failed to update full-text decision:', error);
    }
};

// ==========================================
// Data Extraction 专属逻辑 (极致苹果风重构版)
// ==========================================

// 1. 进入页面时，自动加载要提取的文献数量并渲染列表
window.loadDataExtraction = async function() {
    if (!currentProject || !currentProject.id) return;

    try {
        const response = await fetch(`${API_BASE_URL}/api/get-literatures`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: currentProject.id })
        });
        const result = await response.json();

        if (result.success) {
            // 筛选最终纳入的文献
            const finalPapers = result.data.filter(lit => {
                return lit.full_text_user_decision === 'Include' ||
                       ((!lit.full_text_user_decision || lit.full_text_user_decision === 'Keep') && lit.full_text_decision === 'Included');
            });

            document.getElementById('extract-paper-count').textContent = finalPapers.length;

            // 动态渲染苹果风的待提取列表
            const listContainer = document.getElementById('extraction-paper-list');
            if(listContainer) {
                listContainer.innerHTML = '';
                
                if (finalPapers.length === 0) {
                    listContainer.innerHTML = `<li style="padding: 24px; text-align: center; color: #86868b; font-size: 14px;">No papers included for extraction.</li>`;
                } else {
                    finalPapers.forEach((p, index) => {
                        const li = document.createElement('li');
                        li.style.cssText = `
                            padding: 12px 16px;
                            border-bottom: ${index === finalPapers.length - 1 ? 'none' : '1px solid rgba(0,0,0,0.04)'};
                            display: flex;
                            align-items: center;
                            gap: 12px;
                            background: ${index % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.4)'};
                            border-radius: 8px;
                            margin-bottom: 2px;
                            transition: background-color 0.2s;
                        `;
                        li.onmouseover = () => li.style.backgroundColor = 'rgba(0, 113, 227, 0.05)';
                        li.onmouseout = () => li.style.backgroundColor = index % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.4)';
                        
                        li.innerHTML = `
                            <span style="font-size: 18px;">📄</span>
                            <span style="font-size: 14px; color: #1d1d1f; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1;" title="${p.title}">${p.title}</span>
                            <span style="font-size: 12px; color: #86868b; background: rgba(0,0,0,0.05); padding: 2px 8px; border-radius: 10px;">ID: ${p.id}</span>
                        `;
                        listContainer.appendChild(li);
                    });
                }
            }

            const btn = document.getElementById('start-extraction-btn');
            if(btn) {
                if (finalPapers.length === 0) {
                    btn.disabled = true;
                    btn.innerHTML = 'No Papers Ready';
                    btn.style.backgroundColor = '#a1a1a6';
                    btn.style.boxShadow = 'none';
                } else {
                    btn.disabled = false;
                    btn.innerHTML = '✨ Start AI Data Extraction';
                    btn.style.backgroundColor = '#0071e3';
                    btn.style.boxShadow = '0 8px 24px rgba(0,113,227,0.25)';
                }
            }

            const loadingArea = document.getElementById('extraction-loading-area');
            const iconContainer = document.getElementById('extraction-icon-container');
            if(loadingArea) loadingArea.style.display = 'none';
            if(iconContainer) {
                iconContainer.textContent = '📑';
                iconContainer.style.animation = 'none';
            }
        }
    } catch (e) {
        console.error("Failed to load extraction stats:", e);
    }
};

// 2. 状态检查核心逻辑
async function checkExtractionStatus() {
    if (!currentProject) return;
    try {
        const response = await fetch(`${API_BASE_URL}/api/get-extraction-preview?project_id=${currentProject.id}`);
        const result = await response.json();

        const unstartedView = document.getElementById('extraction-unstarted-view');
        const completedView = document.getElementById('extraction-completed-view');

        if (result.success && result.data && result.data.length > 0) {
            if(unstartedView) unstartedView.style.display = 'none';
            if(completedView) completedView.style.display = 'block';
            renderExtractionTable(result.columns, result.data);
        } else {
            if(unstartedView) unstartedView.style.display = 'block';
            if(completedView) completedView.style.display = 'none';
        }
    } catch (error) {
        console.error("Failed to fetch extraction preview:", error);
    }
}

// 3. 苹果风表格渲染
function renderExtractionTable(columns, data) {
    const thead = document.getElementById('extraction-table-head');
    const tbody = document.getElementById('extraction-table-body');
    if(!thead || !tbody) return;
    thead.innerHTML = ''; tbody.innerHTML = '';

    columns.forEach(col => {
        const th = document.createElement('th');
        th.textContent = col;
        th.style.padding = '14px 20px';
        th.style.borderBottom = '1px solid rgba(0,0,0,0.1)';
        th.style.fontWeight = '600';
        th.style.color = '#1d1d1f';
        th.style.letterSpacing = '0.3px';
        thead.appendChild(th);
    });

    data.forEach(row => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #f2f2f7';
        tr.style.transition = 'background-color 0.2s ease';
        tr.addEventListener('mouseover', () => tr.style.backgroundColor = '#f9f9fb');
        tr.addEventListener('mouseout', () => tr.style.backgroundColor = 'transparent');

        columns.forEach(col => {
            const td = document.createElement('td');
            td.style.padding = '14px 20px';
            td.style.maxWidth = '240px'; 
            td.style.overflow = 'hidden';
            td.style.textOverflow = 'ellipsis';
            td.style.whiteSpace = 'nowrap';
            td.style.color = '#3a3a3c';

            const val = row[col];
            if (typeof val === 'string' && val.trim().startsWith('{')) {
                try {
                    const parsed = JSON.parse(val);
                    td.textContent = parsed.value || val; 
                    td.title = parsed.evidence ? `Evidence: ${parsed.evidence}` : val;
                } catch(e) {
                    td.textContent = val; td.title = val;
                }
            } else {
                td.textContent = val; td.title = val;
            }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

// 4. 绑定提取按钮事件
document.getElementById('start-extraction-btn')?.addEventListener('click', async () => {
    if(!currentProject) return;
    const btn = document.getElementById('start-extraction-btn');
    const loadingArea = document.getElementById('extraction-loading-area');
    const iconContainer = document.getElementById('extraction-icon-container');
    
    if(btn) {
        btn.disabled = true;
        btn.textContent = 'Extracting...';
        btn.style.backgroundColor = '#a1a1a6';
        btn.style.boxShadow = 'none';
    }
    
    if(loadingArea) loadingArea.style.display = 'block';
    if(iconContainer) {
        iconContainer.textContent = '⚙️';
        iconContainer.style.animation = 'spin 2s linear infinite';
    }

    try {
        const response = await fetch(`${API_BASE_URL}/api/run-data-extraction`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ project_id: currentProject.id })
        });
        const result = await response.json();
        if(result.success) {
            checkExtractionStatus(); 
        } else {
            alert('Error: ' + result.message);
        }
    } catch(e) {
        alert('Network request failed.');
    } finally {
        if(btn) {
            btn.disabled = false;
            btn.textContent = '✨ Start AI Data Extraction';
            btn.style.backgroundColor = '#0071e3';
            btn.style.boxShadow = '0 8px 24px rgba(0,113,227,0.25)';
        }
        if(loadingArea) loadingArea.style.display = 'none';
        if(iconContainer) {
            iconContainer.textContent = '📑';
            iconContainer.style.animation = 'none';
        }
    }
});

// 5. 极其优雅的无跳转下载逻辑 (Fetch + Blob)
async function handleDownload(type) {
    if (!currentProject) return;
    const btn = document.getElementById(`download-${type}-btn`);
    if(!btn) return;
    const originalText = btn.textContent;
    btn.textContent = 'Downloading...';
    btn.disabled = true;

    try {
        const response = await fetch(`${API_BASE_URL}/api/download-extraction?project_id=${currentProject.id}&type=${type}`);
        if (response.ok) {
            const blob = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = downloadUrl;
            a.download = `Project_${currentProject.id}_Extraction.${type}`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(downloadUrl);
            document.body.removeChild(a);
        } else {
            const errorText = await response.text();
            alert(`Download Failed: ${errorText}`);
        }
    } catch (error) {
        console.error('Download error:', error);
        alert('Network error occurred while trying to download.');
    } finally {
        btn.textContent = originalText;
        btn.disabled = false;
    }
}

document.getElementById('download-csv-btn')?.addEventListener('click', () => handleDownload('csv'));
document.getElementById('download-xlsx-btn')?.addEventListener('click', () => handleDownload('xlsx'));

document.getElementById('re-run-extraction-btn')?.addEventListener('click', () => {
    if(confirm('Are you sure you want to re-run? This will overwrite existing results.')) {
        const completedView = document.getElementById('extraction-completed-view');
        const unstartedView = document.getElementById('extraction-unstarted-view');
        if(completedView) completedView.style.display = 'none';
        if(unstartedView) unstartedView.style.display = 'block';
        
        const thead = document.getElementById('extraction-table-head');
        const tbody = document.getElementById('extraction-table-body');
        if(thead) thead.innerHTML = '';
        if(tbody) tbody.innerHTML = '';
        
        document.getElementById('start-extraction-btn')?.click();
    }
});

// ==========================================
// 🌟 Profile 页面：视图切换与密码修改逻辑 (安全升级版)
// ==========================================

// 🛡️ 每次打开 Profile 页面时，强制重置状态并清空残影
function openProfilePage() {
    showPage('profile-page'); // 切换页面
    document.getElementById('profile-menu-view').style.display = 'block'; // 强制显示主菜单
    document.getElementById('profile-password-view').style.display = 'none'; // 强制隐藏修改密码视图
    
    // 彻底清空所有密码输入框，杜绝隐私泄漏
    document.getElementById('current-password-input').value = '';
    document.getElementById('new-password-input').value = '';
    document.getElementById('confirm-password-input').value = '';
}

// 切换 iOS 菜单和密码表单视图
function toggleProfileView(view) {
    const menuView = document.getElementById('profile-menu-view');
    const pwdView = document.getElementById('profile-password-view');
    
    // 无论进出，只要触发切换就清空输入框
    document.getElementById('current-password-input').value = '';
    document.getElementById('new-password-input').value = '';
    document.getElementById('confirm-password-input').value = '';

    if (view === 'password') {
        menuView.style.display = 'none';
        pwdView.style.display = 'block';
    } else {
        pwdView.style.display = 'none';
        menuView.style.display = 'block';
    }
}

// 真正向后端发起修改请求
async function submitPasswordChange() {
    const currentPwd = document.getElementById('current-password-input').value;
    const newPwd = document.getElementById('new-password-input').value;
    const confirmPwd = document.getElementById('confirm-password-input').value;

    if (!currentPwd || !newPwd || !confirmPwd) {
        alert("Please fill in all password fields."); return;
    }
    if (newPwd !== confirmPwd) {
        alert("New password and confirmation do not match."); return;
    }
    // 🛡️ 新增拦截：新旧密码不能相同
    if (currentPwd === newPwd) {
        alert("New password cannot be the same as the current password."); 
        document.getElementById('new-password-input').value = '';
        document.getElementById('confirm-password-input').value = '';
        return;
    }
    if (!currentUser || !currentUser.id) {
        alert("Error: User session lost. Please log in again."); return;
    }

    const btn = document.getElementById('update-password-btn');
    const originalText = btn.textContent;
    btn.textContent = "Updating...";
    btn.disabled = true;

    try {
        const response = await fetch(`${API_BASE_URL}/api/change-password`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: currentUser.id,
                current_password: currentPwd,
                new_password: newPwd
            })
        });

        const result = await response.json();

        if (result.success) {
            alert("Password updated successfully! Please log in again with your new password.");
            document.getElementById('logout-btn').click(); // 修改成功后强制登出
        } else {
            alert(`Failed: ${result.message}`); // 后端返回密码错误等提示
        }
    } catch (error) {
        console.error("Change password error:", error);
        alert("A network error occurred.");
    } finally {
        btn.textContent = originalText;
        btn.disabled = false;
    }
}

// ====== 新增：数据库胶囊按钮的点击切换逻辑 ======
document.addEventListener('DOMContentLoaded', () => {
    const chips = document.querySelectorAll('.db-chip');
    chips.forEach(chip => {
        chip.addEventListener('click', () => {
            chip.classList.toggle('active');
            // 🛡️ 防呆设计：保证至少有一个数据库被选中
            const activeChips = document.querySelectorAll('.db-chip.active');
            if (activeChips.length === 0) {
                chip.classList.add('active'); // 强制恢复选中
                alert('You must select at least one database source.');
            }
        });
    });
});