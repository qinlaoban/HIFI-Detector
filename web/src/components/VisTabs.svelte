<script>
  import { t } from '../lib/i18n.svelte.js';
  import { loadSpectrogram, loadWaveform, purgeCharts } from '../lib/charts.js';

  let { fileId } = $props();
  let tab = $state('spectrogram');

  $effect(() => {
    if (tab === 'spectrogram') loadSpectrogram(fileId);
    else loadWaveform(fileId);
    return () => purgeCharts();
  });
</script>

<div class="tabs">
  <button class="tab-btn" class:active={tab === 'spectrogram'} onclick={() => (tab = 'spectrogram')}>{t('tabSpec')}</button>
  <button class="tab-btn" class:active={tab === 'waveform'} onclick={() => (tab = 'waveform')}>{t('tabWave')}</button>
</div>
<div class="tab-content" class:active={tab === 'spectrogram'}>
  <div class="chart-wrap" id="specChart"></div>
</div>
<div class="tab-content" class:active={tab === 'waveform'}>
  <div class="chart-wrap" id="waveChart"></div>
</div>
