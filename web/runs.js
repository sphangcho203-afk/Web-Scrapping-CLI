/* Canonical execution history; specialized stores own cancellation and billing. */
let canonicalRunView = 0;
let canonicalRunTimer;
async function dashRuns() {
  const view = ++canonicalRunView;
  clearTimeout(canonicalRunTimer);
  const url = new URL(location.href);
  const selected = url.searchParams.get('run');
  const offset = Math.max(0, Number(url.searchParams.get('offset')) || 0);
  const current = () => view === canonicalRunView && location.pathname === '/dashboard/runs' && new URL(location.href).searchParams.get('run') === selected;
  const active = run => ['created','queued','running','waiting'].includes(run.execution_status);
  const link = run => '/dashboard/runs?run=' + encodeURIComponent(run.id);
  const stateLabel = run => run.execution_status || run.execution?.status || run.status || 'unknown';
  if (!selected) {
    const data = await api('/api/runs?limit=25&offset=' + offset);
    if (!current()) return;
    const rows = data.runs || [];
    dashboardShell('runs', pageHead('EXECUTION', 'Runs', 'Trace collected data, progress and wallet charges in one place.',
      '<a class="btn primary" data-link href="/dashboard/playground">Start a run</a>') +
      '<article class="card"><div class="table-wrap"><table><thead><tr><th>Capability</th><th>Execution</th><th>Reserved / charged</th><th>Created</th></tr></thead><tbody>' +
      rows.map(run => '<tr><td><a data-link href="' + link(run) + '">' + esc(run.capability_id || 'Execution') + '</a></td><td>' + esc(stateLabel(run)) +
        '</td><td>' + fmt(run.credits_reserved) + ' / ' + fmt(run.credits_charged) + ' credits</td><td>' + esc(when(run.created_at)) + '</td></tr>').join('') +
      '</tbody></table></div>' + (rows.length ? '' : '<p>No runs yet. Start a collection in Playground, Smart Scrape, Site Map or Structured Extract.</p>') +
      '</article>' + datasetPager('/dashboard/runs', offset, 25, Number(data.total || 0)));
    if (rows.some(active)) canonicalRunTimer = setTimeout(() => { if (current()) dashRuns(); }, 10000);
    return;
  }
  const base = '/api/runs/' + encodeURIComponent(selected);
  const data = await api(base);
  if (!current()) return;
  const run = data.run;
  const started = run.started_at ? Date.parse(run.started_at) : null;
  const ended = run.execution_finished_at ? Date.parse(run.execution_finished_at) : null;
  const duration = run.duration_ms != null ? (Number(run.duration_ms)/1000).toFixed(2) + ' seconds' : started && ended ? Math.max(0, Math.round((ended-started)/1000)) + ' seconds' : 'Not recorded';
  const cancellable = (run.source_kind === 'crawl' && active(run)) || (run.source_kind === 'capability' && run.execution_status === 'queued');
  dashboardShell('runs', pageHead('RUN DETAIL', run.capability_id || 'Execution', esc(run.id),
    '<a class="btn" data-link href="/dashboard/runs">All runs</a>') +
    '<article class="card" data-canonical-run><p role="status"><b>' + esc(stateLabel(run)) + '</b>' +
    (run.cancel_requested && active(run) ? ' · cancellation requested' : '') + '</p>' +
    '<div class="ih-inspector-grid"><div><small>Reserved credits</small><b>' + fmt(run.credits_reserved) + '</b></div>' +
    '<div><small>Charged credits</small><b>' + fmt(run.credits_charged) + '</b></div>' +
    '<div><small>Sources</small><b>' + (run.source_count == null ? 'Not recorded' : fmt(run.source_count)) + '</b></div>' +
    '<div><small>Worker retries</small><b>' + fmt(run.retry_count) + '</b></div>' +
    '<div><small>Warnings</small><b>' + fmt(run.warning_count) + '</b></div>' +
    '<div><small>Duration</small><b>' + esc(duration) + '</b></div></div>' +
    (run.warning_count ? '<p>Collection limits, failed pages or schema checks affected the saved output. Review the dataset before using it.</p>' : '') +
    (run.error_code ? '<p role="alert">Execution stopped: ' + esc(run.error_code.replaceAll('_',' ')) + '.</p>' : '') +
    (run.output_dataset_id ? '<a class="btn primary" data-link href="/dashboard/datasets?dataset=' + encodeURIComponent(run.output_dataset_id) + '">Open saved dataset</a> ' : '<p>No saved dataset linked.</p>') +
    (cancellable ? '<button class="btn" id="canonical-run-cancel" ' + (run.cancel_requested ? 'disabled' : '') + '>Cancel run</button><p>Queued cancellation releases reserved credits. Captured work can still be charged.</p>' : '') +
    (run.source_kind === 'capability' && ['running','waiting'].includes(run.execution_status) ? '<p>Upstream work has started. Cancellation is unavailable for this extraction.</p>' : '') +
    (run.parent_run_id ? '<p>Parent run: <a data-link href="/dashboard/runs?run=' + encodeURIComponent(run.parent_run_id) + '">' + esc(run.parent_run_id) + '</a></p>' : '') +
    (run.monitor_id ? '<p>Created by a content monitor.</p>' : '') +
    '<details><summary>Quote and billing reference</summary><p>Billing state: ' + esc(run.status) + '</p><code style="overflow-wrap:anywhere">' + esc(run.quote_revision || 'No reviewed quote recorded') + '</code></details>' +
    '</article><article class="card"><h2>Recorded transitions</h2><p>Events record committed execution facts. Provider attempts are recorded when their usage is settled.</p>' +
    '<ol id="canonical-run-events"></ol><p id="canonical-run-empty" ' + ((data.events || []).length ? 'hidden' : '') + '>No recorded timeline. Older runs contain an imported snapshot.</p>' +
    '<button class="btn" id="canonical-run-more" ' + ((data.events || []).length < 100 ? 'hidden' : '') + '>Load more events</button></article>');
  let after = data.next_after || 0;
  const append = events => {
    const list = $('#canonical-run-events');
    list.insertAdjacentHTML('beforeend', events.map(event => '<li><b>' + esc(event.status) + '</b> · ' + esc(when(event.timestamp)) +
      ' · ' + esc(event.message || event.type.replaceAll('_',' ')) + (event.attempt ? ' · attempt ' + fmt(event.attempt) : '') + '</li>').join(''));
  };
  append(data.events || []);
  const more = $('#canonical-run-more');
  more.onclick = async () => {
    busy(more, true, 'Loading…');
    try {
      const next = await api(base + '?after=' + after + '&limit=100');
      if (!current()) return;
      append(next.events || []); after = next.next_after || after;
      more.hidden = (next.events || []).length < 100;
    } catch (error) { toast(error.message, 'error'); }
    finally { if (more.isConnected) busy(more, false); }
  };
  const cancel = $('#canonical-run-cancel');
  if (cancel) cancel.onclick = async () => {
    busy(cancel, true, 'Cancelling…');
    try { await api(base + '/cancel', {method:'POST'}); if (current()) await dashRuns(); }
    catch (error) { toast(error.message, 'error'); busy(cancel, false); }
  };
  if (active(run)) canonicalRunTimer = setTimeout(() => { if (current()) dashRuns(); }, 10000);
}
