import { t } from './i18n.svelte.js';
import { getSpectrogram, getWaveform } from './api.js';

export async function loadSpectrogram(fileId) {
  if (!fileId) return;
  const Plotly = window.Plotly;
  if (!Plotly) return;
  try {
    const data = await getSpectrogram(fileId);
    const trace = {
      z: data.magnitudes_db,
      x: data.times,
      y: data.freqs,
      type: 'heatmap',
      colorscale: [
        [0, '#1a1a2e'],
        [0.2, '#0f3460'],
        [0.4, '#533483'],
        [0.6, '#e94560'],
        [0.8, '#ffd600'],
        [1, '#ffffff'],
      ],
      zmin: -120,
      zmax: 0,
      colorbar: { title: { text: t('mag'), font: { color: '#e0e0e0', size: 11 } }, tickfont: { color: '#a0a0b0', size: 10 } },
    };
    const layout = {
      xaxis: { title: t('time'), color: '#e0e0e0', gridcolor: '#2a2a4a', zeroline: false },
      yaxis: { title: t('freq'), type: 'log', color: '#e0e0e0', gridcolor: '#2a2a4a', zeroline: false,
        tickformat: ',d', dtick: 1, range: [Math.log10(Math.max(20, data.freqs[1])), Math.log10(data.max_freq)] },
      paper_bgcolor: '#16213e',
      plot_bgcolor: '#1a1a2e',
      font: { color: '#e0e0e0' },
      margin: { l: 60, r: 30, t: 10, b: 50 },
      height: 400,
    };
    return Plotly.newPlot('specChart', [trace], layout, { responsive: true, displayModeBar: false });
  } catch (e) { console.error('Spectrogram error:', e); }
}

export async function loadWaveform(fileId) {
  if (!fileId) return;
  const Plotly = window.Plotly;
  if (!Plotly) return;
  try {
    const data = await getWaveform(fileId);
    const trace = {
      x: data.times,
      y: data.samples,
      type: 'scatter',
      mode: 'lines',
      line: { color: '#e94560', width: 1 },
      fill: 'tozeroy',
      fillcolor: 'rgba(233,69,96,0.15)',
    };
    const layout = {
      xaxis: { title: t('time'), color: '#e0e0e0', gridcolor: '#2a2a4a', zeroline: true, zerolinecolor: '#2a2a4a' },
      yaxis: { title: t('amp'), color: '#e0e0e0', gridcolor: '#2a2a4a', zeroline: true, zerolinecolor: '#2a2a4a', range: [-1, 1] },
      paper_bgcolor: '#16213e',
      plot_bgcolor: '#1a1a2e',
      font: { color: '#e0e0e0' },
      margin: { l: 50, r: 20, t: 10, b: 50 },
      height: 250,
    };
    return Plotly.newPlot('waveChart', [trace], layout, { responsive: true, displayModeBar: false });
  } catch (e) { console.error('Waveform error:', e); }
}

export async function ensureChartsRendered(fileId) {
  const spec = document.getElementById('specChart');
  if (!spec || !spec.data) { try { await loadSpectrogram(fileId); } catch { /* empty */ } }
  const wave = document.getElementById('waveChart');
  if (!wave || !wave.data) { try { await loadWaveform(fileId); } catch { /* empty */ } }
  await new Promise(r => setTimeout(r, 150));
}

export function purgeCharts() {
  const Plotly = window.Plotly;
  if (!Plotly) return;
  try { Plotly.purge('specChart'); } catch { /* empty */ }
  try { Plotly.purge('waveChart'); } catch { /* empty */ }
}
