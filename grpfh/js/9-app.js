function addNavigationListeners() {
    const importBtn = document.getElementById('import-papers-btn');
    if (importBtn) {
        importBtn.onclick = async () => {
            await savePicoData(); await saveProtocolData(); await updateProjectStatus('Import/Search'); showPage('import-search-page');
        };
    }
    const proceedBtn = document.getElementById('proceed-to-abstract-btn');
    if (proceedBtn) {
        proceedBtn.onclick = async () => {
            await saveSearchData(); await updateProjectStatus('Abstract Screening'); showPage('abstract-screen-page');
        };
    }
    const abstractProceedBtn = document.getElementById('proceed-to-data-btn');
    if (abstractProceedBtn) {
        abstractProceedBtn.onclick = async () => {
            await updateProjectStatus('Full-Text Screening'); showPage('full-text-screen-page'); 
        };
    }
    const fulltextProceedBtn = document.getElementById('proceed-to-data-from-fulltext-btn');
    if (fulltextProceedBtn) {
        fulltextProceedBtn.onclick = async () => {
            await updateProjectStatus('Data Extraction'); showPage('data-extraction-page');
        };
    }
}

// ========== 整个应用的启动与初始化中心 ==========
document.addEventListener('DOMContentLoaded', () => {
  addNavigationListeners();

  const savedUser = sessionStorage.getItem('currentUser');
  if (savedUser) {
    currentUser = JSON.parse(savedUser);
    
    const emailDisplays = [document.getElementById('profile-email-display'), document.getElementById('tooltip-email')];
    emailDisplays.forEach(el => { if (el) el.textContent = currentUser.email; });
    const timeDisplay = document.getElementById('tooltip-time');
    if (timeDisplay && currentUser.loginTime) timeDisplay.textContent = `Logged in: ${currentUser.loginTime}`;

    if (currentUser.email === 'admin@neural.net') {
        showPage('admin-dashboard-page');
        const navBar = document.querySelector('.progress-header');
        if (navBar) navBar.style.display = 'none';
        loadAdminStats(); 
    } else {
        showPage('home-page');
        const navBar = document.querySelector('.progress-header');
        if (navBar) navBar.style.display = 'flex';
        loadUserProjects();
    }
  } else {
    const navBar = document.querySelector('.progress-header');
    if (navBar) navBar.style.display = 'flex'; 
    showPage('login-page');
    playLoginEntranceAnimation();
  }

  // 挂载重写原始的 showPage 加载对应页面数据的能力
  const originalShowPage = window.showPage;
  window.showPage = function(pageId) {
    originalShowPage(pageId);
    if (pageId === 'import-search-page') setTimeout(loadLiteratureList, 100);
    else if (pageId === 'abstract-screen-page') setTimeout(loadAbstractScreening, 100);
    else if (pageId === 'data-extraction-page') setTimeout(window.loadDataExtraction, 100);
  };

  // 绑定：文献上传监听
  const uploadBtn = document.getElementById('upload-btn');
  if (uploadBtn) { /* 逻辑已在 literature.js 内部消化或被拆分，为了简洁这里不重复绑定 */ }

  // 绑定：修改/编辑推理 Modal
  document.getElementById('cancelEdit')?.addEventListener('click', closeReasonModal);
  document.getElementById('reasonModal')?.addEventListener('click', function(e) { if (e.target === this) closeReasonModal(); });
  document.getElementById('closeAbstractBtn')?.addEventListener('click', window.closeAbstractModalFunc);

  // 绑定：Create Project Modal 取消功能
  document.getElementById('cancelCreateProjectBtn')?.addEventListener('click', window.closeCreateProjectModal);
  document.getElementById('createProjectModal')?.addEventListener('click', function(e) { if (e.target === this) window.closeCreateProjectModal(); });
  document.getElementById('newProjectNameInput')?.addEventListener('keypress', function (e) { if (e.key === 'Enter') document.getElementById('confirmCreateProjectBtn').click(); });

  // 👇 ================= 把下面这段补在这里 ================= 👇
  // 绑定：确认创建项目按钮
  document.getElementById('confirmCreateProjectBtn')?.addEventListener('click', () => {
      const inputEl = document.getElementById('newProjectNameInput');
      const projectName = inputEl ? inputEl.value.trim() : '';
      if (projectName) {
          createNewProject(projectName);
          window.closeCreateProjectModal();
      } else {
          alert('Project name cannot be empty!');
      }
  });

  // 绑定：下载按钮等
  document.getElementById('download-csv-btn')?.addEventListener('click', () => handleDownload('csv'));
  document.getElementById('download-xlsx-btn')?.addEventListener('click', () => handleDownload('xlsx'));
  document.getElementById('re-run-extraction-btn')?.addEventListener('click', () => {
      if(confirm('Are you sure you want to re-run? This will overwrite existing results.')) {
          const completedView = document.getElementById('extraction-completed-view');
          const unstartedView = document.getElementById('extraction-unstarted-view');
          if(completedView) completedView.style.display = 'none';
          if(unstartedView) unstartedView.style.display = 'block';
          document.getElementById('extraction-table-head').innerHTML = '';
          document.getElementById('extraction-table-body').innerHTML = '';
          document.getElementById('start-extraction-btn')?.click();
      }
  });

  // 绑定：胶囊按钮行为
  document.querySelectorAll('.db-chip').forEach(chip => {
      chip.addEventListener('click', () => {
          chip.classList.toggle('active');
          if (document.querySelectorAll('.db-chip.active').length === 0) {
              chip.classList.add('active'); 
              alert('You must select at least one database source.');
          }
      });
  });

  // PubMed, Export, AI 触发的监听器等... 
  // (因为代码块已经将按钮 ID 和业务拆分得很好，我们将其保持在相应 JS 的顶层或在这执行挂载)
  // 具体参考 Screening 与 Literature 内直接查找 btnById 并 addEventListener 的片段。
});