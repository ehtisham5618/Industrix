/* Local Streamlit component: three independent, acknowledgement-paced sockets.
 * One JPEG in flight per camera; no capture/model/tracker runs in this frame. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const epoch = () => performance.timeOrigin + performance.now();
  const bounded = (a,v,n=1200) => { a.push(v); if(a.length>n)a.shift(); };
  let base='', stopped=false, clockOffset=0, cameras=new Map(), retryTimer=null;
  let telemetryBusy=false, telemetryTimer=null, cameraTimer=null, severity={};
  const metrics = {samples:[],telemetry:[],errors:[],cameraEvents:[],counts:{},detectedFrames:{},
    confirmationStates:{},trackIds:{},outOfOrder:0,staleEvents:0,telemetryUpdates:0,networkErrors:0,
    clockOffsetMs:0,clockUncertaintyMs:null,backend:'',startedAt:epoch(),configuredCameras:[]};
  window.__console={metrics,resetMetrics(){
    for(const key of ['samples','telemetry','errors','cameraEvents'])metrics[key].length=0;
    for(const key of ['counts','detectedFrames','confirmationStates','trackIds'])metrics[key]={};
    metrics.outOfOrder=metrics.staleEvents=metrics.telemetryUpdates=metrics.networkErrors=0;
    metrics.startedAt=epoch();
  }};
  const sendParent = (type,extra={}) => parent.postMessage({isStreamlitMessage:true,type,...extra},'*');
  const fit = () => sendParent('streamlit:setFrameHeight',{height:Math.ceil(document.querySelector('.console').getBoundingClientRect().height)});
  new ResizeObserver(fit).observe(document.body);
  function badge(el,label,kind='offline'){el.textContent=label;el.className='badge '+kind;}
  function state(c,label,kind='offline'){
    if(c.badge.textContent!==label)bounded(metrics.cameraEvents,{camera:c.id,state:label,at:epoch()},300);
    badge(c.badge,label,kind);c.state=label;
    c.canvas.style.opacity=label==='LIVE'?'1':'.35';
  }
  const local = host => ['localhost','127.0.0.1','::1','[::1]'].includes(host);
  async function get(path){
    const response=await fetch(base+path,{signal:AbortSignal.timeout(3500),cache:'no-store'});
    if(!response.ok)throw Error(path+' HTTP '+response.status);
    return response.json();
  }
  function card(config,index){
    const root=document.createElement('article');root.className='camera';root.dataset.camera=config.camera_id;
    // Only static markup enters innerHTML. All backend fields use textContent.
    root.innerHTML='<div class="camera-head"><div><small class="camera-id"></small><h3></h3></div><span class="badge offline">OFFLINE</span></div><div class="image-area"><canvas></canvas><div class="empty">Waiting for evaluated frames</div></div><div class="camera-foot"><span class="rate">0.00 evaluated FPS</span><span class="age">No frame</span></div><div class="focus"></div><div class="severity"></div>';
    root.querySelector('.camera-id').textContent='CAMERA '+String(index+1).padStart(2,'0')+(config.simulation?' · SIMULATION':'');
    root.querySelector('h3').textContent=config.name;
    root.querySelector('.focus').textContent=(config.monitored_classes||[]).join(' · ');
    $('cameras').append(root);
    const c={id:config.camera_id,config,root,canvas:root.querySelector('canvas'),badge:root.querySelector('.badge'),
      empty:root.querySelector('.empty'),rate:root.querySelector('.rate'),age:root.querySelector('.age'),
      state:'OFFLINE',lastReceive:0,lastActivity:0,lastFrame:null,retry:500,socket:null,timer:null,busy:false,generation:-1,frameId:-1};
    cameras.set(c.id,c);connect(c);return c;
  }
  function draw(c,bitmap,m){
    c.canvas.width=bitmap.width;c.canvas.height=bitmap.height;
    const ctx=c.canvas.getContext('2d');ctx.drawImage(bitmap,0,0);bitmap.close();
    const sx=c.canvas.width/m.frame_width,sy=c.canvas.height/m.frame_height;
    for(const zone of m.geofences||[]){
      if(!zone.enabled||!Array.isArray(zone.polygon)||!zone.polygon.length)continue;
      ctx.beginPath();zone.polygon.forEach((p,i)=>{const x=p[0]*c.canvas.width,y=p[1]*c.canvas.height;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
      ctx.closePath();ctx.strokeStyle='#66c9ff';ctx.lineWidth=1;ctx.setLineDash([5,4]);ctx.stroke();ctx.setLineDash([]);
    }
    // Keep label text readable when a tall native source is fitted into a card.
    // Coordinates still use native pixels; only drawing sizes compensate for CSS.
    const visibleScale=Math.min(c.canvas.clientWidth/c.canvas.width,c.canvas.clientHeight/c.canvas.height)||1;
    const fontSize=13/visibleScale,labelHeight=18/visibleScale,padding=5/visibleScale;
    ctx.font='bold '+fontSize+'px system-ui';ctx.lineWidth=2/visibleScale;
    for(const d of m.detections||[]){
      const xy=d.coordinates||{},v=['x1','y1','x2','y2'].map(k=>Number(xy[k]));
      if(!v.every(Number.isFinite)||v[2]<=v[0]||v[3]<=v[1])continue;
      const [x1,y1,x2,y2]=[v[0]*sx,v[1]*sy,v[2]*sx,v[3]*sy];
      const confirmed=['confirmed','active'].includes(d.confirmation_status);
      const sev=severity[c.id]||'normal';
      const color=confirmed?(sev==='critical'?'#ed4444':sev==='warning'?'#ffc04c':'#69bbff'):d.confirmation_status==='candidate'?'#ffca62':'#4fdda4';
      ctx.strokeStyle=color;ctx.strokeRect(x1,y1,x2-x1,y2-y1);
      const track=d.track_id==null?'':' · #'+d.track_id;
      const progress=d.confirmation_status==='candidate'?' · '+(d.persistence_frames||0)+'/'+(d.persist_frames_required||15):confirmed?' · CONFIRMED':'';
      const label=d.class_name+' '+(100*Number(d.confidence||0)).toFixed(0)+'%'+track+progress;
      const width=Math.min(ctx.measureText(label).width+2*padding,c.canvas.width);
      const tx=Math.max(0,Math.min(x1,c.canvas.width-width)),ty=Math.max(labelHeight,y1);
      ctx.fillStyle=color;ctx.fillRect(tx,ty-labelHeight,width,labelHeight);ctx.fillStyle='#101c2a';ctx.fillText(label,tx+padding,ty-padding,width-2*padding);
    }
    c.empty.style.display='none';
  }
  function connect(c){
    if(stopped)return;
    const url=new URL(base+'/cameras/'+encodeURIComponent(c.id)+'/live');url.protocol=url.protocol==='https:'?'wss:':'ws:';
    state(c,'CONNECTING','reconnecting');
    const ws=new WebSocket(url);c.socket=ws;ws.binaryType='arraybuffer';
    ws.onopen=()=>{c.retry=500;c.lastActivity=epoch();};
    ws.onmessage=async event=>{
      c.lastActivity=epoch();
      if(typeof event.data==='string'){
        try{const s=JSON.parse(event.data);const value=s.status?.status;
          if(value!=='running')state(c,value==='reconnecting'?'RECONNECTING':value==='starting'?'CONNECTING':'OFFLINE',value==='reconnecting'?'reconnecting':'offline');
        }catch(e){bounded(metrics.errors,String(e));}return;
      }
      if(c.busy){metrics.outOfOrder++;ws.close(1013,'unexpected unacknowledged frame');return;}
      c.busy=true;
      try{
        const data=event.data,n=new DataView(data).getUint32(0);
        if(n>data.byteLength-4)throw Error('Invalid frame envelope');
        const m=JSON.parse(new TextDecoder().decode(data.slice(4,4+n)));
        if(m.generation<c.generation||(m.generation===c.generation&&m.frame_id<=c.frameId)){
          metrics.outOfOrder++;throw Error('Out of order evaluated result');
        }
        const arrived=epoch()+clockOffset;
        const bitmap=await createImageBitmap(new Blob([data.slice(4+n)],{type:'image/jpeg'}));
        draw(c,bitmap,m);
        // Timestamp after the actual canvas bitmap/overlay update. Browser paint
        // scheduling and display scan-out are deliberately not claimed here.
        const updated=epoch()+clockOffset,delivery=updated-m.result_ready_at*1000;
        const sample={camera_id:c.id,frame_id:m.frame_id,generation:m.generation,
          delivery_ms:delivery,transport_ms:arrived-m.sent_at*1000,encoding_ms:m.encoding_ms,
          inference_ms:m.inference_time*1000,capture_to_canvas_ms:updated-m.timestamp*1000,
          result_ready_at:m.result_ready_at,browser_update_at:updated/1000,
          detections:(m.detections||[]).length,
          tracked:(m.detections||[]).filter(d=>d.track_id!=null).length,
          confirmed:(m.detections||[]).filter(d=>['confirmed','active'].includes(d.confirmation_status)).length};
        bounded(metrics.samples,sample);metrics.counts[c.id]=(metrics.counts[c.id]||0)+1;
        if(sample.detections)metrics.detectedFrames[c.id]=(metrics.detectedFrames[c.id]||0)+1;
        for(const d of m.detections||[]){metrics.confirmationStates[d.confirmation_status]=(metrics.confirmationStates[d.confirmation_status]||0)+1;
          if(d.track_id!=null){metrics.trackIds[c.id]??={};if(Object.keys(metrics.trackIds[c.id]).length<300)metrics.trackIds[c.id][d.track_id]=true;}}
        c.frameId=m.frame_id;c.generation=m.generation;c.lastReceive=epoch();c.lastFrame=m;state(c,'LIVE','live');
        c.age.textContent=(sample.capture_to_canvas_ms/1000).toFixed(2)+' s capture age';
        if(ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'rendered',frame_id:m.frame_id,
          delivery_ms:delivery,frame_age_ms:sample.capture_to_canvas_ms,browser_update_at:updated/1000}));
      }catch(e){bounded(metrics.errors,String(e));ws.close(1011,'frame decode/update failed');}
      finally{c.busy=false;}
    };
    ws.onclose=()=>{if(stopped)return;state(c,'RECONNECTING','reconnecting');
      c.timer=setTimeout(()=>connect(c),c.retry);c.retry=Math.min(5000,c.retry*2);};
    ws.onerror=()=>{metrics.networkErrors++;};
  }
  async function discover(){
    try{const result=await get('/cameras');
      metrics.configuredCameras=result.cameras.map(c=>c.camera_id);
      for(const [i,c] of result.cameras.slice(0,3).entries())if(!cameras.has(c.camera_id))card(c,i);
    }catch(e){badge($('connection'),'Backend offline');metrics.networkErrors++;}
    if(!stopped)cameraTimer=setTimeout(discover,5000);
  }
  async function telemetry(){
    if(telemetryBusy||stopped)return;telemetryBusy=true;
    try{
      const before=epoch(),data=await get('/system/status'),after=epoch(),rtt=after-before;
      // Midpoint clock alignment; retain the lowest-RTT sample for this connection.
      if(metrics.clockUncertaintyMs===null||rtt/2<metrics.clockUncertaintyMs){
        clockOffset=data.server_time*1000-(before+after)/2;
        metrics.clockUncertaintyMs=rtt/2;metrics.clockOffsetMs=clockOffset;
      }
      const e=data.engine||{},t=data.telemetry||{},p=data.privacy||{};
      $('engine').textContent=e.active?[e.name,e.precision].join(' ')+' ('+String(e.device).toUpperCase()+')':'Idle';
      $('cpu').textContent=Number.isFinite(t.cpu_system_percent)?t.cpu_system_percent.toFixed(1)+'%':'Unavailable';
      $('ram').textContent=Number.isFinite(t.process_rss_mb)?t.process_rss_mb.toFixed(0)+' MiB':'Unavailable';
      $('fps').textContent=Number.isFinite(t.aggregate_evaluated_fps)?t.aggregate_evaluated_fps.toFixed(2):'Unavailable';
      $('latency').textContent=Number.isFinite(t.model_inference_mean_ms)?t.model_inference_mean_ms.toFixed(1)+' / '+t.model_inference_p95_ms.toFixed(1)+' ms':'Unavailable';
      $('model-meta').textContent=e.active?'Model: '+(data.model_classes||[]).length+' classes loaded | '+(e.model_version||'')+' | Inference mean / P95: latest '+(t.model_inference_samples||0)+' calls':'Start feeds to verify the active model';
      $('privacy').textContent=local(new URL(base).hostname)&&local(location.hostname)&&p.local_processing_verified===true&&p.cloud_dependency_percent===0?'0% · On-Premise':'External / unverified';
      badge($('connection'),'Backend connected','live');
      for(const c of cameras.values())c.rate.textContent=Number(t.camera_evaluated_fps?.[c.id]||0).toFixed(2)+' evaluated FPS';
      metrics.telemetryUpdates++;bounded(metrics.telemetry,{at:after,...t,engine:e.name,privacy:$('privacy').textContent},300);
      try{const alerts=await get('/alerts/active');severity=alerts.camera_overall_severity||{};
        const events=alerts.events||[];
        for(const c of cameras.values()){
          const value=severity[c.id]||'normal',el=c.root.querySelector('.severity');
          el.textContent='SED-2 '+value.toUpperCase();el.className='severity '+value;
        }
        $('alert-text').textContent=events.length?events.slice(-8).map(e=>String(e.severity||'info').toUpperCase()+' · '+(e.camera_id||'')+' · '+(e.class_name||e.hazard_class||e.event_type||'Safety event')).join(' | '):'No active confirmed safety events';
        $('alerts').className='alerts '+(events.some(e=>e.severity==='critical')?'critical':events.some(e=>e.severity==='warning')?'warning':'');
        try{const relay=await get('/iot/status');
          $('iot-state').textContent=relay.state==='SHUTDOWN_TRIGGERED'?'SIMULATED SAFETY SHUTDOWN | Software mock only | '+relay.trigger_count+' trigger(s)':'Software-only IoT: '+relay.state;
        }catch(error){$('iot-state').textContent='Software-only IoT status unavailable';}
      }catch(error){$('alert-text').textContent=e.active?'Safety events unavailable':'Start streams to monitor safety events';
        for(const c of cameras.values())c.root.querySelector('.severity').textContent='Safety status unavailable';}
    }catch(e){metrics.networkErrors++;badge($('connection'),'Backend offline');
      for(const id of ['engine','cpu','ram','fps','privacy','latency'])$(id).textContent='Unavailable';
      $('model-meta').textContent='Active model unavailable';
      $('iot-state').textContent='Software-only IoT status unavailable';
      for(const c of cameras.values()){state(c,'OFFLINE');c.root.querySelector('.severity').textContent='Safety status unavailable';} $('alert-text').textContent='Backend unavailable; events cannot be verified';
    }finally{telemetryBusy=false;if(!stopped)telemetryTimer=setTimeout(telemetry,1000);}
  }
  setInterval(()=>{
    let live=0;for(const c of cameras.values()){
      if(c.socket?.readyState===WebSocket.OPEN&&epoch()-c.lastActivity>6000){
        state(c,'RECONNECTING','reconnecting');c.socket.close(4000,'Camera transport stopped responding');
      }
      if(c.state==='LIVE'&&epoch()-c.lastReceive>3000){state(c,'STALE','reconnecting');metrics.staleEvents++;}
      if(c.state==='LIVE')live++;
      if(c.lastFrame&&c.state==='LIVE')c.age.textContent=((epoch()+clockOffset-c.lastFrame.timestamp*1000)/1000).toFixed(2)+' s capture age';
    }$('feed-count').textContent=live+' / '+cameras.size+' live feeds';
  },500);
  window.addEventListener('message',event=>{
    if(event.source!==parent||event.data.type!=='streamlit:render')return;
    const value=event.data.args?.backend_url;
    if(!value||value===base)return;
    for(const c of cameras.values()){clearTimeout(c.timer);c.socket.onclose=null;c.socket.close();}
    clearTimeout(cameraTimer);clearTimeout(telemetryTimer);cameras.clear();$('cameras').replaceChildren();
    base=value.replace(/\/$/,'');metrics.backend=base;metrics.clockUncertaintyMs=null;
    discover();telemetry();fit();
  });
  window.addEventListener('beforeunload',()=>{stopped=true;for(const c of cameras.values()){clearTimeout(c.timer);c.socket.close();}});
  sendParent('streamlit:componentReady',{apiVersion:1});fit();
})();
