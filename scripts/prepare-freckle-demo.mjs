import fs from 'node:fs/promises';
import {chromium} from 'playwright-core';

// Real CC BY-SA 4.0 skin photograph; crops and colour variants keep every freckle.
// Regenerates local assets offline. No image generation, smoothing or face edits.
const source=await fs.readFile('assets-src/freckle-demo/source.jpg');
const browser=await chromium.launch({executablePath:process.env.SELF_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
try{
  const page=await browser.newPage();
  const images=await page.evaluate(async encoded=>{
    const photo=new Image();photo.src='data:image/jpeg;base64,'+encoded;await photo.decode();
    const result={};
    for(const [name,offset] of [['natural',[0,0,0]],['warm',[8,3,-3]],['airy',[5,0,4]]]){
      const canvas=document.createElement('canvas');canvas.width=600;canvas.height=500;
      const ctx=canvas.getContext('2d');
      // Right cheek: no eyes, nose, lips or identifying face outline.
      ctx.drawImage(photo,350,600,600,500,0,0,600,500);
      const pixels=ctx.getImageData(0,0,600,500);
      for(let i=0;i<pixels.data.length;i+=4)for(let c=0;c<3;c++)pixels.data[i+c]+=offset[c];
      ctx.putImageData(pixels,0,0);result[name]=canvas.toDataURL('image/png').split(',')[1];
    }
    return result;
  },source.toString('base64'));
  for(const [name,bytes] of Object.entries(images))await fs.writeFile(`entry/src/main/resources/rawfile/ui/freckle-${name}.png`,Buffer.from(bytes,'base64'));
  console.log('Prepared three real local skin photograph crops with preserved freckles.');
}finally{await browser.close();}
