// OpenCrawl public product experience. Examples never submit an execution request.
(() => {
  'use strict';
  Object.assign(paths, {
    browser:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M7 6.5h.01M10 6.5h.01"/>',
    link:'<path d="m10 13 4-4m-6 7-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 1 1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0"/>'
  });
  const endpoint = 'https://opencrawl.top/mcp';
  const configuration = {mcpServers:{OpenCrawl:{url:endpoint,headers:{Authorization:'Bearer <API_KEY>'}}}};
  const workflows = [
    {label:'Research',symbol:'search',prompt:'Research the key claims on this public URL',target:'example.com',title:'From question to evidence.',description:'Discover public sources, collect the page, and keep the references.',output:{source_url:'https://example.com',findings:[],references:[]},route:'/dashboard/playground',draft:'Research the key claims on https://example.com'},
    {label:'Crawl',symbol:'docs',prompt:'Collect the public pages of a website',target:'example.com',title:'A website, made useful.',description:'Collect permitted pages and links with bounded depth and a clear source trail.',output:{url:'https://example.com',pages:[],links:[]},route:'/dashboard/playground',draft:'https://example.com'},
    {label:'Extract',symbol:'code',prompt:'Turn a public page into structured data',target:'example.com',title:'Structure you can work with.',description:'Choose the fields you need and preserve the source behind each result.',output:{source_url:'https://example.com',fields:{},evidence:[]},route:'/dashboard/extract'},
    {label:'Connect',symbol:'plug',prompt:'Connect your agent to OpenCrawl',target:'/mcp',title:'Your agent. One connection.',description:'Use the MCP gateway with a supported client and your own scoped authorization.',output:configuration,route:'/dashboard/connections'}
  ];
  const webTools = [['search','Search','/docs/capabilities#web'],['scan','Smart Scrape','/docs/smart-scrape'],['map','Site Map','/docs/site-map'],['code','Structured Extract','/docs/structured-extract']];
  const link = (href,label,symbol='arrow') => `<a class="oc-landing-link" data-link href="${href}">${label} ${icon(symbol)}</a>`;
  const code = value => esc(JSON.stringify(value,null,2)).replace(/(&quot;[^&]*?&quot;)(\s*:)?/g,(_,value,colon)=>`<span class="oc-json-${colon?'key':'value'}">${value}</span>${colon||''}`);

  renderHome = async function renderHomeExperience() {
    const start = state.me?.user?.email_verified ? '/dashboard' : '/signup';
    publicShell(`
      <a class="oc-home-skip" href="#oc-home-main">Skip to content</a>
      <main class="oc-landing" id="oc-home-main" tabindex="-1">
        <section class="oc-landing-hero" aria-labelledby="oc-home-title">
          <div class="oc-portal-scene" aria-hidden="true"><img src="/assets/glass-portal.webp?v=20261008" width="1459" height="1078" alt="" fetchpriority="high"></div>
          <div class="oc-landing-intro">
            <h1 id="oc-home-title">The internet.<br>Ready for your <span>agent.</span></h1>
            <p>Search, crawl, extract, and connect your agent to the live web.<br>One workspace. Clear evidence. You stay in control.</p>
            <div class="oc-landing-actions"><a class="btn primary large" data-link href="${start}">Start building ${icon('arrow')}</a><a class="btn large" data-link href="/docs/capabilities">Explore the platform ${icon('arrow')}</a></div>
            <p class="oc-landing-methods">Search · Crawl · Extract · Browser · MCP</p>
          </div>
          <section class="oc-product-preview" aria-label="OpenCrawl interactive product preview">
            <header><span><img src="/assets/opencrawl-crab.png" width="28" height="28" alt=""><b>OpenCrawl</b><i>/</i> Playground</span><small>Interactive example</small></header>
            <div class="oc-workflow-tabs" role="tablist" aria-label="Example workflows">
              ${workflows.map((w,i)=>`<button type="button" role="tab" id="oc-workflow-tab-${i}" aria-controls="oc-workflow-panel-${i}" aria-selected="${i===0}" tabindex="${i===0?0:-1}" data-home-workflow="${i}">${icon(w.symbol)} ${w.label}</button>`).join('')}
            </div>
            <div class="oc-preview-query"><span>${icon('search')}<span data-home-prompt>${workflows[0].prompt}</span></span><span class="oc-preview-target">${icon('link')}<span data-home-target>example.com</span></span><button class="btn primary" type="button" data-home-launch aria-label="Open selected workflow">${icon('arrow')}</button></div>
            ${workflows.map((w,i)=>`<div class="oc-preview-panel" role="tabpanel" id="oc-workflow-panel-${i}" aria-labelledby="oc-workflow-tab-${i}" ${i?'hidden':''}><div><h2>${w.title}</h2><p>${w.description}</p></div><div class="oc-preview-output"><span>${i===3?'EXAMPLE CONNECTION':'EXAMPLE OUTPUT'}</span><pre><code>${code(w.output)}</code></pre></div></div>`).join('')}
            <footer><a class="oc-landing-link" data-link data-home-open href="${workflows[0].route}">${icon('external')}<span data-home-open-label>Explore in Playground</span> ${icon('arrow')}</a><small>Illustrative preview · no request is executed</small></footer>
          </section>
        </section>

        <section class="oc-landing-story">
          <div class="oc-landing-container">
            <nav class="oc-operation-strip" aria-label="Explore OpenCrawl operations">
              ${[['search','Search','/docs/capabilities#web'],['docs','Crawl','/docs/capabilities#web'],['code','Extract','/docs/structured-extract'],['settings','Execute','/docs/capabilities'],['activity','Observe','/docs/monitoring']].map(([symbol,label,href])=>`<a data-link href="${href}">${icon(symbol)}<b>${label}</b>${icon('arrow')}</a>`).join('')}
            </nav>
            <div class="oc-story-heading"><div><h2>From a question<br>to <span>usable data.</span></h2><p>Find the right capability. Collect what matters.<br>Keep the source behind every result.</p></div><p>Built around the way agents work.</p></div>
            <ol class="oc-workflow-steps">
              ${[['search','Discover','Search public sources and find the right route.'],['docs','Collect','Fetch, crawl, or browse permitted pages.'],['code','Deliver','Return structured output with source references.']].map(([symbol,title,note],i)=>`<li><span class="oc-glass-icon">${icon(symbol)}</span><div><small>0${i+1}</small><h3>${title}</h3><p>${note}</p></div></li>`).join('')}
            </ol>
            <div class="oc-feature-composition">
              <article class="oc-web-feature"><img src="/assets/glass-globe.webp?v=20261008" width="240" height="240" loading="lazy" decoding="async" alt=""><div><h3>The web, within reach.</h3><p>Search, crawl, map, and extract<br>from public sources.</p>${link('/docs/capabilities#web','Explore web tools')}<nav aria-label="Web tools">${webTools.map(([symbol,label,href])=>`<a data-link href="${href}">${icon(symbol)} ${label}</a>`).join('')}</nav></div></article>
              <div class="oc-feature-rows"><article><span class="oc-glass-icon">${icon('browser')}</span><div><h3>A real browser when you need one.</h3><p>Use controlled browser and sandbox sessions for dynamic pages.</p>${link('/docs/capabilities#browser','Explore browser & sandbox')}</div></article><article><span class="oc-glass-icon">${icon('plug')}</span><div><h3>Your tools. One connection.</h3><p>Connect APIs, remote MCP servers, and authorized app accounts.</p>${link('/docs/sync','Explore connections')}</div></article></div>
            </div>
          </div>
        </section>

        <section class="oc-landing-connect oc-landing-container" aria-labelledby="oc-connect-title">
          <div><h2 id="oc-connect-title">Built for your<br><span>stack.</span></h2><p>One MCP endpoint for the clients you already use.</p><div class="oc-landing-actions"><a class="btn primary large" data-link href="/docs/clients">Connection guide ${icon('arrow')}</a>${link('/docs/keys','API key guide')}</div></div>
          <div><div class="oc-connection-code"><header><span>${icon('plug')} MCP connection</span><button class="btn small" type="button" data-copy="${esc(JSON.stringify(configuration,null,2))}">${icon('copy')} Copy</button></header><pre><code>${code(configuration)}</code></pre></div><p class="oc-code-note">Replace the placeholder with your own scoped key.</p></div>
        </section>

        <section class="oc-landing-final" aria-labelledby="oc-final-title"><img src="/assets/glass-orbit.webp?v=20261008" width="132" height="80" loading="lazy" decoding="async" alt=""><h2 id="oc-final-title">Your next idea<br><span>starts here.</span></h2><p>Give your agent reach. Keep the operation under control.</p><div class="oc-landing-actions"><a class="btn primary large" data-link href="${start}">Start building ${icon('arrow')}</a><a class="btn large" data-link href="/docs">Read the docs ${icon('arrow')}</a></div></section>
      </main>`);
    $('.ih-public-shell').classList.add('oc-home-shell');
    const meta = $('.ih-footer-meta');
    if (meta) meta.remove();
    $('.ih-footer').insertAdjacentHTML('beforeend',`<div class="oc-home-footer-bottom oc-landing-container"><span>© ${new Date().getFullYear()} OpenCrawl</span><span>Explicit · scoped · auditable</span></div>`);
    let selected = 0;
    const tabs = $$('[data-home-workflow]');
    const choose = index => {
      selected=index;
      tabs.forEach((tab,i)=>{tab.setAttribute('aria-selected',String(i===index));tab.tabIndex=i===index?0:-1;$('#oc-workflow-panel-'+i).hidden=i!==index;});
      $('[data-home-prompt]').textContent=workflows[index].prompt;
      $('[data-home-target]').textContent=workflows[index].target;
      $('[data-home-open]').href=workflows[index].route;
      $('[data-home-open-label]').textContent=index<2?'Explore in Playground':index===2?'Explore Structured Extract':'Explore connections';
    };
    tabs.forEach((tab,index)=>{
      tab.addEventListener('click',()=>choose(index));
      tab.addEventListener('keydown',event=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
        event.preventDefault();
        const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
        choose(next);tabs[next].focus();
      });
    });
    const draft = () => {
      const workflow=workflows[selected];
      if(state.me?.user?.email_verified && workflow.draft)state.playgroundDraft=workflow.draft;
    };
    $('[data-home-open]').addEventListener('click',draft);
    $('[data-home-launch]').addEventListener('click',()=>{draft();go(workflows[selected].route);});
  };
})();

