/* Intro video: starts by itself, with sound whenever the browser allows it.
   Browsers refuse sound before the visitor has interacted with the page, so in that case the video
   still starts immediately (muted) and sound switches on at the first click, tap or key press.
   Kept independent of Leaflet and satellite requests. */
(()=>{
 const overlay=document.getElementById('intro'),video=document.getElementById('iv');
 const mute=document.getElementById('mute'),hint=document.getElementById('sound-hint');
 let done=false,locked=false,userMuted=false;
 function finish(){if(done)return;done=true;video.pause();overlay.classList.add('off');
  setTimeout(()=>overlay.remove(),700);document.getElementById('map')?.focus();}
 function unlock(){if(done||!locked||userMuted)return;locked=false;
  video.muted=false;video.defaultMuted=false;video.volume=1;hint.hidden=true;mute.textContent='Mute';}
 async function start(){
  video.muted=false;video.volume=1;
  try{await video.play();if(!done){mute.hidden=false;mute.textContent='Mute'}return}catch(e){}
  if(done)return;
  video.muted=true;locked=true;                       // blocked: play silently right away, unlock on first gesture
  try{await video.play();mute.hidden=false;mute.textContent='Sound on';hint.hidden=false}
  catch(e){hint.hidden=false;hint.textContent='The intro could not play. Press Skip to open the map.'}
 }
 const gesture=e=>{if(e.target&&e.target.closest&&e.target.closest('#mute'))return;unlock()};
 addEventListener('pointerdown',gesture,true);addEventListener('touchstart',gesture,true);
 addEventListener('keydown',e=>{if(done)return;e.stopImmediatePropagation();
  if(e.key==='Escape'){e.preventDefault();finish();return}unlock();},true);
 mute.addEventListener('click',()=>{if(locked){unlock();return}
  video.muted=!video.muted;userMuted=video.muted;mute.textContent=video.muted?'Sound on':'Mute';
  if(video.paused)video.play().catch(()=>{})});
 document.getElementById('skip').addEventListener('click',finish);
 video.addEventListener('ended',finish);
 video.addEventListener('error',finish);
 start();
})();
