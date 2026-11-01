"""Analyse d'image : repère les plants de betterave jaunis ou tachés (cercosporiose).

Version 1, sans apprentissage : segmentation par couleur (espace HSV).
- végétation = pixels verts à jaune-vert assez saturés ;
- symptômes = feuilles jaunies (teinte jaune-vert) et taches brun-rouge à centre gris
  situées à l'intérieur du feuillage.
Elle sera remplacée par un modèle YOLO entraîné, avec la même interface.
"""
import cv2
import numpy as np

# Teintes OpenCV (0-180)
VEG = ((20, 70, 25), (90, 255, 255))       # tout le feuillage
SAIN = ((48, 70, 25), (90, 255, 255))      # vert franc
JAUNI = ((18, 110, 30), (40, 255, 255))     # vert-jaune / jaune
TACHE = ((0, 140, 25), (9, 255, 220))      # brun-rouge


def analyser(bgr, zone_utile=0.42, ratio_min=0.06, aire_min=0.0015):
    """Retourne (liste de détections, masque des symptômes).

    Chaque détection : dict(x, y, w, h, score) en pixels, score = part du feuillage atteinte.
    zone_utile : on ignore le haut de l'image (horizon, haies, prairie).
    """
    h, w = bgr.shape[:2]
    y0 = int(h * zone_utile)
    roi = bgr[y0:]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    veg = cv2.inRange(hsv, *VEG)
    jauni = cv2.inRange(hsv, *JAUNI)
    tache = cv2.inRange(hsv, *TACHE)
    # le feuillage est « fermé » pour englober les taches qui ne sont pas vertes
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    plant = cv2.morphologyEx(veg, cv2.MORPH_CLOSE, k)
    tache = cv2.bitwise_and(tache, plant)
    symp = cv2.bitwise_or(cv2.bitwise_and(jauni, plant), tache)
    symp = cv2.morphologyEx(symp, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    # regroupe les symptômes proches en foyers
    zones = cv2.dilate(symp, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(zones)
    det = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bw * bh < aire_min * w * h:
            continue
        sel = lab[y:y + bh, x:x + bw] == i
        s_p = np.count_nonzero(symp[y:y + bh, x:x + bw][sel])
        p_p = np.count_nonzero(plant[y:y + bh, x:x + bw][sel])
        if p_p == 0:
            continue
        ratio = s_p / p_p
        if ratio >= ratio_min:
            det.append(dict(x=int(x), y=int(y + y0), w=int(bw), h=int(bh), score=float(min(0.99, 0.55 + ratio))))
    full = np.zeros((h, w), np.uint8); full[y0:] = symp
    return det, full


def annoter(bgr, det, titre='VIGIE · détection cercosporiose v1'):
    out = bgr.copy()
    for d in det:
        x, y, w, h = d['x'], d['y'], d['w'], d['h']
        cv2.rectangle(out, (x, y), (x + w, y + h), (40, 40, 220), 2)
        lab = f"cercosporiose {d['score']:.2f}"
        (tw, th), _ = cv2.getTextSize(lab, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(out, (x, max(0, y - th - 8)), (x + tw + 8, y), (40, 40, 220), -1)
        cv2.putText(out, lab, (x + 4, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    etat = f"{len(det)} foyer(s) dans l'image" if det else 'aucun symptome'
    cv2.rectangle(out, (0, 0), (out.shape[1], 26), (95, 36, 163), -1)
    cv2.putText(out, f'VIGIE BETTERAVE  |  {etat}', (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return out


# ----------------------------------------------------------------------------------------------
# Vue aérienne (caméra du drone, orientée vers le sol)
# ----------------------------------------------------------------------------------------------
JAUNE = ((22, 70, 60), (46, 255, 255))                 # feuillage jauni vu de côté (caméra du rover)
JAUNE_AIR = ((22, 120, 60), (42, 255, 255))            # vu du dessus : saturation élevée, écarte les reflets des feuilles saines
ROUGE_1 = ((0, 130, 70), (8, 255, 255))                # taches brun-rouge : début d'infection
ROUGE_2 = ((172, 130, 70), (180, 255, 255))
VERT = ((47, 60, 30), (85, 255, 255))
AIRE_PLANT_M2 = 0.067                                  # surface jaune d'un plant malade vu du dessus


def plants_aerien(bgr, m_par_px):
    """Détecte, plant par plant, les betteraves malades ou en début d'infection sur une vue du dessus.

    Retourne une liste de dict(u, v, classe, score) en pixels. classe : 'malade' ou 'debut'.
    Sans apprentissage (couleur) : même interface que le futur modèle YOLO.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    ell = lambda n: cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (n, n))
    jaune = cv2.inRange(hsv, *JAUNE_AIR)
    jaune = cv2.morphologyEx(jaune, cv2.MORPH_CLOSE, ell(9))
    jaune = cv2.morphologyEx(jaune, cv2.MORPH_OPEN, ell(3))
    n, lab, st, cen = cv2.connectedComponentsWithStats(jaune)
    det = []
    k2 = m_par_px ** 2
    for i in range(1, n):
        aire = st[i, 4] * k2
        if aire < 0.025:
            continue
        nb = max(1, int(round(aire / AIRE_PLANT_M2)))
        if nb == 1:
            centres = [cen[i]]
        else:                                           # feuillages collés : un centre par plant
            ys, xs = np.nonzero(lab == i)
            pts = np.float32(np.c_[xs, ys])
            crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
            _, _, centres = cv2.kmeans(pts, nb, None, crit, 4, cv2.KMEANS_PP_CENTERS)
        sc = float(min(0.99, 0.62 + 0.35 * min(1.0, aire / (nb * AIRE_PLANT_M2))))
        for c in centres:
            det.append(dict(u=float(c[0]), v=float(c[1]), classe='malade', score=sc))
    # début d'infection : quelques taches rouges sur un feuillage encore vert
    rouge = cv2.bitwise_or(cv2.inRange(hsv, *ROUGE_1), cv2.inRange(hsv, *ROUGE_2))
    vert = cv2.dilate(cv2.inRange(hsv, *VERT), ell(15))
    rouge = cv2.bitwise_and(rouge, vert)
    rouge = cv2.bitwise_and(rouge, cv2.bitwise_not(cv2.dilate(jaune, ell(25))))
    amas = cv2.dilate(rouge, ell(max(5, int(0.22 / m_par_px))))
    n, lab, st, cen = cv2.connectedComponentsWithStats(amas)
    for i in range(1, n):
        x, y, w, h, _ = st[i]
        pix = int(np.count_nonzero(rouge[y:y + h, x:x + w][lab[y:y + h, x:x + w] == i]))
        if pix >= 6:
            det.append(dict(u=float(cen[i][0]), v=float(cen[i][1]), classe='debut',
                            score=float(min(0.9, 0.5 + 0.02 * pix))))
    return det


def annoter_aerien(bgr, det, m_par_px, entete=None):
    """Dessine les plants repérés (rouge : malade, orange : début d'infection)."""
    out = bgr.copy()
    couleurs = {'malade': (40, 40, 230), 'debut': (30, 150, 245)}
    r = int(0.24 / m_par_px)
    for d in det:
        c = couleurs[d['classe']]
        p = (int(d['u']), int(d['v']))
        cv2.circle(out, p, r, c, 3, cv2.LINE_AA)
        cv2.putText(out, f"{d['score']:.2f}", (p[0] + r + 4, p[1] + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 2, cv2.LINE_AA)
    if entete:
        cv2.rectangle(out, (0, 0), (out.shape[1], 28), (95, 36, 163), -1)
        cv2.putText(out, entete, (10, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return out


# ----------------------------------------------------------------------------------------------
# Vue du rover (caméra basse, face aux plants)
# ----------------------------------------------------------------------------------------------
def plants_rover(bgr, zone_utile=0.30, aire_min=70):
    """Repère les amas de feuillage jauni sur l'image de la caméra du rover.

    Retourne des dict(u, u0, u1, v, score) : colonne centrale, étendue en colonnes, ligne, score.
    """
    h, w = bgr.shape[:2]
    y0 = int(h * zone_utile)
    hsv = cv2.cvtColor(bgr[y0:], cv2.COLOR_BGR2HSV)
    jaune = cv2.inRange(hsv, *JAUNE)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    jaune = cv2.morphologyEx(cv2.morphologyEx(jaune, cv2.MORPH_CLOSE, k), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    n, lab, st, cen = cv2.connectedComponentsWithStats(jaune)
    det = []
    for i in range(1, n):
        x, y, bw, bh, aire = st[i]
        if aire < aire_min:
            continue
        det.append(dict(u=float(cen[i][0]), u0=int(x), u1=int(x + bw), v=float(cen[i][1] + y0), w=int(bw), h=int(bh),
                        score=float(min(0.99, 0.5 + aire / 1500.0))))
    return det
