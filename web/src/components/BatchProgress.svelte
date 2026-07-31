<script>
  let { text, file, pct } = $props();
</script>

<div class="batch-progress active">
  <div class="spinner"></div>
  <div class="progress-text">{text}</div>
  <div class="bar-outer"><div class="bar-inner" style="width:{pct}%"></div></div>
  <div class="msg" style="font-size:12px;color:var(--text-dim);margin-top:4px">{file}</div>
</div>
