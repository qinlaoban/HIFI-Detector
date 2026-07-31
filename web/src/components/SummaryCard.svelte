<script>
  import { t, fmt } from '../lib/i18n.svelte.js';

  let { data } = $props();

  function computeSummary(d) {
    const q = d.quality, l = d.loudness, dr = d.dynamic_range, a = d.authenticity, m = d.metadata;
    const tpMax = l.true_peak_r_dbtp !== null ? Math.max(l.true_peak_l_dbtp, l.true_peak_r_dbtp) : l.true_peak_l_dbtp;

    const authVerdict = a.verdict || (a.is_suspicious ? 'suspicious' : 'clean');
    const authMap = {
      clean: { key: 'summaryAuthClean', color: 'var(--green)' },
      ambiguous: { key: 'summaryAuthAmbiguous', color: 'var(--yellow)' },
      suspicious: { key: 'summaryAuthSuspicious', color: 'var(--accent2)' },
    };
    const authInfo = authMap[authVerdict] || authMap.clean;

    const qualityIssues = [];
    if (tpMax > 0.5) qualityIssues.push('peak');
    if (q.clipping.samples > 0) qualityIssues.push('clip');
    if (q.dc_offset_pct > 0.1) qualityIssues.push('dc');
    if (q.channel_balance_db > 1) qualityIssues.push('balance');
    if (dr.dr_official < 6) qualityIssues.push('dr');

    const fairNotices = [];
    if (tpMax > 0 && tpMax <= 0.5) fairNotices.push('peak_notice');
    if (dr.dr_official >= 6 && dr.dr_official < 8) fairNotices.push('dr_notice');

    const hasMajor = qualityIssues.includes('clip') || qualityIssues.includes('peak');
    const hasMinor = qualityIssues.includes('dc') || qualityIssues.includes('balance') || qualityIssues.includes('dr') || fairNotices.length > 0;
    const qualityGrade = hasMajor ? 'poor' : hasMinor ? 'fair' : 'good';
    const qualityMap = {
      good: { key: 'summaryQualityGood', color: 'var(--green)' },
      fair: { key: 'summaryQualityFair', color: 'var(--yellow)' },
      poor: { key: 'summaryQualityPoor', color: 'var(--accent2)' },
    };
    const qualityInfo = qualityMap[qualityGrade];

    let headlineKey;
    if (authVerdict === 'suspicious') headlineKey = 'summaryVerdictFake';
    else if (authVerdict === 'ambiguous') headlineKey = 'summaryVerdictWarn';
    else if (qualityGrade === 'poor') headlineKey = 'summaryVerdictIssue';
    else if (qualityGrade === 'good' && d.verdict === 'HIGH_QUALITY') headlineKey = 'summaryVerdictKeep';
    else if (qualityGrade === 'good') headlineKey = 'summaryVerdictOk';
    else headlineKey = 'summaryVerdictWarn';

    return { tpMax, qualityIssues, fairNotices, authInfo, qualityInfo, headlineKey, hasBitrateWarn: !!(m.bitrate_low && m.bitrate_kbps && m.bitrate_pcm_kbps) };
  }

  const summary = $derived(computeSummary(data));

  const tipMap = { peak: 'summaryTipPeak', clip: 'summaryTipClip', dc: 'summaryTipDC', balance: 'summaryTipBalance', dr: 'summaryTipDR' };
  const fmtVars = $derived({
    tp: summary.tpMax !== null && summary.tpMax !== undefined ? summary.tpMax.toFixed(1) : '—',
    n: data.quality.clipping.samples,
    dc: data.quality.dc_offset_pct.toFixed(2),
    bal: data.quality.channel_balance_db.toFixed(1),
    dr: data.dynamic_range.dr_official,
  });
  const noticeMap = { peak_notice: 'summaryTipPeakNotice', dr_notice: 'summaryTipDRNotice' };
  const fmtVars2 = $derived({
    tp: summary.tpMax !== null && summary.tpMax !== undefined ? summary.tpMax.toFixed(1) : '—',
    dr: data.dynamic_range.dr_official,
  });
</script>

<div class="summary-headline">{t(summary.headlineKey)}</div>

<div class="summary-block">
  <div class="sum-title">{t('summaryAuthTitle')}</div>
  <div class="sum-verdict" style="color:{summary.authInfo.color}">{t(summary.authInfo.key)}</div>
  {#if summary.hasBitrateWarn}
    <div class="summary-tip" style="color:var(--yellow);background:rgba(255,193,7,0.08)">
      {fmt(t('summaryBitrateLow'), { actual: data.metadata.bitrate_kbps, pcm: data.metadata.bitrate_pcm_kbps })}
    </div>
  {/if}
  {#if data.authenticity.suspicion_reasons?.length}
    <ul class="summary-ul">
      {#each data.authenticity.suspicion_reasons as reason}
        <li class="dim">{reason}</li>
      {/each}
    </ul>
  {/if}
</div>

<div class="summary-block">
  <div class="sum-title">{t('summaryQualityTitle')}</div>
  <div class="sum-verdict" style="color:{summary.qualityInfo.color}">{t(summary.qualityInfo.key)}</div>
  {#if summary.qualityIssues.length === 0 && summary.fairNotices.length === 0}
    <div style="font-size:12px;color:var(--green);padding:6px 0">{t('summaryTipClean')}</div>
  {:else}
    {#if summary.qualityIssues.length > 0}
      <ul class="summary-ul">
        {#each summary.qualityIssues as issue}
          <li style="margin-bottom:4px">{fmt(t(tipMap[issue]), fmtVars)}</li>
        {/each}
      </ul>
    {/if}
    {#if summary.fairNotices.length > 0}
      <ul class="summary-ul">
        {#each summary.fairNotices as n}
          <li class="tiny">{fmt(t(noticeMap[n]), fmtVars2)}</li>
        {/each}
      </ul>
    {/if}
  {/if}
</div>

<div class="summary-note">{t('summaryQualityGenreNote')}</div>
