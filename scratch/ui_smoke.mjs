// 工作台 DOM 冒烟：用真实后端样例 payload 驱动渲染，捕获前端运行时错误
import {JSDOM} from 'file:///tmp/node_modules/jsdom/lib/api.js';
import fs from 'fs';
import path from 'path';

const root = '/workspace/app';
const html = fs.readFileSync(path.join(root, 'templates/workbench.html'), 'utf8');
const dom = new JSDOM(html, {url: 'http://localhost/', runScripts: 'outside-only', pretendToBeVisual: true});
const {window} = dom;
globalThis.window = window;
globalThis.document = window.document;
globalThis.HTMLElement = window.HTMLElement;
globalThis.Node = window.Node;
globalThis.Blob = window.Blob;
globalThis.ResizeObserver = class { observe() {} unobserve() {} };
globalThis.fetch = async () => ({ok: true, json: async () => payload});

// 用后端真实 evaluate 结果（通过 python 导出）作为 payload
const rawPayload = JSON.parse(fs.readFileSync('/tmp/ui_payload.json', 'utf8'));
const payload = {intake: {counts: {input: 8466, accepted: 6999, isolated: 1065, excluded: 399,
  duplicate: 1, blank: 1, repeated_headers: 1}, isolated_bands: [], row_issues: []}, ...rawPayload};

// 加载静态脚本（ES module 顺序）
async function load(rel) {
  const code = fs.readFileSync(path.join(root, rel), 'utf8');
  return await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
}
const panels = await load('static/panels.js');
// 直接驱动关键渲染函数，模拟 workbench.render -> choose 流程
window.HTMLElement.prototype.replaceChildren = window.HTMLElement.prototype.replaceChildren || function (...nodes) {
  while (this.firstChild) this.removeChild(this.firstChild);
  nodes.forEach((n) => this.appendChild(n));
};
panels.reconcile(payload.reconcile, 250, () => {});
panels.shorteningPanel(payload.shortening);
panels.intake(payload.intake);
const bandRows = window.document.getElementById('band-table').querySelectorAll('tbody tr');
console.log('band rows rendered:', bandRows.length);
console.log('shortened KPI:', window.document.getElementById('shortened').textContent);
console.log('remeasure KPI:', window.document.getElementById('remeasure').textContent);
console.log('excluded KPI:', window.document.getElementById('excluded').textContent);
const segBlocks = window.document.querySelectorAll('.segment-block');
console.log('segment blocks:', segBlocks.length);
const accTitle = window.document.getElementById('acceptance-title').textContent;
console.log('acceptance:', accTitle);
const blocked = [...window.document.querySelectorAll('#acceptance-body .warn')].map((n) => n.textContent);
console.log('blocked lines:', blocked);
if (bandRows.length !== 8 || segBlocks.length !== 2) { console.error('UNEXPECTED RENDER COUNTS'); process.exit(1); }
console.log('UI SMOKE OK');
