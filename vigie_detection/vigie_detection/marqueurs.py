"""Marqueurs visuels dans Gazebo : anneaux de détection, jets de pulvérisation, obstacle.

Les modèles sont créés et supprimés par les services Gazebo (/world/<monde>/create et /remove).
Les appels passent par un fil d'exécution à part pour ne jamais bloquer les nœuds ROS.
"""
import math
import queue
import subprocess
import threading
import time

from .outils import MONDE

COULEURS = {
    'rouge': (0.95, 0.15, 0.12),
    'orange': (1.0, 0.55, 0.1),
    'vert': (0.15, 0.85, 0.35),
    'bleu': (0.25, 0.65, 1.0),
    'blanc': (1.0, 1.0, 1.0),
}


def _materiau(couleur, alpha):
    r, g, b = COULEURS[couleur]
    return (f"<material><ambient>{r} {g} {b} {alpha}</ambient><diffuse>{r} {g} {b} {alpha}</diffuse>"
            f"<emissive>{r * .8} {g * .8} {b * .8} 1</emissive><transparency>{1 - alpha}</transparency></material>")


def _modele(nom, pose, geometrie, couleur, alpha, ombre=False):
    x, y, z, roll, pitch, yaw = pose
    return (f"<sdf version='1.8'><model name='{nom}'><static>true</static><pose>{x:.3f} {y:.3f} {z:.3f} {roll:.4f} {pitch:.4f} {yaw:.4f}</pose>"
            f"<link name='l'><visual name='v'><cast_shadows>{'true' if ombre else 'false'}</cast_shadows>"
            f"<geometry>{geometrie}</geometry>{_materiau(couleur, alpha)}</visual></link></model></sdf>")


class Marqueurs:
    def __init__(self, logger=None, actif=True):
        self.log = logger
        self.actif = actif
        self.q = queue.Queue()
        self.existants = set()
        if actif:
            threading.Thread(target=self._boucle, daemon=True).start()

    # ------------------------------------------------------------------ appels bas niveau
    def _gz(self, service, reqtype, req):
        try:
            subprocess.run(['gz', 'service', '-s', f'/world/{MONDE}/{service}', '--reqtype', reqtype,
                            '--reptype', 'gz.msgs.Boolean', '--timeout', '2000', '--req', req],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
        except Exception as e:                                  # gz absent ou service occupé : sans gravité
            if self.log:
                self.log.debug(f'marqueur ignoré : {e}')

    def _boucle(self):
        while True:
            action, nom, sdf, delai = self.q.get()
            if delai:
                time.sleep(delai)
            if action == 'creer':
                self._gz('create', 'gz.msgs.EntityFactory', 'sdf: "' + sdf.replace('"', '\\"') + '"')
            else:
                self._gz('remove', 'gz.msgs.Entity', f'name: "{nom}" type: MODEL')

    def _creer(self, nom, sdf):
        if not self.actif or nom in self.existants:
            return
        self.existants.add(nom)
        self.q.put(('creer', nom, sdf, 0))

    def retirer(self, nom, delai=0.0):
        if not self.actif:
            return
        self.existants.discard(nom)
        self.q.put(('retirer', nom, '', delai))

    # ------------------------------------------------------------------ marqueurs
    def anneau(self, nom, x, y, couleur, rayon=0.2, alpha=0.7):
        """Disque lumineux au-dessus des buttes, plus une colonne visible de loin pour les détections."""
        geo = f"<cylinder><radius>{rayon * 1.15:.3f}</radius><length>0.012</length></cylinder>"
        self._creer(nom, _modele(nom, (x, y, 0.15, 0, 0, 0), geo, couleur, alpha))
        if couleur in ('rouge', 'orange'):
            colonne = "<cylinder><radius>0.014</radius><length>1.3</length></cylinder>"
            self._creer(nom + '_f', _modele(nom + '_f', (x, y, 0.8, 0, 0, 0), colonne, couleur, 0.55))

    def remplacer_anneau(self, nom_ancien, nom, x, y, couleur, rayon=0.2):
        self.retirer(nom_ancien)
        self.retirer(nom_ancien + '_f')
        self.anneau(nom, x, y, couleur, rayon)

    def jet(self, nom, p0, p1, duree=1.0):
        """Jet de bouillie entre la buse p0 et le plant p1 (x, y, z), retiré après `duree` secondes."""
        dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        L = max(0.02, math.sqrt(dx * dx + dy * dy + dz * dz))
        pitch = math.acos(max(-1.0, min(1.0, dz / L)))
        yaw = math.atan2(dy, dx)
        mx, my, mz = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, (p0[2] + p1[2]) / 2
        geo = f"<cylinder><radius>0.011</radius><length>{L:.3f}</length></cylinder>"
        self._creer(nom, _modele(nom, (mx, my, mz, 0, pitch, yaw), geo, 'bleu', 0.6))
        nuage = nom + '_n'
        geo2 = "<sphere><radius>0.085</radius></sphere>"
        self._creer(nuage, _modele(nuage, (p1[0], p1[1], p1[2], 0, 0, 0), geo2, 'bleu', 0.35))
        self.retirer(nom, duree)
        self.retirer(nuage, duree + 0.2)

    def boite(self, nom, x, y, taille=(0.35, 0.35, 0.3)):
        """Obstacle (rocher) posé dans une allée."""
        geo = f"<box><size>{taille[0]} {taille[1]} {taille[2]}</size></box>"
        sdf = (f"<sdf version='1.8'><model name='{nom}'><static>true</static><pose>{x:.3f} {y:.3f} {taille[2] / 2:.3f} 0 0 0.4</pose>"
               f"<link name='l'><collision name='c'><geometry>{geo}</geometry></collision>"
               f"<visual name='v'><geometry>{geo}</geometry><material><ambient>0.45 0.43 0.40 1</ambient>"
               f"<diffuse>0.55 0.52 0.48 1</diffuse></material></visual></link></model></sdf>")
        self._creer(nom, sdf)
