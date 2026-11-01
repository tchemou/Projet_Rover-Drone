/* Vigie Betterave · jumeau numérique 3D (WebGL / Three.js)
   Lit l'état partagé de la console (window.__vigie) alimenté en direct par ROS 2 via rosbridge.
   Repère Gazebo (x, y, z haut) -> Three.js (x, z, -y). */
(function () {
'use strict';
function boot() {
  const S = window.__vigie, host = document.getElementById('map3d'), T = window.THREE;
  if (!S || !host || !T || !T.OrbitControls) { document.body.classList.add('no3d'); return; }
  const P = (x, y, z = 0) => new T.Vector3(x, z, -y);
  const rng = seed => { let s = seed >>> 0; return () => (s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296; };
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };
  const ROWS = Array.from({ length: 11 }, (_, i) => -3 + i * 0.6), XS = Array.from({ length: 31 }, (_, i) => -6 + i * 0.4);
  const WIND = { value: 0 };

  /* ---------------------------------------------------------------- rendu */
  let renderer;
  try { renderer = new T.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' }); }
  catch (e) { document.body.classList.add('no3d'); return; }
  renderer.setPixelRatio(Math.min(2, devicePixelRatio));
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = T.PCFSoftShadowMap;
  renderer.outputEncoding = T.sRGBEncoding;
  host.appendChild(renderer.domElement); renderer.domElement.className = 'gl3d';
  const scene = new T.Scene();
  scene.fog = new T.FogExp2(0x9bbbd6, 0.0048);
  const camera = new T.PerspectiveCamera(46, 1.9, 0.05, 1400);
  camera.position.set(6.8, 6.4, 10.5);
  const controls = new T.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.07; controls.maxPolarAngle = 1.48; controls.minDistance = 0.8; controls.maxDistance = 48;
  controls.target.set(-0.5, 0.1, 0.3);

  /* ciel, soleil, lumières */
  const sky = new T.Sky(); sky.scale.setScalar(9000); scene.add(sky);
  const su = sky.material.uniforms; su.turbidity.value = 3.2; su.rayleigh.value = 2.2; su.mieCoefficient.value = 0.003; su.mieDirectionalG.value = 0.85;
  const sunDir = new T.Vector3().setFromSphericalCoords(1, T.MathUtils.degToRad(90 - 34), T.MathUtils.degToRad(215));
  su.sunPosition.value.copy(sunDir);
  const sun = new T.DirectionalLight(0xfff0d4, 1.45);
  sun.position.copy(sunDir).multiplyScalar(40); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048); sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.02;
  const sc = sun.shadow.camera; sc.left = -12; sc.right = 12; sc.top = 9; sc.bottom = -9; sc.near = 1; sc.far = 90;
  scene.add(sun, sun.target);
  scene.add(new T.HemisphereLight(0xb4d0f0, 0x3a2e22, 0.55));

  /* ---------------------------------------------------------------- textures procédurales */
  function canvasTex(w, h, draw, rx = 1, ry = 1, srgb = true) {
    const c = document.createElement('canvas'); c.width = w; c.height = h; draw(c.getContext('2d'), w, h);
    const t = new T.CanvasTexture(c); t.wrapS = t.wrapT = T.RepeatWrapping; t.repeat.set(rx, ry); if (srgb) t.encoding = T.sRGBEncoding; t.anisotropy = 8; return t;
  }
  const grassTex = canvasTex(512, 512, (c, w) => { const R = rng(3); c.fillStyle = '#3f6e2d'; c.fillRect(0, 0, w, w);
    for (let i = 0; i < 11000; i++) { const v = R(); c.strokeStyle = v < .4 ? 'rgba(135,195,85,.45)' : v < .75 ? 'rgba(22,58,18,.5)' : 'rgba(214,228,125,.32)'; c.lineWidth = 1; const x = R() * w, y = R() * w; c.beginPath(); c.moveTo(x, y); c.lineTo(x + (R() - .5) * 4, y - 3 - R() * 7); c.stroke(); } }, 70, 70);
  const soilDraw = (bump) => (c, w) => { const R = rng(9); c.fillStyle = bump ? '#808080' : '#6a4a33'; c.fillRect(0, 0, w, w);
    for (let i = 0; i < 16000; i++) { const v = R(), s = 1 + R() * 3.2;
      if (bump) c.fillStyle = v < .5 ? 'rgba(0,0,0,.35)' : 'rgba(255,255,255,.28)'; else c.fillStyle = v < .5 ? 'rgba(30,15,6,.4)' : v < .8 ? 'rgba(200,150,105,.2)' : 'rgba(255,235,210,.12)';
      c.beginPath(); c.arc(R() * w, R() * w, s, 0, 7); c.fill(); } };
  const soilTex = canvasTex(512, 512, soilDraw(false), 9, 5), soilBump = canvasTex(512, 512, soilDraw(true), 9, 5, false);
  const gravelTex = canvasTex(256, 256, (c, w) => { const R = rng(5); c.fillStyle = '#9a9384'; c.fillRect(0, 0, w, w);
    for (let i = 0; i < 2800; i++) { c.fillStyle = R() < .5 ? 'rgba(255,255,255,.3)' : 'rgba(40,35,28,.35)'; c.beginPath(); c.arc(R() * w, R() * w, .8 + R() * 2, 0, 7); c.fill(); } }, 2, 20);
  const padTex = canvasTex(512, 512, (c, w) => { c.fillStyle = '#6c7a82'; c.fillRect(0, 0, w, w); c.strokeStyle = '#f0b43a'; c.lineWidth = 14; c.setLineDash([36, 26]); c.beginPath(); c.arc(w / 2, w / 2, w * .44, 0, 7); c.stroke(); c.setLineDash([]);
    c.fillStyle = '#fff'; c.font = '800 300px sans-serif'; c.textAlign = 'center'; c.textBaseline = 'middle'; c.fillText('H', w / 2, w / 2 + 12); });
  const softTex = canvasTex(64, 64, (c, w) => { const g = c.createRadialGradient(w / 2, w / 2, 0, w / 2, w / 2, w / 2); g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(1, 'rgba(255,255,255,0)'); c.fillStyle = g; c.fillRect(0, 0, w, w); });
  softTex.wrapS = softTex.wrapT = T.ClampToEdgeWrapping;
  const cloudTex = canvasTex(512, 256, (c, w, h) => { const R = rng(17); for (let i = 0; i < 26; i++) { const x = 90 + R() * (w - 180), y = h * .55 + (R() - .5) * 60, r = 40 + R() * 55, g = c.createRadialGradient(x, y, 0, x, y, r);
    g.addColorStop(0, 'rgba(255,255,255,.55)'); g.addColorStop(.6, 'rgba(255,255,255,.22)'); g.addColorStop(1, 'rgba(255,255,255,0)'); c.fillStyle = g; c.fillRect(0, 0, w, h); } });
  cloudTex.wrapS = cloudTex.wrapT = T.ClampToEdgeWrapping;
  // feuilles de betterave : forme, nervures, taches (saine / atteinte)
  function leafTexture(sick) {
    return canvasTex(256, 128, (c, w, h) => {
      const R = rng(sick ? 71 : 61); c.clearRect(0, 0, w, h);
      const path = () => { c.beginPath(); c.moveTo(3, 64); c.bezierCurveTo(52, 2, 170, 8, 252, 64); c.bezierCurveTo(170, 120, 52, 126, 3, 64); c.closePath(); };
      const g = c.createLinearGradient(0, 0, w, 0);
      if (sick) { g.addColorStop(0, '#8d8a26'); g.addColorStop(.5, '#c4b43a'); g.addColorStop(1, '#a89a2a'); } else { g.addColorStop(0, '#256f35'); g.addColorStop(.5, '#3c9a4a'); g.addColorStop(1, '#2f8240'); }
      path(); c.fillStyle = g; c.fill(); c.save(); path(); c.clip();
      for (let i = 0; i < 700; i++) { c.fillStyle = R() < .5 ? 'rgba(255,255,255,.05)' : 'rgba(0,0,0,.06)'; c.fillRect(R() * w, R() * h, 2 + R() * 6, 1 + R() * 3); }
      c.strokeStyle = sick ? 'rgba(244,236,150,.8)' : 'rgba(170,230,170,.75)'; c.lineWidth = 3.2; c.beginPath(); c.moveTo(3, 64); c.lineTo(236, 64); c.stroke(); c.lineWidth = 1.5;
      for (let t = .1; t < .92; t += .085) for (const s of [-1, 1]) { const x = 3 + t * 240; c.beginPath(); c.moveTo(x, 64); c.quadraticCurveTo(x + 18, 64 + s * 22 * (1 - t * .5), x + 46, 64 + s * (44 * (1 - t) + 6)); c.stroke(); }
      if (sick) for (let i = 0; i < 34; i++) { const x = 30 + R() * 200, y = 30 + R() * 68, r = 2 + R() * 4.2; c.fillStyle = '#7a2a1a'; c.beginPath(); c.arc(x, y, r, 0, 7); c.fill(); c.fillStyle = '#d9b9a0'; c.beginPath(); c.arc(x, y, r * .45, 0, 7); c.fill(); c.strokeStyle = 'rgba(120,30,20,.8)'; c.lineWidth = 1; c.beginPath(); c.arc(x, y, r + 1, 0, 7); c.stroke(); }
      c.restore(); path(); c.strokeStyle = sick ? 'rgba(90,70,20,.9)' : 'rgba(15,60,25,.9)'; c.lineWidth = 2; c.stroke();
    });
  }
  const leafOK = leafTexture(false), leafSick = leafTexture(true);

  /* vent : léger balancement injecté dans les matériaux standards */
  function addWind(mat, kind) {
    mat.onBeforeCompile = sh => {
      sh.uniforms.uTime = WIND;
      const body = kind === 'grass' ? 'float f = position.y; transformed.x += sin(uTime*1.9 + ip.x*0.7 + ip.z*0.5)*0.09*f*f; transformed.z += cos(uTime*1.5 + ip.z*0.8 + ip.x*0.3)*0.06*f*f;'
        : kind === 'leaf' ? 'float f = length(position.xz)/0.3; transformed.y += sin(uTime*2.3 + ip.x*1.1 + ip.z*0.9 + position.x*9.0)*0.014*f; transformed.x += sin(uTime*1.7 + ip.x*0.8 + ip.z*0.4)*0.008*f;'
        : 'float f = max(0.0, position.y)*0.3; transformed.x += sin(uTime*1.1 + position.y*1.3)*0.04*f; transformed.z += cos(uTime*0.9 + position.x)*0.03*f;';
      sh.vertexShader = 'uniform float uTime;\n' + sh.vertexShader.replace('#include <begin_vertex>',
        'vec3 transformed = vec3(position);\n#ifdef USE_INSTANCING\n vec3 ip = vec3(instanceMatrix[3][0], instanceMatrix[3][1], instanceMatrix[3][2]);\n#else\n vec3 ip = vec3(0.0);\n#endif\n' + body);
    };
  }

  /* ---------------------------------------------------------------- terrain, collines, chemin */
  const hillH = (x, z) => { const r = Math.hypot(x, z), k = smooth(34, 130, r); return k * (7 + 5 * Math.sin(x * .032 + 1) * Math.cos(z * .027) + 3 * Math.sin(x * .071 + z * .053) + 2 * Math.sin(z * .11)); };
  const gg = new T.PlaneGeometry(760, 760, 240, 240), gp = gg.attributes.position, gc = [];
  for (let i = 0; i < gp.count; i++) { const x = gp.getX(i), z = -gp.getY(i), h = hillH(x, z); gp.setZ(i, h); const d = clamp(h / 12, 0, 1); gc.push(.82 - d * .36, .9 - d * .28, .8 - d * .4); }
  gg.setAttribute('color', new T.Float32BufferAttribute(gc, 3)); gg.computeVertexNormals();
  const ground = new T.Mesh(gg, new T.MeshStandardMaterial({ map: grassTex, vertexColors: true, roughness: 1 })); ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; scene.add(ground);
  const road = new T.Mesh(new T.PlaneGeometry(1.6, 70), new T.MeshStandardMaterial({ map: gravelTex, roughness: .95 }));
  road.rotation.x = -Math.PI / 2; road.position.set(8.55, 0.012, 0); road.receiveShadow = true; scene.add(road);
  const fg = new T.PlaneGeometry(14.6, 7.1, 292, 142), pos = fg.attributes.position, cols = [];
  for (let i = 0; i < pos.count; i++) { const v = pos.getY(i), h = 0.5 + 0.5 * Math.cos(((v + 3) / 0.6) * Math.PI * 2); pos.setZ(i, 0.015 + 0.075 * Math.pow(h, 1.3)); const k = 0.6 + 0.4 * h; cols.push(k, k, k); }
  fg.setAttribute('color', new T.Float32BufferAttribute(cols, 3)); fg.computeVertexNormals();
  const field = new T.Mesh(fg, new T.MeshStandardMaterial({ map: soilTex, bumpMap: soilBump, bumpScale: 2.2, vertexColors: true, roughness: 1 }));
  field.rotation.x = -Math.PI / 2; field.receiveShadow = true; scene.add(field);

  /* herbe : des dizaines de milliers de brins qui ondulent */
  const bladeGeo = (() => { const g = new T.BufferGeometry(), v = [-.012, 0, 0, .012, 0, 0, -.009, .5, 0, .009, .5, 0, 0, 1, 0], c = [.07, .18, .05, .07, .18, .05, .18, .4, .1, .18, .4, .1, .45, .65, .22];
    g.setAttribute('position', new T.Float32BufferAttribute(v, 3)); g.setAttribute('color', new T.Float32BufferAttribute(c, 3)); g.setIndex([0, 1, 2, 1, 3, 2, 2, 3, 4]); g.computeVertexNormals(); return g; })();
  const NG = 38000, grassMat = new T.MeshStandardMaterial({ vertexColors: true, roughness: .9, side: T.DoubleSide }); addWind(grassMat, 'grass');
  const grass = new T.InstancedMesh(bladeGeo, grassMat, NG), RG = rng(77), m4 = new T.Matrix4(), q = new T.Quaternion(), e = new T.Euler(), sc3 = new T.Vector3(), p3 = new T.Vector3();
  for (let i = 0, n = 0; n < NG && i < NG * 6; i++) {
    const x = (RG() - .5) * 52, z = (RG() - .5) * 34;
    if (Math.abs(x) < 7.9 && Math.abs(z) < 4.2) continue;                 // pas dans la parcelle
    if (x > 7.65 && x < 9.45) continue;                                    // ni sur le chemin
    if (Math.hypot(x + 9.2, z - 2.2) < 1.2) continue;                      // ni sur l'aire du drone
    const h = (.16 + RG() * .34) * (1 + .5 * smooth(8, 24, Math.hypot(x, z)) * RG());
    p3.set(x, hillH(x, z) * 0 + .0, z); e.set((RG() - .5) * .3, RG() * 6.28, (RG() - .5) * .3); q.setFromEuler(e); sc3.set(1 + RG(), h, 1); m4.compose(p3, q, sc3); grass.setMatrixAt(n, m4);
    grass.setColorAt(n, new T.Color().setHSL(.23 + RG() * .06, .5 + RG() * .2, .75 + RG() * .35)); n++;
  }
  grass.receiveShadow = true; scene.add(grass);

  /* feuillages organiques (haies, arbres, lisière lointaine) */
  function foliageGeo(r, detail, seed) {
    let g = new T.IcosahedronGeometry(r, detail); g.deleteAttribute("normal"); g.deleteAttribute("uv"); g = T.BufferGeometryUtils.mergeVertices(g, 1e-4); const p = g.attributes.position, R = rng(seed), col = [];
    for (let i = 0; i < p.count; i++) { const x = p.getX(i), y = p.getY(i), z = p.getZ(i), l = Math.hypot(x, y, z), n = 1 + .16 * Math.sin(x * 5.1 + z * 3.7) + .1 * Math.sin(y * 7.3 + x * 2.9) + (R() - .5) * .05;
      p.setXYZ(i, x / l * r * n, y / l * r * n, z / l * r * n); const hgt = clamp(y / r * .5 + .5, 0, 1); col.push(.12 + hgt * .22 + R() * .03, .3 + hgt * .3, .1 + hgt * .08); }
    g.setAttribute('color', new T.Float32BufferAttribute(col, 3)); g.computeVertexNormals(); return g;
  }
  const foliMat = new T.MeshStandardMaterial({ vertexColors: true, roughness: .92 });
  const hedgeG = foliageGeo(1, 2, 5), hedge = new T.InstancedMesh(hedgeG, foliMat, 150), R5 = rng(21);
  for (let i = 0; i < 150; i++) { const side = i < 75 ? 1 : -1, x = -13 + (i % 75) * .36 + R5() * .2, r = .38 + R5() * .24;
    p3.set(x, r * .85, side * -4.9 + (R5() - .5) * .3); sc3.set(r * 1.25, r, r * 1.25); e.set(R5() * 3, R5() * 6, 0); q.setFromEuler(e); m4.compose(p3, q, sc3); hedge.setMatrixAt(i, m4);
    hedge.setColorAt(i, new T.Color().setHSL(.27 + R5() * .05, .65, .55 + R5() * .25)); }
  hedge.castShadow = hedge.receiveShadow = true; scene.add(hedge);
  const trunkMat = new T.MeshStandardMaterial({ color: 0x5a4030, roughness: 1 }), treeFol = foliageGeo(1, 3, 9), treeMat = foliMat.clone(); addWind(treeMat, 'tree');
  const trees = [[-12.5, -4.5], [-9.5, -8.5], [13, -9.5], [14.5, 6.5], [-15.5, 2], [8.5, 9.5], [-6, 11], [11.5, -3.5], [-17, -7], [16, 1]];
  trees.forEach(([x, y], i) => { const h = 3.4 + (i % 3) * .9, t = new T.Mesh(new T.CylinderGeometry(.13, .24, h, 10), trunkMat); t.position.copy(P(x, y, h / 2)); t.castShadow = true; scene.add(t);
    const RT = rng(40 + i); for (let k = 0; k < 6; k++) { const f = new T.Mesh(treeFol, treeMat), s = 1.25 - k * .1 + RT() * .25; f.scale.set(s, s * .9, s); f.position.copy(P(x + (RT() - .5) * 1.3, y + (RT() - .5) * 1.3, h + .5 + k * .42 + RT() * .3)); f.rotation.y = RT() * 6; f.castShadow = true; f.receiveShadow = true; scene.add(f); } });
  const farTrees = new T.InstancedMesh(foliageGeo(1, 1, 3), foliMat, 260), RF = rng(88);
  for (let i = 0; i < 260; i++) { const a = RF() * 6.28, r = 85 + RF() * 110, x = Math.cos(a) * r, z = Math.sin(a) * r, s = 2.5 + RF() * 3.5;
    p3.set(x, hillH(x, z) + s * .8, z); sc3.set(s, s * 1.2, s); e.set(0, RF() * 6, 0); q.setFromEuler(e); m4.compose(p3, q, sc3); farTrees.setMatrixAt(i, m4); farTrees.setColorAt(i, new T.Color().setHSL(.3 + RF() * .05, .5, .35 + RF() * .2)); }
  scene.add(farTrees);
  // hangar, aire du drone, station, bornes
  const hangar = new T.Group(), hm = new T.MeshStandardMaterial({ color: 0x8a9a94, roughness: .55, metalness: .35 });
  const hb = new T.Mesh(new T.BoxGeometry(7, 3, 5), hm); hb.position.y = 1.5; const hr = new T.Mesh(new T.BoxGeometry(7.6, .2, 5.6), new T.MeshStandardMaterial({ color: 0x9a5646, roughness: .7 })); hr.position.y = 3.15;
  const door = new T.Mesh(new T.BoxGeometry(3, 2.4, .1), new T.MeshStandardMaterial({ color: 0x586a64, roughness: .5, metalness: .4 })); door.position.set(0, 1.2, 2.55);
  [hb, hr, door].forEach(o => { o.castShadow = o.receiveShadow = true; hangar.add(o); }); hangar.position.copy(P(-13.5, 9)); scene.add(hangar);
  const pad = new T.Mesh(new T.CircleGeometry(.95, 48), new T.MeshStandardMaterial({ map: padTex, roughness: .8 })); pad.rotation.x = -Math.PI / 2; pad.position.copy(P(-9.2, -2.2, .02)); pad.receiveShadow = true; scene.add(pad);
  const stn = new T.Mesh(new T.BoxGeometry(.8, .05, .52), new T.MeshStandardMaterial({ color: 0x7e898e, roughness: .7 })); stn.position.copy(P(-6.9, .3, .03)); stn.receiveShadow = true; scene.add(stn);
  [[-7.65, -3.85], [-7.65, 3.85], [7.65, -3.85], [7.65, 3.85]].forEach(([x, y]) => { const b = new T.Mesh(new T.CylinderGeometry(.06, .06, .7, 10), new T.MeshStandardMaterial({ color: 0xe9e2c8, roughness: .6 })); b.position.copy(P(x, y, .35)); b.castShadow = true; scene.add(b); });

  /* nuages, halo du soleil, pollen */
  const clouds = []; const RC = rng(5);
  for (let i = 0; i < 12; i++) { const sp = new T.Sprite(new T.SpriteMaterial({ map: cloudTex, transparent: true, opacity: .55 + RC() * .3, depthWrite: false, fog: false })); sp.scale.set(120 + RC() * 120, 50 + RC() * 40, 1);
    sp.position.set((RC() - .5) * 600, 70 + RC() * 40, (RC() - .5) * 500 - 120); clouds.push(sp); scene.add(sp); }
  const glare = new T.Sprite(new T.SpriteMaterial({ map: softTex, color: 0xffe9b0, transparent: true, opacity: .55, blending: T.AdditiveBlending, depthWrite: false, fog: false })); glare.scale.set(420, 420, 1); glare.position.copy(sunDir).multiplyScalar(900); scene.add(glare);
  const NPO = 380, pol = new Float32Array(NPO * 3), polBase = new Float32Array(NPO * 3), RP = rng(31);
  for (let i = 0; i < NPO; i++) { polBase[i * 3] = (RP() - .5) * 30; polBase[i * 3 + 1] = .2 + RP() * 4; polBase[i * 3 + 2] = (RP() - .5) * 20; }
  const polG = new T.BufferGeometry(); polG.setAttribute('position', new T.BufferAttribute(pol, 3));
  const pollen = new T.Points(polG, new T.PointsMaterial({ size: .06, map: softTex, color: 0xfff1c4, transparent: true, opacity: .6, depthWrite: false, blending: T.AdditiveBlending })); pollen.frustumCulled = false; scene.add(pollen);

  /* ---------------------------------------------------------------- plants : feuilles texturées, nervurées, qui bougent au vent */
  function leafGeometry() {
    const len = .31, wid = .15, parts = [], R = rng(13);
    for (let i = 0; i < 8; i++) {
      const g = new T.PlaneGeometry(len, wid, 8, 4); g.rotateX(-Math.PI / 2); g.translate(len / 2, 0, 0); const p = g.attributes.position;
      const bend = .25 + R() * .25;
      for (let k = 0; k < p.count; k++) { const x = p.getX(k) / len, z = p.getZ(k); p.setY(k, len * (bend * x - .5 * x * x) + 2.2 * z * z * (1 - x * .4) + .006 * Math.sin(x * 9 + i)); }
      g.rotateY(i * Math.PI * 2 / 8 + (R() - .5) * .35); g.rotateZ(0); const s = .8 + R() * .32; g.scale(s, s, s); g.computeVertexNormals(); parts.push(g);
    }
    return T.BufferGeometryUtils.mergeBufferGeometries(parts);
  }
  const plantGeo = leafGeometry();
  const mkLeafMat = tex => { const m = new T.MeshStandardMaterial({ map: tex, alphaTest: .42, side: T.DoubleSide, roughness: .5, metalness: 0 }); addWind(m, 'leaf'); return m; };
  const depthFor = tex => new T.MeshDepthMaterial({ depthPacking: T.RGBADepthPacking, map: tex, alphaTest: .42 });
  const healthy = new T.InstancedMesh(plantGeo, mkLeafMat(leafOK), 341), sick = new T.InstancedMesh(plantGeo, mkLeafMat(leafSick), 160);
  healthy.customDepthMaterial = depthFor(leafOK); sick.customDepthMaterial = depthFor(leafSick);
  healthy.castShadow = healthy.receiveShadow = sick.castShadow = sick.receiveShadow = true;
  const R6 = rng(33), hIndex = new Map(); let nPl = 0;
  ROWS.forEach((ry, iy) => XS.forEach((x, ix) => {
    const px = x + (R6() - .5) * .06, py = ry + (R6() - .5) * .05, s = .95 + R6() * .3, rot = R6() * 6.28;
    p3.copy(P(px, py, .07)); e.set(0, rot, 0); q.setFromEuler(e); sc3.set(s, s * (.9 + R6() * .3), s); m4.compose(p3, q, sc3); healthy.setMatrixAt(nPl, m4);
    healthy.setColorAt(nPl, new T.Color().setHSL(.33, .1 + R6() * .1, .85 + R6() * .25)); hIndex.set(iy * 31 + ix, { i: nPl, m: m4.clone(), p: p3.clone(), rot, s }); nPl++;
  }));
  scene.add(healthy);
  const zeroM = new T.Matrix4().makeScale(0, 0, 0); for (let i = 0; i < 160; i++) { sick.setMatrixAt(i, zeroM); sick.setColorAt(i, new T.Color(0xffffff)); } scene.add(sick);
  const sickSlot = new Map(); let sickN = 0;

  /* marqueurs de détection */
  const ringGeo = new T.RingGeometry(.2, .27, 56), beamGeo = new T.CylinderGeometry(.018, .018, 1.4, 8, 1, true), pingGeo = new T.RingGeometry(.97, 1, 64);
  const marks = new Map(), pings = [];
  function addMark(p) {
    const ring = new T.Mesh(ringGeo, new T.MeshBasicMaterial({ color: 0xff4b3a, transparent: true, opacity: .95, side: T.DoubleSide, depthWrite: false })); ring.rotation.x = -Math.PI / 2; ring.position.copy(P(p.x, p.y, .13));
    const beam = new T.Mesh(beamGeo, new T.MeshBasicMaterial({ color: 0xff4b3a, transparent: true, opacity: .35, depthWrite: false, blending: T.AdditiveBlending })); beam.position.copy(P(p.x, p.y, .8));
    scene.add(ring, beam); marks.set(p.id, { ring, beam, treated: false });
    const gx = Math.round((p.x + 6) / .4), gy = Math.round((p.y + 3) / .6), h = hIndex.get(gy * 31 + gx);
    if (h && sickN < 160) { healthy.setMatrixAt(h.i, zeroM); healthy.instanceMatrix.needsUpdate = true; sick.setMatrixAt(sickN, h.m); sickSlot.set(p.id, { s: sickN, h }); sickN++; sick.instanceMatrix.needsUpdate = true; }
    pings.push({ x: p.x, y: p.y, t: performance.now() + pings.length * 80 });
  }

  /* ---------------------------------------------------------------- drone */
  const drone = new T.Group(), metal = (c, m = .4, r = .4) => new T.MeshStandardMaterial({ color: c, metalness: m, roughness: r });
  const dBody = new T.Mesh(new T.BoxGeometry(.2, .055, .2), metal(0xf2f4f6, .15, .3)), dStripe = new T.Mesh(new T.BoxGeometry(.205, .057, .045), metal(0xc63777, .1, .4));
  const dTop = new T.Mesh(new T.BoxGeometry(.15, .018, .15), metal(0x1c2228, .5, .3)); dTop.position.y = .036;
  const dBat = new T.Mesh(new T.BoxGeometry(.12, .035, .07), metal(0x20262c)); dBat.position.y = -.045;
  const dGim = new T.Mesh(new T.BoxGeometry(.07, .04, .06), metal(0x14181c)); dGim.position.set(.04, -.075, 0);
  const dLens = new T.Mesh(new T.CylinderGeometry(.02, .02, .03, 16), metal(0x05070a, .9, .1)); dLens.position.set(.04, -.105, 0);
  const ledF = new T.Mesh(new T.SphereGeometry(.012, 8, 8), new T.MeshBasicMaterial({ color: 0x4dff88 })), ledR = new T.Mesh(new T.SphereGeometry(.012, 8, 8), new T.MeshBasicMaterial({ color: 0xff4b3a }));
  ledF.position.set(.105, 0, 0); ledR.position.set(-.105, 0, 0);
  drone.add(dBody, dStripe, dTop, dBat, dGim, dLens, ledF, ledR);
  const rotors = [];
  [[1, 1], [1, -1], [-1, 1], [-1, -1]].forEach(([sx, sz]) => {
    const ax = sx * .27, az = sz * .27, arm = new T.Mesh(new T.BoxGeometry(.38, .022, .03), metal(0x161b20, .5, .4)); arm.position.set(ax / 2, .005, az / 2); arm.rotation.y = -Math.atan2(az, ax); drone.add(arm);
    const mot = new T.Mesh(new T.CylinderGeometry(.032, .032, .05, 16), metal(0xc63777, .6, .3)); mot.position.set(ax, .02, az); drone.add(mot);
    const leg = new T.Mesh(new T.CylinderGeometry(.006, .006, .13, 6), metal(0x111111)); leg.position.set(ax * .8, -.07, az * .8); drone.add(leg);
    const rg = new T.Group(); rg.position.set(ax, .055, az);
    const bl = new T.MeshStandardMaterial({ color: 0x15181c, roughness: .5 }); [0, 1].forEach(k => { const b = new T.Mesh(new T.BoxGeometry(.26, .004, .024), bl); b.rotation.y = k * Math.PI / 2; rg.add(b); });
    const disc = new T.Mesh(new T.CircleGeometry(.14, 28), new T.MeshBasicMaterial({ color: 0x9fe9ff, transparent: true, opacity: 0, side: T.DoubleSide, depthWrite: false })); disc.rotation.x = -Math.PI / 2; rg.add(disc);
    rg.userData = { dir: (sx * sz > 0 ? 1 : -1), disc }; drone.add(rg); rotors.push(rg); });
  drone.traverse(o => { if (o.isMesh && o.material.opacity !== 0) o.castShadow = true; }); scene.add(drone); drone.visible = false;
  const foot = new T.Mesh(new T.PlaneGeometry(1, 1), new T.MeshBasicMaterial({ color: 0x4fd8ee, transparent: true, opacity: .16, depthWrite: false, side: T.DoubleSide })); foot.rotation.x = -Math.PI / 2;
  const scan = new T.Mesh(new T.PlaneGeometry(1, .06), new T.MeshBasicMaterial({ color: 0x9ff3ff, transparent: true, opacity: .75, depthWrite: false, blending: T.AdditiveBlending, side: T.DoubleSide })); scan.rotation.x = -Math.PI / 2;
  const edges = new T.LineSegments(new T.BufferGeometry().setAttribute('position', new T.Float32BufferAttribute(new Float32Array(8 * 3), 3)), new T.LineBasicMaterial({ color: 0x4fd8ee, transparent: true, opacity: .45 }));
  const frameBox = new T.LineSegments(new T.EdgesGeometry(new T.PlaneGeometry(1, 1)), new T.LineBasicMaterial({ color: 0x9ff3ff })); frameBox.rotation.x = -Math.PI / 2;
  scene.add(foot, scan, edges, frameBox); [foot, scan, edges, frameBox].forEach(o => o.visible = false);

  /* ---------------------------------------------------------------- rover */
  const rover = new T.Group(), rb = new T.Group(); rover.add(rb);
  const chassis = new T.Mesh(new T.BoxGeometry(.31, .085, .27), new T.MeshStandardMaterial({ color: 0xd6407f, metalness: .3, roughness: .32 })); chassis.position.y = .085;
  const plate = new T.Mesh(new T.BoxGeometry(.28, .012, .24), metal(0x20262c, .5, .4)); plate.position.y = .135;
  const lidarBase = new T.Mesh(new T.CylinderGeometry(.033, .04, .03, 24), metal(0x14181c)); lidarBase.position.set(-.04, .16, 0);
  const lidarTop = new T.Group(); lidarTop.position.set(-.04, .185, 0); lidarTop.add(new T.Mesh(new T.CylinderGeometry(.03, .03, .022, 24), metal(0x2a3037, .6, .3)));
  const lbeam = new T.Mesh(new T.BoxGeometry(.05, .004, .004), new T.MeshBasicMaterial({ color: 0xff3d7a })); lbeam.position.x = .03; lidarTop.add(lbeam);
  const cam = new T.Mesh(new T.BoxGeometry(.03, .03, .08), metal(0x0b0e11, .7, .2)); cam.position.set(.14, .15, 0);
  const lens = new T.Mesh(new T.CylinderGeometry(.01, .01, .01, 12), new T.MeshBasicMaterial({ color: 0x5ad1ff })); lens.rotation.z = Math.PI / 2; lens.position.set(.158, .15, 0);
  const tank = new T.Mesh(new T.CylinderGeometry(.07, .07, .15, 28), new T.MeshPhysicalMaterial({ color: 0xbfe3ff, transparent: true, opacity: .42, roughness: .05, clearcoat: 1 })); tank.position.set(-.09, .22, 0);
  const liquid = new T.Mesh(new T.CylinderGeometry(.064, .064, .1, 28), new T.MeshStandardMaterial({ color: 0x2f8bff, emissive: 0x0a3a9a, emissiveIntensity: .6, transparent: true, opacity: .85 })); liquid.position.set(-.09, .2, 0);
  const cap = new T.Mesh(new T.CylinderGeometry(.03, .03, .02, 16), metal(0x15191d)); cap.position.set(-.09, .305, 0);
  const rail = new T.Mesh(new T.BoxGeometry(.04, .02, .46), metal(0x2a3037, .6, .3)); rail.position.set(.04, .165, 0);
  const antenna = new T.Group(); const ap = new T.Mesh(new T.CylinderGeometry(.004, .004, .12, 6), metal(0x111111)); ap.position.y = .06; const ah = new T.Mesh(new T.CylinderGeometry(.022, .022, .012, 20), metal(0xf0f0f0, .3, .3)); ah.position.y = .126; antenna.add(ap, ah); antenna.position.set(-.13, .14, .1);
  const beacon = new T.Mesh(new T.SphereGeometry(.02, 12, 12), new T.MeshBasicMaterial({ color: 0xffa83a })); beacon.position.set(0, .165, -.11);
  const beaconL = new T.PointLight(0xffa83a, 0, 1.6, 2); beaconL.position.copy(beacon.position);
  rb.add(chassis, plate, lidarBase, lidarTop, cam, lens, tank, liquid, cap, rail, antenna, beacon, beaconL);
  const nozzles = [];
  [-1, 1].forEach(s => { const arm = new T.Mesh(new T.BoxGeometry(.025, .02, .075), metal(0xc63777, .2, .4)); arm.position.set(.04, .165, s * .25); const nz = new T.Mesh(new T.ConeGeometry(.014, .06, 12), metal(0xd8dde0, .9, .2)); nz.position.set(.04, .13, s * .285); nz.rotation.x = Math.PI;
    const tip = new T.Mesh(new T.SphereGeometry(.012, 8, 8), new T.MeshBasicMaterial({ color: 0xffb938 })); tip.position.set(.04, .098, s * .285); rb.add(arm, nz, tip); nozzles.push(tip); });
  const wheels = []; [-1, 1].forEach(s => { const w = new T.Mesh(new T.CylinderGeometry(.033, .033, .018, 24), metal(0x101214, .1, .9)); w.rotation.x = Math.PI / 2; w.position.set(0, .033, s * .148); rb.add(w); wheels.push(w);
    const hub = new T.Mesh(new T.CylinderGeometry(.015, .015, .02, 12), metal(0xc63777)); hub.rotation.x = Math.PI / 2; hub.position.set(0, .033, s * .152); rb.add(hub); wheels.push(hub); });
  [[-.14, -.06], [-.14, .06]].forEach(([x, z]) => { const c = new T.Mesh(new T.SphereGeometry(.014, 10, 10), metal(0x333333)); c.position.set(x, .014, z); rb.add(c); });
  rb.traverse(o => { if (o.isMesh && !o.material.transparent) o.castShadow = true; }); scene.add(rover); rover.visible = false;
  const cone = new T.Mesh(new T.CircleGeometry(2.2, 40, -0.515, 1.03), new T.MeshBasicMaterial({ color: 0xe2508d, transparent: true, opacity: .13, depthWrite: false, side: T.DoubleSide })); cone.rotation.x = -Math.PI / 2; cone.position.set(.1, .03, 0); rover.add(cone);
  const lring = new T.Mesh(new T.RingGeometry(.97, 1, 64), new T.MeshBasicMaterial({ color: 0xe2508d, transparent: true, opacity: .5, depthWrite: false, side: T.DoubleSide })); lring.rotation.x = -Math.PI / 2; lring.position.y = .035; rover.add(lring);

  /* ---------------------------------------------------------------- jets de bouillie */
  const NP = 1800, pp = new Float32Array(NP * 3), pv = new Float32Array(NP * 3), pl = new Float32Array(NP);
  for (let i = 0; i < NP; i++) pp[i * 3 + 1] = -50;
  const pg = new T.BufferGeometry(); pg.setAttribute('position', new T.BufferAttribute(pp, 3));
  const pts = new T.Points(pg, new T.PointsMaterial({ size: .06, map: softTex, color: 0x8ccaff, transparent: true, opacity: .95, depthWrite: false, blending: T.AdditiveBlending }));
  pts.frustumCulled = false; scene.add(pts); let pHead = 0; const seenSpray = new Set();
  function emit(s) {
    const a = P(s.fx, s.fy, .13), b = P(s.x, s.y, .1);
    for (let i = 0; i < 90; i++) { const k = pHead++ % NP, d = Math.random() * .5, t = .42 + Math.random() * .12;
      pl[k] = 1 + d; pp[k * 3] = a.x; pp[k * 3 + 1] = a.y; pp[k * 3 + 2] = a.z;
      pv[k * 3] = (b.x - a.x) / t + (Math.random() - .5) * .18; pv[k * 3 + 1] = (b.y - a.y) / t + .9 + Math.random() * .3; pv[k * 3 + 2] = (b.z - a.z) / t + (Math.random() - .5) * .18; }
  }

  /* ---------------------------------------------------------------- traces et route */
  function ribbon(points, w, y) {
    const n = points.length; if (n < 2) return null; const pos = new Float32Array(n * 2 * 3), col = new Float32Array(n * 2 * 3), idx = [];
    for (let i = 0; i < n; i++) { const a = points[Math.max(0, i - 1)], b = points[Math.min(n - 1, i + 1)], dx = b.x - a.x, dy = b.y - a.y, l = Math.hypot(dx, dy) || 1, nx = -dy / l * w / 2, ny = dx / l * w / 2;
      const p1 = P(points[i].x + nx, points[i].y + ny, y), p2 = P(points[i].x - nx, points[i].y - ny, y); pos.set([p1.x, p1.y, p1.z, p2.x, p2.y, p2.z], i * 6); const f = .15 + .85 * i / n; col.set([f, f, f, f, f, f], i * 6); if (i < n - 1) idx.push(i * 2, i * 2 + 1, i * 2 + 2, i * 2 + 1, i * 2 + 3, i * 2 + 2); }
    const g = new T.BufferGeometry(); g.setAttribute('position', new T.BufferAttribute(pos, 3)); g.setAttribute('color', new T.BufferAttribute(col, 3)); g.setIndex(idx); return g;
  }
  const trailR = new T.Mesh(new T.BufferGeometry(), new T.MeshBasicMaterial({ color: 0xff5c9e, vertexColors: true, transparent: true, opacity: .8, depthWrite: false, side: T.DoubleSide, blending: T.AdditiveBlending }));
  const trailD = new T.Mesh(new T.BufferGeometry(), new T.MeshBasicMaterial({ color: 0x4fd8ee, vertexColors: true, transparent: true, opacity: .5, depthWrite: false, side: T.DoubleSide, blending: T.AdditiveBlending }));
  trailR.frustumCulled = trailD.frustumCulled = false; scene.add(trailR, trailD);
  const routeLine = new T.Line(new T.BufferGeometry(), new T.LineDashedMaterial({ color: 0xffffff, dashSize: .18, gapSize: .12, transparent: true, opacity: .85 })); scene.add(routeLine); let routeKey = '';

  /* ---------------------------------------------------------------- post-traitement : lueur, étalonnage, vignette, grain */
  let composer = null, bloom = null, tonePass = null, useBloom = true;
  try {
    composer = new T.EffectComposer(renderer); composer.addPass(new T.RenderPass(scene, camera));
    bloom = new T.UnrealBloomPass(new T.Vector2(512, 256), .5, .65, .84); composer.addPass(bloom);
    const tone = { uniforms: { tDiffuse: { value: null }, exposure: { value: 0.74 }, uTime: { value: 0 } },
      vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }',
      fragmentShader: 'uniform sampler2D tDiffuse; uniform float exposure, uTime; varying vec2 vUv; vec3 aces(vec3 x){ float a=2.51,b=0.03,c=2.43,d=0.59,e=0.14; return clamp((x*(a*x+b))/(x*(c*x+d)+e),0.0,1.0); }'
        + ' void main(){ vec4 t = texture2D(tDiffuse, vUv); vec3 c = aces(t.rgb * exposure); c = mix(vec3(dot(c, vec3(.299,.587,.114))), c, 1.16);'
        + ' c *= vec3(1.03, 1.0, 0.96); float v = smoothstep(0.98, 0.32, distance(vUv, vec2(.5)) * 1.18); c *= mix(0.72, 1.0, v);'
        + ' float g = fract(sin(dot(vUv * vec2(1920., 1080.) + uTime, vec2(12.9898, 78.233))) * 43758.5453); c += (g - .5) * 0.022; gl_FragColor = vec4(c, t.a); }' };
    tonePass = new T.ShaderPass(tone); composer.addPass(tonePass); composer.addPass(new T.ShaderPass(T.GammaCorrectionShader));
  } catch (err) { composer = null; }

  /* ---------------------------------------------------------------- étiquettes HTML projetées */
  const tagsBox = document.createElement('div'); tagsBox.className = 'tags3d'; host.appendChild(tagsBox);
  const mkTag = cls => { const d = document.createElement('div'); d.className = 'tag3d ' + cls; tagsBox.appendChild(d); return d; };
  const tagR = mkTag('r'), tagD = mkTag('d'), tagT = mkTag('t'), tagS = mkTag('s'), tagH = mkTag('s');
  tagS.textContent = 'STATION'; tagH.textContent = 'AIRE DRONE';
  const proj = (v, tag, off = 0) => { const p = v.clone().project(camera); const vis = p.z < 1 && Math.abs(p.x) < 1.1 && Math.abs(p.y) < 1.1; tag.style.display = vis ? '' : 'none'; if (vis) tag.style.transform = `translate(-50%,-50%) translate(${(p.x * .5 + .5) * host.clientWidth}px,${(-p.y * .5 + .5) * host.clientHeight + off}px)`; };
  const intro = document.createElement('div'); intro.className = 'intro3d'; intro.innerHTML = '<div class="i1">VIGIE <span>BETTERAVE</span></div><div class="i2">Jumeau numérique · Parcelle P-07 · Drone D1 + Rover R1</div>'; host.appendChild(intro);

  /* ---------------------------------------------------------------- caméras */
  let mode = 'orbite', camPos = camera.position.clone(), camTgt = controls.target.clone(), orbA = 0.9, introT = 0;
  const ORB_POS = new T.Vector3(6.8, 6.4, 10.5), ORB_TGT = new T.Vector3(-0.5, 0.1, 0.3);
  const bar = document.getElementById('cambar');
  function setMode(m) {
    if (m === 'intro') { introT = .0001; intro.classList.remove('off'); void intro.offsetWidth; intro.classList.add('go'); mode = 'intro'; controls.enabled = false; syncBar(); return; }
    if (m === mode) return;
    if (mode === 'orbite') { camPos.copy(camera.position); camTgt.copy(controls.target); }
    mode = m; controls.enabled = m === 'orbite';
    if (m === 'orbite') { controls.target.copy(camTgt); controls.update(); }
    syncBar();
  }
  function syncBar() { if (bar) bar.querySelectorAll('button[data-cam]').forEach(b => b.classList.toggle('on', b.dataset.cam === mode)); }
  const fsTarget = host.parentElement;
  if (bar) bar.querySelectorAll('button[data-cam]').forEach(b => b.addEventListener('click', () => setMode(b.dataset.cam)));
  document.addEventListener('fullscreenchange', () => document.body.classList.toggle('present', !!document.fullscreenElement));
  const bp = document.getElementById('bPresent'); if (bp) bp.addEventListener('click', () => { if (document.fullscreenElement) document.exitFullscreen(); else if (fsTarget.requestFullscreen) fsTarget.requestFullscreen(); });
  renderer.domElement.addEventListener('pointerdown', () => { if (mode === 'cinema' || mode === 'intro') { introT = 0; setMode('orbite'); } });
  const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

  /* ---------------------------------------------------------------- qualité graphique */
  let quality = 0, userQ = false, fpsAcc = 0, fpsN = 0;
  const NAMES = ['Haute', 'Équilibrée', 'Légère'], bq = document.getElementById('bQual');
  function setQuality(l) {
    quality = l; useBloom = l === 0 && !!composer;
    sun.castShadow = l < 2; sun.shadow.mapSize.set(l === 0 ? 2048 : 1024, l === 0 ? 2048 : 1024); if (sun.shadow.map) { sun.shadow.map.dispose(); sun.shadow.map = null; }
    grass.count = [NG, 14000, 3000][l]; pollen.visible = l < 2; renderer.setPixelRatio(l === 0 ? Math.min(2, devicePixelRatio) : 1);
    if (bq) bq.textContent = 'Qualité : ' + NAMES[l]; resize();
  }
  if (bq) bq.addEventListener('click', () => { userQ = true; setQuality((quality + 1) % 3); });
  let gpuName = ''; try { const gl = renderer.getContext(), ext = gl.getExtension('WEBGL_debug_renderer_info'); gpuName = ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : ''; } catch (e) { /* inconnu */ }
  /* ---------------------------------------------------------------- boucle */
  const sm = { r: null, d: null }; let last = performance.now(), frames = 0, slow = 0, tTrail = 0, wheelA = 0, lidA = 0, active = false, tHud = 0, stage = 0;
  function resize() {
    const w = host.clientWidth, h = host.clientHeight; if (w < 10) return;
    renderer.setSize(w, h, false); renderer.domElement.style.width = '100%'; renderer.domElement.style.height = '100%';
    camera.aspect = w / h; camera.updateProjectionMatrix(); if (composer) { composer.setSize(w, h); bloom.setSize(w, h); }
  }
  new ResizeObserver(resize).observe(host);
  const fmt1 = (n, d = 1) => (n == null || isNaN(n)) ? '–' : Number(n).toFixed(d).replace('.', ',');

  function hudFullscreen(now) {
    if (!document.body.classList.contains("present") || now - tHud < 300) return; tHud = now;
    const m = S.mission || {}, b = S.bilan || {}, t = b.traitement, me = S.meteo, $ = id => document.getElementById(id);
    const rk = me ? me.risque : null, rc = rk >= 66 ? '#ff5a47' : rk >= 33 ? '#f0b43a' : '#4fcf78';
    if ($('fsPh')) $('fsPh').innerHTML = `<small>MISSION</small><b>${m.etat || 'En attente'}</b>`;
    if ($('fsK')) $('fsK').innerHTML = [['repérés', (S.plants || []).length, ''], ['traités', m.traites || 0, ''], ['économie', t ? fmt1(t.economie, 1) : '–', '%'], ['précision', t && t.erreur_moyenne_cm != null ? fmt1(t.erreur_moyenne_cm, 1) : '–', 'cm']].map(([l, v, u]) => `<div><b>${v}<i>${u}</i></b><small>${l}</small></div>`).join('');
    if ($('fsRisk')) $('fsRisk').innerHTML = `<small>RISQUE CERCOSPORIOSE</small><b style="color:${rc}">${rk != null ? fmt1(rk, 0) + ' %' : '–'}</b><div class="rb"><i style="width:${rk || 0}%;background:${rc}"></i></div><small>${me ? fmt1(me.t_air) + ' °C · ' + fmt1(me.hr_air, 0) + ' % HR' : ''}</small>`;
    const di = $('dImg'), ri = $('rImg'), pd = $('pipD'), pr = $('pipR');
    if (pd && di && !di.hidden && pd.src !== di.src) pd.src = di.src; if (pr && ri && !ri.hidden && pr.src !== ri.src) pr.src = ri.src;
  }

  function loop(now) {
    if (!active) return;
    requestAnimationFrame(loop);
    if (!host.offsetParent) return;
    const dtr = (now - last) / 1000, dt = Math.min(.1, dtr); last = now; WIND.value = now / 1000; if (tonePass) tonePass.uniforms.uTime.value = (now / 1000) % 100;
    // adaptation de la qualité si la machine peine
    fpsAcc += dtr; fpsN++; if (fpsAcc > 2) { const fps = fpsN / fpsAcc; fpsAcc = 0; fpsN = 0; if (fps < 20 && quality < 2 && !userQ && document.hasFocus() && !document.hidden) setQuality(quality + 1); }
    if (false) { if (dt > .045) slow++;
      if (slow > 70) { slow = 0; stage++; if (stage === 1 && composer) { useBloom = false; } else if (stage === 2) { renderer.setPixelRatio(1); resize(); } else if (stage === 3) { grass.count = 12000; } } }
    const m = S.mission || {}, de = S.dEtat || {};
    // décor vivant : nuages, pollen
    clouds.forEach((c, i) => { c.position.x += dt * (1.2 + i * .05); if (c.position.x > 320) c.position.x = -320; });
    for (let i = 0; i < NPO; i++) { pol[i * 3] = polBase[i * 3] + Math.sin(now / 3000 + i) * 1.2; pol[i * 3 + 1] = polBase[i * 3 + 1] + Math.sin(now / 1700 + i * 1.7) * .25; pol[i * 3 + 2] = polBase[i * 3 + 2] + Math.cos(now / 2600 + i * .6) * 1.0; }
    polG.attributes.position.needsUpdate = true;
    // rover
    if (S.rover) { if (!sm.r) sm.r = { ...S.rover }; const k = 1 - Math.exp(-dt * 9), r = sm.r; r.x += (S.rover.x - r.x) * k; r.y += (S.rover.y - r.y) * k;
      let dy = S.rover.yaw - r.yaw; dy = Math.atan2(Math.sin(dy), Math.cos(dy)); r.yaw += dy * k; rover.visible = true; rover.position.copy(P(r.x, r.y, .0)); rover.rotation.y = r.yaw; }
    const moving = Math.abs(m.vitesse || 0) > .03, spraying = /pulv/i.test(m.etat || '');
    wheelA += (m.vitesse || 0) * dt / .033; wheels.forEach(w => w.rotation.y = wheelA); lidA += dt * 9; lidarTop.rotation.y = lidA;
    const blink = (Math.floor(now / 260) % 2) === 0 && (moving || spraying); beacon.material.color.setHex(blink ? 0xffd08a : 0x6b4a1c); beaconL.intensity = blink ? 1.6 : 0;
    nozzles.forEach(n => n.material.color.setHex(spraying ? 0x7fd0ff : 0xffb938));
    const ph = (now / 1100) % 1; lring.scale.setScalar(.3 + ph * 1.6); lring.material.opacity = .5 * (1 - ph);
    // drone
    if (S.drone) { if (!sm.d) sm.d = { ...S.drone }; const k = 1 - Math.exp(-dt * 9), d = sm.d; d.x += (S.drone.x - d.x) * k; d.y += (S.drone.y - d.y) * k; d.z += (S.drone.z - d.z) * k; drone.visible = true;
      const flying = d.z > .4; drone.position.copy(P(d.x, d.y, d.z + (flying ? Math.sin(now / 420) * .02 : 0))); drone.rotation.z = flying ? clamp((S.drone.x - d.x) * -.8, -.2, .2) : 0; drone.rotation.x = flying ? clamp((S.drone.y - d.y) * .8, -.2, .2) : 0;
      rotors.forEach(r => { r.rotation.y += r.userData.dir * dt * (flying ? 60 : 3); r.userData.disc.material.opacity = flying ? .16 : 0; });
      ledF.material.color.setHex(Math.floor(now / 300) % 2 ? 0x4dff88 : 0x15502a);
      const scanning = flying && de.phase === 'releve', kz = clamp((d.z - .2) / 3.8, .25, 1.3), hh = 1.95 * kz * 2, hw = 2.6 * kz * 2;
      [foot, scan, edges, frameBox].forEach(o => o.visible = scanning);
      if (scanning) { const cx = d.x + .04; foot.position.copy(P(cx, d.y, .1)); foot.scale.set(hh, hw, 1); frameBox.position.copy(foot.position); frameBox.scale.set(hh, hw, 1);
        const sp = ((now / 1100) % 1) - .5; scan.position.copy(P(cx + sp * hh, d.y, .12)); scan.rotation.z = Math.PI / 2; scan.scale.set(hw, 1, 1);
        const a = edges.geometry.attributes.position, c0 = drone.position; [[1, 1], [1, -1], [-1, 1], [-1, -1]].forEach(([sx, sy], i) => { const g = P(cx + sx * hh / 2, d.y + sy * hw / 2, .1); a.setXYZ(i * 2, c0.x, c0.y - .1, c0.z); a.setXYZ(i * 2 + 1, g.x, g.y, g.z); }); a.needsUpdate = true; } }
    // plants détectés / traités
    (S.plants || []).forEach(p => { if (!marks.has(p.id)) addMark(p); });
    const cib = m.cibles || [];
    marks.forEach((mk, id) => {
      const c = cib.find(x => x.id === id), st = c ? c.etat : 'a_traiter', pulse = .5 + .5 * Math.sin(now / 260 + id);
      if (st === 'traite' && !mk.treated) { mk.treated = true; mk.ring.material.color.setHex(0x3fe07f); mk.beam.visible = false; const sl = sickSlot.get(id);
        if (sl) { sick.setMatrixAt(sl.s, zeroM); sick.instanceMatrix.needsUpdate = true; healthy.setMatrixAt(sl.h.i, sl.h.m); healthy.setColorAt(sl.h.i, new T.Color(.78, .98, 1.0)); healthy.instanceMatrix.needsUpdate = true; healthy.instanceColor.needsUpdate = true; } }
      if (!mk.treated) { mk.ring.scale.setScalar(1 + .08 * pulse); mk.beam.material.opacity = .22 + .22 * pulse; const col = st === 'a_valider' ? 0xf0b43a : 0xff4b3a; mk.ring.material.color.setHex(col); mk.beam.material.color.setHex(col); }
      else mk.ring.scale.setScalar(1.15);
    });
    for (let i = pings.length - 1; i >= 0; i--) { const pi = pings[i], k = (now - pi.t) / 1600; if (k < 0) continue; if (k > 1) { if (pi.mesh) scene.remove(pi.mesh); pings.splice(i, 1); continue; }
      if (!pi.mesh) { pi.mesh = new T.Mesh(pingGeo, new T.MeshBasicMaterial({ color: 0xff6a5a, transparent: true, opacity: .8, depthWrite: false, side: T.DoubleSide })); pi.mesh.rotation.x = -Math.PI / 2; pi.mesh.position.copy(P(pi.x, pi.y, .15)); scene.add(pi.mesh); }
      pi.mesh.scale.setScalar(.2 + k * 1.3); pi.mesh.material.opacity = .8 * (1 - k); }
    // jets
    (S.sprays || []).forEach(s => { if (!seenSpray.has(s.t)) { seenSpray.add(s.t); emit(s); } });
    for (let i = 0; i < NP; i++) { if (pl[i] <= 0) { pp[i * 3 + 1] = -50; continue; } pl[i] -= dt * 1.5; if (pl[i] > 1) continue;
      pv[i * 3 + 1] -= 9.8 * dt * .9; pp[i * 3] += pv[i * 3] * dt; pp[i * 3 + 1] += pv[i * 3 + 1] * dt; pp[i * 3 + 2] += pv[i * 3 + 2] * dt; if (pp[i * 3 + 1] < .05) pl[i] -= .5; }
    pg.attributes.position.needsUpdate = true;
    // traces et route
    if (now - tTrail > 400) { tTrail = now; const gr = ribbon(S.trailR.slice(-260), .07, .035), gd = ribbon(S.trailD.slice(-260), .05, .05);
      if (gr) { trailR.geometry.dispose(); trailR.geometry = gr; } if (gd) { trailD.geometry.dispose(); trailD.geometry = gd; }
      const key = JSON.stringify(m.route || []); if (key !== routeKey) { routeKey = key; const rt = m.route || []; if (rt.length && sm.r) { routeLine.geometry.dispose(); routeLine.geometry = new T.BufferGeometry().setFromPoints([P(sm.r.x, sm.r.y, .06), ...rt.map(p => P(p[0], p[1], .06))]); routeLine.computeLineDistances(); routeLine.visible = true; } else routeLine.visible = false; }
      if (m.phase === 'attente' || m.phase === 'termine') routeLine.visible = false; }
    updateCamera(dt, dtr);
    if (sm.r) { tagR.innerHTML = `<b>R1</b> ${fmt1(Math.abs(m.vitesse || 0), 2)} m/s`; proj(rover.position.clone().add(new T.Vector3(0, .5, 0)), tagR); } else tagR.style.display = 'none';
    if (sm.d && drone.visible && sm.d.z > .4) { tagD.innerHTML = `<b>D1</b> ${fmt1(sm.d.z)} m`; proj(drone.position.clone().add(new T.Vector3(0, .4, 0)), tagD); } else tagD.style.display = 'none';
    if (m.cible) { tagT.innerHTML = `<b>PLANT ${m.cible.id}</b> ${m.cible.etape === 'confirmer' ? 'confirmation' : 'pulvérisation'}`; proj(P(m.cible.x, m.cible.y, 1.0), tagT); } else tagT.style.display = 'none';
    proj(P(-6.9, .3, .6), tagS); proj(P(-9.2, -2.2, .8), tagH);
    hudFullscreen(now);
    if (composer && useBloom) composer.render(); else renderer.render(scene, camera);
  }
  function updateCamera(dt, dtr) {
    camera.up.set(0, 1, 0); if (mode === 'dessus') camera.up.set(0, 0, -1);
    if (mode === 'intro') { introT += Math.min(.25, dtr) / 7.5; const t = ease(clamp(introT, 0, 1)), a = (1 - t) * 2.2 + .0;
      const from = new T.Vector3(Math.cos(a - 2.4) * 34, 16 - 8 * t + 6 * (1 - t), Math.sin(a - 2.4) * 34); const to = ORB_POS;
      camera.position.lerpVectors(from, to, t * t * (3 - 2 * t)); camera.lookAt(new T.Vector3().lerpVectors(new T.Vector3(0, 1.5, 0), ORB_TGT, t)); camPos.copy(camera.position); camTgt.copy(ORB_TGT);
      if (introT >= 1) { introT = 0; mode = 'orbite'; controls.enabled = true; controls.target.copy(ORB_TGT); camera.position.copy(ORB_POS); controls.update(); intro.classList.remove('go'); syncBar(); } return; }
    if (mode === 'orbite') { controls.update(); return; }
    const r = sm.r, d = sm.d; let tp, tt, k = 1 - Math.exp(-dt * 3.2);
    if (mode === 'rover' && r) { const f = new T.Vector3(Math.cos(r.yaw), 0, -Math.sin(r.yaw)); tp = P(r.x, r.y, 0).addScaledVector(f, -1.6).add(new T.Vector3(0, 1.05, 0)); tt = P(r.x, r.y, .1).addScaledVector(f, 1.2); }
    else if (mode === 'fpv' && r) { const f = new T.Vector3(Math.cos(r.yaw), 0, -Math.sin(r.yaw)); tp = P(r.x, r.y, .15).addScaledVector(f, .17); tt = tp.clone().addScaledVector(f, 3).add(new T.Vector3(0, -.05, 0)); k = 1 - Math.exp(-dt * 14); }
    else if (mode === 'drone' && d && d.z > .4) { tp = P(d.x, d.y, d.z).add(new T.Vector3(-3.2, 1.7, 2.6)); tt = P(d.x, d.y, d.z - .5); }
    else if (mode === 'dessus') { tp = new T.Vector3(0, 18, .01); tt = new T.Vector3(0, 0, 0); }
    else if (mode === 'cinema') { orbA += dt * .11; const rad = 13.5 + Math.sin(orbA * .6) * 2; tp = new T.Vector3(Math.cos(orbA) * rad, 5.2 + Math.sin(orbA * .9) * 1.6, Math.sin(orbA) * rad); tt = new T.Vector3(0, .3, 0); }
    else { controls.update(); return; }
    camPos.lerp(tp, k); camTgt.lerp(tt, k); camera.position.copy(camPos); camera.lookAt(camTgt);
  }

  /* ---------------------------------------------------------------- bascule 2D / 3D */
  const c2d = document.getElementById('map'), b2 = document.getElementById('v2d'), b3 = document.getElementById('v3d');
  let firstShow = true;
  function view(v) {
    const on = v === '3d'; host.style.display = on ? '' : 'none'; if (c2d) c2d.style.display = on ? 'none' : '';
    if (b2) b2.classList.toggle('on', !on); if (b3) b3.classList.toggle('on', on); document.body.classList.toggle('view3d', on);
    if (on && !active) { active = true; last = performance.now(); resize(); requestAnimationFrame(loop); if (firstShow) { firstShow = false; setMode('intro'); } } if (!on) active = false;
    try { localStorage.setItem('vigie_vue', v); } catch (e) { /* stockage indisponible : sans conséquence */ }
  }
  if (b2) b2.addEventListener('click', () => view('2d')); if (b3) b3.addEventListener('click', () => view('3d'));
  let pref = '3d'; try { pref = localStorage.getItem('vigie_vue') || '3d'; } catch (e) { /* idem */ }
  setQuality(/swiftshader|llvmpipe|software|basic render/i.test(gpuName) ? 2 : 0);
  view(pref); window.__vigie3d = { setMode, view };
}
if (document.readyState === 'complete') boot(); else window.addEventListener('load', boot);
})();
