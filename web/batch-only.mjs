import puppeteer from 'puppeteer-core';
import { appendFileSync } from 'node:fs';

const LOG = '/tmp/batch-only.log';
appendFileSync(LOG, `\n=== run ${Date.now()} ===\n`);
const log = (...a) => appendFileSync(LOG, a.join(' ') + '\n');

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const WAV = '/tmp/test_audio.wav';
const WAV2 = '/tmp/test_audio2.wav';

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-gpu'],
});
const page = await browser.newPage();
const consoleMsgs = [];
page.on('console', m => consoleMsgs.push(`[${m.type()}] ${m.text()}`));
page.on('pageerror', e => consoleMsgs.push(`[pageerror] ${e}`));

await page.goto('http://127.0.0.1:8099', { waitUntil: 'networkidle0' });
log('page loaded');

const input = await page.$('input[type=file]');
await input.uploadFile(WAV, WAV2);
log('uploaded 2 files');

for (let i = 0; i < 30; i++) {
  await new Promise(r => setTimeout(r, 1000));
  const st = await page.evaluate(() => {
    const bp = document.querySelector('.batch-progress');
    const bs = document.querySelector('.batch-section');
    const err = document.querySelector('.error-box');
    return {
      dbg: (window.__dbg || []).join(' | '),
      batchProgress: !!(bp && bp.classList.contains('active')),
      bpText: bp ? bp.textContent.replace(/\s+/g, ' ').trim().slice(0, 100) : null,
      batchSection: !!(bs && bs.classList.contains('active')),
      bsRows: bs ? bs.querySelectorAll('tbody tr').length : null,
      error: err ? err.textContent : null,
    };
  });
  log(`t+${i + 1}s`, JSON.stringify(st));
  if (st.batchSection) break;
}

log('--- console ---');
log(consoleMsgs.join('\n') || '(none)');
await browser.close();
log('done');
