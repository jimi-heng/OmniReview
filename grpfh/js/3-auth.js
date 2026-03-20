// 登录
document.getElementById('login-btn').addEventListener('click', async () => {
  const inputEmail = document.getElementById('email').value.trim();
  const inputPwd = document.getElementById('password').value.trim();
  const errorTip = document.getElementById('login-error');

  if (!inputEmail || !inputPwd) {
    errorTip.textContent = 'Email and password cannot be empty';
    errorTip.style.display = 'block';
    return;
  }

  try {
    const response = await fetch(`${API_BASE_URL}/api/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: inputEmail, password: inputPwd })
    });

    const result = await response.json();

    if (result.success) {
      errorTip.style.display = 'none';
      const now = new Date();
      const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const dateStr = now.toLocaleDateString([], { month: 'short', day: 'numeric' });

      currentUser = {
        id: result.user_id,
        email: inputEmail, 
        loginTime: `${dateStr}, ${timeStr}`
      };

      const emailDisplays = [document.getElementById('profile-email-display'), document.getElementById('tooltip-email')];
      emailDisplays.forEach(el => { if (el) el.textContent = currentUser.email; });
      const timeDisplay = document.getElementById('tooltip-time');
      if (timeDisplay) timeDisplay.textContent = `Logged in: ${currentUser.loginTime}`;

      sessionStorage.setItem('currentUser', JSON.stringify(currentUser));

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
      errorTip.textContent = result.message;
      errorTip.style.display = 'block';
      document.getElementById('password').value = ''; 
    }
  } catch (error) {
    errorTip.textContent = 'Failed to connect to the server! Please check if the backend is running.';
    errorTip.style.display = 'block';
  }
});

// 退出登录
document.getElementById('logout-btn').addEventListener('click', () => {
  document.getElementById('email').value = '';
  document.getElementById('password').value = '';
  document.getElementById('login-error').style.display = 'none';

  currentUser = null;
  currentProject = null;
  sessionStorage.removeItem('currentUser');
  sessionStorage.removeItem('currentProject');

  showPage('login-page');
  playLoginEntranceAnimation(); 
});

// 注册
document.getElementById('register-btn').addEventListener('click', async () => {
    const regEmail = document.getElementById('reg-email').value.trim();
    const regPwd = document.getElementById('reg-password').value.trim();
    const regConfirmPwd = document.getElementById('reg-confirm-pwd').value.trim();
    const regErrorTip = document.getElementById('register-error');

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
        const response = await fetch(`${API_BASE_URL}/api/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: regEmail, password: regPwd })
        });
        const result = await response.json();
        if (result.success) {
            regErrorTip.style.display = 'none';
            alert('Register success! Please log in.');
            document.getElementById('reg-email').value = '';
            document.getElementById('reg-password').value = '';
            document.getElementById('reg-confirm-pwd').value = '';
            showPage('login-page');
        } else {
            regErrorTip.textContent = result.message;
            regErrorTip.style.display = 'block';
        }
    } catch (error) {
        regErrorTip.textContent = 'Server connection failed!';
        regErrorTip.style.display = 'block';
    }
});

// Profile 页面逻辑
function openProfilePage() {
    showPage('profile-page'); 
    document.getElementById('profile-menu-view').style.display = 'block'; 
    document.getElementById('profile-password-view').style.display = 'none'; 
    document.getElementById('current-password-input').value = '';
    document.getElementById('new-password-input').value = '';
    document.getElementById('confirm-password-input').value = '';
}

function toggleProfileView(view) {
    const menuView = document.getElementById('profile-menu-view');
    const pwdView = document.getElementById('profile-password-view');
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
            document.getElementById('logout-btn').click(); 
        } else {
            alert(`Failed: ${result.message}`); 
        }
    } catch (error) {
        alert("A network error occurred.");
    } finally {
        btn.textContent = originalText;
        btn.disabled = false;
    }
}