export async function analyzeFile(file) {
  const form = new FormData();
  form.append('file', file);
  const resp = await fetch('/api/analyze', { method: 'POST', body: form });
  let data = null;
  try { data = await resp.json(); } catch { /* empty */ }
  if (!resp.ok) {
    throw new Error(data?.detail || 'Analysis failed');
  }
  return data;
}

export async function getSpectrogram(fileId) {
  const resp = await fetch('/api/spectrogram/' + fileId);
  if (!resp.ok) throw new Error('Spectrogram failed');
  return resp.json();
}

export async function getWaveform(fileId) {
  const resp = await fetch('/api/waveform/' + fileId);
  if (!resp.ok) throw new Error('Waveform failed');
  return resp.json();
}
