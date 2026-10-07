export interface SelectionBounds {left:number;top:number;right:number;bottom:number;}
export interface SelectionConversationFrame {x:number;y:number;width:number;maxHeight:number;}

/** Anchor beside the right edge of the lasso. Content grows downward from this position. */
export function selectionConversationFrame(viewWidth:number,viewHeight:number,bounds:SelectionBounds):SelectionConversationFrame {
  const margin=18,gap=18,top=58,bottom=viewHeight-20;
  const minWidth=Math.min(240,viewWidth-margin*2);
  const right=Math.max(margin,Math.min(viewWidth-margin,bounds.right*viewWidth));
  const upper=Math.max(top,Math.min(bottom,bounds.top*viewHeight));
  const lower=Math.max(upper,Math.min(bottom,bounds.bottom*viewHeight));
  // Use the right side consistently. Narrow the card when needed; at the screen
  // edge clamp it inside the viewport instead of switching left, above or below.
  const x=Math.max(margin,Math.min(right+gap,viewWidth-margin-minWidth));
  const width=Math.min(330,viewWidth-margin-x);
  const height=Math.min(320,bottom-top);
  const y=Math.max(top,Math.min(bottom-height,(upper+lower)/2-92));
  return {x,y,width,maxHeight:bottom-y};
}
