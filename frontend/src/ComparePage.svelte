<script>
  import { onMount } from 'svelte'

  export let token = ''
  export let role = ''

  let active = []
  let history = []
  let batches = []
  let experimentId = ''
  let controlId = ''
  let error = ''

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

  async function load() {
    const [a, h, b] = await Promise.all([
      api('/api/comparisons'),
      api('/api/comparisons/history'),
      api('/api/batches'),
    ])
    active = a
    history = h
    batches = b
  }

  async function designate() {
    error = ''
    const exp = Number(experimentId)
    const ctl = Number(controlId)
    if (!exp || !ctl) {
      error = '请填写实验锅与对照锅两笔编号'
      return
    }
    if (exp === ctl) {
      error = '实验锅与对照锅不能是同一笔'
      return
    }
    try {
      await api('/api/comparisons', {
        method: 'POST',
        body: JSON.stringify({ experiment_id: exp, control_id: ctl }),
      })
      experimentId = ''
      controlId = ''
      await load()
    } catch (err) {
      error = err.message
    }
  }

  async function release(id) {
    error = ''
    try {
      await api(`/api/comparisons/${id}/release`, { method: 'POST' })
      await load()
    } catch (err) {
      error = err.message
    }
  }

  function fmt(t) {
    return t ? new Date(t).toLocaleString('zh-CN', { hour12: false }) : ''
  }

  $: potList = batches.map((b) => `#${b.id}（${b.herb}）`).join('、')

  function signed(n) {
    if (n === null || n === undefined) return '—'
    return n > 0 ? `+${n}` : `${n}`
  }

  onMount(load)
</script>

<section class="compare-page">
  <h2>联锅对照</h2>

  {#if role === 'writer'}
    <div class="designate">
      <h3>指定对照</h3>
      <label>
        实验锅编号
        <input type="number" min="1" bind:value={experimentId} list="pot-ids" placeholder="如 1" />
      </label>
      <label>
        对照锅编号
        <input type="number" min="1" bind:value={controlId} list="pot-ids" placeholder="如 2" />
      </label>
      <button on:click={designate}>建立联锅对照</button>
      <datalist id="pot-ids">
        {#each batches as b}
          <option value={b.id}>#{b.id} {b.herb} · {b.verdict}</option>
        {/each}
      </datalist>
      {#if error}<p class="error">{error}</p>{/if}
      <p class="hint">在册锅次：{potList}</p>
    </div>
  {:else}
    <p class="hint">质检员可查看本页对照与履历；指定与解除仅炮制员可操作。</p>
  {/if}

  <h3>生效对照</h3>
  {#if active.length === 0}
    <p class="empty">暂无生效中的联锅对照。</p>
  {:else}
    <div class="pair-list">
      {#each active as pair}
        <article class="pair">
          <div class="pair-head">
            <span>对照单 #{pair.id}</span>
            <span>指定人 {pair.created_by} · {fmt(pair.created_at)}</span>
            {#if role === 'writer'}
              <button class="release" on:click={() => release(pair.id)}>解除对照</button>
            {/if}
          </div>
          <div class="grid">
            <div class="pot experiment">
              <h4>实验锅 #{pair.experiment_id}</h4>
              <p class="herb">{pair.experiment_herb}</p>
              <p>清炒温度 <strong>{pair.experiment_temp ?? '—'}</strong> ℃</p>
              <p>清炒时长 <strong>{pair.experiment_minutes ?? '—'}</strong> 分钟</p>
              <p class="verdict {pair.experiment_verdict === '放行' ? 'pass' : 'reject'}">
                结论：{pair.experiment_verdict}
              </p>
              <p class="reason">{pair.experiment_reason}</p>
            </div>
            <div class="delta">
              <p class="delta-label">服务端核算</p>
              <p class="temp-diff">温度差</p>
              <p class="diff-value">{signed(pair.temp_diff)} ℃</p>
              <p class="sub">实验 − 对照</p>
              <p class="temp-diff">时长差 {signed(pair.minutes_diff)} 分</p>
              <p class="same {pair.verdict_same ? 'yes' : 'no'}">
                结论{pair.verdict_same ? '同向' : '异向'}
              </p>
            </div>
            <div class="pot control">
              <h4>对照锅 #{pair.control_id}</h4>
              <p class="herb">{pair.control_herb}</p>
              <p>清炒温度 <strong>{pair.control_temp ?? '—'}</strong> ℃</p>
              <p>清炒时长 <strong>{pair.control_minutes ?? '—'}</strong> 分钟</p>
              <p class="verdict {pair.control_verdict === '放行' ? 'pass' : 'reject'}">
                结论：{pair.control_verdict}
              </p>
              <p class="reason">{pair.control_reason}</p>
            </div>
          </div>
        </article>
      {/each}
    </div>
  {/if}

  <h3>解除履历</h3>
  {#if history.length === 0}
    <p class="empty">暂无解除记录。</p>
  {:else}
    <table class="history">
      <thead>
        <tr>
          <th>对照单</th><th>实验锅</th><th>对照锅</th><th>温度差</th>
          <th>结论</th><th>指定人 / 时间</th><th>解除人 / 时间</th>
        </tr>
      </thead>
      <tbody>
        {#each history as pair}
          <tr>
            <td>#{pair.id}</td>
            <td>#{pair.experiment_id} {pair.experiment_herb}</td>
            <td>#{pair.control_id} {pair.control_herb}</td>
            <td>{signed(pair.temp_diff)} ℃</td>
            <td>
              {pair.experiment_verdict} / {pair.control_verdict}
              （{pair.verdict_same ? '同向' : '异向'}）
            </td>
            <td>{pair.created_by}<br />{fmt(pair.created_at)}</td>
            <td>{pair.released_by}<br />{fmt(pair.released_at)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>

<style>
  .compare-page h2 {
    color: #7c2d12;
  }
  .designate {
    border: 1px solid #d6c3ad;
    background: #fbf5ec;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 20px;
  }
  .designate label {
    display: inline-flex;
    flex-direction: column;
    font-size: 13px;
    margin-right: 12px;
  }
  .designate input {
    margin-top: 4px;
    padding: 6px;
    width: 140px;
  }
  .hint {
    color: #8a6d4b;
    font-size: 13px;
  }
  .error {
    color: #b91c1c;
  }
  .pair {
    border: 1px solid #d6c3ad;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 16px;
  }
  .pair-head {
    display: flex;
    align-items: center;
    gap: 16px;
    font-size: 13px;
    color: #6b5740;
    margin-bottom: 10px;
  }
  .release {
    margin-left: auto;
  }
  .grid {
    display: grid;
    grid-template-columns: 1fr 12em 1fr;
    gap: 0;
    align-items: stretch;
  }
  .pot {
    border: 1px solid #e2d4bf;
    border-radius: 8px;
    padding: 10px 14px;
    background: #fffdf8;
  }
  .pot.experiment {
    border-left: 4px solid #7c2d12;
  }
  .pot.control {
    border-left: 4px solid #1d4ed8;
  }
  .pot h4 {
    margin: 4px 0;
  }
  .pot .herb {
    font-weight: bold;
    margin: 4px 0 8px;
  }
  .pot p {
    margin: 4px 0;
  }
  .reason {
    color: #8a6d4b;
    font-size: 13px;
  }
  .delta {
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    background: #f3ead9;
    border-block: 1px dashed #c9b18f;
    padding: 8px;
  }
  .delta-label {
    font-size: 12px;
    color: #8a6d4b;
    margin: 0;
  }
  .temp-diff {
    margin: 8px 0 0;
    font-size: 13px;
    color: #6b5740;
  }
  .diff-value {
    font-size: 26px;
    font-weight: bold;
    color: #7c2d12;
    margin: 2px 0;
  }
  .sub {
    font-size: 12px;
    color: #8a6d4b;
    margin: 0 0 6px;
  }
  .same {
    margin-top: 8px;
    padding: 3px 10px;
    border-radius: 999px;
    font-size: 13px;
  }
  .same.yes {
    background: #dcfce7;
    color: #166534;
  }
  .same.no {
    background: #ffedd5;
    color: #9a3412;
  }
  .verdict.pass {
    color: #166534;
    font-weight: bold;
  }
  .verdict.reject {
    color: #b91c1c;
    font-weight: bold;
  }
  .empty {
    color: #8a6d4b;
  }
  table.history {
    border-collapse: collapse;
    width: 100%;
    font-size: 13px;
  }
  .history th,
  .history td {
    border: 1px solid #e2d4bf;
    padding: 6px 8px;
    text-align: left;
    vertical-align: top;
  }
  .history th {
    background: #f3ead9;
  }
  @media (max-width: 720px) {
    .grid {
      grid-template-columns: 1fr;
    }
  }
</style>
