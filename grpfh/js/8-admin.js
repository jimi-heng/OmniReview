async function loadAdminStats() {
    try {
        const response = await fetch(`${API_BASE_URL}/api/admin/stats`);
        const result = await response.json();

        if (result.success) {
            cachedAdminStatsData = result.data;
            window.renderAdminTimeRange('all');
        }
    } catch (error) {
        document.getElementById('stat-total-users').textContent = '-';
        document.getElementById('stat-total-projects').textContent = '-';
        document.getElementById('stat-total-papers').textContent = '-';
    }
}

window.renderAdminTimeRange = function(timeRange) {
    if (!cachedAdminStatsData) return;

    const tabs = document.querySelectorAll('#admin-time-tabs .tab');
    tabs.forEach(tab => tab.classList.remove('active'));
    if (timeRange === 'today') tabs[0].classList.add('active');
    if (timeRange === 'week') tabs[1].classList.add('active');
    if (timeRange === 'month') tabs[2].classList.add('active');
    if (timeRange === 'all') tabs[3].classList.add('active');

    const targetData = cachedAdminStatsData[timeRange]; 

    animateValue('stat-total-users', 0, targetData.users, 1000);
    animateValue('stat-total-projects', 0, targetData.projects.total_proj, 1000);
    animateValue('stat-total-papers', 0, targetData.papers, 1000);

    const projData = targetData.projects;
    const totalProj = projData.total_proj || 1; 

    const pSpico = Math.round((projData.SPICO / totalProj) * 100) || 0;
    const pPeco = Math.round((projData.PECO / totalProj) * 100) || 0;
    const pPiro = Math.round((projData.PIRO / totalProj) * 100) || 0;

    document.getElementById('dist-spico-bar').style.width = pSpico + '%';
    document.getElementById('dist-spico-text').textContent = `${pSpico}% (${projData.SPICO})`;
    document.getElementById('dist-peco-bar').style.width = pPeco + '%';
    document.getElementById('dist-peco-text').textContent = `${pPeco}% (${projData.PECO})`;
    document.getElementById('dist-piro-bar').style.width = pPiro + '%';
    document.getElementById('dist-piro-text').textContent = `${pPiro}% (${projData.PIRO})`;
};

function animateValue(id, start, end, duration) {
    const obj = document.getElementById(id);
    if (!obj) return;
    let startTimestamp = null;
    const step = (timestamp) => {
        if (!startTimestamp) startTimestamp = timestamp;
        const progress = Math.min((timestamp - startTimestamp) / duration, 1);
        const easeOut = 1 - Math.pow(1 - progress, 4); 
        obj.innerHTML = Math.floor(easeOut * (end - start) + start);
        if (progress < 1) {
            window.requestAnimationFrame(step);
        } else { obj.innerHTML = end; }
    };
    window.requestAnimationFrame(step);
}