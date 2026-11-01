"""Classifieur « plant sain / atteint de cercosporiose » : réseau ResNet18 exporté en ONNX, exécuté par OpenCV.

Le modèle est entraîné hors ROS (voir ia/entrainer.py) ; les nœuds n'ont besoin que d'OpenCV.
Recherche du modèle : variable d'environnement VIGIE_MODELE, sinon ~/ia/modele/modele_cercospora_sim.onnx
(modèle adapté à la simulation), sinon ~/ia/modele/modele_cercospora.onnx (modèle entraîné sur le jeu public).
"""
import os

import cv2
import numpy as np

MOYENNE = np.array([0.485, 0.456, 0.406], np.float32)
ECART = np.array([0.229, 0.224, 0.225], np.float32)
CANDIDATS = ('~/ia/modele/modele_cercospora_sim.onnx', '~/ia/modele/modele_cercospora.onnx')


def trouver_modele():
    if os.environ.get('VIGIE_MODELE'):
        return os.path.expanduser(os.environ['VIGIE_MODELE'])
    for c in CANDIDATS:
        c = os.path.expanduser(c)
        if os.path.isfile(c):
            return c
    return None


class Classifieur:
    def __init__(self, chemin=None, taille=224):
        self.chemin = chemin or trouver_modele()
        self.taille = taille
        self.net = cv2.dnn.readNetFromONNX(self.chemin) if self.chemin else None
        self.pret = self.net is not None

    def probabilites(self, recadrages):
        """Probabilité « atteint » (0 à 1) de chaque recadrage (images BGR)."""
        if not self.pret or not recadrages:
            return np.zeros(len(recadrages))
        lot = []
        for c in recadrages:
            r = cv2.cvtColor(cv2.resize(c, (self.taille, self.taille), interpolation=cv2.INTER_AREA if min(c.shape[:2]) > self.taille else cv2.INTER_LINEAR), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            lot.append(((r - MOYENNE) / ECART).transpose(2, 0, 1))
        self.net.setInput(np.ascontiguousarray(np.stack(lot), dtype=np.float32))
        sortie = self.net.forward()
        e = np.exp(sortie - sortie.max(1, keepdims=True))
        return (e / e.sum(1, keepdims=True))[:, 1]
