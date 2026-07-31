<script>
  import { lang, setLang } from '../lib/i18n.svelte.js';
</script>

<header class="header">
  <div><h1>HIFI Detector</h1></div>
  <div class="header-right">
    <select class="lang-select" value={lang.value} onchange={(e) => setLang(e.currentTarget.value)}>
      <option value="en">English</option>
      <option value="zh">中文</option>
      <option value="ja">日本語</option>
    </select>
  </div>
</header>
