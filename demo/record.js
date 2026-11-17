// Record replay.html to webm with Playwright (headless chromium).
const { chromium } = require('/work
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1280, height: 720 }, recordVideo: { dir: 'rec', size: { width: 1280, height: 720 } } });
  const p = await ctx.newPage();
  await p.goto('file://' + __dirname + '/replay.html');
  await p.waitForFunction(() => document.title === 'DONE', null, { timeout: 400000, polling: 1000 });
  const v = p.video(); await ctx.close(); console.log(await v.path()); await b.close();
})();
