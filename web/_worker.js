/**
 * 访问密码门卫（Cloudflare Pages 高级模式 _worker.js）。
 * 所有请求（含 /data/records.json）都需持有有效 auth Cookie，
 * 否则返回密码输入页。密码正确时种 30 天 Cookie。
 */

const PASSWORD = 'Kele123$';
const SECRET = 'compus2027-auth-v1';
const COOKIE_NAME = 'auth';
const MAX_AGE = 60 * 60 * 24 * 30; // 30 天

async function authToken() {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(SECRET), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode('auth-v1'));
  return [...new Uint8Array(sig)].map(b => b.toString(16).padStart(2, '0')).join('');
}

function loginPage(error) {
  return new Response(`<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>访问验证 · 校招信息汇总</title>
<style>
  body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:#f5f7fa; font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif; }
  .card { background:#fff; border:1px solid #e5e9f0; border-radius:12px; padding:32px 36px;
          width:min(360px, 90vw); box-shadow:0 8px 24px rgba(0,0,0,.06); text-align:center; }
  h1 { font-size:20px; margin:0 0 6px; }
  p.tip { color:#6b7280; font-size:13px; margin:0 0 18px; }
  input[type=password] { width:100%; padding:10px 12px; border:1px solid #e5e9f0; border-radius:8px;
         font-size:15px; outline:none; box-sizing:border-box; }
  input[type=password]:focus { border-color:#2563eb; }
  button { width:100%; margin-top:12px; padding:10px; border:none; border-radius:8px;
           background:#2563eb; color:#fff; font-size:15px; cursor:pointer; }
  button:hover { background:#1d4ed8; }
  .err { color:#dc2626; font-size:13px; min-height:18px; margin:8px 0 0; }
</style>
</head>
<body>
  <form class="card" method="POST" action="/__auth">
    <h1>🎓 校招信息汇总</h1>
    <p class="tip">本站为私人看板，请输入访问密码</p>
    <input type="password" name="pw" placeholder="访问密码" autofocus required>
    <button type="submit">进入</button>
    <div class="err">${error ? '密码错误，请重试' : ''}</div>
  </form>
</body>
</html>`, { headers: { 'content-type': 'text/html; charset=utf-8' } });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const expected = await authToken();

    const cookies = request.headers.get('Cookie') || '';
    const m = cookies.match(new RegExp(`(?:^|;\\s*)${COOKIE_NAME}=([a-f0-9]{64})`));
    if (m && m[1] === expected) {
      return env.ASSETS.fetch(request);
    }

    if (url.pathname === '/__auth' && request.method === 'POST') {
      const form = await request.formData();
      if ((form.get('pw') || '') === PASSWORD) {
        return new Response(null, {
          status: 302,
          headers: {
            'Location': '/',
            'Set-Cookie': `${COOKIE_NAME}=${expected}; HttpOnly; Secure; Path=/; Max-Age=${MAX_AGE}; SameSite=Lax`,
          },
        });
      }
      return loginPage(true);
    }
    return loginPage(false);
  },
};
