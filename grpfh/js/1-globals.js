// 全局变量：存储当前编辑的行数据（用于推理编辑）
let currentEditRow = null;
// 在文件开头添加全局变量
let currentUser = null; // 存储当前登录用户信息
let currentProject = null; // 存储当前正在进行的项目

// ====== 核心配置：自动环境识别 ======
// 如果当前网址是 localhost，就请求本地后端的 3000 端口；否则请求云服务器的后端
const API_BASE_URL = (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:3000'
    : '';

// ====== 记录页面层级，用于苹果风滑动动画 ======
let activePageId = 'login-page';
const pageLevel = {
    'home-page': 1,
    'admin-dashboard-page': 1, 
    'profile-page': 2,
    'pico-page': 2,
    'import-search-page': 3,
    'abstract-screen-page': 4,
    'full-text-screen-page': 5,
    'data-extraction-page': 6
};

let projectToDeleteId = null; // 临时存储要删除的项目 ID
let cachedAdminStatsData = null; // 全局缓存后端拉取的全量数据