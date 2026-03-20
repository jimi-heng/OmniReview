window.loadAbstractScreening = async function() {
    const screenTableBody = document.getElementById('screenTableBody');
    if (!screenTableBody || !currentProject || !currentProject.id) return;

    try {
        const response = await fetch(`${API_BASE_URL}/api/get-literatures`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: currentProject.id })
        });
        const result = await response.json();

        if (result.success && result.data.length > 0) {
            screenTableBody.innerHTML = '';
            result.data.forEach((lit, index) => {
                const displayId = index + 1; 
                let aiColor = '#6c757d'; 
                if (lit.ai_decision === 'Included') aiColor = '#34c759'; 
                else if (lit.ai_decision === 'Excluded') aiColor = '#ff3b30'; 
                else if (lit.ai_decision === 'Error') aiColor = '#ff9500'; 
                let shortReason = lit.reasoning && lit.reasoning.length > 80 ? lit.reasoning.substring(0, 80) + '...' : (lit.reasoning || 'No reasoning provided yet');

                const tr = document.createElement('tr');
                tr.setAttribute('data-id', lit.id);
                tr.setAttribute('data-reason', lit.reasoning || '');
                tr.setAttribute('data-abstract', lit.abstract || 'No abstract available.');

                let currentAction = lit.user_decision || 'Keep';
                let btnText = 'Keep AI'; let btnBg = '#f2f2f7'; let btnColor = '#1d1d1f';

                if (currentAction === 'Include') { btnText = 'Included'; btnBg = '#34c759'; btnColor = '#ffffff'; } 
                else if (currentAction === 'Exclude') { btnText = 'Excluded'; btnBg = '#ff3b30'; btnColor = '#ffffff'; }

                tr.innerHTML = `
                    <td>${displayId}</td>
                    <td>${lit.title}</td>
                    <td style="color: ${aiColor}; font-weight: 600;">${lit.ai_decision}</td>
                    <td>
                        <button class="btn" style="font-size: 12px; padding: 6px 14px; border-radius: 14px; font-weight: 600; border: none; transition: all 0.2s cubic-bezier(0.25, 0.8, 0.25, 1); background-color: ${btnBg}; color: ${btnColor}; box-shadow: 0 2px 6px rgba(0,0,0,0.06);" 
                            onclick="toggleUserDecision(this, ${lit.id}, '${currentAction}', '${lit.ai_decision}')">
                            ${btnText}
                        </button>
                    </td>
                    <td class="reason-display" style="cursor: pointer; color: #555; text-decoration: none; transition: color 0.2s ease; line-height: 1.5;" onmouseover="this.style.color='#0071e3'" onmouseout="this.style.color='#555'" onclick="openEditModal(this)" title="Click to view/edit full reasoning">
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
    } catch (error) { console.error('Failed to load abstract screening data:', error); }
};

window.toggleUserDecision = async function(btn, litId, currentAction, aiDecision) {
    let nextAction = (currentAction === 'Keep' || !currentAction) ? ((aiDecision === 'Included') ? 'Exclude' : 'Include') : 'Keep';
    let btnText = 'Keep AI', btnBg = '#f2f2f7', btnColor = '#1d1d1f';
    if (nextAction === 'Include') { btnText = 'Included'; btnBg = '#34c759'; btnColor = '#ffffff'; } 
    else if (nextAction === 'Exclude') { btnText = 'Excluded'; btnBg = '#ff3b30'; btnColor = '#ffffff'; }

    btn.textContent = btnText; btn.style.backgroundColor = btnBg; btn.style.color = btnColor;
    btn.style.transform = 'scale(0.92)'; setTimeout(() => { btn.style.transform = 'scale(1)'; }, 150);
    btn.setAttribute('onclick', `toggleUserDecision(this, ${litId}, '${nextAction}', '${aiDecision}')`);

    try {
        await fetch(`${API_BASE_URL}/api/update-literature-decision`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ literature_id: litId, user_decision: nextAction })
        });
    } catch (error) { alert("Network error, decision might not be saved!"); }
};

window.openEditModal = function(btnElement) {
    currentEditRow = btnElement.closest('tr');
    const originalReason = currentEditRow.getAttribute('data-reason');
    document.getElementById('reasonText').value = originalReason;
    document.getElementById('reasonModal').style.display = 'flex';
};

function closeReasonModal() {
    document.getElementById('reasonModal').style.display = 'none';
    currentEditRow = null;
}

window.openAbstractModal = function(btnElement) {
    const row = btnElement.closest('tr');
    document.getElementById('abstractText').textContent = row.getAttribute('data-abstract');
    document.getElementById('abstractModal').style.display = 'flex';
};

window.closeAbstractModalFunc = function() {
    document.getElementById('abstractModal').style.display = 'none';
};

// Full text screening UI
window.loadFullTextScreening = async function() {
    const tbody = document.getElementById('fulltextTableBody');
    if (!tbody || !currentProject) return;

    try {
        const response = await fetch(`${API_BASE_URL}/api/get-literatures`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: currentProject.id })
        });
        const result = await response.json();

        if (result.success) {
            const includedPapers = result.data.filter(lit => lit.user_decision === 'Include' || ((!lit.user_decision || lit.user_decision === 'Keep') && lit.ai_decision === 'Included'));
            if (includedPapers.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" class="empty-data">No included papers found. Please review Abstract Screening first.</td></tr>`;
                return;
            }

            tbody.innerHTML = '';
            includedPapers.forEach((lit, index) => {
                let statusColor = '#86868b'; let displayStatus = lit.pdf_status || 'Pending';
                if (displayStatus === 'Downloaded') statusColor = '#34c759'; 
                else if (displayStatus.includes('Failed')) { statusColor = '#ff3b30'; displayStatus = displayStatus.replace(' (', '<br><span style="font-size: 11px; font-weight: normal; opacity: 0.8;">(') + '</span>'; }

                let evidenceText = 'Waiting for AI Analysis...';
                if (lit.pico_evidence && lit.pico_evidence !== '{}') {
                    try { evidenceText = `💡 <b>AI Conclusion:</b> ${JSON.parse(lit.pico_evidence).conclusion || 'Extracted'}`; } 
                    catch(e) { evidenceText = '✅ Extracted by AI'; }
                }

                let decisionColor = '#86868b';
                if (lit.full_text_decision === 'Included') decisionColor = '#34c759'; 
                else if (lit.full_text_decision === 'Excluded') decisionColor = '#ff3b30'; 
                else if (lit.full_text_decision === 'Error') decisionColor = '#ff9500';

                let actionContent = '';
                const rawStatus = lit.pdf_status || 'Pending';
                if (rawStatus === 'Downloaded' && lit.pdf_path) {
                    const safePath = encodeURIComponent(lit.pdf_path);
                    actionContent = `
                        <div style="display: flex; flex-direction: column; align-items: center; gap: 8px; position: sticky; top: 120px; z-index: 10;">
                            <button id="view-pdf-btn-${lit.id}" class="btn btn-primary" onclick="togglePdfView(${lit.id}, '${safePath}')" style="font-size: 13px; padding: 8px 20px; border-radius: 20px; border: none;">View PDF</button>
                            <label style="font-size: 11px; color: #86868b; text-align: center; cursor: pointer; margin: 0;"><input type="file" accept="application/pdf" style="display: none;" onchange="autoUploadPDF(${lit.id}, this)">Replace file</label>
                        </div>`;
                } else if (rawStatus.includes('Failed')) {
                    let searchUrl = lit.doi ? `https://doi.org/${lit.doi.replace('https://doi.org/', '').trim()}` : `https://scholar.google.com/scholar?q=${encodeURIComponent(lit.title)}`;
                    actionContent = `
                        <div style="display: flex; flex-direction: column; align-items: center; gap: 8px; position: sticky; top: 120px; z-index: 10;">
                            <label class="btn" style="font-size: 13px; padding: 8px 18px; border-radius: 20px; background-color: #ff3b30; color: white; border: none; cursor: pointer; margin: 0;"><input type="file" accept="application/pdf" style="display: none;" onchange="autoUploadPDF(${lit.id}, this)">⇧ Upload</label>
                            <a href="${searchUrl}" target="_blank" style="font-size: 11px; color: #0071e3; text-decoration: none; font-weight: 500;">Search Source ↗</a>
                        </div>`;
                } else {
                    actionContent = `<div style="display: flex; flex-direction: column; align-items: center; position: sticky; top: 120px; z-index: 10;"><button class="btn btn-secondary" disabled style="font-size: 13px; padding: 8px 20px; border-radius: 20px; border: none;">Waiting...</button></div>`;
                }

                let fullTextUserAction = lit.full_text_user_decision || 'Keep';
                let btnText = 'Keep AI', btnBg = '#f2f2f7', btnColor = '#1d1d1f';
                if (fullTextUserAction === 'Include') { btnText = 'Included'; btnBg = '#34c759'; btnColor = '#ffffff'; } 
                else if (fullTextUserAction === 'Exclude') { btnText = 'Excluded'; btnBg = '#ff3b30'; btnColor = '#ffffff'; }

                let userActionContent = `<button class="btn" style="font-size: 12px; padding: 6px 14px; border-radius: 14px; border: none; background-color: ${btnBg}; color: ${btnColor};" onclick="toggleFullTextUserDecision(this, ${lit.id}, '${fullTextUserAction}', '${lit.full_text_decision || 'Pending'}')">${btnText}</button>`;
                
                const mainTr = document.createElement('tr');
                mainTr.id = `main-row-${lit.id}`;
                mainTr.innerHTML = `<td>${index + 1}</td><td>${lit.title}</td><td style="color: ${statusColor}; font-weight: bold; font-size: 13px;">${displayStatus}</td><td style="color: ${decisionColor}; font-weight: bold;">${lit.full_text_decision || 'Pending'}</td><td>${userActionContent}</td><td style="font-size: 13px; color: #555;">${evidenceText}</td><td id="action-cell-${lit.id}" style="vertical-align: top;">${actionContent}</td>`;
                tbody.appendChild(mainTr);

                if (lit.pdf_path) {
                    const pdfTr = document.createElement('tr');
                    pdfTr.id = `pdf-row-${lit.id}`; pdfTr.style.display = 'none';
                    pdfTr.innerHTML = `<td colspan="6" style="padding: 0; border-bottom: 3px solid #17a2b8;"><div id="pdf-container-${lit.id}" style="width: 100%; background: #e9ecef; position: relative;"></div></td>`;
                    tbody.appendChild(pdfTr);
                }
            });
        }
    } catch (e) {}
};

window.toggleFullTextUserDecision = async function(btn, litId, currentAction, aiDecision) {
    let nextAction = (currentAction === 'Keep' || !currentAction) ? ((aiDecision === 'Included') ? 'Exclude' : 'Include') : 'Keep';
    let btnText = 'Keep AI', btnBg = '#f2f2f7', btnColor = '#1d1d1f';
    if (nextAction === 'Include') { btnText = 'Included'; btnBg = '#34c759'; btnColor = '#ffffff'; } 
    else if (nextAction === 'Exclude') { btnText = 'Excluded'; btnBg = '#ff3b30'; btnColor = '#ffffff'; }

    btn.textContent = btnText; btn.style.backgroundColor = btnBg; btn.style.color = btnColor;
    btn.setAttribute('onclick', `toggleFullTextUserDecision(this, ${litId}, '${nextAction}', '${aiDecision}')`);

    try {
        await fetch(`${API_BASE_URL}/api/update-literature-decision`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ literature_id: litId, full_text_user_decision: nextAction })
        });
    } catch (error) {}
};

window.autoUploadPDF = function(paperId, inputElement) {
    const file = inputElement.files[0]; if (!file) return;
    const label = inputElement.parentElement; const originalHtml = label.innerHTML;
    label.innerHTML = '⏳ Uploading...'; label.style.pointerEvents = 'none'; 
    const formData = new FormData(); formData.append("paper_id", paperId); formData.append("file", file);
    fetch(`${API_BASE_URL}/api/upload-pdf`, { method: "POST", body: formData }).then(res => res.json())
    .then(data => { if (data.success) loadFullTextScreening(); else { alert(data.message); label.innerHTML = originalHtml; label.style.pointerEvents = 'auto'; }})
    .catch(err => { alert("Upload failed."); label.innerHTML = originalHtml; label.style.pointerEvents = 'auto'; });
};

window.togglePdfView = function(litId, safePath) {
    const pdfRow = document.getElementById(`pdf-row-${litId}`);
    const pdfContainer = document.getElementById(`pdf-container-${litId}`);
    const actionCell = document.getElementById(`action-cell-${litId}`);
    const btn = document.getElementById(`view-pdf-btn-${litId}`);

    if (pdfRow.style.display === 'none') {
        pdfRow.style.display = 'table-row'; actionCell.rowSpan = 2;
        if (!pdfContainer.innerHTML.trim()) pdfContainer.innerHTML = `<iframe src="${API_BASE_URL}/api/view-pdf?path=${safePath}" style="width: 100%; height: 800px; border: none; display: block;"></iframe>`;
        btn.innerHTML = 'Close PDF'; btn.classList.replace('btn-primary', 'btn-danger');
    } else {
        pdfRow.style.display = 'none'; actionCell.rowSpan = 1;
        btn.innerHTML = 'View PDF'; btn.classList.replace('btn-danger', 'btn-primary');
    }
};

// ====== 绑定：AI 筛查与 PDF 下载等执行按钮 ======
document.addEventListener('DOMContentLoaded', () => {
    // 1. AI 摘要筛查按钮
    const runAiBtn = document.getElementById('run-ai-screening-btn');
    if (runAiBtn) {
        runAiBtn.addEventListener('click', async () => {
            if (!currentProject || !currentProject.id) return;
            const originalText = runAiBtn.innerHTML;
            runAiBtn.innerHTML = '⏳ AI is reading and screening...'; runAiBtn.disabled = true; runAiBtn.style.backgroundColor = '#6c757d';
            try {
                const response = await fetch(`${API_BASE_URL}/api/run-ai-screening`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ project_id: currentProject.id })
                });
                const result = await response.json();
                if (result.success) { alert(result.message); window.loadAbstractScreening(); } else { alert('Error: ' + result.message); }
            } catch (error) { alert('Network error.'); } 
            finally { runAiBtn.innerHTML = originalText; runAiBtn.disabled = false; runAiBtn.style.backgroundColor = '#28a745'; }
        });
    }

    // 2. 自动下载 PDF 按钮
    const fetchPdfsBtn = document.getElementById('fetch-pdfs-btn');
    if (fetchPdfsBtn) {
        fetchPdfsBtn.addEventListener('click', async () => {
            if (!currentProject || !currentProject.id) return;
            const originalText = fetchPdfsBtn.innerHTML;
            fetchPdfsBtn.innerHTML = '⏳ Crawler is downloading PDFs...'; fetchPdfsBtn.disabled = true; fetchPdfsBtn.style.backgroundColor = '#6c757d';
            try {
                const response = await fetch(`${API_BASE_URL}/api/fetch-pdfs`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ project_id: currentProject.id })
                });
                const result = await response.json();
                if (result.success) { alert(result.message); window.loadFullTextScreening(); } else { alert('Error: ' + result.message); }
            } catch (e) { alert('Network error.'); } 
            finally { fetchPdfsBtn.innerHTML = originalText; fetchPdfsBtn.disabled = false; fetchPdfsBtn.style.backgroundColor = '#17a2b8'; }
        });
    }

    // 3. AI 全文筛查按钮
    const runFullTextAiBtn = document.getElementById('run-fulltext-ai-btn');
    if (runFullTextAiBtn) {
        runFullTextAiBtn.addEventListener('click', async () => {
            if (!currentProject || !currentProject.id) return;
            const originalText = runFullTextAiBtn.innerHTML;
            runFullTextAiBtn.innerHTML = '⏳ Multimodal AI is reading...'; runFullTextAiBtn.disabled = true; runFullTextAiBtn.style.backgroundColor = '#6c757d';
            try {
                const response = await fetch(`${API_BASE_URL}/api/run-fulltext-ai`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ project_id: currentProject.id })
                });
                const result = await response.json();
                if (result.success) { alert(result.message); window.loadFullTextScreening(); } else { alert('Error: ' + result.message); }
            } catch (e) { alert('Network error.'); } 
            finally { runFullTextAiBtn.innerHTML = originalText; runFullTextAiBtn.disabled = false; runFullTextAiBtn.style.backgroundColor = '#28a745'; }
        });
    }

    // 4. 保存编辑的 Reasoning 按钮
    const saveReasonBtn = document.getElementById('saveReason');
    if (saveReasonBtn) {
        saveReasonBtn.addEventListener('click', async function() {
            if (!currentEditRow) return;
            const newReason = document.getElementById('reasonText').value.trim();
            const litId = currentEditRow.getAttribute('data-id');
            if (newReason) {
                try {
                    const response = await fetch(`${API_BASE_URL}/api/update-literature-decision`, {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ literature_id: litId, reasoning: newReason })
                    });
                    const result = await response.json();
                    if (result.success) {
                        currentEditRow.setAttribute('data-reason', newReason);
                        const shortReason = newReason.length > 80 ? newReason.substring(0, 80) + '...' : newReason;
                        currentEditRow.querySelector('.reason-display').textContent = shortReason;
                        document.getElementById('reasonModal').style.display = 'none';
                        alert('Reasoning updated successfully!');
                    } else { alert('Failed to save.'); }
                } catch (error) { console.error(error); }
            } else { alert('Content cannot be empty!'); }
        });
    }
});

// ====== 绑定：Abstract Screening 导出 CSV 按钮 ======
document.addEventListener('DOMContentLoaded', () => {
    const exportCsvBtn = document.getElementById('export-csv-btn');
    if (exportCsvBtn) {
        exportCsvBtn.addEventListener('click', () => {
            if (!currentProject || !currentProject.id) {
                alert('Error: No active project found.');
                return;
            }
            // 利用浏览器的 window.open 直接触发 GET 下载请求
            const downloadUrl = `${API_BASE_URL}/api/export-csv?project_id=${currentProject.id}`;
            window.open(downloadUrl, '_blank');
        });
    }
});