<script>
  import { t } from '../lib/i18n.svelte.js';
  import { ArrowLeft } from 'lucide-svelte';
  import HiResHero from './HiResHero.svelte';
  import SummaryCard from './SummaryCard.svelte';
  import InfoCard from './InfoCard.svelte';
  import QualityCard from './QualityCard.svelte';
  import AuthCard from './AuthCard.svelte';
  import VisTabs from './VisTabs.svelte';
  import ReportCard from './ReportCard.svelte';

  let { data, file, fileId, fromBatchIndex = -1, onReset, onBackToBatch } = $props();

  const verdictInfo = $derived(
    {
      HIGH_QUALITY: [t('highQuality'), 'HIGH_QUALITY'],
      CLEAN: [t('clean'), 'CLEAN'],
      WARN: [t('minorIssues'), 'WARN'],
      ISSUES: [t('issuesDetected'), 'ISSUES'],
    }[data.verdict] || [data.verdict, 'ISSUES'],
  );

  let audioUrl = $state('');
  $effect(() => {
    if (!file) {
      audioUrl = '';
      return;
    }
    const url = URL.createObjectURL(file);
    audioUrl = url;
    return () => URL.revokeObjectURL(url);
  });
</script>

<div class="results active">
  <div class="btn-row">
    {#if fromBatchIndex >= 0}
      <button class="btn" onclick={onBackToBatch}><ArrowLeft size={16} /> {t('backToBatch')}</button>
    {:else}
      <button class="btn" onclick={onReset}><ArrowLeft size={16} /> {t('analyzeAnother')}</button>
    {/if}
  </div>

  <HiResHero {data} />

  <div class="verdict {verdictInfo[1]}">{verdictInfo[0]}</div>

  {#if file && audioUrl}
    <div class="card audio-card">
      <audio controls preload="auto" src={audioUrl}></audio>
    </div>
  {/if}

  <div class="card" style="border-color:var(--accent2)">
    <div class="card-hdr open">{t('cardSummary')}</div>
    <div class="card-body show">
      <SummaryCard {data} />
    </div>
  </div>

  <div class="card">
    <div class="card-hdr open">{t('cardReport')}</div>
    <div class="card-body show">
      <ReportCard {data} />
    </div>
  </div>

  <div class="card">
    <div class="card-hdr open">{t('cardInfo')}</div>
    <div class="card-body show">
      <InfoCard {data} />
    </div>
  </div>

  <div class="card">
    <div class="card-hdr open">{t('cardQuality')}</div>
    <div class="card-body show">
      <QualityCard {data} />
    </div>
  </div>

  <div class="card">
    <div class="card-hdr open">{t('cardAuth')}</div>
    <div class="card-body show">
      <AuthCard {data} />
    </div>
  </div>

  <div class="card">
    <div class="card-hdr open">{t('cardVis')}</div>
    <div class="card-body show">
      <VisTabs {fileId} />
    </div>
  </div>
</div>
