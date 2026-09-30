// Execute the real client validator with its generated product repositories.
import { build } from 'esbuild';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

const result = await build({
  entryPoints: ['entry/src/main/ets/services/PlannerClient.ets'],
  bundle: true, write: false, format: 'esm', platform: 'node', loader: { '.ets': 'ts' },
  plugins: [{ name: 'test-platform', setup(builder) {
    builder.onResolve({ filter: /^@kit\./ }, args => ({ path: args.path, namespace: 'test-platform' }));
    builder.onLoad({ filter: /.*/, namespace: 'test-platform' }, () => ({ contents: 'export const http={}; export const util={};' }));
    builder.onResolve({ filter: /^\.\.?\// }, args => {
      const resolved = new URL(args.path+'.ets', pathToFileURL(args.resolveDir+'/'));
      if (fs.existsSync(resolved)) return { path: resolved.pathname.replace(/^\/([A-Za-z]:)/, '$1') };
    });
  } }]
});
const { PlannerClient } = await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64'));
const client = new PlannerClient();
const records = JSON.parse(fs.readFileSync('shared/products/audit-v2/products_cn.json','utf8'));
const snapshot = {userText:'介绍 OLAY 的产品资料', regions:[{regionId:'circle-1'}], layers:[],
  annotatedRegionId:'circle-1', careAdviceRequested:true, productContextIds:[]};
const plan = {decision:'explain',shortMessage:'这是有来源的产品资料。',operations:[],explanationRefs:[],question:'',
  selectionObservations:[{regionId:'circle-1',area:'eye',concern:'none',confidence:'clear',basis:'image'}]};
for(const product of records) {
  client.validate({...plan,explanationRefs:[product.product_id]},snapshot);
}
assert.throws(()=>client.validate({...plan,explanationRefs:['CN999']},snapshot));
assert.throws(()=>client.validate({...plan,selectionObservations:[{...plan.selectionObservations[0],regionId:'unselected'}]},snapshot));
assert.throws(()=>client.validate({...plan,selectionObservations:[{...plan.selectionObservations[0],confidence:'uncertain'}]},snapshot));
client.validate({...plan,careGuide:{productId:'CN008',whyHere:'眼周可以有轻柔的日常护理步骤。',howToUse:'在眼周轻轻点开，避开眼内。'}},snapshot);
console.log('Client integration passed: all 74 AI references resolve; eye care and selection boundaries validated.');
