export interface PreviewGeometry {contentWidth:number;contentHeight:number;streamWidth:number;streamHeight:number;rotation:number;mirrored:boolean;}
export interface PreviewPoint {x:number;y:number;}

/** The analysis PixelMap is rotated first; front-preview mirroring and center crop are applied here. */
export function previewGeometry(rawWidth:number,rawHeight:number,rotation:number,viewportWidth:number,viewportHeight:number,mirrored:boolean):PreviewGeometry{
 const swap=rotation===90||rotation===270;
 const streamWidth=swap?rawHeight:rawWidth,streamHeight=swap?rawWidth:rawHeight;
 const scale=Math.max(viewportWidth/streamWidth,viewportHeight/streamHeight);
 return {contentWidth:streamWidth*scale,contentHeight:streamHeight*scale,streamWidth,streamHeight,rotation,mirrored};
}
export function previewPoint(x:number,y:number,geometry:PreviewGeometry):PreviewPoint{
 return {x:((geometry.mirrored?1-x:x)-.5)*geometry.contentWidth,y:(y-.5)*geometry.contentHeight};
}
