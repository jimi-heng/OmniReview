window.switchImportTab = function(type) {
    const importTab = document.querySelector('.tab[onclick*="import"]');
    const searchTab = document.querySelector('.tab[onclick*="search"]');
    if(importTab && searchTab) {
        if(type === 'import') { importTab.classList.add('active'); searchTab.classList.remove('active'); }
        else { importTab.classList.remove('active'); searchTab.classList.add('active'); }
    }
    document.getElementById('import-section').style.display = type === 'import' ? 'block' : 'none';
    document.getElementById('search-section').style.display = type === 'search' ? 'block' : 'none';
};

function parseBibFile(text) {
  const literatures = [];
  const entries = text.split('@').filter(entry => entry.trim());
  entries.forEach(entry => {
    const titleMatch = entry.match(/title\s*=\s*\{([^}]+)\}/i);
    const authorMatch = entry.match(/author\s*=\s*\{([^}]+)\}/i);
    const journalMatch = entry.match(/journal\s*=\s*\{([^}]+)\}/i);
    const yearMatch = entry.match(/year\s*=\s*\{([0-9]+)\}/i);
    const doiMatch = entry.match(/doi\s*=\s*\{([^}]+)\}/i); 
    const abstractMatch = entry.match(/abstract\s*=\s*\{([^}]+)\}/i); 

    if (titleMatch) {
      literatures.push({
        title: titleMatch[1].trim().replace(/[\{\}]/g, ''),
        author: authorMatch ? authorMatch[1].trim().replace(/[\{\}]/g, '') : '',
        journal: journalMatch ? journalMatch[1].trim().replace(/[\{\}]/g, '') : '',
        year: yearMatch ? parseInt(yearMatch[1]) : null,
        doi: doiMatch ? doiMatch[1].trim().replace(/[\{\}]/g, '') : '', 
        abstract: abstractMatch ? abstractMatch[1].trim().replace(/[\{\}]/g, '') : '' 
      });
    }
  });
  return literatures;
}

function parseRisFile(text) {
  const literatures = [];
  const entries = text.split(/ER\s+-/);
  entries.forEach(entry => {
    if (!entry.trim()) return;
    const lines = entry.split(/\n|\r\n/);
    let lit = { title: '', author: [], journal: '', year: null, doi: '', abstract: '' };
    let currentTag = '';

    lines.forEach(line => {
      const match = line.match(/^([A-Z0-9]{2})\s+-\s+(.*)$/);
      if (match) {
        currentTag = match[1];
        const val = match[2].trim();
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
         lit.abstract += ' ' + line.trim();
      }
    });
    if (lit.title) {
      lit.author = lit.author.join('; ');
      literatures.push(lit);
    }
  });
  return literatures;
}

window.loadLiteratureList = async function() {
    const tableBody = document.getElementById('literature-table-body');
    if (!tableBody || !currentProject || !currentProject.id) return;

    try {
      const response = await fetch(`${API_BASE_URL}/api/get-literatures`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: currentProject.id, user_id: currentUser.id })
      });
      const result = await response.json();

      if (result.success && result.data.length > 0) {
        tableBody.innerHTML = '';
        result.data.forEach((lit, index) => {
          const displayId = index + 1; 
          const tr = document.createElement('tr');
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
        tableBody.innerHTML = `<tr><td colspan="5" class="empty-data">No literature data yet - Upload or search to view results</td></tr>`;
      }
    } catch (error) {
      tableBody.innerHTML = `<tr><td colspan="5" class="empty-data" style="color: red;">Failed to load literatures!</td></tr>`;
    }
};

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
                data_type: 'search_params', 
                data_content: searchData
            })
        });
    } catch (error) { console.error('Failed to save search data:', error); }
}

// ====== 绑定：所有文献获取与导入的交互事件 ======
document.addEventListener('DOMContentLoaded', () => {
    // 1. 修复：Max Papers 数字增减
    const maxPapersInput = document.getElementById('max-papers');
    const btnUp = document.getElementById('max-papers-up');
    const btnDown = document.getElementById('max-papers-down');
    const steps = [10, 30, 50, 100, 200];
    if (btnUp) {
        btnUp.addEventListener('click', () => {
            let currentVal = parseInt(maxPapersInput.value) || 0;
            let nextVal = steps.find(s => s > currentVal) || steps[steps.length - 1];
            maxPapersInput.value = nextVal;
        });
    }
    if (btnDown) {
        btnDown.addEventListener('click', () => {
            let currentVal = parseInt(maxPapersInput.value) || 0;
            let prevVal = [...steps].reverse().find(s => s < currentVal) || steps[0];
            maxPapersInput.value = prevVal;
        });
    }

    // 2. 修复：Upload Citations 按钮逻辑
    const uploadBtn = document.getElementById('upload-btn');
    if (uploadBtn) {
        uploadBtn.addEventListener('click', async () => {
            const fileInput = document.getElementById('file-upload');
            const uploadError = document.getElementById('upload-error');
            const files = fileInput.files;

            uploadError.style.display = 'none'; uploadError.textContent = '';
            if (files.length === 0) { uploadError.textContent = 'Please select at least one citation file!'; uploadError.style.display = 'block'; return; }

            let totalSuccess = 0, totalDuplicates = 0; let errorFiles = [];

            for (let i = 0; i < files.length; i++) {
                const file = files[i];
                const fileExt = file.name.split('.').pop().toLowerCase();
                if (!['bib', 'ris'].includes(fileExt)) { errorFiles.push(`${file.name} (unsupported)`); continue; }

                const fileContent = await new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onload = (e) => resolve(e.target.result);
                    reader.onerror = (e) => reject(e);
                    reader.readAsText(file);
                });

                let literatures = fileExt === 'bib' ? parseBibFile(fileContent) : parseRisFile(fileContent);
                if (literatures.length === 0) { errorFiles.push(`${file.name} (no valid data)`); continue; }

                try {
                    if (!currentProject || !currentProject.id) { alert('No active project found.'); return; }
                    for (let lit of literatures) {
                        lit.project_id = currentProject.id;
                        const response = await fetch(`${API_BASE_URL}/api/upload-literature`, {
                            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(lit)
                        });
                        const result = await response.json();
                        if (result.success) { result.inserted ? totalSuccess++ : totalDuplicates++; }
                    }
                } catch (err) { errorFiles.push(`${file.name} (upload failed)`); }
            }

            let message = `Upload Completed!\n- Success: ${totalSuccess}\n- Skipped Duplicates: ${totalDuplicates}\n`;
            if (errorFiles.length > 0) message += `- Failed: ${errorFiles.join(', ')}`;
            alert(message);
            fileInput.value = ''; window.loadLiteratureList();

            // 👇 补上这句：上传完重置文本
            if (fileChosenText) {
                fileChosenText.textContent = 'No file chosen';
                fileChosenText.style.color = '#86868b';
            }
        });
    }

    // ====== 修复：Apple 风格自定义文件上传文本联动 ======
    const fileInput = document.getElementById('file-upload');
    const fileChosenText = document.getElementById('file-chosen-text');
    
    if (fileInput && fileChosenText) {
        fileInput.addEventListener('change', function() {
            if (this.files && this.files.length > 1) {
                // 选了多个文件显示：3 files chosen
                fileChosenText.textContent = `${this.files.length} files chosen`;
                fileChosenText.style.color = '#1d1d1f'; // 变成深色表示已选
            } else if (this.files && this.files.length === 1) {
                // 选了单个文件显示文件名
                fileChosenText.textContent = this.files[0].name;
                fileChosenText.style.color = '#1d1d1f';
            } else {
                // 没选文件恢复默认
                fileChosenText.textContent = 'No file chosen';
                fileChosenText.style.color = '#86868b';
            }
        });
    }

    // 3. 修复：Initiate Literature Search 按钮逻辑
    const searchPubmedBtn = document.getElementById('search-pubmed-btn');
    if (searchPubmedBtn) {
        searchPubmedBtn.addEventListener('click', async () => {
            const keywords = document.getElementById('search-keywords').value.trim();
            const maxPapers = document.getElementById('max-papers').value;
            const activeChips = document.querySelectorAll('.db-chip.active');
            const selectedDBs = Array.from(activeChips).map(chip => chip.getAttribute('data-db'));

            if (!keywords) { alert('Please enter search keywords.'); return; }
            if (!currentProject || !currentProject.id) { alert('Please select a project first.'); return; }

            const originalText = searchPubmedBtn.textContent;
            searchPubmedBtn.textContent = 'Searching... (May take a while)'; searchPubmedBtn.disabled = true;

            try {
                const response = await fetch(`${API_BASE_URL}/api/search-pubmed`, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ project_id: currentProject.id, keywords: keywords, max_papers: parseInt(maxPapers), databases: selectedDBs })
                });
                const result = await response.json();
                if (result.success) { alert(result.message); } else { alert('Search Error: ' + result.message); }
            } catch (error) { alert('Network error. Is the Python backend running?'); } 
            finally { searchPubmedBtn.textContent = originalText; searchPubmedBtn.disabled = false; window.loadLiteratureList(); }
        });
    }
});
