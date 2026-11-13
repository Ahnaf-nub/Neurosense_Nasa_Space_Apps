/* Exact supplied JPEG sheets, decoded locally. White backgrounds are keyed at
   runtime so the original artwork stays intact; no external image service. */
const Ranger=(()=>{
 const frames={},ready=[];
 function frame(img,rect,scale){
  const [sx,sy,w,h]=rect,c=document.createElement('canvas');c.width=w;c.height=h;
  const ctx=c.getContext('2d',{willReadFrequently:true});ctx.drawImage(img,sx,sy,w,h,0,0,w,h);
  const data=ctx.getImageData(0,0,w,h),p=data.data;
  // JPEG white is not exactly 255. Keep dark outlines and colored highlights.
  // Remove only pale pixels connected to an edge; retain white eye details.
  const visited=new Uint8Array(w*h),queue=new Int32Array(w*h);let head=0,tail=0;
  function push(x,y){if(x<0||y<0||x>=w||y>=h)return;const n=y*w+x,i=n*4;
   if(visited[n])return;visited[n]=1;
   if(p[i+3]===0||Math.min(p[i],p[i+1],p[i+2])>225){queue[tail++]=n;p[i+3]=0;}}
  for(let x=0;x<w;x++){push(x,0);push(x,h-1)}
  for(let y=0;y<h;y++){push(0,y);push(w-1,y)}
  while(head<tail){const n=queue[head++],x=n%w,y=Math.floor(n/w);push(x-1,y);push(x+1,y);push(x,y-1);push(x,y+1)}
  let left=w,right=0,top=h,bottom=0;
  for(let y=0;y<h;y++)for(let x=0;x<w;x++)if(p[(y*w+x)*4+3]){
   left=Math.min(left,x);right=Math.max(right,x);top=Math.min(top,y);bottom=Math.max(bottom,y);}
  ctx.putImageData(data,0,0);
  return {c,left,top,w:right-left+1,h:bottom-top+1,scale};
 }
 function load(src,build){const img=new Image();ready.push(new Promise(resolve=>{img.onload=()=>{build(img);resolve(true)};img.onerror=()=>resolve(false)}));img.src=src;}
 load('ranger-idle.png',img=>{const f=frame(img,[500,325,600,1000],1);f.scale=82/f.h;frames.idle=[f]});
 load('ranger-walk.jpg',img=>{
  ['down','up','left','right'].forEach((dir,row)=>{
   const [y,h]=[[0,145],[147,140],[290,135],[431,133]][row];
   frames[dir]=Array.from({length:4},(_,col)=>frame(img,[365+col*131,y,105,h],.62));
  });
 });
 load('ranger-dig.jpg',img=>{
  frames.dig=Array.from({length:8},(_,i)=>frame(img,[350+(i%4)*205,i<4?0:220,150,i<4?214:201],.50));
  frames.digSide=Array.from({length:8},(_,i)=>frame(img,[350+(i%4)*205,i<4?424:615,160,i<4?188:204],.50));
 });
 function draw(canvas,dir,moving,now,digUntil){if(!canvas)return;
  const digging=now<digUntil,side=dir==='left'||dir==='right';
  const list=frames[digging?(side?'digSide':'dig'):(moving?dir:'idle')]||frames[dir];if(!list)return;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const index=reduced?0:digging?Math.min(7,Math.floor((1200-(digUntil-now))/150)):(moving?Math.floor(now/140)%4:0);
  const f=list[index];if(!f||f.w<=0)return;
  const ctx=canvas.getContext('2d');ctx.setTransform(2,0,0,2,0,0);ctx.clearRect(0,0,88,112);ctx.imageSmoothingEnabled=false;
  ctx.fillStyle='#0005';ctx.beginPath();ctx.ellipse(44,108,18,3,0,0,Math.PI*2);ctx.fill();
  const w=f.w*f.scale,h=f.h*f.scale;
  if(digging&&dir==='left'){ctx.translate(88,0);ctx.scale(-1,1)}
  ctx.drawImage(f.c,f.left,f.top,f.w,f.h,44-w/2,108-h,w,h);
 }
 return {draw,ready:Promise.all(ready)};
})();
