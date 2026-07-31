<script>
  import { t } from '../lib/i18n.svelte.js';
  import { BadgeCheck, BadgeX, CircleHelp, Minus } from 'lucide-svelte';

  let { data } = $props();
  const h = $derived(data.hires);

  const ico = $derived({
    genuine_hires: BadgeCheck,
    fake_hires: BadgeX,
    suspicious: CircleHelp,
    not_hires: Minus,
  });
  const label = $derived({
    genuine_hires: t('hiresGenuine'),
    fake_hires: t('hiresFake'),
    suspicious: t('hiresSuspicious'),
    not_hires: t('hiresNot'),
  });
</script>

{#if h}
  {@const Icon = ico[h.verdict] ?? Minus}
  <div class="hires-hero {h.verdict}">
    <div class="hires-top">
      <div class="hires-verdict">
        <span class="ico">
          <Icon size={28} strokeWidth={2} />
        </span>
        {label[h.verdict] ?? h.verdict}
      </div>
      <div class="hires-spec">
        <div class="lbl">{t('hiresClaimed')}</div>
        <div class="val">{h.hires_target}</div>
      </div>
    </div>
    <div class="hires-summary">{h.summary}</div>
    <div class="hires-conf">{t('hiresConfidence')}: {Math.round(h.confidence * 100)}%</div>
    {#if h.verdict === 'genuine_hires' || h.verdict === 'suspicious'}
      <div class="hires-scope">{t('hiresResampleNote')}</div>
    {/if}
    {#if h.issues && h.issues.length}
      <div class="hires-issues">
        {#each h.issues as iss}
          <div class="hires-issue">
            <div class="head"><span>{iss.headline}</span><span class="conf">{Math.round(iss.confidence * 100)}%</span></div>
            <div class="det">{iss.detail}</div>
          </div>
        {/each}
      </div>
    {/if}
  </div>
{/if}
