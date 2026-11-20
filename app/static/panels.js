export const $ = (id) => document.getElementById(id);
export const fixed = (value, digits = 3) => value == null ? '—' : Number(value).toFixed(digits);
const scientific = (value) => value == null ? '—' : value.toExponential(3);
const states = {
  FIT: ['可拟合', 'good'], INSUFFICIENT: ['范围不足', 'warn'], ISOLATED: ['隔离', 'bad'],
  REMEASURE: ['退回补测', 'bad'],
};
const modes = {FULL: '整带', SHORTENED: '缩短采信', BLOCKED: '段不成立', FATAL: '完整性拒收'};

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function specs(items) {
  const root = el('dl', null, 'specs');
  for (const [key, value] of items) {
    const column = el('div');
    column.append(el('dt', key), el('dd', value ?? '—'));
    root.append(column);
  }
  return root;
}

function action(label, click) {
  const button = el('button', label);
  button.type = 'button';
  button.addEventListener('click', click);
  return button;
}

function evidence(title, body) {
  $('evidence-title').textContent = title;
  $('evidence-text').textContent = JSON.stringify(body, null, 2);
  $('evidence').showModal();
}

function table(host, headers, rows, selected = -1) {
  const target = typeof host === 'string' ? $(host) : host;
  if (!rows.length) {
    target.replaceChildren(el('p', '暂无记录', 'empty'));
    return;
  }
  const node = el('table', null, 'ledger');
  const head = node.createTHead().insertRow();
  for (const title of headers) {
    const heading = el('th', title);
    heading.scope = 'col';
    head.append(heading);
  }
  const body = node.createTBody();
  rows.forEach((row, index) => {
    const tr = body.insertRow();
    if (index === selected) tr.setAttribute('aria-selected', 'true');
    for (const item of row) {
      const td = tr.insertCell();
      if (item instanceof Node) td.append(item);
      else {
        td.textContent = item ?? '—'; td.title = td.textContent;
        if (typeof item === 'number' || /^-?\d+\.\d+/.test(item ?? '')) td.className = 'num';
      }
    }
  });
  target.replaceChildren(node);
}

export function fitPanel(fit, row) {
  if (!fit) {
    $('fit-tiles').replaceChildren(el('p', row?.findings[0]?.message || '暂无可用区间', 'empty'));
    return;
  }
  $('fit-tiles').replaceChildren(...[['T20', fit.t20], ['T30', fit.t30]].map(([name, trial]) => {
    const tile = el('section', null, 'fit-tile');
    const title = el('div', null, 'tile-heading');
    title.append(el('h3', name), el('strong', `${fixed(trial.rt60_s)}${trial.rt60_s != null ? ' s' : ''}`));
    tile.append(title, el('p', `${trial.from_db} 至 ${trial.to_db} dB`, 'muted'));
    if (trial.error) tile.append(el('p', trial.error.message, 'warn'));
    if (trial.window) tile.append(specs([
      ['时段 / s', `${fixed(trial.window.start_s)}–${fixed(trial.window.end_s)}`], ['采样点', trial.window.point_count],
      ['斜率 / dB/s', fixed(trial.slope_db_s ?? trial.regression?.slope_db_s, 2)], ['R²', fixed(trial.r2 ?? trial.regression?.r2, 4)],
      ['来源行', `${trial.window.start_line} → ${trial.window.end_line}`],
    ]));
    return tile;
  }));
}

export function noisePanel(noise) {
  if (!noise) {
    $('noise-body').replaceChildren(el('p', '此频带没有可用响应', 'empty'));
    return;
  }
  const depth = el('progress', null, 'depth');
  depth.max = Math.max(60, Math.ceil(noise.usable_depth_db));
  depth.value = noise.usable_depth_db;
  depth.setAttribute('aria-label', '可用衰减深度');
  $('noise-body').replaceChildren(specs([
    ['峰值至噪声 / dB', fixed(noise.peak_to_noise_db, 1)], ['噪声功率 / Pa²', scientific(noise.noise_power_pa2)],
    ['可用深度 / dB', fixed(noise.usable_depth_db, 1)], ['噪声底 / dB', fixed(noise.floor_db, 1)],
    ['可用截止 / s', fixed(noise.usable_until_s)], ['测噪起点 / s', fixed(noise.noise_from_s)],
    ['最低余量 / dB', noise.required_margin_db], ['适用档位', noise.supports_t30 ? 'T20 / T30' : noise.supports_t20 ? 'T20' : '无'],
  ]), depth);
}

export function reconcile(data, band, pick) {
  const totals = data.totals;
  for (const key of ['fitted', 'insufficient', 'flagged']) $(key).textContent = totals[key];
  $('shortened').textContent = totals.shortened ?? 0;
  $('remeasure').textContent = totals.remeasure ?? 0;
  $('excluded').textContent = totals.excluded_rows ?? 0;
  $('balance').textContent = data.status === 'MATCHED' ? '频带、样本已对平' : `存在勾稽差额（行 ${totals.row_difference} / 带 ${totals.band_difference}）`;
  table('band-table', ['Hz', '判定', '采信方式', 'T20 / s', 'T30 / s', '标差', '证据'], data.bands.map((row) => {
    const [label, style] = states[row.status];
    const adopted = row.shortening?.adopted_lines;
    const range = adopted ? el('span', `行 ${adopted.first}–${adopted.last}`, 'muted') : (modes[row.mode] ?? '—');
    return [action(`${row.band_hz}`, () => pick(row.band_hz)), el('span', label, `status-label ${style}`),
      el('span', modes[row.mode] ?? '—', row.mode === 'SHORTENED' ? 'status-label good' : 'muted'),
      fixed(row.t20_s), fixed(row.t30_s), row.gap_flag ? el('span', `${fixed(100 * row.relative_gap, 1)}%`, 'warn') : '—',
      action('查看', () => evidence(`${row.band_hz} Hz 判定`, row))];
  }), data.bands.findIndex((row) => row.band_hz === band));
  renderAcceptance(data);
}

function renderAcceptance(data) {
  const panel = $('acceptance-panel');
  const acceptance = data.acceptance;
  if (!acceptance) { panel.hidden = true; return; }
  panel.hidden = false;
  const ok = acceptance.acceptable;
  $('acceptance-title').textContent = ok ? '缩短结果可验收' : '缩短结果不可整体验收，存在退回补测频带';
  $('acceptance-title').className = ok ? 'good-text' : 'bad-text';
  $('acceptance-meta').textContent = `整带拟合 ${acceptance.full_fit_bands} · 缩短采信 ${acceptance.shortened_fit_bands} · 退回补测 ${acceptance.remeasure_bands} · 范围不足 ${acceptance.insufficient_bands}`;
  const blocked = data.bands.filter((row) => row.status === 'REMEASURE')
    .map((row) => `${row.band_hz} Hz（${modes[row.mode]}：${(row.findings || []).map((f) => f.code).join('、')}）`);
  const shortened = data.bands.filter((row) => row.mode === 'SHORTENED')
    .map((row) => `${row.band_hz} Hz 采信行 ${row.shortening.adopted_lines.first}–${row.shortening.adopted_lines.last}`);
  $('acceptance-body').replaceChildren(
    el('p', ok ? '所有频带均有可发布拟合或仅为动态范围不足，无退回补测项。' : '以下频带必须补测后才能整体验收：', ok ? 'good-text' : 'bad-text'),
    ...blocked.map((text) => el('p', `• ${text}`, 'warn')),
    ...shortened.map((text) => el('p', `• 缩短保留：${text}（曲线、拟合、归档对账至同一采信行）`, 'muted')),
  );
}

export function shorteningPanel(shortening) {
  const host = $('shortening-body');
  if (!shortening || !shortening.bands.length) {
    host.replaceChildren(el('p', '该来源没有坏行断开的频带，全部按整带连续采样处理。', 'empty'));
    return;
  }
  const blocks = shortening.bands.map((item) => {
    const wrap = el('div', null, 'segment-block');
    const head = el('div', null, 'segment-head');
    head.append(el('strong', `${item.band_hz} Hz`),
      el('span', item.adopted_label ? `采信 ${item.adopted_label} · ${item.reason.message}` : `退回补测 · ${item.reason.message}`,
        item.adopted_label ? 'status-label good' : 'status-label bad'));
    const rows = item.segments.map((seg) => [
      seg.label, `序号 ${seg.start_index}–${seg.end_index}`, `行 ${seg.first_line}–${seg.last_line}`, seg.sample_count,
      fixed(seg.usable_depth_db, 1),
      seg.adopted ? el('span', '采信', 'status-label good') : seg.admissible ? el('span', '留档未采信', 'status-label warn')
        : el('span', `挡下 · ${seg.block_reason?.code ?? ''}`, 'status-label bad'),
      fixed(seg.t20_rt60_s), fixed(seg.t30_rt60_s),
    ]);
    const holder = el('div', null, 'shortening-table');
    table(holder, ['连续段', '采样序号', '来源行', '点数', '可用深度/dB', '处置', 'T20/s', 'T30/s'], rows);
    wrap.append(head, holder);
    return wrap;
  });
  host.replaceChildren(...blocks);
}

export function intake(data) {
  const count = data.counts;
  $('intake-data').replaceChildren(specs([['编码', data.encoding], ['输入记录', count.input], ['采信', count.accepted],
    ['隔离', count.isolated], ['排除段', count.excluded ?? 0], ['重复', count.duplicate], ['空白', count.blank],
    ['重复表头', count.repeated_headers]]));
  const findings = data.isolated_bands.flatMap((band) => band.findings.map((item) => ({band_hz: band.band_hz, ...item})));
  const rows = [...findings, ...data.row_issues];
  table('intake-issues', ['频带 / Hz', '来源行', '原因码', '证据'], rows.map((row) => [row.band_hz, row.line ?? row.lines?.join('、'),
    row.code, action('查看', () => evidence(row.message, row))]));
}

export function calibration(data) {
  table('calibration-data', ['Hz', '输入单位', '增益 / dB', '系数 / Pa', '峰值 / Pa', 'RMS / Pa', '来源行'], data.bands.map((row) => [
    row.band_hz, row.input.unit, row.input.gain_db, scientific(row.factor_pa), fixed(row.peak_pa, 5), fixed(row.rms_pa, 5), row.peak_line,
  ]));
}

export function history(runs, current, pick) {
  table('run-list', ['批次', '来源摘要', '规则', '归档时间 UTC', '耗时 ms', '结果摘要'], runs.map((row) => [
    action(row.id.slice(0, 12), () => pick(row.id)), row.source_id.slice(0, 12), row.version, row.created_at.slice(0, 19).replace('T', ' '),
    row.elapsed_ms, action(row.digest.slice(0, 12), () => evidence('运行清单', row)),
  ]), runs.findIndex((row) => row.id === current));
}
