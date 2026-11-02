"""Évalue hors simulation la détection aérienne par IA sur les vues enregistrées par generer_jeu_sim.py.

Pour chaque vue (position du drone connue), on compare les plants signalés « atteints » à la vérité terrain.
Mesures : rappel sur les plants malades et en début d'infection, fausses alertes, couverture de la segmentation
(part des plants réels pour lesquels un centre candidat a été trouvé à moins de 15 cm), erreur de position.

Usage : python3 evaluer_detection_aerienne.py [dossier_sim] [--couleur]
"""
import json
import math
import os
import sys

import cv2
import numpy as np

from vigie_detection.analyse import plants_aerien, plants_aerien_ia
from vigie_detection.classifieur import Classifieur

FOV, L, H = 1.2, 800, 600


def main():
    dossier = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else '~/ia/donnees/sim')
    couleur = '--couleur' in sys.argv
    meta = json.load(open(os.path.join(dossier, 'vues', 'meta.json'), encoding='utf-8'))
    verite = meta['verite']
    clf = None if couleur else Classifieur()
    print('méthode :', 'seuillage de couleur' if couleur else f'réseau de neurones ({os.path.basename(clf.chemin)})')
    stats = {'malade': [0, 0], 'debut': [0, 0]}          # [retrouvés, présents]
    fp = tot_pred = cand_ok = cand_tot = 0
    erreurs = []
    for nom, pose in meta['vues'].items():
        img = cv2.imread(os.path.join(dossier, 'vues', nom + '.jpg'))
        X, Y, Z = pose['x'], pose['y'], pose['z']
        s = 2 * (Z - 0.22) * math.tan(FOV / 2) / L

        def monde(u, v):
            return X + 0.04 + (H / 2 - v) * s, Y - (u - L / 2) * s

        det = plants_aerien(cv2.resize(img, (L // 2, H // 2), interpolation=cv2.INTER_AREA), s * 2) if couleur else plants_aerien_ia(img, s, clf, pose=(X + 0.04, Y))
        if couleur:
            for d in det:
                d['u'] *= 2; d['v'] *= 2
        det = [d for d in det if 50 < d['u'] < L - 50 and 40 < d['v'] < H - 40]
        pts = [monde(d['u'], d['v']) for d in det]
        dans = [p for p in verite if abs(p['x'] - (X + .04)) < (H / 2 - 40) * s and abs(p['y'] - Y) < (L / 2 - 50) * s]
        for p in dans:
            if p['classe'] in stats:
                stats[p['classe']][1] += 1
                proche = min((math.hypot(p['x'] - x, p['y'] - y) for x, y in pts), default=9)
                if proche < 0.2:
                    stats[p['classe']][0] += 1
                    erreurs.append(proche)
        for x, y in pts:
            tot_pred += 1
            if not any(math.hypot(p['x'] - x, p['y'] - y) < 0.2 for p in dans if p['classe'] != 'saine'):
                fp += 1
    for c, lib in (('malade', 'plants malades'), ('debut', 'débuts d’infection')):
        r, n = stats[c]
        print(f"rappel {lib} : {r}/{n} ({100 * r / max(1, n):.1f} %)")
    print(f"fausses alertes : {fp} sur {tot_pred} plants signalés ({100 * fp / max(1, tot_pred):.1f} %)")
    if erreurs:
        print(f"erreur de position des plants retrouvés : moyenne {100 * np.mean(erreurs):.1f} cm · 95e centile {100 * np.percentile(erreurs, 95):.1f} cm")


if __name__ == '__main__':
    main()
