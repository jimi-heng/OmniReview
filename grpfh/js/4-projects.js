async function loadUserProjects() {
    if (!currentUser) return;
    try {
        const response = await fetch(`${API_BASE_URL}/api/get-projects`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: currentUser.id })
        });
        const result = await response.json();
        if (result.success) renderProjects(result.data);
    } catch (error) { console.error('Failed to load projects:', error); }
}

function renderProjects(projects) {
    const homePage = document.getElementById('home-page');
    const projectsContainer = homePage.querySelector('.card');
    if (!projectsContainer) return;

    const headerHtml = `
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
            <h3 style="margin: 0;">Recent Projects</h3>
            <button class="btn btn-primary" id="create-project-btn">Create New Project</button>
        </div>
    `;

    if (projects.length === 0) {
        projectsContainer.innerHTML = headerHtml + `
            <div class="empty-data">No projects yet. Click "Create New Project" to start.</div>
        `;
    } else {
        let projectsHtml = headerHtml;
        projects.forEach(project => {
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

    const createBtn = document.getElementById('create-project-btn');
    if (createBtn) {
        createBtn.replaceWith(createBtn.cloneNode(true));
        const newCreateBtn = document.getElementById('create-project-btn');
        newCreateBtn.addEventListener('click', window.openCreateProjectModal);
    }
}

async function createNewProject(projectName) {
    if (!currentUser) return;
    try {
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

async function continueProject(projectId) {
    try {
        clearAllInputs(); 
        const response = await fetch(`${API_BASE_URL}/api/get-project-data`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: projectId })
        });
        const result = await response.json();

        if (result.success) {
            currentProject = { id: projectId };
            
            if (result.data.project_type) {
                currentProject.type = result.data.project_type;
            } else {
                currentProject.type = 'SPICO'; 
            }
            if (currentProject.type === 'PICOS') {
                currentProject.type = 'SPICO';
            }
            renderPicoPageByType(currentProject.type);

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

            if (result.data.protocol) {
                if (result.data.protocol.criteria !== undefined) {
                    document.getElementById('additional-criteria').value = result.data.protocol.criteria;
                }
            }
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

async function editProjectName(projectId, buttonElement) {
    const projectItem = buttonElement.closest('.project-item');
    const nameElement = projectItem.querySelector('.project-name');
    const oldName = nameElement.textContent;

    const newName = prompt('Edit project name:', oldName);
    if (newName && newName.trim() && newName.trim() !== oldName) {
        try {
            const response = await fetch(`${API_BASE_URL}/api/update-project-name`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: projectId, project_name: newName.trim() })
            });
            const result = await response.json();
            if (result.success) nameElement.textContent = newName.trim();
        } catch (error) { alert('Failed to update project name'); }
    }
}

function deleteProject(projectId, projectName) {
    projectToDeleteId = projectId;
    document.getElementById('deleteProjectNameDisplay').textContent = `"${projectName}"`;
    document.getElementById('deleteProjectModal').style.display = 'flex';
}

function closeDeleteModal() {
    document.getElementById('deleteProjectModal').style.display = 'none';
    projectToDeleteId = null;
}

document.getElementById('cancelDeleteBtn')?.addEventListener('click', closeDeleteModal);
document.getElementById('deleteProjectModal')?.addEventListener('click', function(e) {
    if (e.target === this) closeDeleteModal();
});

document.getElementById('confirmDeleteBtn')?.addEventListener('click', async () => {
    if (!projectToDeleteId) return;
    const projectId = projectToDeleteId;
    closeDeleteModal();

    try {
        const response = await fetch(`${API_BASE_URL}/api/delete-project`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: projectId })
        });
        const result = await response.json();

        if (result.success) {
            if (currentProject && currentProject.id === projectId) {
                currentProject = null;
                sessionStorage.removeItem('currentProject');
                clearAllInputs();
            }
            loadUserProjects();
        } else {
            alert('Failed to delete project: ' + result.message);
        }
    } catch (error) {
        alert('Network error occurred while trying to delete the project.');
    }
});

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

async function saveProtocolData() {
    if (!currentProject || !currentProject.id) return;
    const protocolData = { criteria: document.getElementById('additional-criteria').value };
    try {
        await fetch(`${API_BASE_URL}/api/save-project-data`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: currentProject.id, data_type: 'protocol', data_content: protocolData })
        });
    } catch (error) { console.error('Failed to save protocol data:', error); }
}

async function updateProjectStatus(status) {
    if (!currentProject || !currentProject.id) return;
    try {
        await fetch(`${API_BASE_URL}/api/update-project-status`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_id: currentProject.id, status: status })
        });
    } catch (error) { console.error('Failed to update project status:', error); }
}

// 暴露创建项目相关的 Modal 事件到 window 作用域供 App.js 挂载
window.openCreateProjectModal = function() {
    const newProjectNameInput = document.getElementById('newProjectNameInput');
    newProjectNameInput.value = ''; 
    document.getElementById('createProjectModal').style.display = 'flex';
    newProjectNameInput.focus(); 
};

window.closeCreateProjectModal = function() {
    document.getElementById('createProjectModal').style.display = 'none';
};