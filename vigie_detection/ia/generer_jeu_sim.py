"""Génère un jeu d'images de plants issu de la simulation, étiqueté avec la vérité terrain du monde Gazebo.

Le drone est déplacé à des positions et altitudes variées (service Gazebo set_pose) ; pour chaque vue on
recadre chaque plant visible autour de sa position connue et on l'enregistre dans le dossier de sa classe
(saine / debut / malade). Les recadrages servent à mesurer l'écart entre vraies photos et images simulées,
puis à adapter le modèle. À lancer quand la simulation tourne (sans mission en cours).

Usage : python3 generer_jeu_sim.py [dossier_sortie] [nb_vues_aleatoires]
"""
import math
import os
import random
import re
import subprocess
import sys
import time

import cv2
import rclpy
from ament_index_python.packages import get_package_share_directory
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

FOV, LARGEUR, HAUTEUR = 1.2, 800, 600
DEC_CAM_X, HAUT_CAM, HAUT_FEUILLES = 0.04, 0.10, 0.12
COTE = 96                                    # taille des recadrages en pixels (à 4 m : ≈ 0,64 m)


def verite():
    chemin = os.path.join(get_package_share_directory('agri_sim'), 'worlds', 'champ_realiste.sdf')
    txt = open(chemin, encoding='utf-8').read()
    return [{'classe': m.group(1), 'nom': m.group(2), 'x': float(m.group(3)), 'y': float(m.group(4))}
            for m in re.finditer(r"model://betterave_(saine|debut|malade)_\w</uri><name>(\w+)</name><pose>([-\d.]+) ([-\d.]+)", txt)]


def placer_drone(x, y, z):
    req = f'name:"drone_agri" position:{{x:{x:.3f} y:{y:.3f} z:{z:.3f}}} orientation:{{w:1}}'
    subprocess.run(['gz', 'service', '-s', '/world/default/set_pose', '--reqtype', 'gz.msgs.Pose', '--reptype', 'gz.msgs.Boolean',
                    '--timeout', '3000', '--req', req], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


class Capteur(Node):
    def __init__(self):
        super().__init__('generateur_jeu_sim')
        self.img = None
        self.t = 0.0
        self.create_subscription(Image, '/drone/camera/image_raw', self.cb, qos_profile_sensor_data)

    def cb(self, m):
        self.img, self.t = m, time.monotonic()

    def vue(self, attente=2.2):
        self.img = None
        t0 = time.monotonic()
        while time.monotonic() - t0 < attente + 2:
            rclpy.spin_once(self, timeout_sec=0.1)
            if self.img is not None and time.monotonic() - t0 > attente:
                return CvBridge().imgmsg_to_cv2(self.img, 'bgr8')
        return None


def main():
    sortie = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/ia/donnees/sim')
    n_alea = int(sys.argv[2]) if len(sys.argv) > 2 else 70
    for c in ('saine', 'debut', 'malade', 'vues'):
        os.makedirs(os.path.join(sortie, c), exist_ok=True)
    meta = {}
    plants = verite()
    rnd = random.Random(11)
    vues = []
    for p in plants:                                         # vues centrées sur chaque plant atteint, 2 altitudes
        if p['classe'] != 'saine':
            for z in (3.6, 4.4):
                vues.append((p['x'] + rnd.uniform(-1.2, 1.2), p['y'] + rnd.uniform(-1.0, 1.0), z))
    for _ in range(n_alea):                                  # vues aléatoires sur toute la parcelle
        vues.append((rnd.uniform(-5.5, 5.5), rnd.uniform(-2.6, 2.6), rnd.uniform(3.4, 4.6)))
    rclpy.init()
    cap = Capteur()
    n = {'saine': 0, 'debut': 0, 'malade': 0}
    t0 = time.time()
    for i, (X, Y, Z) in enumerate(vues):
        placer_drone(X, Y, Z)
        img = cap.vue()
        if img is None:
            continue
        cv2.imwrite(os.path.join(sortie, 'vues', f'vue_{i:03d}.jpg'), img, [cv2.IMWRITE_JPEG_QUALITY, 93])
        meta[f'vue_{i:03d}'] = {'x': X, 'y': Y, 'z': Z}
        h = Z - HAUT_CAM - HAUT_FEUILLES
        s = 2 * h * math.tan(FOV / 2) / LARGEUR
        for p in plants:
            u = LARGEUR / 2 - (p['y'] - Y) / s
            v = HAUTEUR / 2 - (p['x'] - (X + DEC_CAM_X)) / s
            r = COTE // 2
            if r + 4 < u < LARGEUR - r - 4 and r + 4 < v < HAUTEUR - r - 4:
                rec = img[int(v) - r:int(v) + r, int(u) - r:int(u) + r]
                cv2.imwrite(os.path.join(sortie, p['classe'], f"{p['nom']}__v{i:03d}.png"), rec)
                n[p['classe']] += 1
        if i % 20 == 0:
            print(f'vue {i + 1}/{len(vues)} · {n} · {time.time() - t0:.0f} s', flush=True)
    import json
    json.dump({'vues': meta, 'verite': plants}, open(os.path.join(sortie, 'vues', 'meta.json'), 'w'), indent=0)
    placer_drone(-9.2, -2.2, 0.13)                           # le drone retourne sur son aire
    print('terminé :', n)


if __name__ == '__main__':
    main()
