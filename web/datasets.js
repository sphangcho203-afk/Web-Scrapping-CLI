/* Account-owned saved outputs. No API secrets are embedded in export URLs. */
async function dashDatasets() {
  const selected = new URL(location.href).searchParams.get('dataset');
  const offset = Math.max(0, Number(new URL(location.href).searchParams.get('offset')) || 0);
  const query = new URL(location.href).searchParams.get('q') || '';
  const root = '/dashboard/datasets';
  if (!selected) {
    const data = await api('/api/datasets?limit=25&offset=' + offset);
    const items = Array.isArray(data.datasets) ? data.datasets : [];
    dashboardShell('datasets', pageHead('OUTPUT', 'Datasets',
      'Saved search, crawl and research records. Reopen results or download them without running collection again.',
      '<a class="btn primary" data-link href="/dashboard/playground">Collect data</a>') +
      '<article class="card">' + (items.length ?
        '<div class="table-wrap"><table><thead><tr><th>Name</th><th>Operation</th><th>Rows</th><th>Created</th></tr></thead><tbody>' +
        items.map(item => '<tr><td><a data-link href="' + root + '?dataset=' + encodeURIComponent(item.id) + '">' + esc(item.name) +
          '</a></td><td>' + esc(item.operation) + '</td><td>' + fmt(item.row_count) + '</td><td>' + when(item.created_at) + '</td></tr>').join('') +
        '</tbody></table></div>' : '<div class="smart-empty"><span><b>No saved outputs yet</b><p>Run a search, research query or crawl in Playground. Results are saved automatically.</p></span></div>') +
      '</article>' + datasetPager(root, offset, 25, Number(data.total || 0)));
    return;
  }
  const base = '/api/datasets/' + encodeURIComponent(selected);
  const data = await api(base + '?limit=50&offset=' + offset + '&q=' + encodeURIComponent(query));
  const dataset = data.dataset || {}, rows = Array.isArray(data.rows) ? data.rows : [];
  const columns = Array.isArray(dataset.columns) ? dataset.columns : [];
  const view = root + '?dataset=' + encodeURIComponent(selected);
  dashboardShell('datasets', pageHead('SAVED OUTPUT', esc(dataset.name),
    esc(dataset.operation) + ' · ' + fmt(dataset.row_count) + ' records · ' + when(dataset.created_at),
    '<a class="btn" data-link href="' + root + '">All datasets</a>') +
    '<section class="card dataset-controls"><form id="dataset-rename"><label>Name<input name="name" maxlength="120" required value="' + esc(dataset.name) + '"></label><button class="btn" type="submit">Rename</button></form>' +
    '<div class="dataset-exports">' + ['json', 'jsonl', 'csv'].map(format => '<button class="btn small" data-dataset-export="' + format + '">Download ' + format.toUpperCase() + '</button>').join('') +
    '<button class="btn danger small" id="dataset-delete">Delete dataset</button></div>' +
    '<a data-link href="/dashboard/usage?run=' + encodeURIComponent(dataset.request_id) + '">View original run and charge</a></section>' +
    '<form id="dataset-filter" class="dataset-filter"><label>Filter records<input name="q" maxlength="200" value="' + esc(query) + '" placeholder="Search text, URL or field value"></label><button class="btn" type="submit">Filter</button></form>' +
    '<article class="card">' + (rows.length ? '<div class="table-wrap dataset-table"><table><thead><tr>' + columns.map(column => '<th>' + esc(column) + '</th>').join('') +
      '</tr></thead><tbody>' + rows.map(row => '<tr>' + columns.map(column => '<td><div>' + esc(typeof row[column] === 'object' && row[column] !== null ? JSON.stringify(row[column]) : String(row[column] ?? '')) + '</div></td>').join('') + '</tr>').join('') + '</tbody></table></div>' :
      '<div class="smart-empty"><span><b>No matching records</b><p>' + (query ? 'Clear the filter to see all saved records.' : 'This collection returned no records.') + '</p></span></div>') + '</article>' +
    datasetPager(view + '&q=' + encodeURIComponent(query), offset, 50, Number(data.total || 0)));
  $('#dataset-filter').onsubmit = event => {
    event.preventDefault();
    go(view + '&q=' + encodeURIComponent(event.currentTarget.elements.q.value));
  };
  $('#dataset-rename').onsubmit = async event => {
    event.preventDefault();
    const button = event.submitter;
    busy(button, true, 'Saving…');
    try {
      await api(base, {method: 'PATCH', body: {name: event.currentTarget.elements.name.value}});
      await dashDatasets();
      toast('Dataset renamed', 'success');
    } catch (error) { toast(error.message, 'error'); busy(button, false); }
  };
  $('#dataset-delete').onclick = async event => {
    if (!confirm('Delete this saved output? The run and its original charge remain in Usage.')) return;
    const button = event.currentTarget;
    busy(button, true, 'Deleting…');
    try { await api(base, {method: 'DELETE'}); go(root); }
    catch (error) { toast(error.message, 'error'); busy(button, false); }
  };
  $$('[data-dataset-export]').forEach(button => button.onclick = async () => {
    busy(button, true, 'Downloading…');
    try {
      const format = button.dataset.datasetExport;
      const response = await fetch(base + '/export?format=' + format, {credentials: 'same-origin'});
      if (!response.ok) throw new Error('Download failed. Refresh the page and check your session.');
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url; link.download = selected + '.' + format;
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { toast(error.message, 'error'); }
    finally { busy(button, false); }
  });
}

function datasetPager(base, offset, limit, total) {
  const separator = base.includes('?') ? '&' : '?';
  return '<nav class="dataset-pager" aria-label="Dataset pagination"><span>' + (total ? (offset + 1) + '–' + Math.min(total, offset + limit) : '0') + ' of ' + fmt(total) + '</span>' +
    (offset > 0 ? '<a class="btn small" data-link href="' + base + separator + 'offset=' + Math.max(0, offset - limit) + '">Previous</a>' : '') +
    (offset + limit < total ? '<a class="btn small" data-link href="' + base + separator + 'offset=' + (offset + limit) + '">Next</a>' : '') + '</nav>';
}
