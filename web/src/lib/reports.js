import { t, fmt } from './i18n.svelte.js';
import { escapeHtml, formatFileSize, fmtDuration } from './utils.js';
import { ensureChartsRendered } from './charts.js';

function reportFileName(filename, ext) {
  const fname = (filename || 'hifi-report').replace(/\.[^.]+$/, '');
  const ts = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
  return `HIFI-Report_${fname}_${ts}.${ext}`;
}

function downloadBlob(content, filename, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function tpMaxOf(d) {
  const l = d.loudness;
  return l.true_peak_r_dbtp !== null ? Math.max(l.true_peak_l_dbtp, l.true_peak_r_dbtp) : l.true_peak_l_dbtp;
}

export async function buildHtmlReport(d) {
  const Plotly = window.Plotly;
  let specImg = '', waveImg = '';
  try { specImg = await Plotly.toImage('specChart', { format: 'png', width: 1000, height: 400 }); } catch (e) { console.warn('spec export failed', e); }
  try { waveImg = await Plotly.toImage('waveChart', { format: 'png', width: 1000, height: 250 }); } catch (e) { console.warn('wave export failed', e); }

  const m = d.metadata, q = d.quality, l = d.loudness, dr = d.dynamic_range, a = d.authenticity;
  const tpMax = tpMaxOf(d);
  const now = new Date().toLocaleString();

  const verdictMap = { HIGH_QUALITY: 'High Quality', CLEAN: 'Clean', WARN: 'Minor Issues', ISSUES: 'Issues Detected' };
  const verdict = verdictMap[d.verdict] || d.verdict;

  const row = (label, value) =>
    `<tr><td style="padding:6px 12px;border-bottom:1px solid #eee;color:#555">${label}</td><td style="padding:6px 12px;border-bottom:1px solid #eee;font-weight:600">${value}</td></tr>`;
  const mRow = (label, value, status) => {
    const col = status === 'red' ? '#e94560' : status === 'yellow' ? '#d4a017' : status === 'green' ? '#2e7d32' : '#555';
    return `<tr><td style="padding:6px 12px;border-bottom:1px solid #eee;color:#555">${label}</td><td style="padding:6px 12px;border-bottom:1px solid #eee;font-weight:600;color:${col}">${value}</td></tr>`;
  };

  const infoTable = `<table style="border-collapse:collapse;width:100%;font-size:13px;margin:8px 0">` +
    row(t('format'), m.format) + row(t('subtype'), m.subtype) +
    row(t('sampleRate'), (m.sample_rate / 1000).toFixed(1) + ' kHz') + row(t('bitDepth'), m.bit_depth + ' bit') +
    row(t('channels'), m.channels + ' ch') + row(t('duration'), fmtDuration(m.duration_s)) +
    row(t('fileSize'), formatFileSize(m.file_size_bytes)) +
    (m.bitrate_kbps ? row(t('bitrate'), m.bitrate_kbps + ' kbps' + (m.bitrate_pcm_kbps ? ' / PCM ' + m.bitrate_pcm_kbps + ' kbps' : '')) : '') + `</table>`;

  const qTable = `<table style="border-collapse:collapse;width:100%;font-size:13px;margin:8px 0">` +
    mRow(t('clipping'), q.clipping.samples > 0 ? q.clipping.samples + ' ' + t('samples') : t('clean'), q.clipping.samples > 0 ? 'red' : 'green') +
    mRow(t('dcOffset'), q.dc_offset_pct.toFixed(2) + '%', q.dc_offset_pct > 0.1 ? 'yellow' : 'green') +
    mRow(t('chanBalance'), q.channel_balance_db.toFixed(1) + ' dB', q.channel_balance_db > 1 ? 'yellow' : 'green') +
    mRow(t('truePeak'), tpMax.toFixed(2) + ' dBTP', tpMax > -0.1 ? 'red' : tpMax > -1 ? 'yellow' : 'green') +
    mRow(t('dynamicRange'), 'DR ' + dr.dr_official, dr.dr_official >= 10 ? 'green' : 'red') +
    mRow(t('rmsLevel'), l.rms_l_dbfs.toFixed(1) + ' dBFS', 'dim') +
    mRow(t('integratedLUFS'), l.integrated_lufs.toFixed(1) + ' LUFS', 'dim') +
    mRow(t('loudnessRange'), l.loudness_range_lu.toFixed(1) + ' LU', 'dim') +
    mRow(t('bitDepthAuth'), q.bit_depth_suspicious ? t('suspect') + ' (' + m.bit_depth + '→' + q.effective_bits + ')' : t('ok'), q.bit_depth_suspicious ? 'yellow' : 'green') +
    `</table>`;

  const aTable = `<table style="border-collapse:collapse;width:100%;font-size:13px;margin:8px 0">` +
    mRow(t('spectralCutoff'), a.has_sharp_cutoff ? (a.cutoff_freq_hz || 0).toFixed(0) + ' Hz (' + (a.cutoff_suspected_codec || t('unknown')) + ')' : t('noneDetected'), a.has_sharp_cutoff ? 'red' : 'green') +
    mRow(t('upsampling'), a.is_suspected_upsampled ? '~' + (a.upsample_source_rate_hint || 0) + ' Hz' : t('notDetected'), a.is_suspected_upsampled ? 'red' : 'green') +
    mRow(t('bit24Auth'), (!a.low_bits_active && m.bit_depth >= 24) ? t('suspect') : t('ok'), (!a.low_bits_active && m.bit_depth >= 24) ? 'yellow' : 'green') +
    `</table>`;

  const summaryHtml = buildSummaryHtml(d);
  const specBlock = specImg ? `<img src="${specImg}" style="width:100%;border:1px solid #ddd;border-radius:6px;margin:8px 0">` : `<p style="color:#999">Spectrogram unavailable</p>`;
  const waveBlock = waveImg ? `<img src="${waveImg}" style="width:100%;border:1px solid #ddd;border-radius:6px;margin:8px 0">` : `<p style="color:#999">Waveform unavailable</p>`;

  return `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>HIFI Detector Report — ${d.filename}</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Hiragino Sans GB',sans-serif;max-width:860px;margin:0 auto;padding:32px;color:#222;line-height:1.6}
  h1{font-size:22px;margin:0 0 4px} .sub{color:#888;font-size:13px;margin-bottom:24px}
  h2{font-size:16px;border-bottom:2px solid #e94560;padding-bottom:6px;margin:28px 0 12px}
  .verdict{padding:14px 20px;border-radius:8px;font-size:18px;font-weight:700;text-align:center;margin:16px 0;background:#1b5e20;color:#69f0ae}
  .footer{margin-top:32px;padding-top:16px;border-top:1px solid #eee;color:#aaa;font-size:12px}
</style></head><body>
  <h1>HIFI Detector — Audio Analysis Report</h1>
  <div class="sub">${d.filename} · Generated ${now}</div>
  <div class="verdict">${verdict}</div>
  <h2>Summary & Recommendation</h2>
  ${summaryHtml}
  <h2>Audio Info</h2>
  ${infoTable}
  <h2>Quality Analysis</h2>
  ${qTable}
  <h2>Authenticity</h2>
  ${aTable}
  <h2>Spectrogram</h2>
  ${specBlock}
  <h2>Waveform</h2>
  ${waveBlock}
  <div class="footer">Generated by HIFI Detector — Offline audio authenticity & quality detection. No files were uploaded.</div>
</body></html>`;
}

function buildSummaryHtml(d) {
  const q = d.quality, l = d.loudness, dr = d.dynamic_range, a = d.authenticity, m = d.metadata;
  const tpMax = tpMaxOf(d);

  const authVerdict = a.verdict || (a.is_suspicious ? 'suspicious' : 'clean');
  const authMap = {
    clean: { key: 'summaryAuthClean', color: '#2e7d32' },
    ambiguous: { key: 'summaryAuthAmbiguous', color: '#d4a017' },
    suspicious: { key: 'summaryAuthSuspicious', color: '#e94560' },
  };
  const authInfo = authMap[authVerdict] || authMap.clean;

  const qIssues = [];
  if (tpMax > 0.5) qIssues.push('peak');
  if (q.clipping.samples > 0) qIssues.push('clip');
  if (q.dc_offset_pct > 0.1) qIssues.push('dc');
  if (q.channel_balance_db > 1) qIssues.push('balance');
  if (dr.dr_official < 6) qIssues.push('dr');
  const fairNotices = [];
  if (tpMax > 0 && tpMax <= 0.5) fairNotices.push('peak_notice');
  if (dr.dr_official >= 6 && dr.dr_official < 8) fairNotices.push('dr_notice');
  const hasMajor = qIssues.includes('clip') || qIssues.includes('peak');
  const hasMinor = qIssues.includes('dc') || qIssues.includes('balance') || qIssues.includes('dr') || fairNotices.length > 0;
  const qualityGrade = hasMajor ? 'poor' : hasMinor ? 'fair' : 'good';
  const qualityMap = {
    good: { key: 'summaryQualityGood', color: '#2e7d32' },
    fair: { key: 'summaryQualityFair', color: '#d4a017' },
    poor: { key: 'summaryQualityPoor', color: '#e94560' },
  };
  const qualityInfo = qualityMap[qualityGrade];

  let h = '';

  h += `<div style="margin-bottom:16px">`;
  h += `<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:4px">${t('summaryAuthTitle')}</div>`;
  h += `<div style="font-size:14px;font-weight:600;color:${authInfo.color};margin-bottom:4px">${t(authInfo.key)}</div>`;
  if (m.bitrate_low && m.bitrate_kbps && m.bitrate_pcm_kbps) {
    h += `<div style="font-size:12px;color:#d4a017;margin-top:4px;padding:6px 10px;background:#fff8e1;border-radius:4px">${fmt(t('summaryBitrateLow'), { actual: m.bitrate_kbps, pcm: m.bitrate_pcm_kbps })}</div>`;
  }
  if (a.suspicion_reasons && a.suspicion_reasons.length > 0) {
    h += '<ul style="margin:6px 0 0 0;padding-left:20px;line-height:1.7">';
    for (const reason of a.suspicion_reasons) h += `<li style="font-size:12px;color:#666">${reason}</li>`;
    h += '</ul>';
  }
  h += '</div>';

  h += `<div>`;
  h += `<div style="font-size:13px;font-weight:600;color:#888;margin-bottom:4px">${t('summaryQualityTitle')}</div>`;
  h += `<div style="font-size:14px;font-weight:600;color:${qualityInfo.color};margin-bottom:4px">${t(qualityInfo.key)}</div>`;
  if (qIssues.length === 0 && fairNotices.length === 0) {
    h += `<p style="color:#2e7d32;font-size:13px">${t('summaryTipClean')}</p>`;
  } else {
    if (qIssues.length > 0) {
      const tipMap = { peak: 'summaryTipPeak', clip: 'summaryTipClip', dc: 'summaryTipDC', balance: 'summaryTipBalance', dr: 'summaryTipDR' };
      const vars = { tp: tpMax != null ? tpMax.toFixed(1) : '—', n: q.clipping.samples, dc: q.dc_offset_pct.toFixed(2), bal: q.channel_balance_db.toFixed(1), dr: dr.dr_official };
      h += '<ul style="margin:6px 0 0 0;padding-left:20px;line-height:1.7">';
      for (const issue of qIssues) h += `<li style="font-size:12px">${fmt(t(tipMap[issue]), vars)}</li>`;
      h += '</ul>';
    }
    if (fairNotices.length > 0) {
      const noticeMap = { peak_notice: 'summaryTipPeakNotice', dr_notice: 'summaryTipDRNotice' };
      const vars2 = { tp: tpMax != null ? tpMax.toFixed(1) : '—', dr: dr.dr_official };
      h += '<ul style="margin:4px 0 0 0;padding-left:20px;line-height:1.7">';
      for (const n of fairNotices) h += `<li style="font-size:11px;color:#999">${fmt(t(noticeMap[n]), vars2)}</li>`;
      h += '</ul>';
    }
  }
  h += `<div style="margin-top:8px;font-size:11px;color:#999;border-top:1px solid #eee;padding-top:8px">${t('summaryQualityGenreNote')}</div>`;
  h += '</div>';

  return h;
}

export function buildTextReport(d) {
  const m = d.metadata, q = d.quality, l = d.loudness, dr = d.dynamic_range, a = d.authenticity;
  const tpMax = tpMaxOf(d);
  const now = new Date().toLocaleString();
  const L = [];
  L.push('# HIFI Detector — Audio Analysis Report');
  L.push('');
  L.push(`**File:** ${d.filename}`);
  L.push(`**Generated:** ${now}`);
  L.push('');

  const verdictMap = { HIGH_QUALITY: 'High Quality', CLEAN: 'Clean', WARN: 'Minor Issues', ISSUES: 'Issues Detected' };
  L.push(`## Verdict: ${verdictMap[d.verdict] || d.verdict}`);
  L.push('');

  const authVerdict = a.verdict || (a.is_suspicious ? 'suspicious' : 'clean');
  const authKeyMap = { clean: 'summaryAuthClean', ambiguous: 'summaryAuthAmbiguous', suspicious: 'summaryAuthSuspicious' };
  L.push('## ' + t('summaryAuthTitle'));
  L.push(t(authKeyMap[authVerdict] || 'summaryAuthClean'));
  if (m.bitrate_low && m.bitrate_kbps && m.bitrate_pcm_kbps) {
    L.push('- ' + fmt(t('summaryBitrateLow'), { actual: m.bitrate_kbps, pcm: m.bitrate_pcm_kbps }));
  }
  if (a.suspicion_reasons && a.suspicion_reasons.length > 0) {
    for (const reason of a.suspicion_reasons) L.push('- ' + reason);
  }
  L.push('');

  const qIssues = [];
  if (tpMax > 0.5) qIssues.push('peak');
  if (q.clipping.samples > 0) qIssues.push('clip');
  if (q.dc_offset_pct > 0.1) qIssues.push('dc');
  if (q.channel_balance_db > 1) qIssues.push('balance');
  if (dr.dr_official < 6) qIssues.push('dr');
  const fairNotices = [];
  if (tpMax > 0 && tpMax <= 0.5) fairNotices.push('peak_notice');
  if (dr.dr_official >= 6 && dr.dr_official < 8) fairNotices.push('dr_notice');
  const hasMajor = qIssues.includes('clip') || qIssues.includes('peak');
  const hasMinor = qIssues.includes('dc') || qIssues.includes('balance') || qIssues.includes('dr') || fairNotices.length > 0;
  const qualityGrade = hasMajor ? 'poor' : hasMinor ? 'fair' : 'good';
  const qKeyMap = { good: 'summaryQualityGood', fair: 'summaryQualityFair', poor: 'summaryQualityPoor' };

  L.push('## ' + t('summaryQualityTitle'));
  L.push(t(qKeyMap[qualityGrade]));
  if (qIssues.length === 0 && fairNotices.length === 0) {
    L.push('- ' + t('summaryTipClean'));
  } else {
    if (qIssues.length > 0) {
      const tipMap = { peak: 'summaryTipPeak', clip: 'summaryTipClip', dc: 'summaryTipDC', balance: 'summaryTipBalance', dr: 'summaryTipDR' };
      const vars = { tp: tpMax != null ? tpMax.toFixed(1) : '—', n: q.clipping.samples, dc: q.dc_offset_pct.toFixed(2), bal: q.channel_balance_db.toFixed(1), dr: dr.dr_official };
      for (const issue of qIssues) L.push('- ' + fmt(t(tipMap[issue]), vars));
    }
    if (fairNotices.length > 0) {
      const noticeMap = { peak_notice: 'summaryTipPeakNotice', dr_notice: 'summaryTipDRNotice' };
      const vars2 = { tp: tpMax != null ? tpMax.toFixed(1) : '—', dr: dr.dr_official };
      for (const n of fairNotices) L.push('  - ' + fmt(t(noticeMap[n]), vars2));
    }
  }
  L.push('');
  L.push(t('summaryQualityGenreNote'));
  L.push('');

  L.push('## Audio Info');
  L.push(`- ${t('format')}: ${m.format}`);
  L.push(`- ${t('subtype')}: ${m.subtype}`);
  L.push(`- ${t('sampleRate')}: ${(m.sample_rate / 1000).toFixed(1)} kHz`);
  L.push(`- ${t('bitDepth')}: ${m.bit_depth} bit`);
  L.push(`- ${t('channels')}: ${m.channels} ch`);
  L.push(`- ${t('duration')}: ${fmtDuration(m.duration_s)}`);
  L.push(`- ${t('fileSize')}: ${formatFileSize(m.file_size_bytes)}`);
  if (m.bitrate_kbps) L.push(`- ${t('bitrate')}: ${m.bitrate_kbps} kbps` + (m.bitrate_pcm_kbps ? ` / PCM ${m.bitrate_pcm_kbps} kbps` : ''));
  L.push('');

  L.push('## Quality Analysis');
  L.push(`- ${t('clipping')}: ${q.clipping.samples > 0 ? q.clipping.samples + ' ' + t('samples') : t('clean')}`);
  L.push(`- ${t('dcOffset')}: ${q.dc_offset_pct.toFixed(2)}%`);
  L.push(`- ${t('chanBalance')}: ${q.channel_balance_db.toFixed(1)} dB`);
  L.push(`- ${t('truePeak')}: ${tpMax.toFixed(2)} dBTP`);
  L.push(`- ${t('dynamicRange')}: DR ${dr.dr_official}`);
  L.push(`- ${t('rmsLevel')}: ${l.rms_l_dbfs.toFixed(1)} dBFS`);
  L.push(`- ${t('integratedLUFS')}: ${l.integrated_lufs.toFixed(1)} LUFS`);
  L.push(`- ${t('loudnessRange')}: ${l.loudness_range_lu.toFixed(1)} LU`);
  L.push(`- ${t('bitDepthAuth')}: ${q.bit_depth_suspicious ? t('suspect') + ' (' + m.bit_depth + '→' + q.effective_bits + ')' : t('ok')}`);
  L.push('');

  L.push('## Authenticity');
  L.push(`- ${t('spectralCutoff')}: ${a.has_sharp_cutoff ? (a.cutoff_freq_hz || 0).toFixed(0) + ' Hz (' + (a.cutoff_suspected_codec || t('unknown')) + ')' : t('noneDetected')}`);
  L.push(`- ${t('upsampling')}: ${a.is_suspected_upsampled ? '~' + (a.upsample_source_rate_hint || 0) + ' Hz' : t('notDetected')}`);
  L.push(`- ${t('bit24Auth')}: ${(!a.low_bits_active && m.bit_depth >= 24) ? t('suspect') : t('ok')}`);
  L.push('');
  L.push('---');
  L.push('*Generated by HIFI Detector — Offline audio authenticity & quality detection. No files were uploaded.*');
  return L.join('\n');
}

export async function downloadReport(d, reportFmt) {
  if (!d) return;
  if (reportFmt === 'graphic') {
    await ensureChartsRendered(d.file_id);
    const html = await buildHtmlReport(d);
    downloadBlob(html, reportFileName(d.filename, 'html'), 'text/html;charset=utf-8');
  } else {
    const md = buildTextReport(d);
    downloadBlob(md, reportFileName(d.filename, 'md'), 'text/markdown;charset=utf-8');
  }
}
