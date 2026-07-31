<script>
  import { t } from '../lib/i18n.svelte.js';
  import { ArrowLeft } from 'lucide-svelte';

  let { results, selectedIndex = -1, onSelect, onReset } = $props();

  function tpMax(r) {
    const l = r.loudness;
    return l.true_peak_r_dbtp !== null ? Math.max(l.true_peak_l_dbtp, l.true_peak_r_dbtp) : l.true_peak_l_dbtp;
  }
  function tpColor(r) {
    const tp = tpMax(r);
    return tp > 0 ? 'var(--red)' : tp > -1 ? 'var(--yellow)' : 'var(--text-dim)';
  }
  function authLabel(r) {
    const v = r.authenticity.verdict;
    return v === 'suspicious' ? t('suspect') : v === 'ambiguous' ? t('warn') : t('ok');
  }
  function authColor(r) {
    const v = r.authenticity.verdict;
    return v === 'suspicious' ? 'red' : v === 'ambiguous' ? 'yellow' : 'green';
  }
  const shortHires = {
    genuine_hires: t('hiresShortGenuine'),
    fake_hires: t('hiresShortFake'),
    suspicious: t('hiresShortSuspicious'),
    not_hires: t('hiresShortNot'),
    undetermined: t('hiresShortUndetermined'),
  };

  const counts = $derived(results.reduce((acc, r) => {
    if (r.error) acc.error++;
    else if (r.verdict === 'ISSUES') acc.issues++;
    else if (r.verdict === 'WARN') acc.warn++;
    else acc.ok++;
    return acc;
  }, { ok: 0, warn: 0, issues: 0, error: 0 }));

  const claimed = $derived(results.filter((r) => !r.error && r.hires && r.hires.claims_hires));
  const fakes = $derived(claimed.filter((r) => r.hires.verdict === 'fake_hires').length);
  const genuine = $derived(claimed.filter((r) => r.hires.verdict === 'genuine_hires').length);
  const fakeRate = $derived(claimed.length ? Math.round((fakes / claimed.length) * 100) : 0);
</script>

<div class="batch-section active">
  <div style="text-align:center;margin-bottom:8px">
    <button class="btn" onclick={onReset}><ArrowLeft size={16} /> {t('analyzeAnother')}</button>
  </div>

  <div class="batch-summary">
    <span class="stat ok">{t('batchOk')}: {counts.ok}</span>
    <span class="stat warn">{t('batchWarn')}: {counts.warn}</span>
    <span class="stat issues">{t('batchIssues')}: {counts.issues}</span>
    {#if counts.error > 0}<span class="stat error">{t('batchError')}: {counts.error}</span>{/if}
    {#if claimed.length}
      <span style="margin-top:10px">
        <span class="stat ok">{t('hiresGenuine')}: {genuine}</span>
        <span class="stat issues">{t('hiresFake')}: {fakes}</span>
        <span class="stat {fakeRate > 0 ? 'issues' : 'ok'}">{t('hiresFakeRate')}: {fakeRate}%</span>
      </span>
    {/if}
  </div>

  <div class="card">
    <div class="card-hdr open">{t('batchResults')}</div>
    <div class="card-body show" style="padding:0;overflow-x:auto">
      <table class="batch-table">
        <thead>
          <tr>
            <th>#</th>
            <th>{t('batchColFile')}</th>
            <th>{t('batchColHires')}</th>
            <th>{t('batchColFormat')}</th>
            <th>{t('batchColDR')}</th>
            <th>{t('batchColTP')}</th>
            <th>{t('batchColAuth')}</th>
            <th>{t('batchColVerdict')}</th>
          </tr>
        </thead>
        <tbody>
          {#each results as r, i}
            <tr class:selected={i === selectedIndex} onclick={() => onSelect(i)}>
              {#if r.error}
                <td>{i + 1}</td>
                <td class="batch-filename" title={r.filename}>{r.filename}</td>
                <td colspan="5" style="color:#999">{r.error}</td>
                <td><span class="verdict-badge ERROR">ERROR</span></td>
              {:else}
                <td>{i + 1}</td>
                <td class="batch-filename" title={r.filename}>{r.filename}</td>
                <td>
                  {#if r.hires}
                    <span class="hires-badge {r.hires.verdict}">{shortHires[r.hires.verdict] ?? r.hires.verdict}</span>
                  {:else}—{/if}
                </td>
                <td>{r.metadata.format || '?'} {(r.metadata.sample_rate / 1000).toFixed(1)}kHz</td>
                <td>DR{r.dynamic_range.dr_official}</td>
                <td style="color:{tpColor(r)}">{tpMax(r).toFixed(1)}</td>
                <td style="color:var(--{authColor(r)})">{authLabel(r)}</td>
                <td><span class="verdict-badge {r.verdict}">{r.verdict.replace('_', ' ')}</span></td>
              {/if}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>
</div>
