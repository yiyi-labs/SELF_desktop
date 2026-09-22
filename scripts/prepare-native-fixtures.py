from pathlib import Path
from PIL import Image, ImageDraw
root=Path(__file__).resolve().parents[1]
out=root/'entry/src/main/resources/rawfile/native-fixtures'
out.mkdir(parents=True,exist_ok=True)
image=Image.new('RGB',(33,49),'white');draw=ImageDraw.Draw(image)
draw.rectangle((0,0,15,23),fill='red');draw.rectangle((17,0,32,23),fill='lime');draw.rectangle((0,25,15,48),fill='blue')
for orientation in range(1,9):
    exif=Image.Exif();exif[274]=orientation
    image.save(out/f'orientation-{orientation}.jpg',quality=100,subsampling=0,exif=exif)
image.save(out/'odd-stride.png')
print('Prepared eight original EXIF fixtures and an odd-width PNG. No personal photos used.')
