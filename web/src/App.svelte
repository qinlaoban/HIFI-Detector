<script>
  import Header from './components/Header.svelte';
  import UploadDropzone from './components/UploadDropzone.svelte';
  import BatchProgress from './components/BatchProgress.svelte';
  import BatchResults from './components/BatchResults.svelte';
  import Results from './components/Results.svelte';
  import { lang, t } from './lib/i18n.svelte.js';
  import { analyzeFile } from './lib/api.js';
  import { isSupported, MAX_BATCH_FILES } from './lib/utils.js';
  import { purgeCharts } from './lib/charts.js';

  let view = $state('upload');
  let errorMsg = $state('');
  let currentData = $state(null);
  let currentFile = $state(null);
  let fileId = $state(null);
  let batchResults = $state([]);
  let fromBatchIndex = $state(-1);
  let selectedRowIndex = $state(-1);
  let batchText = $state('');
  let batchFile = $state('');
  let batchPct = $state(0);

  $effect(() => {
    if (typeof localStorage !== 'undefined') localStorage.setItem('hifi-lang', lang.value);
    if (typeof document !== 'undefined') document.documentElement.lang = lang.value;
  });

  function showError(msg) {
    errorMsg = msg;
  }

  function handleFiles(files) {
      if (!files || files.length === 0) return;
    if (files.length === 1) {
      if (!isSupported(files[0].name)) {
        showError('Unsupported format: ' + files[0].name);
        return;
      }
      handleFile(files[0]);
    } else {
      handleBatch(files);
    }
  }

  async function handleFile(file) {
    currentFile = file;
    fromBatchIndex = -1;
    selectedRowIndex = -1;
    errorMsg = '';
    view = 'progress';
    try {
      const data = await analyzeFile(file);
      fileId = data.file_id;
      currentData = data;
      view = 'results';
    } catch (e) {
      view = 'upload';
      showError(e.message);
    }
  }

  async function handleBatch(files) {
    const audioFiles = files.filter((f) => isSupported(f.name));
    if (audioFiles.length === 0) {
      showError('No supported audio files found.');
      return;
    }
    if (audioFiles.length > MAX_BATCH_FILES) {
      showError(t('batchTooMany').replace('{n}', MAX_BATCH_FILES));
      return;
    }
    errorMsg = '';
    view = 'batchProgress';
    batchResults = [];
    selectedRowIndex = -1;
    const total = audioFiles.length;
    for (let i = 0; i < total; i++) {
      const file = audioFiles[i];
      batchText = t('batchProgress').replace('{i}', i + 1).replace('{total}', total);
      batchPct = (i / total) * 100;
      batchFile = file.name;
      try {
        const data = await analyzeFile(file);
        data.file = file;
        batchResults = [...batchResults, data];
      } catch (e) {
        batchResults = [...batchResults, { filename: file.name, error: e.message, file }];
      }
    }
    batchPct = 100;
    view = 'batch';
  }

  function showBatchDetail(index) {
    const r = batchResults[index];
    if (!r || r.error) return;
    selectedRowIndex = index;
    currentFile = r.file;
    currentData = r;
    fileId = r.file_id;
    fromBatchIndex = index;
    view = 'results';
  }

  function backToBatch() {
    purgeCharts();
    currentData = null;
    currentFile = null;
    fromBatchIndex = -1;
    selectedRowIndex = -1;
    view = 'batch';
  }

  function resetToUpload() {
    purgeCharts();
    currentData = null;
    currentFile = null;
    fileId = null;
    fromBatchIndex = -1;
    selectedRowIndex = -1;
    batchResults = [];
    errorMsg = '';
    view = 'upload';
  }
</script>

<Header />

<div class="container">
  {#if errorMsg}
    <div class="error-box">{errorMsg}</div>
  {/if}

  {#if view === 'upload'}
    <UploadDropzone onFiles={handleFiles} />
  {:else if view === 'progress'}
    <div class="progress active">
      <div class="spinner"></div>
      <div class="msg">{t('analyzing')}</div>
    </div>
  {:else if view === 'batchProgress'}
    <BatchProgress text={batchText} file={batchFile} pct={batchPct} />
  {:else if view === 'batch'}
    <BatchResults results={batchResults} selectedIndex={selectedRowIndex} onSelect={showBatchDetail} onReset={resetToUpload} />
  {:else if view === 'results' && currentData}
    <Results
      data={currentData}
      file={currentFile}
      fileId={fileId}
      fromBatchIndex={fromBatchIndex}
      onReset={resetToUpload}
      onBackToBatch={backToBatch}
    />
  {/if}
</div>
