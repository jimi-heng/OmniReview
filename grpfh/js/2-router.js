// ====== 处理 Apple 风格登录页入场动画逻辑 ======
function playLoginEntranceAnimation() {
    const navbar = document.querySelector('.navbar');
    if (navbar) navbar.style.display = 'none';

    document.getElementById('login-title')?.classList.add('animate-item');
    document.getElementById('login-subtitle')?.classList.add('animate-item');
    document.getElementById('feature-1')?.classList.add('animate-item');
    document.getElementById('feature-2')?.classList.add('animate-item');
    document.getElementById('feature-3')?.classList.add('animate-item');
    document.getElementById('login-card')?.classList.add('animate-item');

    void document.body.offsetWidth;

    document.getElementById('login-title')?.classList.add('play-animation');
    document.getElementById('login-subtitle')?.classList.add('play-animation');
    document.getElementById('feature-1')?.classList.add('play-animation');
    document.getElementById('feature-2')?.classList.add('play-animation');
    document.getElementById('feature-3')?.classList.add('play-animation');
    document.getElementById('login-card')?.classList.add('play-animation');
}

// 更新顶部进度导航激活状态
function updateProgressStep(activeStepId) {
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

// 通用页面切换函数（所有按钮跳转核心）
function showPage(pageId) {
    // 🌟 核心修复：每次切换页面时瞬间回到顶部，彻底解决底部白屏渲染 Bug！
    window.scrollTo(0, 0);
    
    if (pageId === 'home-page' && currentUser && currentUser.email === 'admin@neural.net') {
        pageId = 'admin-dashboard-page';
        const navBar = document.querySelector('.progress-header');
        if (navBar) navBar.style.display = 'none';
        loadAdminStats(); 
    }
    if (pageId === 'home-page') {
        const navPico = document.getElementById('step-pico');
        if (navPico) navPico.textContent = '2. Criteria Setup';
    }

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

    let isForward = true;
    if (pageLevel[pageId] !== undefined && pageLevel[activePageId] !== undefined) {
        isForward = pageLevel[pageId] >= pageLevel[activePageId];
    }
    if (pageId === 'home-page') isForward = false;

    const allPages = ['login-page', 'register-page', 'home-page', 'admin-dashboard-page', 'profile-page', 'pico-page', 'import-search-page', 'abstract-screen-page', 'full-text-screen-page', 'data-extraction-page'];
    allPages.forEach(id => {
        const el = document.getElementById(id);
        if (el && id !== pageId) {
            el.style.display = 'none';
            el.classList.remove('ios-slide-in-forward', 'ios-slide-in-backward');
        }
    });
    
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
            if (activePageId !== 'login-page' && activePageId !== 'register-page') {
                targetEl.classList.remove('ios-slide-in-forward', 'ios-slide-in-backward');
                void targetEl.offsetWidth;
                targetEl.classList.add(isForward ? 'ios-slide-in-forward' : 'ios-slide-in-backward');
            }
        }
        const megaWrapper = document.getElementById('auth-mega-wrapper');
        if (megaWrapper) megaWrapper.style.display = 'none';
        document.body.classList.remove('hide-nav');
    }

    activePageId = pageId;

    const loginBg = document.querySelector('.login-background');
    if (loginBg) {
        loginBg.style.display = (pageId === 'login-page' || pageId === 'register-page') ? 'block' : 'none';
    }

    if (pageId === 'data-extraction-page' && currentProject) {
        checkExtractionStatus();
    }
    
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

// 昼夜主题切换核心逻辑
document.addEventListener('DOMContentLoaded', () => {
    const themeBtn = document.getElementById('theme-toggle-btn');
    const themeIcon = document.getElementById('theme-icon');
    
    if (document.body.classList.contains('dark-theme')) {
        themeIcon.textContent = '☀️';
    } else {
        themeIcon.textContent = '🌙';
    }

    themeBtn.addEventListener('click', () => {
        document.body.classList.toggle('dark-theme');
        const isDark = document.body.classList.contains('dark-theme');
        
        if (isDark) {
            themeIcon.textContent = '☀️';
            localStorage.setItem('app-theme', 'dark');
        } else {
            themeIcon.textContent = '🌙';
            localStorage.setItem('app-theme', 'light');
        }
    });
});

// 统一清空输入框
function clearAllInputs() {
    const textInputs = [
        'spico-s', 'spico-p', 'spico-i', 'spico-c', 'spico-o',
        'peco-p', 'peco-e', 'peco-c', 'peco-o',
        'piro-p', 'piro-i', 'piro-r', 'piro-o',
        'additional-criteria', 'search-keywords'
    ];
    textInputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    const maxPapers = document.getElementById('max-papers');
    if (maxPapers) maxPapers.value = 200;
    const fileUpload = document.getElementById('file-upload');
    if (fileUpload) fileUpload.value = '';
}