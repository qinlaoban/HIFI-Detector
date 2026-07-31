<script>
  import { t } from '../lib/i18n.svelte.js';

  let { data } = $props();

  const metrics = $derived((() => {
    const q = data.quality, l = data.loudness, dr = data.dynamic_range, m = data.metadata;
    const tpMax = l.true_peak_r_dbtp !== null ? Math.max(l.true_peak_l_dbtp, l.true_peak_r_dbtp) : l.true_peak_l_dbtp;
    const drLabel = dr.dr_official >= 14 ? t('excellent') : dr.dr_official >= 10 ? t('good') : dr.dr_official >= 8 ? t('transition') : t('bad');
    const drColor = dr.dr_official >= 10 ? 'green' : dr.dr_official >= 8 ? 'yellow' : 'red';
    return [
      { name: t('clipping'), text: q.clipping.samples > 0 ? q.clipping.samples + ' ' + t('samples') : t('clean'), color: q.clipping.samples > 0 ? 'red' : 'green', barPct: Math.min(100, (q.clipping.ratio_pct || 0) / 0.01 * 100) },
      { name: t('dcOffset'), text: q.dc_offset_pct > 0.1 ? t('warn') : t('clean'), color: q.dc_offset_pct > 0.1 ? 'yellow' : 'green', barPct: Math.min(100, q.dc_offset_pct / 0.5 * 100) },
      { name: t('chanBalance'), text: q.channel_balance_db > 1 ? t('warn') : t('ok'), color: q.channel_balance_db > 1 ? 'yellow' : 'green', barPct: Math.min(100, q.channel_balance_db / 3 * 100) },
      { name: t('truePeak'), text: tpMax.toFixed(2) + ' ' + t('dBTP'), color: tpMax > -0.1 ? 'red' : tpMax > -1 ? 'yellow' : 'green', barPct: Math.min(100, Math.max(0, (tpMax + 6) / 6 * 100)) },
      { name: t('dynamicRange'), text: drLabel, color: drColor, barPct: Math.min(100, dr.dr_official / 20 * 100) },
      { name: t('rmsLevel'), text: l.rms_l_dbfs.toFixed(1) + ' ' + t('dBFS'), color: 'dim', barPct: 0 },
      { name: t('integratedLUFS'), text: l.integrated_lufs.toFixed(1) + ' ' + t('LUFS'), color: 'dim', barPct: 0 },
      { name: t('loudnessRange'), text: l.loudness_range_lu.toFixed(1) + ' ' + t('LU'), color: 'dim', barPct: 0 },
      { name: t('bitDepthAuth'), text: q.bit_depth_suspicious ? t('suspect') + ' (' + m.bit_depth + '→' + q.effective_bits + ')' : t('ok'), color: q.bit_depth_suspicious ? 'yellow' : 'green', barPct: 0 },
    ];
  })());
</script>

<div class="metrics">
  {#each metrics as mt}
    <div class="metric-row">
      <span class="name">{mt.name}</span>
      <div class="bar-wrap"><div class="bar-fill {mt.color}" style="width:{mt.barPct}%"></div></div>
      <span class="status {mt.color}">{mt.text}</span>
    </div>
  {/each}
</div>
