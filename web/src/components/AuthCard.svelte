<script>
  import { t } from '../lib/i18n.svelte.js';

  let { data } = $props();

  const metrics = $derived((() => {
    const a = data.authenticity, m = data.metadata;
    let cfDetail = a.has_sharp_cutoff ? t('suspect') : t('noneDetected');
    const cfColor = a.has_sharp_cutoff ? 'red' : 'green';
    if (a.has_sharp_cutoff) {
      cfDetail = (a.cutoff_freq_hz || 0).toFixed(0) + ' ' + t('Hz') + ' (' + (a.cutoff_suspected_codec || t('unknown')) + ')';
    }
    let upDetail = a.is_suspected_upsampled ? t('suspect') : t('notDetected');
    const upColor = a.is_suspected_upsampled ? 'red' : 'green';
    if (a.is_suspected_upsampled) {
      upDetail = '~' + (a.upsample_source_rate_hint || 0) + ' ' + t('Hz') + ' source';
    }
    const b24V = (!a.low_bits_active && m.bit_depth >= 24) ? [t('suspect'), 'yellow'] : [t('ok'), 'green'];
    const suspV = a.is_suspicious ? [t('yes') + ' (' + Math.round(a.overall_confidence * 100) + '%)', 'red'] : [t('no'), 'green'];
    const items = [
      { name: t('spectralCutoff'), text: cfDetail, color: cfColor },
      { name: t('upsampling'), text: upDetail, color: upColor },
      { name: t('bit24Auth'), text: b24V[0], color: b24V[1] },
      { name: t('suspicion'), text: suspV[0], color: suspV[1] },
    ];
    if (a.suspicion_reasons && a.suspicion_reasons.length) {
      items.push({ name: 'Reasons', text: a.suspicion_reasons.join('; '), color: 'red' });
    }
    return items;
  })());
</script>

<div class="metrics">
  {#each metrics as mt}
    <div class="metric-row">
      <span class="name">{mt.name}</span>
      <span style="flex:1;font-size:13px;color:var(--text-dim)"></span>
      <span class="status {mt.color}">{mt.text}</span>
    </div>
  {/each}
</div>
