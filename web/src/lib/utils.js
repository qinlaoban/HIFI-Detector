import { t } from './i18n.svelte.js';

export const ALLOWED_EXTENSIONS = ['flac', 'wav', 'mp3', 'aiff', 'aif', 'ogg', 'opus', 'm4a', 'alac', 'ape', 'wv'];
export const MAX_BATCH_FILES = 30;
export const MAX_FILE_SIZE = 600 * 1024 * 1024;

export function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export function isSupported(name) {
  const ext = name.split('.').pop().toLowerCase();
  return ALLOWED_EXTENSIONS.includes(ext);
}

export function formatFileSize(bytes) {
  if (!bytes || bytes < 0) return '0 MB';
  const isWindows = /Win/.test(navigator.platform) || /Windows/.test(navigator.userAgent);
  const kb = isWindows ? 1024 : 1000;
  const mb = kb * kb;
  const gb = mb * kb;
  if (bytes >= gb) {
    return (bytes / gb).toFixed(2) + ' GB';
  }
  if (bytes < mb) {
    return Math.round(bytes / kb) + ' KB';
  }
  return (bytes / mb).toFixed(1) + ' ' + t('MB');
}

export function fmtDuration(s) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return m + ':' + String(sec).padStart(2, '0');
}
