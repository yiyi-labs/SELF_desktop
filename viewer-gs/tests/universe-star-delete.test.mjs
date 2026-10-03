// Run the real store against an in-memory app-private filesystem. Never deletes user data.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import os from 'node:os';
import path from 'node:path';
import {transformSync} from 'esbuild';

const source=fs.readFileSync(new URL('../../entry/src/main/ets/services/PortraitStarStore.ets',import.meta.url),'utf8')
  .replace(/^import .*;\r?$/gm,'').replace('export class PortraitStarStore','class PortraitStarStore');
const code=transformSync(source+'\nglobalThis.Store=PortraitStarStore;',{loader:'ts',target:'es2020'}).code;
const id=n=>n.toString(16).padStart(32,'0'),directory=n=>'/private/models/'+id(n),indexPath='/private/portrait-stars.json';
const modelFiles=['portrait.gaussian.ply','portrait.view.json','portrait.preview.png','portrait.preview.gaussian.ply','portrait.scene-v3.gaussian.ply','portrait.glb'];
function fixture(){
  const files=new Map(),dirs=new Set(['/private','/private/models']),deleted=[];let writeFails=false,unlinkFails=false;
  const add=n=>{
    dirs.add(directory(n));for(const name of modelFiles)files.set(directory(n)+'/'+name,'x'.repeat(name.endsWith('.json')?256:4096));
  };
  add(1);add(2);add(3);
  files.set(indexPath,JSON.stringify({schemaVersion:1,stars:[1,2,3].map(n=>({jobId:id(n),name:'记忆 '+n,createdAt:100-n}))}));
  const fake={
    accessSync:path=>files.has(path)||dirs.has(path),readTextSync:path=>files.get(path),statSync:path=>({size:files.get(path).length}),
    listFileSync:path=>[...new Set([...files.keys(),...dirs].filter(name=>name.startsWith(path+'/')).map(name=>name.slice(path.length+1).split('/')[0]))],
    unlinkSync:path=>{if(unlinkFails)throw new Error('busy file');assert.ok(files.has(path));files.delete(path);deleted.push(path);},
    rmdirSync:path=>{assert.equal(fake.listFileSync(path).length,0);dirs.delete(path);deleted.push(path);}
  };
  const context=vm.createContext({fs:fake,console:{warn:()=>{}},Date});vm.runInContext(code,context);
  const assets={writeAtomic:(path,text)=>{if(writeFails)throw new Error('disk unavailable');files.set(path,text);}};
  const create=()=>new context.Store({filesDir:'/private'},assets),store=create();
  return {store,create,files,dirs,deleted,add,failWrite:()=>writeFails=true,failUnlink:()=>unlinkFails=true,
    allowUnlink:()=>unlinkFails=false,index:()=>JSON.parse(files.get(indexPath))};
}

test('delete removes only that memory and its known local model files',()=>{
  const f=fixture();f.files.set(directory(2)+'/unrelated.txt','keep');f.dirs.add(directory(2)+'/nested');
  f.store.remove(id(2));assert.deepEqual(Array.from(f.store.list(),star=>star.jobId),[id(1),id(3)]);
  for(const name of modelFiles){assert.equal(f.files.has(directory(2)+'/'+name),false);assert.equal(f.files.has(directory(1)+'/'+name),true);}
  assert.equal(f.files.get(directory(2)+'/unrelated.txt'),'keep');assert.equal(f.dirs.has(directory(2)+'/nested'),true);
  assert.deepEqual(f.index().deletedIds,[id(2)]);
});
test('restart and late downloads cannot resurrect a deleted memory',()=>{
  const f=fixture();f.store.remove(id(2));assert.equal(f.dirs.has(directory(2)),false);f.add(2);
  assert.deepEqual(Array.from(f.create().list(),star=>star.jobId),[id(1),id(3)]);
  for(const name of modelFiles)assert.equal(f.files.has(directory(2)+'/'+name),false,'late downloads must also be cleaned');
  assert.throws(()=>f.create().upsert(id(2),'回来了'),/已被删除/);
  f.store.upsert(id(1),'改名');assert.deepEqual(f.index().deletedIds,[id(2)]);
  f.store.remove(id(2));assert.deepEqual(f.index().deletedIds,[id(2)]);
});
test('index write failure happens before any file is deleted',()=>{
  const f=fixture(),before=new Map(f.files);f.failWrite();assert.throws(()=>f.store.remove(id(2)),/disk unavailable/);
  assert.deepEqual(f.files,before);assert.deepEqual(f.deleted,[]);assert.equal(f.store.list().length,3);
});
test('busy local files cannot cause the deleted star to reappear',()=>{
  const f=fixture();f.failUnlink();assert.throws(()=>f.store.remove(id(2)),/尚未清理完成/);
  assert.equal(f.files.has(directory(2)+'/portrait.gaussian.ply'),true);
  assert.deepEqual(Array.from(f.create().list(),star=>star.jobId),[id(1),id(3)]);
  f.allowUnlink();f.create().list();
  for(const name of modelFiles)assert.equal(f.files.has(directory(2)+'/'+name),false);
});
test('malformed IDs never construct or delete a path outside the memory store',()=>{
  for(const bad of ['../other','',id(2)+'/../../other',id(2).toUpperCase()+'X']){
    const f=fixture(),before=new Map(f.files);assert.throws(()=>f.store.remove(bad),/编号无效/);
    assert.deepEqual(f.files,before);assert.deepEqual(f.deleted,[]);
  }
});
test('old indexes remain readable and an unindexed model can also be deleted permanently',()=>{
  const f=fixture();assert.equal(f.store.list().length,3);f.add(4);f.store.remove(id(4));
  assert.deepEqual(Array.from(f.store.list(),star=>star.jobId),[id(1),id(2),id(3)]);
  assert.deepEqual(f.index().deletedIds,[id(4)]);
});

test('the real store physically unlinks all six assets on disk, with another memory untouched',()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'self-star-delete-')),models=path.join(root,'models');
  const assets=[];
  fs.mkdirSync(models);
  for(const n of [1,2]){
    const folder=path.join(models,id(n));fs.mkdirSync(folder);
    for(const name of modelFiles){const file=path.join(folder,name);fs.writeFileSync(file,'x'.repeat(4096));assets.push(file);}
  }
  const index=path.join(root,'portrait-stars.json');
  fs.writeFileSync(index,JSON.stringify({schemaVersion:1,stars:[1,2].map(n=>({jobId:id(n),name:'测试记忆',createdAt:n}))}));
  try{
    const context=vm.createContext({Date,console,fs:{accessSync:fs.existsSync,readTextSync:file=>fs.readFileSync(file,'utf8'),
      statSync:fs.statSync,listFileSync:fs.readdirSync,unlinkSync:fs.unlinkSync,rmdirSync:fs.rmdirSync}});
    vm.runInContext(code,context);
    const store=new context.Store({filesDir:root.replaceAll('\\','/')},{writeAtomic:(file,value)=>{
      fs.writeFileSync(file+'.tmp',value);fs.renameSync(file+'.tmp',file);
    }});
    store.remove(id(1));
    for(const name of modelFiles){
      assert.equal(fs.existsSync(path.join(models,id(1),name)),false);
      assert.equal(fs.statSync(path.join(models,id(2),name)).size,4096);
    }
    assert.equal(fs.existsSync(path.join(models,id(1))),false);
    assert.deepEqual(Array.from(store.list(),star=>star.jobId),[id(2)]);
  }finally{
    for(const file of assets)if(fs.existsSync(file))fs.unlinkSync(file);
    for(const n of [1,2]){const folder=path.join(models,id(n));if(fs.existsSync(folder))fs.rmdirSync(folder);}
    fs.unlinkSync(index);fs.rmdirSync(models);fs.rmdirSync(root);
  }
});
