"""Nœud ROS 2 : mission du rover (relevé, confirmation, traitement ciblé) et sécurité.

Deux modes de mission :
  - normal   : le drone survole la parcelle et envoie les plants suspects ; le rover s'y rend, confirme
               la maladie de près avec sa caméra, puis pulvérise uniquement les plants atteints ;
  - dégradé  : sans drone, le rover parcourt lui-même les allées pour repérer les foyers, puis les traite.

Deux modes de contrôle : « auto » (mission) et « manuel » (téléopération, avec arrêt devant les obstacles).

Sécurité (jamais désactivée) : arrêt d'urgence verrouillé, arrêt sur perte de liaison avec la console,
arrêt devant un obstacle détecté au LiDAR.

Abonnements : /odom, /scan, /vigie/commande, /vigie/heartbeat, /vigie/teleop,
              /vigie/drone/zones, /vigie/drone/etat, /vigie/rover/vue
Publications : /cmd_vel (TwistStamped), /vigie/mission, /vigie/pulverisation
"""
import json
import math
import time

import rclpy
from geometry_msgs.msg import Twist, TwistStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String

from .marqueurs import Marqueurs
from .outils import ALLEES, DOSE_PLANT_L, SPAWN, X_BOUT, angle_norm, yaw_de

ALLEES_RELEVE = [-2.7, -1.5, -0.3, 0.9, 2.1, 2.7]       # allées parcourues en mode dégradé
PORTEE_SONDE = (0.10, 0.50)                            # sortie latérale de la sonde (m)
COURSE_SONDE = 0.15                                     # débattement longitudinal de la sonde (m)


def nav(x, y, tol=0.12, **kw):
    return dict(p=(x, y), type='nav', tol=tol, **kw)


class Mission(Node):
    def __init__(self):
        super().__init__('mission_vigie')
        self.declare_parameter('vitesse', 0.80)
        self.declare_parameter('vitesse_releve', 0.55)
        self.declare_parameter('duree_pulverisation', 1.2)
        self.declare_parameter('distance_obstacle', 0.30)
        self.declare_parameter('delai_liaison', 3.0)
        self.declare_parameter("timeout_drone", 900.0)
        self.declare_parameter('marqueurs', True)
        self.declare_parameter('demarrage_auto', False)
        self.mark = Marqueurs(self.get_logger(), self.get_parameter('marqueurs').value)

        self.phase = 'attente'
        self.mode = 'normal'
        self.controle = 'auto'
        self.etat_txt = "en attente de l'ordre de mission"
        self.cause_arret = None
        self.pause = False
        self.pose = None
        self.dist_front = 9.9
        self.obstacle = False
        self.obstacle_nom = None
        self.cibles = []
        self.route = []
        self.etape = None
        self.sous = 'aller'
        self.t_etape = 0.0
        self.litres = 0.0
        self.dist = 0.0
        self.derniere = None
        self.vit = 0.0
        self.t_hb = None
        self.hb_actif = False
        self.teleop = (0.0, 0.0, 0.0)
        self.zones_drone = None
        self.drone_etat = {}
        self.vue = None
        self.t_releve = 0.0
        self.t_drone = 0.0                     # dernier message reçu du drone
        self.vues_rover = {}
        self.nb_jets = 0

        self.pub =self.create_publisher(TwistStamped, '/cmd_vel', 10)
        self.pub_etat = self.create_publisher(String, '/vigie/mission', 10)
        self.pub_spray = self.create_publisher(String, '/vigie/pulverisation', 10)
        self.create_subscription(Odometry, '/odom', self.on_odom, 10)
        self.create_subscription(Odometry, '/rover/gnss', self.on_gnss, 10)
        self.create_subscription(LaserScan, '/scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(String, '/vigie/commande', self.on_commande, 10)
        self.create_subscription(String, '/vigie/heartbeat', self.on_heartbeat, 10)
        self.create_subscription(Twist, '/vigie/teleop', self.on_teleop, 10)
        self.create_subscription(String, '/vigie/drone/zones', lambda m: setattr(self, 'zones_drone', json.loads(m.data)), 10)
        self.create_subscription(String, '/vigie/drone/etat', self.on_drone_etat, 10)
        self.create_subscription(String, '/vigie/rover/vue', self.on_vue, 10)
        self.create_timer(0.05, self.boucle)
        self.create_timer(0.2, self.publier)
        if self.get_parameter('demarrage_auto').value:
            self.create_timer(8.0, self.demarrer_une_fois)
        self.get_logger().info('Mission prête')

    def demarrer_une_fois(self):
        if self.phase == 'attente':
            self.on_commande(String(data='demarrer'))

    # ------------------------------------------------------------------ entrées
    def on_odom(self, m):
        self.vit = m.twist.twist.linear.x                       # vitesse mesurée par les roues

    def on_gnss(self, m):
        """Position absolue du rover (GNSS RTK simulé) : les roues dérivent, pas le GNSS."""
        p = m.pose.pose.position
        self.pose = (p.x, p.y, yaw_de(m.pose.pose.orientation))
        if self.derniere:
            d = math.hypot(self.pose[0] - self.derniere[0], self.pose[1] - self.derniere[1])
            if d < 0.5:
                self.dist += d
        self.derniere = self.pose

    def on_scan(self, m):
        mini = 9.9
        for i, r in enumerate(m.ranges):
            ang = angle_norm(m.angle_min + i * m.angle_increment)
            if abs(ang) <= math.radians(8) and m.range_min < r < m.range_max:
                mini = min(mini, r)
        self.dist_front = mini

    def on_drone_etat(self, m):
        self.drone_etat = json.loads(m.data)
        self.t_drone = time.monotonic()

    def on_heartbeat(self, m):
        self.t_hb = time.monotonic()
        self.hb_actif = True

    def on_teleop(self, m):
        self.teleop = (m.linear.x, m.angular.z, time.monotonic())

    def on_vue(self, m):
        self.vue = json.loads(m.data)
        self.vue['_t'] = time.monotonic()
        if self.phase == 'releve_rover':
            for d in self.vue.get('dets', []):
                if 'x' in d and d.get('r', 9) < 2.5:
                    self.fusionner_vue(d)

    def on_commande(self, m):
        c = m.data.strip().lower()
        log = self.get_logger()
        if c == 'arret_urgence':
            self.declencher_arret('urgence')
        elif c == 'rearmer':
            if self.cause_arret:
                log.info('Arrêt levé · mission en pause')
                self.cause_arret = None
                self.pause = True
        elif c.startswith('mode:'):
            if self.phase in ('attente', 'termine'):
                self.mode = c.split(':', 1)[1]
                log.info(f'Mode de mission : {self.mode}')
        elif c.startswith('controle:'):
            self.controle = c.split(':', 1)[1]
            if self.controle == 'manuel':
                self.pause = True
            log.info(f'Contrôle : {self.controle}')
        elif c == 'demarrer':
            if self.cause_arret:
                log.warn('Démarrage refusé : arrêt actif (utiliser « rearmer »)')
            elif self.phase in ('attente', 'termine'):
                self.nouvelle_mission()
        elif c == 'pause':
            self.pause = True
        elif c == 'reprendre':
            if not self.cause_arret:
                self.pause = False
                self.controle = 'auto'
        elif c == 'retour' and self.pose and not self.cause_arret:
            self.route = self.chemin_station(self.pose[:2])
            self.phase = 'retour'
            self.pause = False
            self.controle = 'auto'
            self.etape = None
        elif c == 'obstacle:poser' and self.pose:
            x, y, yaw = self.pose
            ox, oy = x + 1.1 * math.cos(yaw), y + 1.1 * math.sin(yaw)
            self.obstacle_nom = f'obstacle_{int(time.time()) % 100000}'
            self.mark.boite(self.obstacle_nom, ox, oy)
            log.warn(f'Obstacle posé devant le rover (x={ox:.2f}, y={oy:.2f})')
        elif c == 'obstacle:retirer' and self.obstacle_nom:
            self.mark.retirer(self.obstacle_nom)
            self.obstacle_nom = None
        elif c.startswith('valider:'):
            self.valider(int(c.split(':')[1]))
        elif c.startswith('rejeter:'):
            for t in self.cibles:
                if t['id'] == int(c.split(':')[1]) and t['etat'] == 'a_valider':
                    t['etat'] = 'rejete'

    def declencher_arret(self, cause):
        if self.cause_arret is None:
            self.cause_arret = cause
            self.get_logger().warn(f"ARRÊT ({'arrêt d’urgence' if cause == 'urgence' else 'perte de liaison'}) · rover immobilisé")
        self.envoyer(0.0, 0.0)

    # ------------------------------------------------------------------ cibles
    def nouvelle_mission(self):
        self.cibles, self.route, self.litres, self.dist = [], [], 0.0, 0.0
        self.nb_jets = 0
        self.vues_rover = {}
        self.pause = False
        self.controle = 'auto'
        self.etape = None
        self.t_releve = time.monotonic()
        if self.mode == 'degrade':
            self.phase = 'releve_rover'
            self.route = self.route_releve()
            self.get_logger().warn('Mode dégradé : relevé de la parcelle par le rover seul')
        else:
            self.phase = 'releve_drone'
            self.get_logger().info('Mission lancée : relevé par le drone')

    def fusionner_vue(self, d):
        """Ajoute une détection de la caméra du rover (mode dégradé), en regroupant les voisines."""
        for v in self.vues_rover.values():
            if math.hypot(v['x'] - d['x'], v['y'] - d['y']) < 0.3:
                n = v['n']
                v['x'] = (v['x'] * n + d['x']) / (n + 1)
                v['y'] = (v['y'] * n + d['y']) / (n + 1)
                v['n'] = n + 1
                return
        k = len(self.vues_rover) + 1
        self.vues_rover[k] = {'x': d['x'], 'y': d['y'], 'n': 1, 'classe': d.get('classe', 'malade'), 'score': d.get('score', 0.7)}

    def cibles_depuis_drone(self):
        out = []
        for p in (self.zones_drone or {}).get('plants', []):
            if p['classe'] == 'malade':           # les débuts d'infection (taches minuscules) ne sont pas fiables à 4 m
                out.append({'id': p['id'], 'x': p['x'], 'y': p['y'], 'classe': p['classe'], 'score': p['score'],
                            'source': 'drone', 'etat': 'a_traiter', 'mk': f"mk_det_{p['id']}"})
        return out

    def cibles_depuis_rover(self):
        out = []
        for k, v in self.vues_rover.items():
            if v['n'] >= 3:
                out.append({'id': 1000 + k, 'x': round(v['x'], 3), 'y': round(v['y'], 3), 'classe': v['classe'],
                            'score': v['score'], 'source': 'rover', 'etat': 'a_traiter', 'mk': f'mk_det_r{k}'})
                self.mark.anneau(f'mk_det_r{k}', v['x'], v['y'], 'rouge', 0.2)
        return out

    def valider(self, ident):
        for t in self.cibles:
            if t['id'] == ident and t['etat'] == 'a_valider':
                t['etat'] = 'valide'
                t['confirme'] = True
                self.get_logger().info(f'Cible {ident} validée par l’opérateur')
        if self.phase in ('retour', 'termine') and any(t['etat'] == 'valide' for t in self.cibles):
            self.relancer_traitement()

    def relancer_traitement(self):
        self.route = self.route_traitement()
        self.phase = 'traitement'
        self.etape = None

    # ------------------------------------------------------------------ routes
    def route_releve(self):
        """Serpentin dans les allées choisies, en partant de la tournière où se trouve le rover."""
        depart_ouest = (self.pose[0] if self.pose else SPAWN[0]) < 0
        r = []
        for a in ALLEES_RELEVE:
            a1, a2 = (-X_BOUT, X_BOUT) if depart_ouest else (X_BOUT, -X_BOUT)
            r += [nav(a1, a), nav(a2, a, vitesse='releve')]
            depart_ouest = not depart_ouest
        return r + self.chemin_station(r[-1]['p'])

    def chemin_station(self, depart):
        """Du point donné jusqu'à la station : sortie par la tournière la plus proche, puis allée centrale."""
        x, y = depart
        xh = X_BOUT if x > 0 else -X_BOUT
        r = []
        if abs(x) < X_BOUT - 0.05:
            r.append(nav(xh, y))
        r.append(nav(xh, SPAWN[1]))
        if xh > 0:
            r.append(nav(-X_BOUT, SPAWN[1]))
        r.append(nav(SPAWN[0], SPAWN[1], fin=True))
        return r

    def route_traitement(self):
        """Par allée : point de confirmation avant chaque foyer, puis un arrêt par plant à traiter."""
        cibles = [t for t in self.cibles if t['etat'] in ('a_traiter', 'valide')]
        groupes = {}
        for t in cibles:
            a = min(ALLEES, key=lambda al: (abs(al - t['y']), al))
            groupes.setdefault(a, []).append(t)
        cx, cy, _ = self.pose
        ordre, courant, restant = [], cy, set(groupes)
        while restant:                                       # allée la plus proche à chaque fois
            a = min(restant, key=lambda al: abs(al - courant))
            ordre.append(a)
            courant = a
            restant.discard(a)
        r = []
        for a in ordre:
            xh = X_BOUT if cx > 0 else -X_BOUT               # on entre par la tournière la plus proche
            if abs(cx) < X_BOUT - 0.05:
                r.append(nav(xh, cy))
            r.append(nav(xh, a, tol=0.04))              # entrée d'allée : bien centré entre les rangs
            d = 1 if xh < 0 else -1
            stops = sorted(groupes[a], key=lambda t: t['x'] * d)
            derniere = None
            for t in stops:
                if derniere is None or abs(t['x'] - derniere) > 1.3:
                    r.append(dict(p=(max(-X_BOUT, min(X_BOUT, t['x'] - d * 1.0)), a), type='confirmer', cible=t['id']))
                r.append(dict(p=(t['x'], a), type='pulveriser', cible=t['id']))
                derniere = t['x']
            cx, cy = stops[-1]['x'], a
        return r + self.chemin_station((cx, cy))

    # ------------------------------------------------------------------ pilotage bas niveau
    def envoyer(self, v, w):
        t = TwistStamped()
        t.header.stamp = self.get_clock().now().to_msg()
        t.twist.linear.x, t.twist.angular.z = float(v), float(w)
        self.pub.publish(t)

    def liaison_ok(self):
        if not self.hb_actif:
            return True
        return (time.monotonic() - self.t_hb) < self.get_parameter('delai_liaison').value

    def aller_a(self, p, vmax, tol):
        """Un pas du suiveur de points. Retourne True si le point est atteint."""
        x, y, yaw = self.pose
        dx, dy = p[0] - x, p[1] - y
        d = math.hypot(dx, dy)
        if d < tol:
            return True
        err = angle_norm(math.atan2(dy, dx) - yaw)
        w = max(-1.0, min(1.0, 2.2 * err))
        if abs(err) > 0.5:
            v = 0.0
        else:
            v = min(vmax * (1.0 - abs(err) / 0.5), 0.8 * d + 0.03)
        self.commander(v, w)
        return False

    def commander(self, v, w):
        """Applique l'arrêt devant obstacle à toute commande d'avance."""
        self.obstacle = self.dist_front < self.get_parameter('distance_obstacle').value
        if v > 0 and self.dist_front < 0.65:
            v *= 0.5
        if v > 0 and self.obstacle:
            v = 0.0
        self.envoyer(v, w)

    # ------------------------------------------------------------------ boucle
    def boucle(self):
        if self.pose is None:
            return
        if not self.liaison_ok():
            self.declencher_arret('liaison')
        if self.cause_arret:
            self.envoyer(0.0, 0.0)
            self.etat_txt = "ARRÊT D'URGENCE" if self.cause_arret == 'urgence' else 'LIAISON PERDUE · rover arrêté'
            return
        if self.controle == 'manuel':
            v, w, t = self.teleop
            if time.monotonic() - t > 0.4:
                v, w = 0.0, 0.0
            self.commander(v, w)
            self.etat_txt = 'téléopération' + (' · obstacle devant' if self.obstacle else '')
            return
        if self.pause:
            self.envoyer(0.0, 0.0)
            self.etat_txt = 'mission en pause'
            return
        if self.phase == 'releve_drone':
            self.envoyer(0.0, 0.0)
            self.attendre_drone()
        elif self.phase in ('releve_rover', 'traitement', 'retour'):
            self.executer_route()
        else:
            self.envoyer(0.0, 0.0)
            if self.phase == 'attente':
                self.etat_txt = "en attente de l'ordre de mission"

    def attendre_drone(self):
        z = self.zones_drone
        ecoule = time.monotonic() - self.t_releve
        ph = self.drone_etat.get('phase', '?')
        self.etat_txt = f"le drone relève la parcelle · {self.drone_etat.get('couverture', 0):.0f} % couvert"
        if z and z.get('termine') and ph in ('atterrissage', 'atterri'):
            self.cibles = self.cibles_depuis_drone()
            self.get_logger().info(f'Relevé du drone terminé : {len(self.cibles)} plant(s) suspect(s)')
            self.lancer_traitement()
        elif (ecoule > 15 and time.monotonic() - self.t_drone > 20) or ecoule > self.get_parameter('timeout_drone').value:
            # drone silencieux depuis 20 s (ou relevé bien trop long) : on ne l'attend plus
            self.get_logger().error('Drone muet : bascule en mode dégradé (relevé par le rover)')
            self.mode = 'degrade'
            self.phase = 'releve_rover'
            self.route = self.route_releve()
            self.etape = None

    def lancer_traitement(self):
        if not self.cibles:
            self.route = self.chemin_station(self.pose[:2])
            self.phase = 'retour'
            self.etape = None
            return
        self.relancer_traitement()

    def executer_route(self):
        if not self.route:
            self.fin_de_route()
            return
        etape = self.route[0]
        if etape is not self.etape:
            self.etape, self.t_etape, self.sous = etape, time.monotonic(), 'aller'
        vmax = self.get_parameter('vitesse_releve' if etape.get('vitesse') == 'releve' else 'vitesse').value
        t = etape['type']
        if t == 'nav':
            self.etat_txt = {'releve_rover': 'relevé de la parcelle par le rover', 'retour': 'retour à la station'}.get(self.phase, 'déplacement vers le prochain foyer')
            if self.obstacle:
                self.etat_txt = 'OBSTACLE détecté · rover arrêté'
            if self.aller_a(etape['p'], vmax, etape.get('tol', 0.12)):
                self.route.pop(0)
        elif t == 'confirmer':
            self.etape_confirmer(etape, vmax)
        elif t == 'pulveriser':
            self.etape_pulveriser(etape, vmax)

    def cible(self, ident):
        return next((c for c in self.cibles if c['id'] == ident), None)

    def etape_confirmer(self, etape, vmax):
        cible = self.cible(etape['cible'])
        if self.sous == 'aller':
            self.etat_txt = f"approche du plant {etape['cible']}"
            if self.aller_a(etape['p'], min(vmax, 0.5), 0.06):
                self.sous, self.t_etape = 'regarder', time.monotonic()
        else:
            self.envoyer(0.0, 0.0)
            self.etat_txt = f"confirmation par la caméra · plant {etape['cible']}"
            ok = self.confirmation(cible)
            if ok or time.monotonic() - self.t_etape > 1.6:
                self.route.pop(0)
                self.etape = None
                groupe = []
                for e in self.route:
                    if e['type'] == 'confirmer':
                        break
                    if e['type'] == 'pulveriser':
                        groupe.append(e)
                for e in groupe:
                    c = self.cible(e['cible'])
                    if not c:
                        continue
                    if ok:
                        c['confirme'] = True
                    else:                                   # pas de pulvérisation à l'aveugle : l'opérateur tranche
                        c['etat'] = 'a_valider'
                        self.get_logger().warn(f"Plant {c['id']} non confirmé par la caméra : validation opérateur requise")
                if not ok:
                    self.route = [e for e in self.route if not any(e is g for g in groupe)]

    def confirmation(self, cible):
        """La caméra du rover voit-elle des symptômes dans la direction attendue du plant ?"""
        if not cible or not self.vue or time.monotonic() - self.vue['_t'] > 0.8:
            return False
        x, y, yaw = self.pose
        att = angle_norm(math.atan2(cible['y'] - y, cible['x'] - x) - yaw)
        return any(d['ang0'] - 0.10 <= att <= d['ang1'] + 0.10 and d.get('score', 0) >= 0.5 for d in self.vue.get('dets', []))

    def etape_pulveriser(self, etape, vmax):
        cible = self.cible(etape['cible'])
        if cible is None or cible['etat'] not in ('a_traiter', 'valide'):
            self.route.pop(0)
            self.etape = None
            return
        if self.sous == 'aller':
            self.etat_txt = f"positionnement sur le plant {cible['id']}"
            if self.aller_a(etape['p'], min(vmax, 0.3), 0.03):
                self.sous, self.t_etape = 'viser', time.monotonic()
        elif self.sous == 'viser':
            self.envoyer(0.0, 0.0)
            self.etat_txt = f"visée de la sonde · plant {cible['id']}"
            if time.monotonic() - self.t_etape > 0.5 and abs(self.vit) < 0.02:
                self.tirer(cible)
                self.sous, self.t_etape = 'jet', time.monotonic()
        else:
            self.envoyer(0.0, 0.0)
            self.etat_txt = f"pulvérisation · plant {cible['id']}"
            if time.monotonic() - self.t_etape > self.get_parameter('duree_pulverisation').value:
                cible['etat'] = 'traite'
                self.mark.remplacer_anneau(cible['mk'], f"mk_trt_{cible['id']}", cible['x'], cible['y'], 'vert', 0.22)
                self.route.pop(0)
                self.etape = None

    def tirer(self, cible):
        """La sonde latérale se place sur le plant ; le jet part de la buse."""
        x, y, yaw = self.pose
        dx, dy = cible['x'] - x, cible['y'] - y
        av = math.cos(yaw) * dx + math.sin(yaw) * dy                      # devant le rover
        lat = -math.sin(yaw) * dx + math.cos(yaw) * dy                    # à gauche du rover
        cote = 1 if lat >= 0 else -1
        sortie = max(PORTEE_SONDE[0], min(PORTEE_SONDE[1], abs(lat)))
        av = max(-COURSE_SONDE, min(COURSE_SONDE, av))
        tx = x + math.cos(yaw) * av - math.sin(yaw) * cote * sortie       # pointe réelle de la sonde (repère monde)
        ty = y + math.sin(yaw) * av + math.cos(yaw) * cote * sortie
        buse = (x - math.sin(yaw) * cote * 0.215, y + math.cos(yaw) * cote * 0.215, 0.13)
        self.nb_jets += 1
        self.litres += DOSE_PLANT_L
        self.mark.jet(f'mk_jet_{self.nb_jets}', buse, (tx, ty, 0.14), self.get_parameter('duree_pulverisation').value)
        msg = {'n': self.nb_jets, 'cible': cible['id'], 'x': round(tx, 3), 'y': round(ty, 3),
               'litres': DOSE_PLANT_L, 'source': cible.get('source'), 'classe': cible['classe']}
        self.pub_spray.publish(String(data=json.dumps(msg)))
        self.get_logger().info(f"Jet sur le plant {cible['id']} ({cible['classe']}) · pointe à ({tx:.2f}, {ty:.2f})")

    def fin_de_route(self):
        self.envoyer(0.0, 0.0)
        self.etape = None
        if self.phase == 'releve_rover':
            self.cibles = self.cibles_depuis_rover()
            self.get_logger().info(f'Relevé du rover terminé : {len(self.cibles)} plant(s) suspect(s)')
            self.lancer_traitement()
        elif self.phase == 'traitement':
            self.route = self.chemin_station(self.pose[:2])
            self.phase = 'retour'
            n = sum(1 for c in self.cibles if c['etat'] == 'traite')
            self.get_logger().info(f'Traitement terminé : {n} plant(s) traité(s)')
        else:
            self.phase = 'termine'
            self.etat_txt = 'mission terminée'
            self.get_logger().info('Mission terminée')

    # ------------------------------------------------------------------ sortie
    def publier(self):
        if self.pose is None:
            return
        cible = None
        if self.etape and self.etape.get('cible'):
            c = self.cible(self.etape['cible'])
            if c:
                cible = {'id': c['id'], 'x': c['x'], 'y': c['y'], 'etape': self.etape['type']}
        etat = {
            'phase': self.phase, 'mode': self.mode, 'controle': self.controle, 'etat': self.etat_txt,
            'pose': {'x': round(self.pose[0], 3), 'y': round(self.pose[1], 3), 'yaw': round(self.pose[2], 3)},
            'vitesse': round(self.vit, 2), 'distance': round(self.dist, 1), 'litres': round(self.litres, 3),
            'obstacle': bool(self.obstacle), 'dist_obstacle': round(min(self.dist_front, 9.9), 2),
            'arret_cause': self.cause_arret, 'pause': self.pause, 'liaison': self.liaison_ok(),
            'cible': cible,
            'cibles': [{'id': c['id'], 'x': c['x'], 'y': c['y'], 'classe': c['classe'], 'etat': c['etat'],
                        'confirme': c.get('confirme', False), 'source': c.get('source')} for c in self.cibles],
            'route': [[round(e['p'][0], 2), round(e['p'][1], 2)] for e in self.route[:14]],
            'traites': sum(1 for c in self.cibles if c['etat'] == 'traite'),
            'a_valider': sum(1 for c in self.cibles if c['etat'] == 'a_valider'),
            'jets': self.nb_jets,
        }
        self.pub_etat.publish(String(data=json.dumps(etat)))


def main():
    rclpy.init()
    n = Mission()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        n.envoyer(0, 0)
        n.destroy_node()
        rclpy.try_shutdown()
