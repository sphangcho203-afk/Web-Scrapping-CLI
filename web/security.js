(() => {
  const request = async (path, options = {}) => {
    const init = {
      credentials: 'include',
      ...options,
      headers: {'Content-Type': 'application/json', ...(options.headers || {})},
    };
    if (init.body && typeof init.body !== 'string') init.body = JSON.stringify(init.body);
    const res = await fetch(path, init);
    let data = {};
    try { data = await res.json(); } catch {}
    if (!res.ok) {
      const detail = data?.detail;
      const message = typeof detail === 'string' ? detail : (detail?.message || data?.error || `Request failed (${res.status})`);
      throw new Error(message);
    }
    return data;
  };

  const notify = message => {
    if (typeof window.toast === 'function') return window.toast(message);
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  };

  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, c => ({
    '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;'
  }[c]));

  function modal(inner) {
    const wrap = document.createElement('div');
    wrap.className = 'modal-backdrop';
    wrap.innerHTML = `<div class="modal">${inner}</div>`;
    document.body.appendChild(wrap);
    wrap.querySelectorAll('[data-close]').forEach(btn => btn.onclick = () => wrap.remove());
    return wrap;
  }

  function showTwoFactorChallenge() {
    const card = document.querySelector('.auth-card');
    if (!card) return;
    card.innerHTML = `
      <h2>Two-factor authentication</h2>
      <p>Enter the 6-digit code from your authenticator app, or use one recovery code.</p>
      <form id="two-factor-login" class="form-grid">
        <div class="field"><label>Authenticator or recovery code</label><input class="input" name="code" autocomplete="one-time-code" required autofocus></div>
        <button class="btn btn-primary" type="submit">Verify & sign in</button>
      </form>
      <p class="small muted" style="margin-top:18px">This challenge expires in 10 minutes.</p>`;
    const form = card.querySelector('#two-factor-login');
    form.onsubmit = async event => {
      event.preventDefault();
      const code = new FormData(form).get('code');
      try {
        await request('/api/auth/2fa/challenge', {method:'POST', body:{code}});
        location.assign('/dashboard');
      } catch (error) {
        notify(error.message);
      }
    };
  }

  function enhanceAuth(mode) {
    const params = new URLSearchParams(location.search);
    if (mode === 'login' && params.get('two_factor') === 'required') {
      showTwoFactorChallenge();
      return;
    }
    const form = document.querySelector('#auth-form');
    if (!form) return;
    form.onsubmit = async event => {
      event.preventDefault();
      const payload = Object.fromEntries(new FormData(form).entries());
      try {
        const result = await request(mode === 'signup' ? '/api/auth/signup' : '/api/auth/login', {
          method:'POST', body:payload,
        });
        if (result.two_factor_required) {
          showTwoFactorChallenge();
          return;
        }
        if (mode === 'signup') {
          notify(result.verification_sent ? 'Account created — check your email for the verification code.' : 'Account created. Email delivery is not configured yet.');
          location.assign('/dashboard/settings');
        } else {
          location.assign('/dashboard');
        }
      } catch (error) {
        notify(error.message);
      }
    };
  }

  async function setupTwoFactor() {
    try {
      const setup = await request('/api/auth/2fa/setup', {method:'POST'});
      const wrap = modal(`
        <div class="card-title"><h3>Set up authenticator</h3><button class="btn btn-sm" data-close>×</button></div>
        <p class="muted">Add this account in Google Authenticator, Microsoft Authenticator, 1Password, Aegis, or another TOTP app.</p>
        <div class="field"><label>Secret</label><div class="secret-box" style="user-select:all">${escapeHtml(setup.secret)}</div></div>
        <div class="field"><label>Authenticator URI</label><div class="secret-box" style="font-size:12px;overflow-wrap:anywhere">${escapeHtml(setup.otpauth_uri)}</div></div>
        <form id="confirm-2fa" class="form-grid" style="margin-top:18px">
          <div class="field"><label>6-digit code</label><input class="input" name="code" autocomplete="one-time-code" inputmode="numeric" maxlength="6" required></div>
          <button class="btn btn-primary">Enable 2FA</button>
        </form>`);
      wrap.querySelector('#confirm-2fa').onsubmit = async event => {
        event.preventDefault();
        const code = new FormData(event.currentTarget).get('code');
        try {
          const result = await request('/api/auth/2fa/confirm', {method:'POST', body:{code}});
          wrap.remove();
          const recovery = modal(`
            <h3>Save your recovery codes</h3>
            <p class="muted">Each code works once. Store them somewhere separate from your authenticator.</p>
            <div class="secret-box" style="white-space:pre-line;line-height:1.8">${result.recovery_codes.map(escapeHtml).join('\n')}</div>
            <button class="btn btn-primary" data-close style="margin-top:16px">I saved them</button>`);
          recovery.querySelector('[data-close]').onclick = () => { recovery.remove(); location.reload(); };
        } catch (error) { notify(error.message); }
      };
    } catch (error) { notify(error.message); }
  }

  function disableTwoFactor() {
    const wrap = modal(`
      <div class="card-title"><h3>Disable 2FA</h3><button class="btn btn-sm" data-close>×</button></div>
      <p class="muted">Confirm with your current authenticator code or one recovery code.</p>
      <form id="disable-2fa" class="form-grid">
        <div class="field"><label>Code</label><input class="input" name="code" autocomplete="one-time-code" required></div>
        <button class="btn btn-danger">Disable two-factor authentication</button>
      </form>`);
    wrap.querySelector('#disable-2fa').onsubmit = async event => {
      event.preventDefault();
      const code = new FormData(event.currentTarget).get('code');
      try {
        await request('/api/auth/2fa/disable', {method:'POST', body:{code}});
        wrap.remove();
        notify('Two-factor authentication disabled');
        location.reload();
      } catch (error) { notify(error.message); }
    };
  }

  async function enhanceSettings() {
    if (!location.pathname.startsWith('/dashboard/settings')) return;
    const content = document.querySelector('.content');
    if (!content || content.querySelector('#security-center')) return;
    try {
      const status = await request('/api/security/status');
      const card = document.createElement('div');
      card.id = 'security-center';
      card.className = 'card';
      card.style.maxWidth = '760px';
      card.style.marginTop = '16px';
      card.innerHTML = `
        <div class="card-title"><div><h3>Security center</h3><p class="muted small">Email verification, login protection and account recovery.</p></div></div>
        <div class="provider-grid">
          <div class="provider"><div><strong>Email verification</strong><small>${status.email_verified ? 'Verified' : 'Verification required'}</small></div><span class="pill ${status.email_verified ? 'good' : 'warn'}">${status.email_verified ? 'Verified' : 'Pending'}</span></div>
          <div class="provider"><div><strong>Transactional mail</strong><small>${escapeHtml(status.mail_provider || 'Not configured')}</small></div><span class="pill ${status.transactional_mail_configured ? 'good' : 'warn'}">${status.transactional_mail_configured ? 'Ready' : 'Pending'}</span></div>
          <div class="provider"><div><strong>Authenticator 2FA</strong><small>${status.two_factor_enabled ? 'TOTP enabled' : 'Optional extra sign-in protection'}</small></div><span class="pill ${status.two_factor_enabled ? 'good' : 'warn'}">${status.two_factor_enabled ? 'Enabled' : 'Off'}</span></div>
        </div>
        ${status.email_verified ? '' : `
          <div style="margin-top:22px"><h3>Verify your email</h3><p class="muted">Use the link in your email or enter the 6-digit code here.</p>
          <form id="verify-email-code" style="display:flex;gap:10px;flex-wrap:wrap"><input class="input" name="code" inputmode="numeric" maxlength="6" placeholder="000000" required style="max-width:220px"><button class="btn btn-primary">Verify</button><button type="button" class="btn" id="resend-verification">Resend email</button></form></div>`}
        <div style="margin-top:22px"><h3>Two-factor authentication</h3><p class="muted">${status.two_factor_enabled ? 'Your account requires a TOTP or recovery code after password/GitHub sign-in.' : 'Protect sign-in with a time-based one-time password from your authenticator app.'}</p>
          <button class="btn ${status.two_factor_enabled ? 'btn-danger' : 'btn-primary'}" id="toggle-2fa" ${!status.two_factor_available && !status.two_factor_enabled ? 'disabled' : ''}>${status.two_factor_enabled ? 'Disable 2FA' : 'Set up 2FA'}</button>
          ${!status.two_factor_available ? '<p class="small muted">Server-side encryption must be configured before TOTP can be enabled.</p>' : ''}
        </div>`;
      content.appendChild(card);
      const verifyForm = card.querySelector('#verify-email-code');
      if (verifyForm) verifyForm.onsubmit = async event => {
        event.preventDefault();
        const code = new FormData(verifyForm).get('code');
        try {
          await request('/api/auth/email-verification/confirm', {method:'POST', body:{code}});
          notify('Email verified');
          location.reload();
        } catch (error) { notify(error.message); }
      };
      const resend = card.querySelector('#resend-verification');
      if (resend) resend.onclick = async () => {
        try {
          const result = await request('/api/auth/email-verification/send', {method:'POST'});
          notify(result.sent === false ? 'Verification created, but mail delivery is not configured.' : 'Verification email sent');
        } catch (error) { notify(error.message); }
      };
      const toggle = card.querySelector('#toggle-2fa');
      if (toggle) toggle.onclick = () => status.two_factor_enabled ? disableTwoFactor() : setupTwoFactor();
      if (new URLSearchParams(location.search).get('verified') === '1') notify('Email verified successfully');
    } catch (error) {
      console.error('security center', error);
    }
  }

  const originalRenderAuth = window.renderAuth;
  if (typeof originalRenderAuth === 'function') {
    window.renderAuth = function(mode) {
      originalRenderAuth(mode);
      enhanceAuth(mode);
    };
  }
  const originalDashSettings = window.dashSettings;
  if (typeof originalDashSettings === 'function') {
    window.dashSettings = function() {
      originalDashSettings();
      queueMicrotask(enhanceSettings);
    };
  }

  if (location.pathname === '/login') enhanceAuth('login');
  if (location.pathname === '/signup') enhanceAuth('signup');
  if (location.pathname.startsWith('/dashboard/settings')) enhanceSettings();
})();
