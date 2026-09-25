<script>
  import ComparePage from './ComparePage.svelte'

  let username = 'processor'
  let password = 'herb123456'
  let token = localStorage.getItem('herb_token') || ''
  let role = localStorage.getItem('herb_role') || ''
  let route = window.location.hash
  let rows = []
  let herb = '白芍'
  let tempC = 110
  let minutes = 10
  let error = ''

  window.addEventListener('hashchange', () => (route = window.location.hash))

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || '请求失败')
    return data
  }

  async function enter() {
    const data = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    token = data.access_token
    role = data.role
    localStorage.setItem('herb_token', token)
    localStorage.setItem('herb_role', role)
    await load()
  }

  async function load() {
    rows = await api('/api/batches')
  }

  async function save() {
    error = ''
    try {
      await api('/api/batches', {
        method: 'POST',
        body: JSON.stringify({
          herb,
          steps: [{ name: '清炒', temp_c: Number(tempC), minutes: Number(minutes) }],
        }),
      })
      await load()
    } catch (err) {
      error = err.message
    }
  }

  function leave() {
    localStorage.clear()
    token = ''
    role = ''
    window.location.hash = ''
  }

  if (token) load()
</script>

<main>
  <h1>饮片炮制记录台</h1>
  {#if !token}
    <p>炮制记录整包保存。清炒温度须在 80 到 150，时长须在 5 到 30 分钟。</p>
    <input bind:value={username} />
    <input type="password" bind:value={password} />
    <button on:click={enter}>登录</button>
    <p>processor / herb123456 可写；checker / check123456 只读</p>
  {:else}
    <nav class="topbar">
      <a class:active={!route || route === '#' || route === '#/'} href="#/">炮制记录</a>
      <a class:active={route.startsWith('#/compare')} href="#/compare">联锅对照</a>
      <button class="logout" on:click={leave}>退出</button>
    </nav>

    {#if route.startsWith('#/compare')}
      <ComparePage {token} {role} />
    {:else}
      {#if role === 'writer'}
        <section class="entry">
          <h3>写入清炒记录</h3>
          <input bind:value={herb} placeholder="饮片" />
          <input type="number" bind:value={tempC} placeholder="温度℃" />
          <input type="number" bind:value={minutes} placeholder="时长(分)" />
          <button on:click={save}>写入清炒记录</button>
          {#if error}<p class="error">{error}</p>{/if}
        </section>
      {/if}
      <h3>锅次记录（编号用于联锅对照）</h3>
      <ul class="batches">
        {#each rows as row}
          <li>
            <span class="pot-no">#{row.id}</span>
            {row.herb} · 温度 {row.doc.steps[0].temp_c}℃ · 时长 {row.doc.steps[0].minutes}分
            · <span class:pass={row.verdict === '放行'} class:reject={row.verdict !== '放行'}>{row.verdict}</span>
            · {row.reason}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</main>

<style>
  main {
    font-family: sans-serif;
    max-width: 960px;
    margin: 24px auto;
    color: #3f2f1f;
  }
  h1 {
    color: #7c2d12;
  }
  .topbar {
    display: flex;
    align-items: center;
    gap: 16px;
    border-bottom: 2px solid #d6c3ad;
    padding-bottom: 8px;
    margin-bottom: 16px;
  }
  .topbar a {
    text-decoration: none;
    color: #6b5740;
    padding: 4px 10px;
    border-radius: 6px;
  }
  .topbar a.active {
    background: #7c2d12;
    color: #fff;
  }
  .topbar .logout {
    margin-left: auto;
  }
  .entry input {
    margin-right: 8px;
    padding: 6px;
  }
  .error {
    color: #b91c1c;
  }
  .batches {
    padding-left: 0;
    list-style: none;
  }
  .batches li {
    padding: 6px 8px;
    border-bottom: 1px solid #ece1cf;
  }
  .pot-no {
    display: inline-block;
    min-width: 2.6em;
    font-weight: bold;
    color: #7c2d12;
  }
  .pass {
    color: #166534;
    font-weight: bold;
  }
  .reject {
    color: #b91c1c;
    font-weight: bold;
  }
</style>
