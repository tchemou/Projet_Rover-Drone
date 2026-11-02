"""Nœud ROS 2 : bilan de la simulation, comparé aux critères de réussite de la note de clarification.

La vérité terrain (état réel de chaque plant) est lue dans le fichier du monde Gazebo. Elle ne sert
qu'à évaluer : aucun autre nœud n'y a accès.

Critères (cibles provisoires de la note, à confirmer au CC2) :
    - détection  : au moins 80 % de plants correctement classés (sain / malade)
    - traitement : pulvérisation à moins de 10 cm du plant visé
    - sécurité   : arrêt complet en moins d'1 s après l'arrêt d'urgence ou une perte de liaison
    - interface  : données du milieu rafraîchies au moins une fois par seconde
"""
import json
import math
import os
import re
import time
from datetime import datetime

import rclpy
from ament_index_python.packages import get_package_share_directory
from nav_msgs.msg import Odometry
from rclpy.node import Node
from std_msgs.msg import String

from .outils import litres_plein_champ


def charger_verite():
    chemin = os.path.join(get_package_share_directory('agri_sim'), 'worlds', 'champ_realiste.sdf')
    txt = open(chemin, encoding='utf-8').read()
    out = []
    for m in re.finditer(r"model://betterave_(saine|debut|malade)_\w</uri><name>(\w+)</name><pose>([-\d.]+) ([-\d.]+)", txt):
        out.append({'classe': m.group(1), 'nom': m.group(2), 'x': float(m.group(3)), 'y': float(m.group(4))})
    return out


class Bilan(Node):
    def __init__(self):
        super().__init__('bilan_simulation')
        self.verite = charger_verite()
        self.malades = [p for p in self.verite if p['classe'] == 'malade']
        self.debuts = [p for p in self.verite if p['classe'] == 'debut']
        self.sains = [p for p in self.verite if p['classe'] == 'saine']
        self.get_logger().info(f'Vérité terrain : {len(self.sains)} sains, {len(self.debuts)} en début d\'infection, {len(self.malades)} malades')
        self.zones = None
        self.sprays = []
        self.mission = {}
        self.meteo_t = []
        self.estop_t0 = None
        self.estop_dt = None
        self.v_rover = 0.0
        self.t_debut = None
        self.t_fin = None
        self.rapport_ecrit = False
        self.pub = self.create_publisher(String, '/vigie/bilan', 10)
        self.create_subscription(String, '/vigie/drone/zones', lambda m: setattr(self, 'zones', json.loads(m.data)), 10)
        self.create_subscription(String, '/vigie/pulverisation', self.on_spray, 10)
        self.create_subscription(String, '/vigie/mission', self.on_mission, 10)
        self.create_subscription(String, '/vigie/meteo', lambda m: self.meteo_t.append(time.monotonic()), 10)
        self.create_subscription(Odometry, '/odom', self.on_odom, 10)
        self.create_timer(1.0, self.publier)

    # ------------------------------------------------------------------ entrées
    def on_spray(self, m):
        self.sprays.append(json.loads(m.data))

    def on_odom(self, m):
        self.v_rover = abs(m.twist.twist.linear.x) + abs(m.twist.twist.angular.z) * 0.15
        if self.estop_t0 is not None and self.estop_dt is None and self.v_rover < 0.01:
            self.estop_dt = round(time.monotonic() - self.estop_t0, 2)
            self.get_logger().info(f"Arrêt complet {self.estop_dt} s après le déclenchement")

    def on_mission(self, m):
        d = json.loads(m.data)
        prev = self.mission.get('arret_cause')
        self.mission = d
        if d.get('arret_cause') and not prev:                  # front montant : arrêt d'urgence ou perte de liaison
            self.estop_t0 = time.monotonic()
            self.estop_dt = None if self.v_rover > 0.01 else 0.0
        if d.get('phase') in ('releve_rover', 'releve_drone', 'traitement') and self.t_debut is None:
            self.t_debut = time.monotonic()
        if d.get('phase') == 'termine' and self.t_fin is None:
            self.t_fin = time.monotonic()

    # ------------------------------------------------------------------ calculs
    def plus_proche(self, x, y, liste, rayon=0.25):
        best, bd = None, rayon
        for p in liste:
            d = math.hypot(p['x'] - x, p['y'] - y)
            if d < bd:
                best, bd = p, d
        return best, bd

    def bilan_detection(self):
        if not self.zones or not self.zones.get('plants'):
            return None
        det = self.zones['plants']
        vus_m, vus_d, fp, err = set(), set(), 0, []
        for d in det:                                       # un plant signalé est « bon » s'il est réellement atteint (malade ou début)
            p, dist = self.plus_proche(d['x'], d['y'], self.malades)
            if p:
                vus_m.add(p['nom']); err.append(dist)
                continue
            p, dist = self.plus_proche(d['x'], d['y'], self.debuts)
            if p:
                vus_d.add(p['nom']); err.append(dist)
            else:
                fp += 1
        tp = len(vus_m)
        fn = len(self.malades) - tp
        # exactitude sain / atteint sur tous les plants de la parcelle (un début d'infection est un plant atteint)
        total = len(self.sains) + len(self.malades) + len(self.debuts)
        bons = (len(self.sains) - fp) + tp + len(vus_d)
        err_cm = sorted(e * 100 for e in err)
        return {'vrais_malades': len(self.malades), 'detectes': tp, 'rates': fn, 'fausses_alertes': fp,
                'rappel': round(100 * tp / max(1, len(self.malades)), 1),
                'precision': round(100 * tp / max(1, tp + fp), 1),
                'exactitude': round(100 * bons / max(1, total), 1),
                'debuts_total': len(self.debuts), 'debuts_reperes': len(vus_d), 'rappel_debuts': round(100 * len(vus_d) / max(1, len(self.debuts)), 1),
                'erreur_position_cm': round(sum(err_cm) / len(err_cm), 1) if err_cm else None,
                'erreur_position_p95_cm': round(err_cm[int(0.95 * (len(err_cm) - 1))], 1) if err_cm else None}

    def bilan_traitement(self):
        if not self.sprays:
            return None
        err, faux = [], 0
        for s in self.sprays:
            p, d = self.plus_proche(s['x'], s['y'], self.malades + self.debuts, rayon=0.4)
            if p:
                err.append(d * 100)
            else:
                faux += 1
        couverts = sum(1 for p in self.malades if any(math.hypot(s['x'] - p['x'], s['y'] - p['y']) <= 0.12 for s in self.sprays))
        litres = sum(s.get('litres', 0) for s in self.sprays)
        plein = litres_plein_champ()
        err_s = sorted(err)
        return {'jets': len(self.sprays), 'jets_hors_cible': faux,
                'erreur_moyenne_cm': round(sum(err) / len(err), 1) if err else None,
                'erreur_max_cm': round(err_s[-1], 1) if err else None,
                'dans_10cm': round(100 * sum(1 for e in err if e <= 10) / max(1, len(err)), 1),
                'plants_couverts': couverts, 'couverture_traitement': round(100 * couverts / max(1, len(self.malades)), 1),
                'litres': round(litres, 3), 'litres_plein_champ': round(plein, 2),
                'economie': round(100 * (1 - litres / plein), 1)}

    def bilan_interface(self):
        now = time.monotonic()
        recents = [t for t in self.meteo_t if now - t < 5]
        self.meteo_t = recents
        return {'frequence_meteo_hz': round(len(recents) / 5.0, 2) if recents else 0.0}

    def critere(self, ok):
        return 'ok' if ok else 'ko' if ok is False else 'na'

    def publier(self):
        det, trt, itf = self.bilan_detection(), self.bilan_traitement(), self.bilan_interface()
        duree = None
        if self.t_debut:
            duree = round((self.t_fin or time.monotonic()) - self.t_debut, 1)
        crit = {
            'detection': self.critere(det['exactitude'] >= 80 if det else None),
            'traitement': self.critere((trt['erreur_moyenne_cm'] is not None and trt['erreur_moyenne_cm'] <= 10) if trt else None),
            'securite': self.critere(self.estop_dt <= 1.0 if self.estop_dt is not None else None),
            'interface': self.critere(itf['frequence_meteo_hz'] >= 1.0 if itf['frequence_meteo_hz'] else None),
        }
        out = {'detection': det, 'traitement': trt, 'interface': itf, 'arret_s': self.estop_dt,
               'duree_mission_s': duree, 'criteres': crit, 'mode': self.mission.get('mode')}
        self.pub.publish(String(data=json.dumps(out)))
        if self.t_fin and not self.rapport_ecrit:
            self.rapport_ecrit = True
            self.ecrire_rapport(out)

    def ecrire_rapport(self, out):
        dossier = os.path.expanduser('~/vigie_rapports')
        os.makedirs(dossier, exist_ok=True)
        nom = datetime.now().strftime('mission_%Y%m%d_%H%M%S')
        with open(os.path.join(dossier, nom + '.json'), 'w', encoding='utf-8') as f:
            json.dump({'bilan': out, 'mission': self.mission, 'jets': self.sprays, 'zones': self.zones}, f, ensure_ascii=False, indent=1)
        self.get_logger().info(f'Rapport de mission enregistré : {dossier}/{nom}.json')


def main():
    rclpy.init()
    n = Bilan()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        n.destroy_node()
        rclpy.try_shutdown()
