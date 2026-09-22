"""Original editable lathe meshes, not downloaded product photos or exact packaging scans.

Produces standard self-contained GLB body/lid assets compatible with our strict
native static-mesh loader. The separate lid receives a runtime transform.
No Blender installation or .blend runtime dependency. Dimensions are visual units,
NOT measured SKU dimensions, dose, material parameters or efficacy calibration.
"""
import io, json, math, struct, hashlib
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'entry/src/main/resources/rawfile/products/3d'
OUT.mkdir(parents=True,exist_ok=True)
FONT=Path('C:/Windows/Fonts/arial.ttf')
font=ImageFont.truetype(str(FONT),72)
small=ImageFont.truetype(str(FONT),19)

def texture(color, label, light=False):
    im=Image.new('RGBA',(1024,512),color+(255,))
    d=ImageDraw.Draw(im)
    ink=(69,63,64,255) if light else (239,223,190,255)
    # Plain brand text, independently typeset; no trademark graphic/photo copied.
    d.text((512,194),'OLAY',font=font,fill=ink,anchor='mm')
    d.line((451,240,573,240),fill=ink,width=2)
    d.text((512,280),label,font=small,fill=ink,anchor='mm')
    d.rectangle((0,494,128,511),fill=(239,232,216,255))
    b=io.BytesIO();im.save(b,format='PNG');return b.getvalue()

def plain(color):
    b=io.BytesIO();Image.new('RGBA',(4,4),color+(255,)).save(b,format='PNG');return b.getvalue()

def lathe(profile, offset=(0,0,0), n=96, uscale=1, vmin=.05, vmax=.9, cream=False):
    vertices=[];indices=[]
    low=min(y for y,r in profile);high=max(y for y,r in profile)
    for j,(y,r) in enumerate(profile):
        a=profile[max(0,j-1)];b=profile[min(len(profile)-1,j+1)]
        dy=b[0]-a[0];dr=b[1]-a[1];length=math.hypot(dy,dr) or 1
        for k in range(n+1):
            u=k/n;t=(u-.5)*2*math.pi
            sn,cs=math.sin(t),math.cos(t)
            tu,tv=(.05,.98) if cream and j>=len(profile)-3 else (u*uscale,vmin+(vmax-vmin)*(1-(y-low)/(high-low)))
            vertices.append((offset[0]+r*sn,offset[1]+y,offset[2]+r*cs,
                             sn*dy/length,-dr/length,cs*dy/length,
                             tu,tv))
    for j in range(len(profile)-1):
        for k in range(n):
            a=j*(n+1)+k;b=a+n+1
            indices.extend((a,a+1,b,b,a+1,b+1))
    return vertices,indices

def merge(parts):
    vertices=[];indices=[]
    for vs,ids in parts:
        start=len(vertices);vertices.extend(vs);indices.extend(start+i for i in ids)
    return vertices,indices

def glb(path, mesh, png):
    vs,ids=mesh;buffer=bytearray();views=[];access=[]
    def add(data,target=None):
        while len(buffer)%4:buffer.append(0)
        view={'buffer':0,'byteOffset':len(buffer),'byteLength':len(data)}
        if target:view['target']=target
        views.append(view);buffer.extend(data);return len(views)-1
    for first,count,kind in [(0,3,'VEC3'),(3,3,'VEC3'),(6,2,'VEC2')]:
        data=struct.pack('<'+'f'*(len(vs)*count),*(v[first+i] for v in vs for i in range(count)))
        a={'bufferView':add(data,34962),'componentType':5126,'count':len(vs),'type':kind}
        if first==0:
            a['min']=[min(v[i] for v in vs) for i in range(3)]
            a['max']=[max(v[i] for v in vs) for i in range(3)]
        access.append(a)
    access.append({'bufferView':add(struct.pack('<'+'I'*len(ids),*ids),34963),'componentType':5125,'count':len(ids),'type':'SCALAR'})
    picture=add(png)
    doc={'asset':{'version':'2.0','generator':'SELF original product lathe v1'},
         'scene':0,'scenes':[{'nodes':[0]}],'nodes':[{'mesh':0}],
         'meshes':[{'primitives':[{'attributes':{'POSITION':0,'NORMAL':1,'TEXCOORD_0':2},'indices':3,'material':0}]}],
         'materials':[{'pbrMetallicRoughness':{'baseColorTexture':{'index':0},'metallicFactor':0,'roughnessFactor':.3}}],
         'textures':[{'source':0}],'images':[{'bufferView':picture,'mimeType':'image/png'}],
         'accessors':access,'bufferViews':views,'buffers':[{'byteLength':len(buffer)}],
         'extras':{'selfRepresentation':'original approximate packaging study; not measured SKU geometry'}}
    j=json.dumps(doc,separators=(',',':')).encode();j+=b' '*((-len(j))%4)
    buffer+=b'\0'*((-len(buffer))%4)
    path.write_bytes(struct.pack('<III',0x46546c67,2,12+8+len(j)+8+len(buffer))+struct.pack('<II',len(j),0x4e4f534a)+j+struct.pack('<II',len(buffer),0x004e4942)+buffer)
    return {'file':path.name,'vertices':len(vs),'triangles':len(ids)//3,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}

jar=[(-1.35,.0),(-1.35,.94),(-1.32,1.04),(-1.25,1.10),(-1.12,1.12),(-.12,1.10),(.0,1.04),(.06,.98),(.17,.96),(.24,.96),(.24,.81),(.07,.79),(-.01,.0)]
jar_lid=[(.22,0),(.22,1.03),(.25,1.10),(.30,1.12),(.57,1.12),(.66,1.08),(.70,.98),(.71,.0)]
bottle=[(-1.55,0),(-1.55,.45),(-1.51,.52),(-1.43,.55),(.54,.55),(.70,.52),(.83,.43),(.88,.24),(1.12,.24),(1.16,.18),(1.20,0)]
bottle_lid=[(.88,0),(.88,.29),(.92,.33),(1.40,.33),(1.47,.29),(1.49,0)]
tube=[(-1.52,0),(-1.52,.32),(-1.44,.39),(-.6,.46),(.64,.55),(.85,.53),(.91,0)]
tube_lid=[(-1.91,0),(-1.91,.31),(-1.85,.39),(-1.52,.39),(-1.47,.34),(-1.47,0)]
ampoule=[(-1.4,0),(-1.4,.36),(-1.35,.42),(.20,.42),(.42,.33),(.6,.15),(.84,.15),(.86,0)]
ampoule_lid=[(.60,0),(.60,.17),(.67,.19),(1.35,.15),(1.45,.09),(1.47,0)]
styles=[('red-jar',jar,jar_lid,(135,9,26),(206,173,104),'CREAM',False),
        ('black-jar',jar,jar_lid,(22,24,27),(184,153,96),'CREAM',False),
        ('white-pump',bottle,bottle_lid,(232,231,224),(194,195,198),'SERUM',True),
        ('black-tube',tube,tube_lid,(18,20,23),(195,162,95),'SERUM',False),
        ('white-set',bottle,bottle_lid,(226,225,220),(194,195,198),'CARE',True),
        ('white-ampoule',ampoule,ampoule_lid,(216,225,228),(205,205,207),'SERUM',True)]
manifest=[]
for name,body,cap,bodycolor,capcolor,label,light in styles:
    if name=='white-set':
        def scaled(p,s):return [(y*s,r*s) for y,r in p]
        a=merge([lathe(scaled(body,.78),(-.56,-.15,0)),lathe(scaled(body,.62),(.58,-.36,.10))])
        b=merge([lathe(scaled(cap,.78),(-.56,-.15,0)),lathe(scaled(cap,.62),(.58,-.36,.10))])
    else:a,b=lathe(body,cream=name.endswith('-jar')),lathe(cap)
    manifest.append({'style':name,'body':glb(OUT/(name+'-body.glb'),a,texture(bodycolor,label,light)),
                     'lid':glb(OUT/(name+'-lid.glb'),b,plain(capcolor)),
                     'openDirection':-1 if name=='black-tube' else 1})
(OUT/'manifest.json').write_text(json.dumps({'schemaVersion':1,'license':'Original SELF geometry and label typesetting; OLAY name for identification only. No product photo copied.','representation':'approximate 3D appearance, not verified physical dimensions or mechanisms','models':manifest},indent=2),encoding='utf-8')
print('Generated',len(manifest),'original 3D studies with separate native-animated lids.')
