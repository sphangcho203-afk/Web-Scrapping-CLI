(() => {
  const path = location.pathname;
  if (path !== '/forgot-password' && path !== '/reset-password') return;

  const root = document.getElementById('app');
  const escapeHtml = value => String(value ?? '').replace(/[&<>\"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;', "'": '&#39;'
  }[char]));

  const request = async (url, body) => {
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    let data = {};
    try { data = await response.json(); } catch {}
    if (!response.ok) {
      const detail = data?.detail;
      throw new Error(typeof detail === 'string' ? detail : (detail?.message || 'Request failed'));
    }
    return data;
  };

  const shell = content => {
    root.innerHTML = `<main class="auth-wrap"><section class="auth-art"><div><a class="brand" href="/"><img src="/assets/mark.svg" width="38" height="38" alt=""><div class="brand-name">INTERNET <span>HANDS</span></div></a></div><div><span class="eyebrow">Account security</span><h1>Recover access without weakening your keys.</h1><p class="hero-copy">Password reset links expire quickly. Existing sessions are invalidated after a successful reset.</p></div><div class="muted small">API keys remain independently revocable from the developer console.</div></section><section class="auth-panel">${content}</section></main>`;
  };

  if (path === '/forgot-password') {
    shell(`<div class="auth-card"><h2>Reset password</h2><p>Enter your account email. The response is identical whether or not an account exists.</p><form id="recovery-form" class="form-grid"><div class="field"><label>Email</label><input class="input" required type="email" name="email" autocomplete="email"></div><button class="btn btn-primary" type="submit">Send reset link</button></form><div id="recovery-result" class="small muted" style="margin-top:18px"></div><p class="small muted" style="margin-top:18px"><a href="/login">Back to sign in</a></p></div>`);
    document.getElementById('recovery-form').addEventListener('submit', async event => {
      event.preventDefault();
      const result = document.getElementById('recovery-result');
      const form = new FormData(event.currentTarget);
      result.textContent = 'Sending…';
      try {
        const data = await request('/api/auth/password-reset/request', { email: form.get('email') });
        result.textContent = data.message || 'If that account exists, a reset link has been sent.';
      } catch (error) {
        result.textContent = error.message;
      }
    });
    return;
  }

  const token = new URLSearchParams(location.search).get('token') || '';
  shell(`<div class="auth-card"><h2>Choose a new password</h2><p>This reset invalidates existing web sessions and should be followed by reviewing active API keys.</p>${token ? '' : '<div class="callout">The reset token is missing from this URL.</div>'}<form id="reset-form" class="form-grid"><div class="field"><label>New password</label><input class="input" required minlength="8" type="password" name="password" autocomplete="new-password"></div><div class="field"><label>Confirm password</label><input class="input" required minlength="8" type="password" name="confirm" autocomplete="new-password"></div><button class="btn btn-primary" type="submit" ${token ? '' : 'disabled'}>Update password</button></form><div id="reset-result" class="small muted" style="margin-top:18px"></div><p class="small muted" style="margin-top:18px"><a href="/login">Back to sign in</a></p></div>`);
  document.getElementById('reset-form').addEventListener('submit', async event => {
    event.preventDefault();
    const result = document.getElementById('reset-result');
    const form = new FormData(event.currentTarget);
    const password = String(form.get('password') || '');
    const confirm = String(form.get('confirm') || '');
    if (password !== confirm) {
      result.textContent = 'Passwords do not match.';
      return;
    }
    result.textContent = 'Updating…';
    try {
      await request('/api/auth/password-reset/confirm', { token: escapeHtml(token), password });
      result.innerHTML = 'Password updated. <a href="/login">Sign in again</a>.';
      event.currentTarget.querySelector('button').disabled = true;
    } catch (error) {
      result.textContent = error.message;
    }
  });
})();
