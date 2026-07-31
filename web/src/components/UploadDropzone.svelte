<script>
  import { Music } from 'lucide-svelte';
  import { t } from '../lib/i18n.svelte.js';
  import { ALLOWED_EXTENSIONS } from '../lib/utils.js';

  let { onFiles } = $props();
  let dragOver = $state(false);
  let inputEl;

  function handleInput(e) {
    onFiles(Array.from(e.currentTarget.files));
    e.currentTarget.value = '';
  }

  function handleDrop(e) {
    e.preventDefault();
    dragOver = false;
    onFiles(Array.from(e.dataTransfer.files));
  }
</script>

<div class="upload-section">
  <div
    class="dropzone"
    class:drag-over={dragOver}
    role="button"
    tabindex="0"
    aria-label={t('dropTitle')}
    onclick={() => inputEl?.click()}
    onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); inputEl?.click(); } }}
    ondragover={(e) => { e.preventDefault(); dragOver = true; }}
    ondragleave={() => (dragOver = false)}
    ondrop={handleDrop}
  >
    <div class="icon"><Music size={42} strokeWidth={1.5} /></div>
    <div class="title">{t('dropTitle')}</div>
    <div class="hint">{t('dropHint')}</div>
    <input
      type="file"
      accept={ALLOWED_EXTENSIONS.map((e) => '.' + e).join(',')}
      multiple
      bind:this={inputEl}
      onchange={handleInput}
    />
  </div>
</div>
