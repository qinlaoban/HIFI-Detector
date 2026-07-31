<script>
  import { t } from '../lib/i18n.svelte.js';
  import { formatFileSize, fmtDuration } from '../lib/utils.js';

  let { data } = $props();
  const m = $derived(data.metadata);

  const items = $derived([
    [t('format'), m.format],
    [t('subtype'), m.subtype],
    [t('sampleRate'), (m.sample_rate / 1000).toFixed(1) + ' ' + t('kHz')],
    [t('bitDepth'), m.bit_depth + ' ' + t('bit')],
    [t('channels'), m.channels + ' ' + t('ch')],
    [t('duration'), fmtDuration(m.duration_s)],
    [t('fileSize'), formatFileSize(m.file_size_bytes)],
    [t('bitrate'), m.bitrate_kbps ? m.bitrate_kbps + ' ' + t('kbps') + (m.bitrate_pcm_kbps ? ' / PCM ' + m.bitrate_pcm_kbps : '') : 'N/A'],
  ]);
</script>

<div class="info-grid">
  {#each items as [l, v]}
    <div class="info-item"><div class="lbl">{l}</div><div class="val">{v}</div></div>
  {/each}
</div>
