import { describe,it,expect } from '@ohos/hypium';
import { abilityDelegatorRegistry } from '@kit.TestKit';
import { common } from '@kit.AbilityKit';
import { fileIo as fs } from '@kit.CoreFileKit';
import { util } from '@kit.ArkTS';
import { zlib,deviceInfo } from '@kit.BasicServicesKit';
import { SELF_SCHEMA,SELF_PLY_CONTRACT,SelfTransferManifest,validateManifest,safeEntry } from '../../../main/ets/transfer/SelfTransferContract';
import { inspectZip } from '../../../main/ets/transfer/SelfTransferZipGuard';
import { inspectPly } from '../../../main/ets/transfer/SelfTransferPly';
import { makeDir,writeText,fileSha256,removeTransferTree } from '../../../main/ets/transfer/TransferFiles';
import { TransferDiagnostic } from '../../../main/ets/transfer/TransferState';
import { ShareDiagnostic } from '../../../main/ets/transfer/HarmonyShareBridge';

interface RuntimeDiagnostic {requestId:number;coordinator:TransferDiagnostic;share:ShareDiagnostic;}

/** Uses real device filesystem, official zlib and SHA-256. Isolated cache fixtures only; no user model index changes. */
export default function selfTransferSuite(){
  describe('SELFTransferDiagnostics',()=>{
    it('readActualForegroundWindowRegistration',0,async()=>{
      const delegator=abilityDelegatorRegistry.getAbilityDelegator(),context=delegator.getAppContext();
      await delegator.startAbility({bundleName:context.applicationInfo.name,abilityName:'EntryAbility'});
      let hostContext:common.UIAbilityContext|undefined=undefined;
      for(let attempt=0;attempt<50;attempt++){
        try{hostContext=(await delegator.getCurrentTopAbility()).context;break;}catch(_){
          await new Promise<void>((resolve)=>setTimeout(resolve,100));
        }
      }
      if(!hostContext)throw new Error('Host window did not enter foreground');
      const path=hostContext.cacheDir+'/self_transfer/diagnostics.json';
      const requestId=Date.now();
      await delegator.startAbility({bundleName:context.applicationInfo.name,abilityName:'EntryAbility',parameters:{selfTransferDiagnostic:requestId}});
      let value:RuntimeDiagnostic|undefined=undefined;
      for(let attempt=0;attempt<50;attempt++){
        if(fs.accessSync(path)){
          const candidate=JSON.parse(fs.readTextSync(path)) as RuntimeDiagnostic;
          if(candidate.requestId===requestId){value=candidate;break;}
        }
        await new Promise<void>((resolve)=>setTimeout(resolve,100));
      }
      if(!value)throw new Error('No fresh runtime diagnostic received');
      await delegator.print('SELF_TRANSFER_RUNTIME_DIAGNOSTIC '+JSON.stringify(value));
      expect(value.share.api).assertEqual(deviceInfo.sdkApiVersion);
      expect(value.share.windowId>0).assertTrue();
      expect(!(value.share.sendRegistered&&value.share.receiveRegistered)).assertTrue();
    });
  });
  describe('SELFTransferNative',()=>{
    it('officialZipAndPlyRoundTripPreservesSha256',0,async()=>{
      const context=abilityDelegatorRegistry.getAbilityDelegator().getAppContext();
      const owned=context.cacheDir+'/self-transfer-native-tests',root=owned+'/'+util.generateRandomUUID(true);makeDir(root+'/source/model');
      try{
        const names=['x','y','z','f_dc_0','f_dc_1','f_dc_2','opacity','scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3'];
        const header='ply\nformat binary_little_endian 1.0\nelement vertex 96\n'+names.map((name:string)=>'property float '+name).join('\n')+'\nend_header\n';
        const bytes=new ArrayBuffer(96*names.length*4),data=new DataView(bytes);
        for(let vertex=0;vertex<96;vertex++)for(let p=0;p<names.length;p++){
          const name=names[p],value=name==='rot_0'?1:name.startsWith('scale_')?-3:name==='x'?vertex*.01:0;
          data.setFloat32((vertex*names.length+p)*4,value,true);
        }
        const source=root+'/source/model/model.ply',file=fs.openSync(source,fs.OpenMode.CREATE|fs.OpenMode.READ_WRITE|fs.OpenMode.TRUNC);
        try{fs.writeSync(file.fd,header);fs.writeSync(file.fd,bytes);fs.fsyncSync(file.fd);}finally{fs.closeSync(file);}
        const digest=await fileSha256(source);
        const manifest:SelfTransferManifest={schema:SELF_SCHEMA,protocolVersion:1,packageId:util.generateRandomUUID(true),createdAt:new Date().toISOString(),
          producer:{appFamily:'SELF',variant:'device-test',appVersion:'0.1.0',bundleName:context.applicationInfo.name},
          model:{kind:'gaussian-splatting',format:'ply',formatContract:SELF_PLY_CONTRACT,entry:'model/model.ply',byteLength:fs.statSync(source).size,sha256:digest},
          assets:[{role:'model',path:'model/model.ply',required:true,byteLength:fs.statSync(source).size,sha256:digest}],requiredFeatures:['model.ply'],optionalFeatures:[]};
        validateManifest(manifest);writeText(root+'/source/manifest.json',JSON.stringify(manifest));
        const archive=root+'/native.self3d.zip';
        await zlib.compressFile(root+'/source',archive,{level:zlib.CompressLevel.COMPRESS_LEVEL_NO_COMPRESSION,keepTopLevelFolder:false});
        const zip=await inspectZip(archive);expect(zip.entries.some((entry)=>entry.path==='manifest.json')).assertTrue();
        makeDir(root+'/received');await zlib.decompressFile(archive,root+'/received',{});
        const received=root+'/received/model/model.ply',info=await inspectPly(received);
        expect(info.vertexCount).assertEqual(96);expect(await fileSha256(received)).assertEqual(digest);
        const evidence='SELF_TRANSFER_NATIVE_EVIDENCE '+JSON.stringify({api:deviceInfo.sdkApiVersion,deviceType:deviceInfo.deviceType,
          sourceSha256:digest,receivedSha256:await fileSha256(received),vertexCount:info.vertexCount,match:true});
        console.info(evidence);await abilityDelegatorRegistry.getAbilityDelegator().print(evidence);
      }finally{removeTransferTree(root,owned);}
    });
    it('protocolRejectsUnsafePaths',0,()=>{
      for(const path of ['../model.ply','model/../file','model\\file','/model/model.ply','C:/model.ply'])expect(safeEntry(path)).assertFalse();
      expect(safeEntry('model/model.ply')).assertTrue();expect(safeEntry('viewer/viewer_state.json')).assertTrue();
    });
  });
}
