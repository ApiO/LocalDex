/** Offline FBX mesh renderer. Geometry is parsed by the local Python server.
 * No CDN, 3D engine installation, global assets, or downloaded-file writes.
 * This is a STATIC GEOMETRY preview, not a full FBX runtime or skinning renderer.
 */
export function startFbxViewer(canvas, mesh) {
  const gl = canvas.getContext('webgl', { antialias: true, alpha: false, preserveDrawingBuffer: false });
  if (!gl) return startCanvasMeshViewer(canvas, mesh);

  const vertexSource = `
    attribute vec3 position;
    attribute vec3 normal;
    uniform vec2 angles;
    uniform float zoom;
    uniform float aspect;
    varying float lighting;
    void main() {
      float cy = cos(angles.y), sy = sin(angles.y);
      float cx = cos(angles.x), sx = sin(angles.x);
      vec3 p = vec3(cy*position.x + sy*position.z, position.y, -sy*position.x + cy*position.z);
      p = vec3(p.x, cx*p.y - sx*p.z, sx*p.y + cx*p.z);
      vec3 n = vec3(cy*normal.x + sy*normal.z, normal.y, -sy*normal.x + cy*normal.z);
      n = normalize(vec3(n.x, cx*n.y - sx*n.z, sx*n.y + cx*n.z));
      lighting = .42 + .56*abs(dot(n, normalize(vec3(.3, .75, .63))));
      gl_Position = vec4(p.x * zoom / max(aspect, 1.), p.y * zoom * min(aspect, 1.), -p.z*.35, 1.);
    }`;
  const fragmentSource = `
    precision mediump float;
    varying float lighting;
    void main() {
      gl_FragColor = vec4(vec3(.56, .69, .96) * lighting, 1.);
    }`;
  const shader = (type, text) => {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, text); gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      const error = gl.getShaderInfoLog(sh); gl.deleteShader(sh);
      throw Error('3D shader failed: ' + error);
    }
    return sh;
  };
  const vs = shader(gl.VERTEX_SHADER, vertexSource), fs = shader(gl.FRAGMENT_SHADER, fragmentSource);
  const program = gl.createProgram();
  gl.attachShader(program, vs); gl.attachShader(program, fs); gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS))
    throw Error('3D renderer unavailable: ' + gl.getProgramInfoLog(program));
  gl.deleteShader(vs); gl.deleteShader(fs);

  const points = mesh.vertices, faces = mesh.triangles;
  const flat = new Float32Array(faces.length * 6);
  for (let i = 0, k = 0; i < faces.length; i += 3) {
    const a = faces[i]*3, b = faces[i+1]*3, c = faces[i+2]*3;
    const ax = points[a], ay = points[a+1], az = points[a+2];
    const ux = points[b]-ax, uy = points[b+1]-ay, uz = points[b+2]-az;
    const vx = points[c]-ax, vy = points[c+1]-ay, vz = points[c+2]-az;
    let nx = uy*vz-uz*vy, ny = uz*vx-ux*vz, nz = ux*vy-uy*vx;
    const len = Math.hypot(nx,ny,nz) || 1;
    nx /= len; ny /= len; nz /= len;
    for (const ix of [a,b,c]) {
      flat[k++] = points[ix]; flat[k++] = points[ix+1]; flat[k++] = points[ix+2];
      flat[k++] = nx; flat[k++] = ny; flat[k++] = nz;
    }
  }
  const vbo = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
  gl.bufferData(gl.ARRAY_BUFFER, flat, gl.STATIC_DRAW);
  gl.useProgram(program);
  const pLoc = gl.getAttribLocation(program, 'position'), nLoc = gl.getAttribLocation(program, 'normal');
  gl.enableVertexAttribArray(pLoc); gl.vertexAttribPointer(pLoc, 3, gl.FLOAT, false, 24, 0);
  gl.enableVertexAttribArray(nLoc); gl.vertexAttribPointer(nLoc, 3, gl.FLOAT, false, 24, 12);
  const aLoc = gl.getUniformLocation(program, 'angles');
  const zLoc = gl.getUniformLocation(program, 'zoom');
  const aspectLoc = gl.getUniformLocation(program, 'aspect');
  gl.enable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE);
  gl.clearColor(.078, .105, .156, 1);

  let angles = [-.33, .63], zoom = 1.1, dragging = false, oldX = 0, oldY = 0, ended = false;
  let scheduled = 0;
  const draw = () => {
    scheduled = 0;
    if (ended || !canvas.isConnected) return;
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(1, Math.floor(canvas.clientWidth * pixelRatio));
    const h = Math.max(1, Math.floor(canvas.clientHeight * pixelRatio));
    if (w !== canvas.width || h !== canvas.height) { canvas.width = w; canvas.height = h; }
    gl.viewport(0, 0, w, h);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.useProgram(program); gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    gl.uniform2f(aLoc, angles[0], angles[1]);
    gl.uniform1f(zLoc, zoom); gl.uniform1f(aspectLoc, w/h);
    gl.drawArrays(gl.TRIANGLES, 0, faces.length);
  };
  const redraw = () => { if (!scheduled && !ended) scheduled = requestAnimationFrame(draw); };
  const down = e => {
    dragging = true; oldX = e.clientX; oldY = e.clientY;
    canvas.setPointerCapture(e.pointerId);
  };
  const move = e => {
    if (!dragging) return;
    angles[1] += (e.clientX - oldX)*.012;
    angles[0] += (e.clientY - oldY)*.012;
    oldX = e.clientX; oldY = e.clientY; redraw();
  };
  const up = () => { dragging = false; };
  const wheel = e => { e.preventDefault(); zoom = Math.max(.3, Math.min(5, zoom * Math.exp(-e.deltaY*.001))); redraw(); };
  canvas.addEventListener('pointerdown', down);
  canvas.addEventListener('pointermove', move);
  canvas.addEventListener('pointerup', up);
  canvas.addEventListener('pointercancel', up);
  canvas.addEventListener('wheel', wheel, { passive: false });
  const observer = new ResizeObserver(redraw); observer.observe(canvas);
  redraw();
  return () => {
    ended = true;
    if (scheduled) cancelAnimationFrame(scheduled);
    observer.disconnect();
    canvas.removeEventListener('pointerdown', down);
    canvas.removeEventListener('pointermove', move);
    canvas.removeEventListener('pointerup', up);
    canvas.removeEventListener('pointercancel', up);
    canvas.removeEventListener('wheel', wheel);
    gl.deleteBuffer(vbo); gl.deleteProgram(program);
    gl.getExtension('WEBGL_lose_context')?.loseContext();
  };
}


// CPU-backed fallback for browser sessions without WebGL/GPU acceleration.
// It still gives the user an interactive 3D-shaped shaded mesh preview.
function startCanvasMeshViewer(canvas, mesh) {
  const ctx = canvas.getContext('2d');
  if (!ctx) throw Error('Canvas preview unavailable');
  const points=mesh.vertices, tris=mesh.triangles;
  let yaw=.67, pitch=-.28, zoom=1, dragging=false, px=0, py=0, ended=false, pending=0;
  const step = Math.max(3, Math.ceil(tris.length / 3 / 3200)*3);
  const render = () => {
    pending=0;
    if (ended || !canvas.isConnected) return;
    const ratio=Math.min(window.devicePixelRatio||1, 2);
    const width=Math.max(1, Math.floor(canvas.clientWidth*ratio));
    const height=Math.max(1,Math.floor(canvas.clientHeight*ratio));
    canvas.width=width;canvas.height=height;
    ctx.fillStyle='#141b29';ctx.fillRect(0,0,width,height);
    const cosY=Math.cos(yaw), sinY=Math.sin(yaw), cosX=Math.cos(pitch), sinX=Math.sin(pitch);
    const project=(ix) => {
      const x=points[ix*3],y=points[ix*3+1],z=points[ix*3+2];
      const xx=cosY*x+sinY*z, zz=-sinY*x+cosY*z;
      return [xx,cosX*y-sinX*zz,sinX*y+cosX*zz];
    };
    const out=[];
    for (let k=0;k<tris.length;k+=step) {
      if (k+2>=tris.length) break;
      const a=project(tris[k]),b=project(tris[k+1]),c=project(tris[k+2]);
      const ux=b[0]-a[0],uy=b[1]-a[1],uz=b[2]-a[2];
      const vx=c[0]-a[0],vy=c[1]-a[1],vz=c[2]-a[2];
      let nx=uy*vz-uz*vy,ny=uz*vx-ux*vz,nz=ux*vy-uy*vx;
      const len=Math.hypot(nx,ny,nz)||1;
      const lit=Math.max(.22, Math.min(.9,.45+ .45*Math.abs((nx*.32+ny*.78+nz*.54)/len)));
      out.push([(a[2]+b[2]+c[2])/3,a,b,c,lit]);
    }
    out.sort((a,b)=>a[0]-b[0]);
    const scale=.92*Math.min(width,height)*zoom;
    const xy=v=>[width*.5+v[0]*scale,height*.5-v[1]*scale];
    for (const [,a,b,c,lit] of out) {
      const [ax,ay]=xy(a),[bx,by]=xy(b),[cx,cy]=xy(c);
      ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(bx,by);ctx.lineTo(cx,cy);ctx.closePath();
      ctx.fillStyle=`rgb(${Math.round(lit*155)},${Math.round(lit*180)},${Math.round(lit*242)})`;
      ctx.fill();ctx.strokeStyle='rgba(205,175,238,.16)';ctx.lineWidth=.6*ratio;ctx.stroke();
    }
  };
  const redraw=()=>{if(!pending && !ended) pending=requestAnimationFrame(render);};
  const down=e=>{dragging=true;px=e.clientX;py=e.clientY;canvas.setPointerCapture(e.pointerId);};
  const move=e=>{if (!dragging) return;yaw+=(e.clientX-px)*.011;pitch+=(e.clientY-py)*.011;px=e.clientX;py=e.clientY;redraw();};
  const up=()=>{dragging=false;};
  const wheel=e=>{e.preventDefault();zoom=Math.max(.35,Math.min(4,zoom*Math.exp(-e.deltaY*.001)));redraw();};
  canvas.addEventListener('pointerdown',down);
  canvas.addEventListener('pointermove',move);
  canvas.addEventListener('pointerup',up);
  canvas.addEventListener('pointercancel',up);
  canvas.addEventListener('wheel',wheel,{passive:false});
  const observer=new ResizeObserver(redraw);observer.observe(canvas);
  redraw();
  return ()=>{ended=true;if(pending)cancelAnimationFrame(pending);observer.disconnect();
    canvas.removeEventListener('pointerdown',down);canvas.removeEventListener('pointermove',move);
    canvas.removeEventListener('pointerup',up);canvas.removeEventListener('pointercancel',up);
    canvas.removeEventListener('wheel',wheel);};
}
