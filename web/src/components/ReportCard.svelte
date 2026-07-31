<script>
  import { t } from '../lib/i18n.svelte.js';
  import { downloadReport } from '../lib/reports.js';
  import { Download } from 'lucide-svelte';

  let { data } = $props();
  let reportFmt = $state('graphic');
  let generating = $state(false);

  async function onDownload() {
    generating = true;
    try {
      await downloadReport(data, reportFmt);
    } catch (e) {
      console.error('Report download failed:', e);
    } finally {
      generating = false;
    }
  }
</script>

<div class="report-opts">
  <button class="rpt-btn" class:active={reportFmt === 'graphic'} onclick={() => (reportFmt = 'graphic')}>{t('rptGraphic')}</button>
  <button class="rpt-btn" class:active={reportFmt === 'text'} onclick={() => (reportFmt = 'text')}>{t('rptText')}</button>
</div>
<button class="download-btn" onclick={onDownload} disabled={generating}>
  <Download size={14} style="vertical-align:-2px;margin-right:6px" />
  {generating ? t('rptGen') : t('rptDownload')}
</button>
