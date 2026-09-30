/* Durable jobs remain accessible after closing Playground or reloading. */
let crawlRunView = 0;
async function dashCrawlRuns() {
  const view = ++crawlRunView;
  clearTimeout(state.crawlRunTimer);
  const selected = new URL(location.href).searchParams.get('run');
  const offset = Math.max(0, Number(new URL(location.href).searchParams.get('offset')) || 0);
  const current = () => view === crawlRunView && location.pathname === '/dashboard/crawl-runs' && new URL(location.href).searchParams.get('run') === selected;
  if (!selected) {
    const data = await api('/api/crawl-runs?limit=25&offset=' + offset);
    if (!current()) return;
    dashboardShell('crawl-runs', pageHead('COLLECTION', 'Background crawls',
      'Crawls continue after you close the page. Queued runs normally start within five minutes.',
      '<a class="btn primary" data-link href="/dashboard/playground">Collect data</a>') +
      '<article class="card"><div class="table-wrap"><table><thead><tr><th>URL</th><th>Status</th><th>Pages</th><th>Credits</th></tr></thead><tbody>' +
      (data.runs || []).map(run => '<tr><td><a data-link href="/dashboard/crawl-runs?run=' + encodeURIComponent(run.id) + '">' + esc(run.url) +
        '</a></td><td>' + esc(run.status) + '</td><td>' + fmt(run.progress.pages) + '</td><td>' + fmt(run.credits_charged) + '</td></tr>').join('') +
      '</tbody></table></div>' + ((data.runs || []).length ? '' : '<p>No background crawls yet. Enable background collection for a URL in Playground.</p>') + '</article>' +
      datasetPager('/dashboard/crawl-runs', offset, 25, Number(data.total || 0)));
    if ((data.runs || []).some(run => ['queued', 'running'].includes(run.status))) state.crawlRunTimer = setTimeout(() => { if (current()) dashCrawlRuns(); }, 10000);
    return;
  }
  const base = '/api/crawl-runs/' + encodeURIComponent(selected);
  const {run} = await api(base);
  if (!current()) return;
  const active = ['queued', 'running'].includes(run.status);
  dashboardShell('crawl-runs', pageHead('BACKGROUND CRAWL', 'Collection progress', esc(run.url),
    '<a class="btn" data-link href="/dashboard/crawl-runs">All background crawls</a>') +
    '<article class="card"><p role="status"><b>' + esc(run.status) + (run.cancel_requested && active ? ' · cancellation requested' : '') + '</b></p>' +
    '<p>' + fmt(run.progress.pages) + ' pages captured · ' + fmt(run.progress.discovered_urls) + ' URLs discovered · attempt ' + fmt(run.attempts) + '</p>' +
    '<p>' + fmt(run.credits_reserved) + ' credits reserved · ' + fmt(run.credits_charged) + ' charged</p>' +
    (run.status === 'queued' ? '<p>Waiting for a worker. You can close this page and return later.</p>' : '') +
    (run.progress.frontier_truncated ? '<p>The URL frontier reached its storage limit; some discovered links were skipped.</p>' : '') +
    (run.progress.truncated ? '<p>The saved output is partial because a crawl limit or interruption was reached.</p>' : '') +
    (run.error_code ? '<p role="alert">Collection stopped: ' + esc(run.error_code.replaceAll('_', ' ')) + '. Any saved records remain available below.</p>' : '') +
    (run.dataset_id ? '<a class="btn primary" data-link href="/dashboard/datasets?dataset=' + encodeURIComponent(run.dataset_id) + '">Open saved records</a> ' : '') +
    (active ? '<button id="crawl-run-cancel" class="btn" ' + (run.cancel_requested ? 'disabled' : '') + '>Cancel collection</button><p>Queued cancellation releases all reserved credits. Captured work can still be charged.</p>' : '') + '</article>');
  const button = $('#crawl-run-cancel');
  if (button) button.onclick = async () => {
    busy(button, true, 'Cancelling…');
    try { await api(base + '/cancel', {method: 'POST'}); if (current()) await dashCrawlRuns(); }
    catch (error) { toast(error.message, 'error'); busy(button, false); }
  };
  if (active) state.crawlRunTimer = setTimeout(() => { if (current()) dashCrawlRuns(); }, 10000);
}
