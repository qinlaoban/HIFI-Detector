import puppeteer from 'puppeteer-core';
import { appendFileSync } from 'node:fs';

const LOG = '/tmp/e2e.log';
appendFileSync(LOG, `\n=== run ${Date.now()} ===\n`);
function log(...a) { appendFileSync(LOG, a.join(' ') + '\n'); }

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const BASE = 'http://127.0.0.1:8099';
const WAV = '/tmp/test_audio.wav';

const sleep = ms => new Promise(r => setTimeout(r, ms));

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-gpu'],
});
const page = await browser.newPage();
const errors = [];
const dbg = [];
page.on('console', m => {
  if (m.type() === 'error') errors.push(m.text());
  if (m.type() === 'log' && m.text().includes('[dbg]')) dbg.push(m.text());
});
page.on('pageerror', e => errors.push(String(e)));

async function step(name) {
  const pct = process.env.CI ? '' : '';
  console.log(`[step] ${name}`);
}

// 1. 首页
await page.goto(BASE, { waitUntil: 'networkidle0' });
await step('首页加载: dropzone=' + (await page.$('input[type=file]') !== null));

// 2. 单文件上传
const input = await page.$('input[type=file]');
await input.uploadFile(WAV);
await step('上传触发，等待结果...');
await page.waitForSelector('.results.active', { timeout: 30000 });
await sleep(1500);

const verdict = await page.$eval('.results .verdict', el => el.textContent.trim());
const hires = await page.$eval('.hires-hero', el => el.textContent.trim().slice(0, 60));
const summary = await page.$eval('.summary-headline', el => el.textContent.trim());
const infoItems = await page.$$eval('.info-item', els => els.length);
const metricRows = await page.$$eval('.metric-row', els => els.length);
await step(`verdict="${verdict}" | hires="${hires}" | summary="${summary}" | info=${infoItems} metrics=${metricRows}`);

// 3. 图表 tab
await page.$$eval('.tab-btn', (els) => els.find(e => e.textContent.includes('Spectrogram')).click());
await sleep(2500);
const specRendered = await page.evaluate(() => {
  const el = document.querySelector('#specChart');
  return el && el.data && el.data.length ? el.data[0].type : null;
});
await page.$$eval('.tab-btn', (els) => els.find(e => e.textContent.includes('Waveform')).click());
await sleep(2500);
const waveRendered = await page.evaluate(() => {
  const el = document.querySelector('#waveChart');
  return el && el.data && el.data.length ? el.data[0].type : null;
});
await step(`spectrogram=${specRendered} waveform=${waveRendered}`);

// 4. 报告下载（graphic 默认 → 切 text 再下载）
const client = await page.target().createCDPSession();
await client.send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: '/tmp/hifi-dl' });
await page.click('.download-btn');
await sleep(4000);
await page.$$eval('.rpt-btn', (els) => els.find(e => e.textContent.includes('Text')).click());
await sleep(500);
await page.click('.download-btn');
await sleep(2500);
await step('报告下载触发完成');

// 5. 返回上传（单文件场景 analyzeAnother）
await page.click('.btn-row .btn');
await sleep(800);
const backToUpload1 = await page.$('.dropzone') !== null;
await step(`analyzeAnother → upload=${backToUpload1}`);

// 6. 批量上传（2 个 wav）
const input2 = await page.$('input[type=file]');
await input2.uploadFile(WAV, '/tmp/test_audio2.wav');
await page.waitForSelector('.batch-section.active', { timeout: 30000 });
await sleep(1200);
const rows = await page.$$eval('.batch-table tbody tr', els => els.length);
const badge = await page.$eval('.batch-summary', el => el.textContent.trim().replace(/\s+/g, ' '));
await step(`batch rows=${rows} | badge="${badge}"`);

// 行点击详情
await page.click('.batch-table tbody tr');
await sleep(2500);
const detailShown = await page.$('.results.active') !== null;
const fromBatch = await page.$eval('.btn-row .btn', el => el.textContent.trim());
await step(`batch detail shown=${detailShown} backBtn="${fromBatch}"`);

// 返回批量
await page.click('.btn-row .btn');
await sleep(800);
const backToBatch = await page.$('.batch-section.active') !== null;
await step(`back to batch=${backToBatch}`);

// 批量重置 → 上传
await page.click('.batch-section .btn');
await sleep(800);
const backToUpload = await page.$('.dropzone') !== null;
await step(`back to upload=${backToUpload}`);

console.log('=== JS errors ===');
console.log(errors.length ? errors.join('\n') : '(none)');
console.log('=== dbg logs ===');
console.log(dbg.length ? dbg.join('\n') : '(none)');
await browser.close();
console.log('E2E DONE');
