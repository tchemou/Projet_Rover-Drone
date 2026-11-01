#!/usr/bin/env python3
"""Génère le paquet ROS 2 agri_sim : exploitation de betteraves sucrières pour Gazebo Harmonic.

Scène : parcelle labourée en buttes (11 rangs de 12 m), tournières, passages de roues,
chemin empierré, prairie, haie, arbres, hangar, aire du drone et station de base du rover.
Tous les maillages et textures sont générés ici (aucun téléchargement).
"""
import math, os, random, shutil
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, 'agri_sim')
rng = random.Random(7)

# ------------------------------------------------------------------ plan de l'exploitation
FIELD_X = (-6.0, 6.0)                 # rangs : de x = -6 à x = 6 m
ROW_SPACING = 0.6
ROWS_Y = [round(-3.0 + i * ROW_SPACING, 2) for i in range(11)]
PLANT_SPACING = 0.4
RIDGE_H = 0.05
SOIL = (-7.4, 7.4, -3.6, 3.6)         # parcelle labourée avec tournières
FOCI = [(-3.2, -1.6, 0.9), (1.5, 1.4, 0.7), (3.8, -0.8, 1.1), (-0.8, 2.3, 0.6)]
WORLD = 44.0                          # côté de la scène (m)
ROAD_Y = -5.2                         # chemin empierré au sud de la parcelle
SHED = (-11.0, -8.4)                  # hangar
PAD = (-9.2, -2.2)                    # aire du drone, à côté de la parcelle
SPAWN = (-6.9, 0.3)                   # station du rover, dans la tournière ouest


def in_rect(x, y, r, m=0.0):
    return r[0] - m <= x <= r[1] + m and r[2] - m <= y <= r[3] + m


def field_height(x, y):
    """Buttes sous les rangs ; tournières planes ; légère transition."""
    if not (FIELD_X[0] - 0.3 <= x <= FIELD_X[1] + 0.3):
        return 0.0
    d = min(abs(y - r) for r in ROWS_Y)
    if abs(y) > 3.0 + ROW_SPACING / 2:
        return 0.0
    edge = min(1.0, (min(x - (FIELD_X[0] - 0.3), (FIELD_X[1] + 0.3) - x)) / 0.3)
    return edge * RIDGE_H * max(0.0, math.cos(math.pi * d / ROW_SPACING)) ** 2


def meadow_height(x, y):
    dx = max(0.0, abs(x) - SOIL[1])
    dy = max(0.0, abs(y) - SOIL[3])
    t = min(1.0, math.hypot(dx, dy) / 4.0)
    und = 0.35 * (0.5 + 0.5 * math.sin(x * 0.21 + 0.8) * math.cos(y * 0.17 - 0.3)) + 0.15 * math.sin(x * 0.07 + y * 0.11)
    h = 0.02 + t * t * max(0.0, und)
    # le chemin, le hangar et l'aire du drone restent plats
    if abs(y - ROAD_Y) < 2.0 or math.hypot(x - SHED[0], y - SHED[1]) < 5 or math.hypot(x - PAD[0], y - PAD[1]) < 2.5:
        k = 0.0
        if abs(y - ROAD_Y) < 2.0: k = max(k, 1 - abs(y - ROAD_Y) / 2.0)
        k = max(k, 1 - math.hypot(x - SHED[0], y - SHED[1]) / 5)
        k = max(k, 1 - math.hypot(x - PAD[0], y - PAD[1]) / 2.5)
        h = h * (1 - min(1, 1.6 * k)) + 0.02 * min(1, 1.6 * k)
    return h


def disease(x, y):
    v = 0.0
    for fx, fy, r in FOCI:
        d = math.hypot(x - fx, y - fy)
        v = max(v, math.exp(-(d * d) / (2 * (r / 1.6) ** 2)))
    return v


# ------------------------------------------------------------------ textures
def noise(w, h, scale, seed):
    r = np.random.RandomState(seed)
    small = r.rand(h // scale + 2, w // scale + 2)
    img = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    return np.asarray(img).astype(np.float32) / 255.0


def fbm(w, h, seed, scales=(4, 16, 64), weights=(0.5, 0.3, 0.2)):
    return sum(wt * noise(w, h, s, seed + i) for i, (s, wt) in enumerate(zip(scales, weights)))


def to_img(a):
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def tex_soil(path):
    s = 1024
    n = fbm(s, s, 1, (6, 24, 96))
    base = np.array([88, 64, 45], np.float32)
    img = to_img(base * (0.70 + 0.55 * n[..., None]))
    d = ImageDraw.Draw(img); r = np.random.RandomState(4)
    for _ in range(1400):
        x, y, rad = r.randint(0, s), r.randint(0, s), r.randint(2, 8)
        c = tuple(int(v) for v in base * r.uniform(0.55, 1.3))
        d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=c)
    for _ in range(220):
        x, y, rad = r.randint(0, s), r.randint(0, s), r.randint(1, 4)
        g = r.randint(135, 185)
        d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=(g, g - 10, g - 24))
    img.filter(ImageFilter.GaussianBlur(0.7)).save(path)


def tex_grass(path):
    s = 1024
    n = fbm(s, s, 11, (3, 20, 90))
    base = np.array([84, 126, 52], np.float32)
    img = to_img(base * (0.62 + 0.62 * n[..., None]))
    d = ImageDraw.Draw(img); r = np.random.RandomState(14)
    for _ in range(9000):
        x, y, l = r.randint(0, s), r.randint(0, s), r.randint(4, 13)
        a = r.uniform(-0.7, 0.7) - math.pi / 2
        c = tuple(int(v) for v in base * r.uniform(0.7, 1.5))
        d.line([x, y, x + l * math.cos(a), y + l * math.sin(a)], fill=c, width=1)
    for _ in range(120):   # petites fleurs
        x, y = r.randint(0, s), r.randint(0, s)
        c = [(235, 225, 120), (240, 240, 235), (200, 150, 210)][r.randint(0, 3)]
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=c)
    img.save(path)


def tex_gravel(path):
    s = 1024
    n = fbm(s, s, 40, (3, 12, 60))
    base = np.array([150, 140, 122], np.float32)
    img = to_img(base * (0.72 + 0.4 * n[..., None]))
    d = ImageDraw.Draw(img); r = np.random.RandomState(41)
    for _ in range(7000):
        x, y, rad = r.randint(0, s), r.randint(0, s), r.randint(1, 5)
        g = r.randint(95, 205)
        d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=(g, g - 6, g - 16))
    img.filter(ImageFilter.GaussianBlur(0.5)).save(path)


def tex_leaf(path, state):
    w, h = 512, 256
    r = np.random.RandomState({'saine': 21, 'debut': 22, 'malade': 23}[state])
    n = 0.6 * noise(w, h, 16, 30) + 0.4 * noise(w, h, 64, 31)
    base = np.array([92, 124, 42] if state == 'malade' else [46, 112, 44], np.float32)
    img = base * (0.8 + 0.4 * n[..., None])
    yy = np.abs(np.linspace(-1, 1, h))[:, None]
    if state == 'malade':
        img = img + (yy ** 3)[..., None] * np.array([70, 36, -12], np.float32)
    img = img * (1.05 - 0.12 * (yy ** 2)[..., None])       # bords un peu plus sombres
    img[:, :26] = np.array([150, 176, 112], np.float32)     # pétiole (base de la feuille)
    pil = to_img(img); d = ImageDraw.Draw(pil)
    vein = (168, 204, 138)
    d.line([0, h // 2, w, h // 2], fill=vein, width=7)
    for i in range(1, 9):
        x0 = 26 + i * (w - 26) / 9
        for sg in (-1, 1):
            d.line([x0, h / 2, x0 + 52, h / 2 + sg * 0.47 * h], fill=vein, width=2)
    for _ in range({'saine': 0, 'debut': 14, 'malade': 75}[state]):
        x, y, rad = r.randint(40, w - 20), r.randint(20, h - 20), r.randint(4, 8)
        d.ellipse([x - rad, y - rad, x + rad, y + rad], fill=(120, 40, 26))
        ri = max(2, int(rad * 0.55))
        d.ellipse([x - ri, y - ri, x + ri, y + ri], fill=(206, 199, 184))
    pil.filter(ImageFilter.GaussianBlur(0.5)).save(path)


def tex_bark(path):
    w, h = 256, 512
    n = noise(w, h, 4, 50) * 0.5 + noise(w, h, 24, 51) * 0.5
    stripes = (np.sin(np.linspace(0, 40, w))[None, :] * 0.5 + 0.5) * 0.25
    base = np.array([82, 64, 48], np.float32)
    to_img(base * (0.65 + 0.5 * n[..., None] + stripes[..., None])).save(path)


def tex_foliage(path, seed, tint):
    s = 512
    n = fbm(s, s, seed, (3, 10, 40))
    base = np.array(tint, np.float32)
    img = to_img(base * (0.55 + 0.8 * n[..., None]))
    d = ImageDraw.Draw(img); r = np.random.RandomState(seed)
    for _ in range(2500):
        x, y = r.randint(0, s), r.randint(0, s)
        c = tuple(int(v) for v in base * r.uniform(0.6, 1.5))
        d.ellipse([x - 3, y - 2, x + 3, y + 2], fill=c)
    img.save(path)


def tex_metal(path, col, ribs=True):
    w, h = 512, 512
    n = noise(w, h, 32, 60)
    base = np.array(col, np.float32)
    img = base * (0.9 + 0.15 * n[..., None])
    if ribs:
        rib = (np.sin(np.linspace(0, 2 * math.pi * 24, w)) * 0.5 + 0.5)[None, :, None]
        img = img * (0.82 + 0.25 * rib)
    to_img(img).save(path)


def tex_concrete(path):
    s = 512
    n = fbm(s, s, 70, (2, 12, 50))
    img = to_img(np.array([150, 150, 146], np.float32) * (0.78 + 0.35 * n[..., None]))
    d = ImageDraw.Draw(img)
    d.line([0, s // 2, s, s // 2], fill=(110, 110, 108), width=2)
    d.line([s // 2, 0, s // 2, s], fill=(110, 110, 108), width=2)
    img.save(path)


def font(size):
    for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf']:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def tex_pad(path):
    s = 512
    img = Image.new('RGB', (s, s), (58, 60, 62)); d = ImageDraw.Draw(img)
    d.ellipse([20, 20, s - 20, s - 20], outline=(235, 235, 230), width=14)
    d.ellipse([60, 60, s - 60, s - 60], outline=(214, 50, 110), width=6)
    f = font(230)
    d.text((s / 2, s / 2), 'H', fill=(240, 240, 235), font=f, anchor='mm')
    img.save(path)


def tex_dock(path):
    w, h = 512, 256
    img = Image.new('RGB', (w, h), (64, 66, 70)); d = ImageDraw.Draw(img)
    for i in range(-h, w, 40):
        d.polygon([(i, h), (i + 20, h), (i + 20 + h * 0.4, 0), (i + h * 0.4, 0)], fill=(214, 50, 110))
    d.rectangle([24, 24, w - 24, h - 24], fill=(64, 66, 70))
    d.text((w / 2, h / 2), 'ROVER R1', fill=(240, 240, 235), font=font(64), anchor='mm')
    img.save(path)


def tex_sign(path):
    w, h = 1024, 512
    img = Image.new('RGB', (w, h), (245, 243, 236)); d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 110], fill=(163, 36, 95))
    d.text((40, 55), 'VIGIE BETTERAVE', fill=(255, 255, 255), font=font(66), anchor='lm')
    d.text((40, 200), 'Parcelle P-07', fill=(30, 40, 35), font=font(70), anchor='lm')
    d.text((40, 300), 'Betterave sucrière · 0,60 ha', fill=(70, 80, 75), font=font(46), anchor='lm')
    d.text((40, 400), 'Surveillance drone + rover', fill=(70, 80, 75), font=font(46), anchor='lm')
    img.save(path)


# ------------------------------------------------------------------ maillages OBJ
class Obj:
    def __init__(self):
        self.v, self.vt, self.vn, self.f = [], [], [], []

    def grid(self, P, UV, double=False, flip=False):
        """P : tableau (nu+1, nv+1, 3) ; UV : (nu+1, nv+1, 2)."""
        nu, nv = P.shape[0] - 1, P.shape[1] - 1
        du, dv = np.gradient(P, axis=0), np.gradient(P, axis=1)
        N = np.cross(du, dv); N /= np.linalg.norm(N, axis=2, keepdims=True) + 1e-9
        if flip: N = -N
        b = len(self.v)
        self.v += [tuple(p) for p in P.reshape(-1, 3)]
        self.vt += [tuple(t) for t in UV.reshape(-1, 2)]
        self.vn += [tuple(n) for n in N.reshape(-1, 3)]
        idx = lambda i, j: b + i * (nv + 1) + j
        for i in range(nu):
            for j in range(nv):
                a, c, e, g = idx(i, j), idx(i + 1, j), idx(i + 1, j + 1), idx(i, j + 1)
                t1, t2 = (a, c, e), (a, e, g)
                if flip: t1, t2 = (a, e, c), (a, g, e)
                self.f += [t1, t2]
                if double:
                    self.f += [(t1[0], t1[2], t1[1]), (t2[0], t2[2], t2[1])]

    def save(self, path):
        with open(path, 'w') as f:
            for p in self.v: f.write('v %.4f %.4f %.4f\n' % p)
            for t in self.vt: f.write('vt %.4f %.4f\n' % t)
            for n in self.vn: f.write('vn %.4f %.4f %.4f\n' % n)
            for a, b, c in self.f:
                f.write(f'f {a+1}/{a+1}/{a+1} {b+1}/{b+1}/{b+1} {c+1}/{c+1}/{c+1}\n')


def surface(x0, x1, y0, y1, step, hfun, uvscale):
    nu, nv = max(1, int(round((x1 - x0) / step))), max(1, int(round((y1 - y0) / step)))
    xs, ys = np.linspace(x0, x1, nu + 1), np.linspace(y0, y1, nv + 1)
    P = np.zeros((nu + 1, nv + 1, 3)); UV = np.zeros((nu + 1, nv + 1, 2))
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            P[i, j] = (x, y, hfun(x, y)); UV[i, j] = (x / uvscale, y / uvscale)
    return P, UV


def mesh_plant(path, seed):
    r = random.Random(seed); o = Obj()
    n = r.randint(11, 14); golden = math.radians(137.5)
    for i in range(n):
        inner = i / n
        yaw = i * golden + r.uniform(-0.2, 0.2)
        L = r.uniform(0.17, 0.24) * (1.0 - 0.42 * inner)
        Wd = L * r.uniform(0.44, 0.54)
        pitch = math.radians(r.uniform(26, 38) + 38 * inner)
        droop = r.uniform(0.05, 0.11) * (1 - inner)
        pet = r.uniform(0.04, 0.07) * (1 - 0.5 * inner)
        cy, sy = math.cos(yaw), math.sin(yaw)
        nu, nv = 6, 2
        P = np.zeros((nu + 1, nv + 1, 3)); UV = np.zeros((nu + 1, nv + 1, 2))
        tot = pet + L
        for a in range(nu + 1):
            s = tot * a / nu
            ul = max(0.0, (s - pet) / L)                     # position le long du limbe
            half = (0.5 * Wd * math.sin(math.pi * min(1, ul ** 0.75 * 1.02)) + 0.0025) if s > pet else 0.005
            z = 0.012 + s * math.sin(pitch) - droop * (ul ** 2) * L
            along = s * math.cos(pitch)
            for b in range(nv + 1):
                v = -1 + 2 * b / nv
                lat = v * half
                cup = 0.02 * v * v * math.sin(math.pi * ul)
                wav = 0.004 * math.sin(10 * ul + 3 * v)
                P[a, b] = (along * cy - lat * sy, along * sy + lat * cy, z + cup + wav)
                UV[a, b] = (s / tot, (v + 1) / 2)
        o.grid(P, UV, double=True)
    o.save(path)


def sphere_blob(o, cx, cy, cz, rx, ry, rz, seed, nu=14, nv=10, bump=0.18):
    r = np.random.RandomState(seed)
    ph = r.uniform(0, 6.28, 4)
    P = np.zeros((nu + 1, nv + 1, 3)); UV = np.zeros((nu + 1, nv + 1, 2))
    for i in range(nu + 1):
        th = 2 * math.pi * i / nu
        for j in range(nv + 1):
            fi = math.pi * j / nv
            k = 1 + bump * (math.sin(3 * th + ph[0]) * math.sin(2 * fi + ph[1]) + 0.5 * math.sin(5 * th + ph[2]) * math.cos(3 * fi + ph[3]))
            P[i, j] = (cx + rx * k * math.sin(fi) * math.cos(th), cy + ry * k * math.sin(fi) * math.sin(th), cz + rz * k * math.cos(fi))
            UV[i, j] = (2 * i / nu, j / nv)
    o.grid(P, UV, flip=True)


def mesh_tree_trunk(path, h):
    o = Obj(); nu, nv = 12, 6
    P = np.zeros((nu + 1, nv + 1, 3)); UV = np.zeros((nu + 1, nv + 1, 2))
    for i in range(nu + 1):
        th = 2 * math.pi * i / nu
        for j in range(nv + 1):
            z = h * j / nv; rad = 0.22 * (1 - 0.55 * j / nv) + (0.08 if j == 0 else 0)
            P[i, j] = (rad * math.cos(th), rad * math.sin(th), z); UV[i, j] = (i / nu, z / 1.5)
    o.grid(P, UV)
    o.save(path)


def mesh_tree_crown(path, h, seed):
    o = Obj(); r = random.Random(seed)
    sphere_blob(o, 0, 0, h + 0.9, 2.0, 2.0, 1.7, seed)
    for k in range(4):
        a = k * 1.57 + r.uniform(-0.3, 0.3)
        sphere_blob(o, 1.2 * math.cos(a), 1.2 * math.sin(a), h + 0.4 + r.uniform(0, 0.8), 1.3, 1.3, 1.1, seed + k + 1)
    o.save(path)


def mesh_hedge(path, length, seed):
    o = Obj(); r = random.Random(seed)
    x = -length / 2
    while x < length / 2:
        rad = r.uniform(0.45, 0.7)
        sphere_blob(o, x, r.uniform(-0.15, 0.15), rad * 0.9, rad, rad * 0.9, rad * 1.05, r.randint(0, 999), nu=10, nv=8)
        x += rad * 1.1
    o.save(path)


def mesh_quad(path, sx, sy, uvx=1, uvy=1):
    o = Obj()
    P = np.array([[[-sx / 2, -sy / 2, 0], [-sx / 2, sy / 2, 0]], [[sx / 2, -sy / 2, 0], [sx / 2, sy / 2, 0]]], float)
    UV = np.array([[[0, 0], [0, uvy]], [[uvx, 0], [uvx, uvy]]], float)
    o.grid(P, UV); o.save(path)


# ------------------------------------------------------------------ écriture des modèles
def pbr(tex, rough=0.95):
    return (f'<material><ambient>1 1 1 1</ambient><diffuse>1 1 1 1</diffuse><specular>0.05 0.05 0.05 1</specular>'
            f'<pbr><metal><albedo_map>{tex}</albedo_map><roughness>{rough}</roughness><metalness>0</metalness></metal></pbr></material>')


def write_model(name, links_xml, desc, static=True):
    d = os.path.join(ROOT, 'models', name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'model.sdf'), 'w') as f:
        f.write(f'<?xml version="1.0"?>\n<sdf version="1.8">\n<model name="{name}">\n<static>{"true" if static else "false"}</static>\n{links_xml}\n</model>\n</sdf>\n')
    with open(os.path.join(d, 'model.config'), 'w') as f:
        f.write(f'<?xml version="1.0"?>\n<model><name>{name}</name><version>1.0</version><sdf version="1.8">model.sdf</sdf>'
                f'<author><name>Projet Rover &amp; Drone Agricole</name></author><description>{desc}</description></model>\n')
    os.makedirs(os.path.join(d, 'meshes'), exist_ok=True)
    return os.path.join(d, 'meshes')


def mesh_visual(name, uri, tex, shadows=True, pose='0 0 0 0 0 0'):
    return (f'<visual name="{name}"><pose>{pose}</pose><cast_shadows>{"true" if shadows else "false"}</cast_shadows>'
            f'<geometry><mesh><uri>{uri}</uri></mesh></geometry>{pbr(tex)}</visual>')


def box_visual(name, size, pose, tex=None, color=None, emissive=None):
    mat = pbr(tex, 0.7) if tex else (f'<material><ambient>{color}</ambient><diffuse>{color}</diffuse>'
                                     + (f'<emissive>{emissive}</emissive>' if emissive else '') + '</material>')
    return f'<visual name="{name}"><pose>{pose}</pose><geometry><box><size>{size}</size></box></geometry>{mat}</visual>'


def box_collision(name, size, pose):
    return f'<collision name="{name}"><pose>{pose}</pose><geometry><box><size>{size}</size></box></geometry></collision>'


def build_models():
    # ---- plants de betterave (3 états × 2 formes)
    for state in ('saine', 'debut', 'malade'):
        for k, var in enumerate('ab'):
            name = f'betterave_{state}_{var}'
            link = (f'<link name="link"><collision name="tige"><pose>0 0 0.12 0 0 0</pose>'
                    f'<geometry><cylinder><radius>0.05</radius><length>0.24</length></cylinder></geometry></collision>'
                    + mesh_visual('plant', f'model://{name}/meshes/plant.obj', f'model://{name}/meshes/feuille_{name}.png')
                    + '</link>')
            m = write_model(name, link, f'Plant de betterave sucrière ({state}).')
            mesh_plant(os.path.join(m, 'plant.obj'), seed={'saine': 10, 'debut': 20, 'malade': 30}[state] + 5 * k)
            tex_leaf(os.path.join(m, f'feuille_{name}.png'), state)

    # ---- sol : parcelle labourée, prairie, chemin
    name = 'exploitation_sol'
    link = ('<link name="link"><collision name="sol"><geometry><plane><normal>0 0 1</normal><size>60 60</size></plane></geometry></collision>'
            + mesh_visual('parcelle', f'model://{name}/meshes/parcelle.obj', f'model://{name}/meshes/terre.png', shadows=False)
            + mesh_visual('prairie', f'model://{name}/meshes/prairie.obj', f'model://{name}/meshes/herbe.png', shadows=False)
            + mesh_visual('chemin', f'model://{name}/meshes/chemin.obj', f'model://{name}/meshes/gravier.png', shadows=False)
            + '</link>')
    m = write_model(name, link, 'Parcelle labourée en buttes, prairie et chemin empierré.')
    o = Obj(); P, UV = surface(SOIL[0], SOIL[1], SOIL[2], SOIL[3], 0.1, field_height, 1.5); o.grid(P, UV); o.save(os.path.join(m, 'parcelle.obj'))
    # prairie : grande grille, creusée sous la parcelle et le chemin
    def meadow(x, y):
        if in_rect(x, y, SOIL, 0.25): return -0.03
        if abs(y - ROAD_Y) < 1.3 and abs(x) < WORLD / 2: return 0.0
        return meadow_height(x, y)
    o = Obj(); P, UV = surface(-WORLD / 2, WORLD / 2, -WORLD / 2, WORLD / 2, 0.5, meadow, 2.5); o.grid(P, UV); o.save(os.path.join(m, 'prairie.obj'))
    o = Obj(); P, UV = surface(-WORLD / 2, WORLD / 2, ROAD_Y - 1.2, ROAD_Y + 1.2, 0.2, lambda x, y: 0.025 + 0.015 * math.cos(math.pi * (y - ROAD_Y) / 2.4) - 0.012 * (abs(abs(y - ROAD_Y) - 0.6) < 0.18), 1.2)
    o.grid(P, UV); o.save(os.path.join(m, 'chemin.obj'))
    tex_soil(os.path.join(m, 'terre.png')); tex_grass(os.path.join(m, 'herbe.png')); tex_gravel(os.path.join(m, 'gravier.png'))

    # ---- arbres (2 formes) et haie
    for k, (h, tint) in enumerate([(2.6, (66, 116, 48)), (3.2, (82, 124, 46))]):
        name = f'arbre_{k}'
        link = ('<link name="link"><collision name="tronc"><pose>0 0 1 0 0 0</pose><geometry><cylinder><radius>0.25</radius><length>2</length></cylinder></geometry></collision>'
                + mesh_visual('tronc', f'model://{name}/meshes/tronc.obj', f'model://{name}/meshes/ecorce.png')
                + mesh_visual('feuillage', f'model://{name}/meshes/feuillage.obj', f'model://{name}/meshes/feuillage.png') + '</link>')
        m = write_model(name, link, 'Arbre de bord de champ.')
        mesh_tree_trunk(os.path.join(m, 'tronc.obj'), h + 0.6)
        mesh_tree_crown(os.path.join(m, 'feuillage.obj'), h, 100 + k)
        tex_bark(os.path.join(m, 'ecorce.png')); tex_foliage(os.path.join(m, 'feuillage.png'), 80 + k, tint)
    name = 'haie'
    link = ('<link name="link">' + box_collision('c', '20 0.9 1.2', '0 0 0.6 0 0 0')
            + mesh_visual('haie', f'model://{name}/meshes/haie.obj', f'model://{name}/meshes/feuillage.png') + '</link>')
    m = write_model(name, link, 'Haie bocagère.')
    mesh_hedge(os.path.join(m, 'haie.obj'), 20, 5); tex_foliage(os.path.join(m, 'feuillage.png'), 90, (60, 108, 44))

    # ---- hangar ouvert (bardage métallique)
    name = 'hangar'
    W_, D_, H_ = 5.0, 3.6, 3.0
    vis = (box_visual('dalle', f'{W_+0.4} {D_+0.4} 0.08', '0 0 0.04 0 0 0', tex=f'model://{name}/meshes/beton.png')
           + box_visual('fond', f'{W_} 0.08 {H_}', f'0 {D_/2} {H_/2} 0 0 0', tex=f'model://{name}/meshes/bardage.png')
           + box_visual('gauche', f'0.08 {D_} {H_}', f'{-W_/2} 0 {H_/2} 0 0 0', tex=f'model://{name}/meshes/bardage.png')
           + box_visual('droite', f'0.08 {D_} {H_}', f'{W_/2} 0 {H_/2} 0 0 0', tex=f'model://{name}/meshes/bardage.png')
           + box_visual('toit', f'{W_+0.5} {D_+0.6} 0.06', f'0 0 {H_+0.18} 0.12 0 0', tex=f'model://{name}/meshes/toit.png')
           + box_visual('panneau', '1.6 0.04 0.8', f'0 {-D_/2+0.05} {H_-0.55} 0 0 0', tex=f'model://{name}/meshes/panneau.png'))
    col = (box_collision('fond', f'{W_} 0.08 {H_}', f'0 {D_/2} {H_/2} 0 0 0') + box_collision('g', f'0.08 {D_} {H_}', f'{-W_/2} 0 {H_/2} 0 0 0')
           + box_collision('d', f'0.08 {D_} {H_}', f'{W_/2} 0 {H_/2} 0 0 0'))
    m = write_model(name, f'<link name="link">{col}{vis}</link>', 'Hangar agricole ouvert.')
    tex_concrete(os.path.join(m, 'beton.png')); tex_metal(os.path.join(m, 'bardage.png'), (96, 112, 104))
    tex_metal(os.path.join(m, 'toit.png'), (128, 70, 56)); tex_sign(os.path.join(m, 'panneau.png'))

    # ---- aire du drone + drone posé (maquette statique en attendant PX4)
    name = 'aire_drone'
    vis = (f'<visual name="aire"><pose>0 0 0.02 0 0 0</pose><geometry><mesh><uri>model://{name}/meshes/aire.obj</uri></mesh></geometry>{pbr(f"model://{name}/meshes/aire.png", 0.8)}</visual>'
           + box_visual('socle', '2.2 2.2 0.03', '0 0 0.015 0 0 0', color='0.25 0.26 0.27 1'))
    drone = ('<visual name="corps"><pose>0 0 0.16 0 0 0</pose><geometry><box><size>0.26 0.18 0.08</size></box></geometry>'
             '<material><ambient>0.12 0.12 0.13 1</ambient><diffuse>0.15 0.15 0.16 1</diffuse></material></visual>'
             '<visual name="capot"><pose>0 0 0.21 0 0 0</pose><geometry><box><size>0.18 0.12 0.03</size></box></geometry>'
             '<material><ambient>0.64 0.14 0.37 1</ambient><diffuse>0.75 0.18 0.43 1</diffuse></material></visual>'
             '<visual name="camera"><pose>0.12 0 0.11 0 0.6 0</pose><geometry><sphere><radius>0.035</radius></sphere></geometry>'
             '<material><ambient>0.05 0.05 0.05 1</ambient><diffuse>0.08 0.08 0.1 1</diffuse></material></visual>')
    for i, (sx, sy) in enumerate([(1, 1), (1, -1), (-1, 1), (-1, -1)]):
        yaw = math.atan2(sy, sx)
        drone += (f'<visual name="bras{i}"><pose>{0.16*sx} {0.16*sy} 0.17 0 0 {yaw:.3f}</pose><geometry><box><size>0.3 0.025 0.02</size></box></geometry>'
                  '<material><ambient>0.15 0.15 0.16 1</ambient><diffuse>0.2 0.2 0.21 1</diffuse></material></visual>'
                  f'<visual name="moteur{i}"><pose>{0.27*sx} {0.27*sy} 0.19 0 0 0</pose><geometry><cylinder><radius>0.025</radius><length>0.05</length></cylinder></geometry>'
                  '<material><ambient>0.2 0.2 0.2 1</ambient><diffuse>0.3 0.3 0.3 1</diffuse></material></visual>'
                  f'<visual name="helice{i}"><pose>{0.27*sx} {0.27*sy} 0.22 0 0 0</pose><geometry><cylinder><radius>0.13</radius><length>0.004</length></cylinder></geometry>'
                  '<material><ambient>0.6 0.6 0.62 1</ambient><diffuse>0.7 0.7 0.72 1</diffuse></material></visual>'
                  f'<visual name="pied{i}"><pose>{0.1*sx} {0.08*sy} 0.06 0 0 0</pose><geometry><cylinder><radius>0.008</radius><length>0.12</length></cylinder></geometry>'
                  '<material><ambient>0.1 0.1 0.1 1</ambient><diffuse>0.15 0.15 0.15 1</diffuse></material></visual>')
    m = write_model(name, f'<link name="link">{box_collision("c", "2.2 2.2 0.03", "0 0 0.015 0 0 0")}{vis}{drone}</link>', 'Aire de décollage du drone.')
    mesh_quad(os.path.join(m, 'aire.obj'), 1.8, 1.8); tex_pad(os.path.join(m, 'aire.png'))

    # ---- station de base du rover
    name = 'station_rover'
    vis = (f'<visual name="dalle"><pose>0 0 0.006 0 0 0</pose><geometry><mesh><uri>model://{name}/meshes/dalle.obj</uri></mesh></geometry>{pbr(f"model://{name}/meshes/dalle.png", 0.8)}</visual>'
           + box_visual('borne', '0.1 0.24 0.32', '-0.33 0 0.16 0 0 0', color='0.22 0.23 0.24 1')
           + box_visual('voyant', '0.105 0.12 0.025', '-0.33 0 0.28 0 0 0', color='0.2 0.9 0.4 1', emissive='0.1 0.8 0.3 1'))
    m = write_model(name, f'<link name="link">{vis}</link>', 'Station de recharge du rover.')
    mesh_quad(os.path.join(m, 'dalle.obj'), 0.6, 0.3); tex_dock(os.path.join(m, 'dalle.png'))

    # ---- borne d'angle de parcelle
    name = 'borne'
    vis = ('<visual name="poteau"><pose>0 0 0.35 0 0 0</pose><geometry><cylinder><radius>0.04</radius><length>0.7</length></cylinder></geometry>'
           '<material><ambient>0.45 0.32 0.2 1</ambient><diffuse>0.55 0.4 0.25 1</diffuse></material></visual>'
           + box_visual('tete', '0.1 0.1 0.08', '0 0 0.72 0 0 0', color='0.75 0.15 0.4 1'))
    write_model(name, f'<link name="link"><collision name="c"><pose>0 0 0.35 0 0 0</pose><geometry><cylinder><radius>0.04</radius><length>0.7</length></cylinder></geometry></collision>{vis}</link>', 'Borne de parcelle.')


# ------------------------------------------------------------------ monde
def include(model, name, x, y, z=0.0, yaw=0.0):
    return f'    <include><uri>model://{model}</uri><name>{name}</name><pose>{x:.3f} {y:.3f} {z:.3f} 0 0 {yaw:.3f}</pose></include>'


def build_world():
    parts, counts = [], {'saine': 0, 'debut': 0, 'malade': 0}
    parts.append(include('exploitation_sol', 'exploitation', 0, 0))
    parts.append(include('station_rover', 'station_rover', SPAWN[0], SPAWN[1]))
    parts.append(include('aire_drone', 'aire_drone', PAD[0], PAD[1], 0.02))
    parts.append(include('hangar', 'hangar', SHED[0], SHED[1], 0.02, math.pi))
    for k, (x, y) in enumerate([(SOIL[0] - 0.25, SOIL[2] - 0.25), (SOIL[0] - 0.25, SOIL[3] + 0.25), (SOIL[1] + 0.25, SOIL[2] - 0.25), (SOIL[1] + 0.25, SOIL[3] + 0.25)]):
        parts.append(include('borne', f'borne_{k}', x, y))
    parts.append(include('haie', 'haie_nord', 0, 6.8, 0.02))
    parts.append(include('haie', 'haie_est', 11.0, 6.2, 0.02, math.pi / 2))
    for k, (x, y, v) in enumerate([(-12.5, 4.5, 0), (-9.5, 8.5, 1), (13.5, 8.5, 0), (14.5, -6.5, 1), (5.0, 10.5, 1), (-15.5, -2.0, 0), (8.5, -9.5, 0)]):
        parts.append(include(f'arbre_{v}', f'arbre_{k}', x, y, 0.0, rng.uniform(0, 6.28)))
    for ri, ry in enumerate(ROWS_Y):
        n = int(round((FIELD_X[1] - FIELD_X[0]) / PLANT_SPACING)) + 1
        for i in range(n):
            x = FIELD_X[0] + i * PLANT_SPACING + rng.uniform(-0.04, 0.04)
            y = ry + rng.uniform(-0.025, 0.025)
            if rng.random() < 0.025:
                continue
            dv = disease(x, y)
            state = 'malade' if dv > 0.55 else 'debut' if dv > 0.22 else 'saine'
            counts[state] += 1
            parts.append(include(f'betterave_{state}_{rng.choice("ab")}', f'b_{ri:02d}_{i:02d}', x, y, field_height(x, y) - 0.004, rng.uniform(0, 6.28)))
    sdf = f'''<?xml version="1.0"?>
<sdf version="1.8">
  <world name="default">
    <physics name="1ms" type="ignored">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1.0</real_time_factor>
    </physics>
    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>
    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>
    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>
    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors">
      <render_engine>ogre2</render_engine>
    </plugin>
    <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>

    <scene>
      <ambient>0.62 0.62 0.66 1</ambient>
      <background>0.66 0.79 0.94 1</background>
      <shadows>true</shadows>
      <grid>false</grid>
      <sky></sky>
    </scene>

    <light type="directional" name="soleil">
      <cast_shadows>true</cast_shadows>
      <pose>0 0 30 0 0 0</pose>
      <diffuse>1.0 0.94 0.84 1</diffuse>
      <specular>0.25 0.25 0.25 1</specular>
      <direction>-0.5 0.38 -0.78</direction>
      <intensity>1.2</intensity>
    </light>
    <light type="directional" name="ciel">
      <cast_shadows>false</cast_shadows>
      <pose>0 0 30 0 0 0</pose>
      <diffuse>0.28 0.32 0.4 1</diffuse>
      <specular>0 0 0 1</specular>
      <direction>0.4 -0.3 -0.85</direction>
    </light>

{chr(10).join(parts)}
  </world>
</sdf>
'''
    os.makedirs(os.path.join(ROOT, 'worlds'), exist_ok=True)
    with open(os.path.join(ROOT, 'worlds', 'champ_realiste.sdf'), 'w') as f:
        f.write(sdf)
    return counts


def build_package():
    with open(os.path.join(ROOT, 'package.xml'), 'w') as f:
        f.write('''<?xml version="1.0"?>
<?xml-model href="http://download.ros.org/schema/package_format3.xsd" schematypens="http://www.w3.org/2001/XMLSchema"?>
<package format="3">
  <name>agri_sim</name>
  <version>0.2.0</version>
  <description>Exploitation de betteraves sucrières simulée dans Gazebo (projet Rover &amp; Drone agricole, JUNIA).</description>
  <maintainer email="vianytchemou@gmail.com">Pagnol TCHEMOU</maintainer>
  <license>Apache-2.0</license>
  <buildtool_depend>ament_cmake</buildtool_depend>
  <exec_depend>ros_gz_sim</exec_depend>
  <exec_depend>turtlebot3_gazebo</exec_depend>
  <export><build_type>ament_cmake</build_type></export>
</package>
''')
    with open(os.path.join(ROOT, 'CMakeLists.txt'), 'w') as f:
        f.write('cmake_minimum_required(VERSION 3.8)\nproject(agri_sim)\nfind_package(ament_cmake REQUIRED)\n'
                'install(DIRECTORY launch models worlds DESTINATION share/${PROJECT_NAME})\nament_package()\n')
    os.makedirs(os.path.join(ROOT, 'launch'), exist_ok=True)
    with open(os.path.join(ROOT, 'launch', 'champ_realiste.launch.py'), 'w') as f:
        f.write(f'''#!/usr/bin/env python3
"""Exploitation de betteraves + Turtlebot 3 (burger ou waffle selon TURTLEBOT3_MODEL)."""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import AppendEnvironmentVariable, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    agri = get_package_share_directory('agri_sim')
    tb3 = get_package_share_directory('turtlebot3_gazebo')
    ros_gz_sim = get_package_share_directory('ros_gz_sim')
    world = os.path.join(agri, 'worlds', 'champ_realiste.sdf')
    x_pose = LaunchConfiguration('x_pose', default='{SPAWN[0]}')
    y_pose = LaunchConfiguration('y_pose', default='{SPAWN[1]}')
    return LaunchDescription([
        AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH', os.path.join(agri, 'models')),
        AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH', os.path.join(tb3, 'models')),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(ros_gz_sim, 'launch', 'gz_sim.launch.py')),
            launch_arguments={{'gz_args': ['-r -s -v2 ', world], 'on_exit_shutdown': 'true'}}.items()),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(ros_gz_sim, 'launch', 'gz_sim.launch.py')),
            launch_arguments={{'gz_args': '-g -v2 ', 'on_exit_shutdown': 'true'}}.items()),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(tb3, 'launch', 'spawn_turtlebot3.launch.py')),
            launch_arguments={{'x_pose': x_pose, 'y_pose': y_pose}}.items()),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(tb3, 'launch', 'robot_state_publisher.launch.py')),
            launch_arguments={{'use_sim_time': 'true'}}.items()),
    ])
''')
    with open(os.path.join(ROOT, 'README.md'), 'w') as f:
        f.write('''# agri_sim

Exploitation de betteraves sucrières pour Gazebo Harmonic (ROS 2 Jazzy).

- Parcelle P-07 : 11 rangs de 12 m sur buttes, écartement 0,60 m, un plant tous les 0,40 m, tournières
- 4 foyers de cercosporiose : plants sains, en début d'infection et malades
- Prairie, chemin empierré, haie, arbres, hangar, aire du drone, station de base du rover

    export TURTLEBOT3_MODEL=waffle   # waffle = caméra
    ros2 launch agri_sim champ_realiste.launch.py

Les maillages et textures sont générés par `generate.py` (python3 + numpy + pillow).
''')


if __name__ == '__main__':
    if os.path.exists(ROOT):
        shutil.rmtree(ROOT)
    os.makedirs(ROOT)
    build_models()
    counts = build_world()
    build_package()
    shutil.copy(os.path.abspath(__file__), os.path.join(ROOT, 'generate.py'))
    print('Plants :', counts)
