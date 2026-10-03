"""Paid capability probe. Uses only original synthetic images, never a face or user file."""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw
from deepseek_client import propose, ModelFailure
from test_contracts import snapshot

async def main():
    folder=Path(__file__).resolve().parents[2]/"docs/evidence/deepseek"
    folder.mkdir(parents=True,exist_ok=True)
    results=[]
    cases=[("red-circle","red",1,"rose"),("blue-squares","blue",3,"terracotta")]
    for name,color,count,preset in cases:
        image=Image.new("RGB",(768,768),"white");draw=ImageDraw.Draw(image)
        if count==1:draw.ellipse((200,200,568,568),fill=(240,25,30))
        else:
            for x,y in [(110,160),(450,160),(280,450)]:draw.rectangle((x,y,x+170,y+170),fill=(20,55,240))
        path=folder/(name+".png");image.save(path)
        s=snapshot();s.requestId="vision-"+name+"-"+str(int(datetime.now().timestamp()));s.snapshotId=s.requestId
        s.userText="这是一张无个人信息的能力测试图片。请用中文在 shortMessage 明确描述图中主色、形状和数量；如果是红色选 rose，如果是蓝色选 terracotta，为已登记 lip 区域提议轻度数字试色。不要猜测图片外内容。"
        try:
            result=await propose(s,[path.read_bytes()]);p=result["plan"]
            message=p["shortMessage"];described=("红" in message and "圆" in message and ("一" in message or "1" in message)) if count==1 else ("蓝" in message and ("方" in message) and ("三" in message or "3" in message))
            selected=len(p["operations"])==1 and p["operations"][0]["presetId"]==preset
            results.append({"case":name,"status":"passed" if described and selected else "failed","visualDescriptionMatched":described,"toolSelectionMatched":selected,"result":result})
        except ModelFailure as error:
            results.append({"case":name,"status":"unverified" if str(error)=="missing_key" else "failed","reason":str(error)})
    summary={"testedAt":datetime.now(timezone.utc).isoformat(),"source":"Capability probe targeting official DeepSeek HTTPS API; original nonpersonal synthetic images. Missing key means no API request was sent.","cases":results}
    (folder/"live-results.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0 if all(r["status"]=="passed" for r in results) else 2
if __name__=="__main__":sys.exit(asyncio.run(main()))
