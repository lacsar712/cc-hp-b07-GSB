<script>
  let username = 'processor'
  let password = 'herb123456'
  let token = localStorage.getItem('herb_token') || ''
  let role = localStorage.getItem('herb_role') || ''
  let displayName = localStorage.getItem('herb_name') || ''
  let rows = []
  let herb = '白芍'
  let tempC = 110
  let minutes = 10
  let error = ''

  let view = location.hash === '#/compare' ? 'compare' : 'records'
  let pairs = []
  let history = []
  let expId = ''
  let ctlId = ''
  let compareError = ''

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
    displayName = data.username
    localStorage.setItem('herb_token', token)
    localStorage.setItem('herb_role', role)
    localStorage.setItem('herb_name', displayName)
    await load()
  }

  async function load() {
    rows = await api('/api/batches')
    if (view === 'compare') await loadCompare()
  }

  async function loadCompare() {
    pairs = await api('/api/pairs')
    history = await api('/api/pairs/history')
  }

  function onHash() {
    view = location.hash === '#/compare' ? 'compare' : 'records'
    compareError = ''
    if (token && view === 'compare') loadCompare()
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

  async function designate() {
    compareError = ''
    try {
      await api('/api/pairs', {
        method: 'POST',
        body: JSON.stringify({ experiment_batch_id: Number(expId), control_batch_id: Number(ctlId) }),
      })
      expId = ''
      ctlId = ''
      await loadCompare()
    } catch (err) {
      compareError = err.message
    }
  }

  async function unbind(id) {
    compareError = ''
    try {
      await api(`/api/pairs/${id}/unbind`, { method: 'POST' })
      await loadCompare()
    } catch (err) {
      compareError = err.message
    }
  }

  function leave() {
    localStorage.clear()
    token = ''
    role = ''
  }

  function fmtTemp(v) {
    return v === null || v === undefined ? '—' : `${v}℃`
  }

  function fmtMinutes(v) {
    return v === null || v === undefined ? '—' : `${v} 分钟`
  }

  function fmtDiff(d) {
    if (d === null || d === undefined) return '—'
    return `${d > 0 ? '+' : ''}${d}℃`
  }

  function fmtTime(s) {
    return s ? new Date(s).toLocaleString() : ''
  }

  if (token) load()
</script>

<svelte:window on:hashchange={onHash} />

{#if token}
  <nav>
    <strong>饮片炮制记录台</strong>
    <a href="#/" class:active={view === 'records'}>记录台</a>
    <a href="#/compare" class:active={view === 'compare'}>联锅对照</a>
    <span class="who">{displayName || username} · {role === 'writer' ? '炮制员' : '质检员'}</span>
    <button on:click={leave}>退出</button>
  </nav>
{/if}

<main>
  {#if !token}
    <h1>饮片炮制记录台</h1>
    <p>炮制记录整包保存。清炒温度须在 80 到 150，时长须在 5 到 30 分钟。</p>
    <input bind:value={username} />
    <input type="password" bind:value={password} />
    <button on:click={enter}>登录</button>
    <p>processor / herb123456 可写；checker / check123456 只读</p>
  {:else if view === 'records'}
    <h1>饮片炮制记录台</h1>
    {#if role === 'writer'}
      <input bind:value={herb} placeholder="饮片" />
      <input type="number" bind:value={tempC} />
      <input type="number" bind:value={minutes} />
      <button on:click={save}>写入清炒记录</button>
      {#if error}<p class="err">{error}</p>{/if}
    {/if}
    <ul>
      {#each rows as row}
        <li>#{row.id} {row.herb} · {row.verdict} · {row.reason} · 温度 {row.doc.steps[0].temp_c}</li>
      {/each}
    </ul>
  {:else}
    <h1>联锅对照实验页</h1>

    <section>
      <h2>指定对照</h2>
      {#if role === 'writer'}
        <label>
          实验锅编号
          <select bind:value={expId}>
            <option value="" disabled>选择记录</option>
            {#each rows as row}
              <option value={row.id}>#{row.id} {row.herb} · {row.verdict}</option>
            {/each}
          </select>
        </label>
        <label>
          对照锅编号
          <select bind:value={ctlId}>
            <option value="" disabled>选择记录</option>
            {#each rows as row}
              <option value={row.id}>#{row.id} {row.herb} · {row.verdict}</option>
            {/each}
          </select>
        </label>
        <button on:click={designate} disabled={!expId || !ctlId}>指定对照</button>
      {:else}
        <p>质检员可查看对照结果；指定与解除由炮制员操作。</p>
      {/if}
      {#if compareError}<p class="err">{compareError}</p>{/if}
    </section>

    <section>
      <h2>对照并排</h2>
      {#if pairs.length === 0}
        <p>当前没有进行中的联锅对照。</p>
      {:else}
        {#each pairs as pair}
          <div class="pair">
            <div class="side">
              <h3>实验锅 #{pair.experiment.batch_id} {pair.experiment.herb}</h3>
              <p>温度 {fmtTemp(pair.experiment.temp_c)}</p>
              <p>时长 {fmtMinutes(pair.experiment.minutes)}</p>
              <p>结论 {pair.experiment.verdict} · {pair.experiment.reason}</p>
            </div>
            <div class="mid">
              <p class="diff">温度差 {fmtDiff(pair.temp_diff)}</p>
              <p>{pair.same_direction ? '结论同向' : '结论不同向'}</p>
              {#if role === 'writer'}
                <button on:click={() => unbind(pair.id)}>解除对照</button>
              {/if}
            </div>
            <div class="side">
              <h3>对照锅 #{pair.control.batch_id} {pair.control.herb}</h3>
              <p>温度 {fmtTemp(pair.control.temp_c)}</p>
              <p>时长 {fmtMinutes(pair.control.minutes)}</p>
              <p>结论 {pair.control.verdict} · {pair.control.reason}</p>
            </div>
          </div>
        {/each}
      {/if}
    </section>

    <section>
      <h2>解除履历</h2>
      {#if history.length === 0}
        <p>暂无解除记录。</p>
      {:else}
        <ul>
          {#each history as h}
            <li>
              实验锅 #{h.experiment.batch_id} {h.experiment.herb} ↔ 对照锅 #{h.control.batch_id} {h.control.herb}
              · 温度差 {fmtDiff(h.temp_diff)}
              · {h.created_by} 指定
              · {h.unbound_by} 于 {fmtTime(h.unbound_at)} 解除
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  {/if}
</main>

<style>
  main { font-family: sans-serif; max-width: 720px; margin: 24px auto; color: #3f2f1f; }
  h1 { color: #7c2d12; }
  h2 { color: #7c2d12; font-size: 18px; }
  input, select { margin-right: 8px; padding: 6px; }
  .err { color: #b91c1c; }
  nav {
    font-family: sans-serif; display: flex; align-items: center; gap: 16px;
    padding: 10px 20px; background: #7c2d12; color: #fff;
  }
  nav strong { margin-right: 8px; }
  nav a { color: #fde8d8; text-decoration: none; padding: 2px 6px; border-radius: 4px; }
  nav a.active { background: #9a3412; color: #fff; font-weight: bold; }
  nav .who { margin-left: auto; font-size: 13px; }
  nav button { padding: 4px 10px; }
  section { border: 1px solid #e7d8c9; border-radius: 8px; padding: 12px 16px; margin: 16px 0; }
  .pair { display: flex; gap: 12px; align-items: stretch; margin: 12px 0; }
  .pair .side { flex: 1; border: 1px solid #e7d8c9; border-radius: 8px; padding: 8px 12px; background: #fffaf4; }
  .pair .side h3 { margin: 4px 0 8px; font-size: 15px; }
  .pair .side p { margin: 4px 0; }
  .pair .mid {
    width: 150px; display: flex; flex-direction: column; justify-content: center;
    align-items: center; text-align: center; border-radius: 8px; background: #fde8d8; padding: 8px;
  }
  .pair .mid .diff { font-weight: bold; color: #7c2d12; }
  label { margin-right: 12px; }
</style>
