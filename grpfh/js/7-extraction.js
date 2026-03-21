function switchDataTab(type) {
    const tabs = document.querySelectorAll('.tabs')[1].querySelectorAll('.tab');
    tabs.forEach(tab => tab.classList.remove('active'));
    ['outcome-section', 'characteristics-section', 'pico-evidence-section'].forEach(id => {
        document.getElementById(id).style.display = 'none';
    });
    if (type === 'outcome') { tabs[0].classList.add('active'); document.getElementById('outcome-section').style.display = 'block'; } 
    else if (type === 'characteristics') { tabs[1].classList.add('active'); document.getElementById('characteristics-section').style.display = 'block'; } 
    else if (type === 'pico') { tabs[2].classList.add('active'); document.getElementById('pico-evidence-section').style.display = 'block'; }
}

window.loadDataExtraction = async function() {
    if (!currentProject || !currentProject.id) return;
    try {
        const response = await fetch(`${API_BASE_URL}/api/get-literatures`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: currentProject.id, user_id: currentUser.id })
        });
        const result = await response.json();

        if (result.success) {
            const finalPapers = result.data.filter(lit => lit.full_text_user_decision === 'Include' || ((!lit.full_text_user_decision || lit.full_text_user_decision === 'Keep') && lit.full_text_decision === 'Included'));
            document.getElementById('extract-paper-count').textContent = finalPapers.length;

            const listContainer = document.getElementById('extraction-paper-list');
            if(listContainer) {
                listContainer.innerHTML = '';
                if (finalPapers.length === 0) listContainer.innerHTML = `<li style="padding: 24px; text-align: center; color: #86868b; font-size: 14px;">No papers included for extraction.</li>`;
                else {
                    finalPapers.forEach((p, index) => {
                        const li = document.createElement('li');
                        li.style.cssText = `padding: 12px 16px; border-bottom: ${index === finalPapers.length - 1 ? 'none' : '1px solid rgba(0,0,0,0.04)'}; display: flex; align-items: center; gap: 12px; background: ${index % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.4)'}; border-radius: 8px; margin-bottom: 2px; transition: background-color 0.2s;`;
                        li.onmouseover = () => li.style.backgroundColor = 'rgba(0, 113, 227, 0.05)'; li.onmouseout = () => li.style.backgroundColor = index % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.4)';
                        li.innerHTML = `<span style="font-size: 18px;">📄</span><span style="font-size: 14px; color: #1d1d1f; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1;" title="${p.title}">${p.title}</span><span style="font-size: 12px; color: #86868b; background: rgba(0,0,0,0.05); padding: 2px 8px; border-radius: 10px;">ID: ${p.id}</span>`;
                        listContainer.appendChild(li);
                    });
                }
            }

            const btn = document.getElementById('start-extraction-btn');
            if(btn) {
                if (finalPapers.length === 0) { btn.disabled = true; btn.innerHTML = 'No Papers Ready'; btn.style.backgroundColor = '#a1a1a6'; } 
                else { btn.disabled = false; btn.innerHTML = '✨ Start AI Data Extraction'; btn.style.backgroundColor = '#0071e3'; }
            }

            const loadingArea = document.getElementById('extraction-loading-area');
            const iconContainer = document.getElementById('extraction-icon-container');
            if(loadingArea) loadingArea.style.display = 'none';
            if(iconContainer) { iconContainer.textContent = '📑'; iconContainer.style.animation = 'none'; }
        }
    } catch (e) {}
};

async function checkExtractionStatus() {
    if (!currentProject) return;
    try {
        const response = await fetch(`${API_BASE_URL}/api/get-extraction-preview?project_id=${currentProject.id}&user_id=${currentUser.id}`);
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
    } catch (error) {}
}

function renderExtractionTable(columns, data) {
    const thead = document.getElementById('extraction-table-head');
    const tbody = document.getElementById('extraction-table-body');
    if(!thead || !tbody) return;
    thead.innerHTML = ''; tbody.innerHTML = '';

    columns.forEach(col => {
        const th = document.createElement('th'); th.textContent = col; th.style.padding = '14px 20px'; th.style.borderBottom = '1px solid rgba(0,0,0,0.1)'; th.style.fontWeight = '600'; th.style.color = '#1d1d1f';
        thead.appendChild(th);
    });

    data.forEach(row => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #f2f2f7';
        tr.addEventListener('mouseover', () => tr.style.backgroundColor = '#f9f9fb');
        tr.addEventListener('mouseout', () => tr.style.backgroundColor = 'transparent');

        columns.forEach(col => {
            const td = document.createElement('td');
            td.style.padding = '14px 20px'; td.style.maxWidth = '240px'; td.style.overflow = 'hidden'; td.style.textOverflow = 'ellipsis'; td.style.whiteSpace = 'nowrap'; td.style.color = '#3a3a3c';

            const val = row[col];
            if (typeof val === 'string' && val.trim().startsWith('{')) {
                try { const parsed = JSON.parse(val); td.textContent = parsed.value || val; td.title = parsed.evidence ? `Evidence: ${parsed.evidence}` : val; } 
                catch(e) { td.textContent = val; td.title = val; }
            } else { td.textContent = val; td.title = val; }
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

async function handleDownload(type) {
    if (!currentProject) return;
    const btn = document.getElementById(`download-${type}-btn`); if(!btn) return;
    const originalText = btn.textContent; btn.textContent = 'Downloading...'; btn.disabled = true;

    try {
        const response = await fetch(`${API_BASE_URL}/api/download-extraction?project_id=${currentProject.id}&user_id=${currentUser.id}&type=${type}`);
        if (response.ok) {
            const blob = await response.blob(); const downloadUrl = window.URL.createObjectURL(blob);
            const a = document.createElement('a'); a.style.display = 'none'; a.href = downloadUrl; a.download = `Project_${currentProject.id}_Extraction.${type}`;
            document.body.appendChild(a); a.click(); window.URL.revokeObjectURL(downloadUrl); document.body.removeChild(a);
        } else { alert(`Download Failed: ${await response.text()}`); }
    } catch (error) { alert('Network error occurred while trying to download.'); } 
    finally { btn.textContent = originalText; btn.disabled = false; }
}

// ====== 绑定：最终的数据提取执行按钮 ======
document.addEventListener('DOMContentLoaded', () => {
    // Start Extraction 按钮
    const startExtractBtn = document.getElementById('start-extraction-btn');
    if (startExtractBtn) {
        startExtractBtn.addEventListener('click', async () => {
            if(!currentProject) return;
            const btn = document.getElementById('start-extraction-btn');
            const loadingArea = document.getElementById('extraction-loading-area');
            const iconContainer = document.getElementById('extraction-icon-container');
            
            btn.disabled = true; btn.textContent = 'Extracting...'; btn.style.backgroundColor = '#a1a1a6';
            if(loadingArea) loadingArea.style.display = 'block';
            if(iconContainer) { iconContainer.textContent = '⚙️'; iconContainer.style.animation = 'spin 2s linear infinite'; }

            try {
                const response = await fetch(`${API_BASE_URL}/api/run-data-extraction`, {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ project_id: currentProject.id, user_id: currentUser.id })
                });
                const result = await response.json();
                if(result.success) { checkExtractionStatus(); } else { alert('Error: ' + result.message); }
            } catch(e) { alert('Network request failed.'); } 
            finally {
                btn.disabled = false; btn.textContent = '✨ Start AI Data Extraction'; btn.style.backgroundColor = '#0071e3';
                if(loadingArea) loadingArea.style.display = 'none';
                if(iconContainer) { iconContainer.textContent = '📑'; iconContainer.style.animation = 'none'; }
            }
        });
    }
});
