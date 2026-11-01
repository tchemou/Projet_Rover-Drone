"""Nœud ROS 2 : drone de relevé de la parcelle.

Le drone décolle de son aire, survole la parcelle en deux passes (plan de vol par points de passage),
détecte les plants atteints sur les images de sa caméra, les géolocalise et envoie la liste au rover.

Abonnements : /drone/odom, /drone/camera/image_raw, /vigie/commande
Publications : /drone/cmd_vel            (geometry_msgs/Twist, vers Gazebo)
               /vigie/drone/etat         (std_msgs/String, JSON : phase, altitude, batterie, couverture…)
               /vigie/drone/zones        (std_msgs/String, JSON : plants repérés et zones à traiter)
               /vigie/drone/image/compressed (sensor_msgs/CompressedImage, vue annotée)
"""
import json
import math
from collections import deque

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String

from .analyse import annoter_aerien, plants_aerien
from .marqueurs import Marqueurs
from .outils import AIRE_DRONE, CHAMP, dans_champ

DEC_CAM_X = 0.04                 # la caméra est 4 cm devant le centre du drone
HAUT_CAM = 0.10                  # et 10 cm plus bas
HAUT_FEUILLES = 0.12             # hauteur moyenne du feuillage au-dessus du sol
FOV = 1.2                        # champ horizontal de la caméra (rad)
LARGEUR_PX, HAUTEUR_PX = 800, 600
CELLULE = 0.25                   # maille de suivi de la couverture (m)


class Drone(Node):
    def __init__(self):
        super().__init__('drone_releve')
        self.declare_parameter('altitude', 4.0)
        self.declare_parameter('vitesse', 1.4)
        self.declare_parameter('passes_y', [1.65, -1.65])
        self.declare_parameter('x_debut', -6.8)
        self.declare_parameter('x_fin', 6.8)
        self.declare_parameter('marqueurs', True)
        self.declare_parameter('vues_min', 3)
        self.alt = self.get_parameter('altitude').value
        self.vmax = self.get_parameter('vitesse').value
        self.bridge = CvBridge()
        self.mark = Marqueurs(self.get_logger(), self.get_parameter('marqueurs').value)

        self.odom = deque(maxlen=200)         # (t, x, y, z)
        self.pose = None
        self.vit = np.zeros(3)
        self.phase = 'au_sol'
        self.mode = 'normal'
        self.stop = False
        self.pause = False
        self.wp = []                           # points de passage restants
        self.wp_total = 0
        self.batterie = 100.0
        self.plants = []                       # plants repérés (coordonnées monde)
        self.nb_images = 0
        x0, x1, y0, y1 = CHAMP
        self.nx, self.ny = int((x1 - x0) / CELLULE), int((y1 - y0) / CELLULE)
        self.couvert = np.zeros((self.nx, self.ny), bool)
        self.vue = None                        # dernier aperçu annoté
        self.t_img_pub = 0.0
        self.t_traite = 0.0
        cv2.setNumThreads(2)                   # laisse la main au simulateur

        self.pub = self.create_publisher(Twist, '/drone/cmd_vel', 10)
        self.pub_etat = self.create_publisher(String, '/vigie/drone/etat', 10)
        self.pub_zones = self.create_publisher(String, '/vigie/drone/zones', 10)
        self.pub_jpg = self.create_publisher(CompressedImage, '/vigie/drone/image/compressed', 5)
        self.create_subscription(Odometry, '/drone/odom', self.on_odom, 10)
        self.create_subscription(Image, '/drone/camera/image_raw', self.on_image, qos_profile_sensor_data)
        self.create_subscription(String, '/vigie/commande', self.on_commande, 10)
        self.create_timer(0.05, self.boucle)
        self.create_timer(0.5, self.publier_etat)
        self.create_timer(1.0, self.publier_zones)
        self.get_logger().info('Drone prêt sur son aire · en attente de la commande de mission')

    # ------------------------------------------------------------------ entrées
    def on_odom(self, m):
        p = m.pose.pose.position
        t = m.header.stamp.sec + m.header.stamp.nanosec * 1e-9
        self.odom.append((t, p.x, p.y, p.z))
        self.pose = (p.x, p.y, p.z)

    def on_commande(self, m):
        c = m.data.strip().lower()
        if c.startswith('mode:'):
            self.mode = c.split(':', 1)[1]
            if self.mode == 'degrade' and self.phase == 'au_sol':
                self.get_logger().warn('Mode dégradé : drone indisponible')
        elif c == 'demarrer' and self.phase in ('au_sol', 'atterri') and self.mode == 'normal':
            self.stop = self.pause = False
            self.lancer_vol()
        elif c == 'arret_urgence':
            self.stop = True
            self.get_logger().warn("Arrêt d'urgence : drone en vol stationnaire")
        elif c == 'rearmer':
            self.stop = False
        elif c == 'pause':
            self.pause = True
        elif c == 'reprendre':
            self.pause = False

    def lancer_vol(self):
        x_a, y_a = AIRE_DRONE
        x0, x1 = self.get_parameter('x_debut').value, self.get_parameter('x_fin').value
        ys = list(self.get_parameter('passes_y').value)
        pts = [(x_a, y_a, self.alt)]
        sens = 1
        for y in ys:
            a, b = (x0, x1) if sens > 0 else (x1, x0)
            pts += [(a, y, self.alt), (b, y, self.alt)]
            sens = -sens
        pts += [(x_a, y_a, self.alt)]
        self.wp = pts
        self.wp_total = len(pts)
        self.phase = 'decollage'
        self.get_logger().info(f'Décollage · plan de vol de {len(pts)} points à {self.alt:.1f} m')

    # ------------------------------------------------------------------ commande de vol
    def boucle(self):
        if self.pose is None:
            return
        cible = None
        vmax = self.vmax
        if self.stop or self.pause or self.phase in ('au_sol', 'atterri'):
            cible = None
        elif self.phase == 'decollage':
            x_a, y_a = AIRE_DRONE
            cible, vmax = (x_a, y_a, self.alt), 1.2
            if abs(self.pose[2] - self.alt) < 0.08:
                self.wp.pop(0)
                self.phase = 'releve'
                self.get_logger().info('Altitude atteinte · début du relevé de la parcelle')
        elif self.phase == 'releve':
            if not self.wp:
                self.phase = 'retour'
            else:
                cible = self.wp[0]
                if math.dist(self.pose, cible) < 0.12:
                    self.wp.pop(0)
        elif self.phase == 'retour':
            x_a, y_a = AIRE_DRONE
            cible = (x_a, y_a, self.alt)
            vmax = 2.0
            if math.hypot(self.pose[0] - x_a, self.pose[1] - y_a) < 0.12:
                self.phase = 'atterrissage'
                self.publier_zones(final=True)
                self.get_logger().info(f'Relevé terminé · {len(self.plants_confirmes())} plant(s) à traiter · atterrissage')
        elif self.phase == 'atterrissage':
            x_a, y_a = AIRE_DRONE
            cible, vmax = (x_a, y_a, 0.13), 0.7
            if self.pose[2] < 0.2:
                self.phase = 'atterri'
                cible = None
        self.piloter(cible, vmax)
        if self.phase in ('decollage', 'releve', 'retour', 'atterrissage') and not self.stop and not self.pause:
            self.batterie = max(0.0, self.batterie - 0.05 * 0.034)

    def piloter(self, cible, vmax):
        dt = 0.05
        if cible is None:
            voulu = np.zeros(3)
        else:
            e = np.array(cible) - np.array(self.pose)
            d = float(np.linalg.norm(e))
            v = min(vmax, 1.3 * d + 0.03)
            voulu = e / d * v if d > 1e-6 else np.zeros(3)
        dv = voulu - self.vit
        amax = 1.6 * dt
        n = float(np.linalg.norm(dv))
        if n > amax:
            dv = dv / n * amax
        self.vit = self.vit + dv
        t = Twist()
        t.linear.x, t.linear.y, t.linear.z = (float(c) for c in self.vit)
        self.pub.publish(t)

    # ------------------------------------------------------------------ vision
    def pose_a(self, t):
        """Position interpolée du drone à l'instant t (secondes, horloge de simulation)."""
        if len(self.odom) < 2:
            return None
        a = list(self.odom)
        if t <= a[0][0]:
            return a[0][1:]
        if t >= a[-1][0]:
            return a[-1][1:]
        for p, q in zip(a, a[1:]):
            if p[0] <= t <= q[0]:
                k = (t - p[0]) / max(1e-9, q[0] - p[0])
                return tuple(p[i] + k * (q[i] - p[i]) for i in (1, 2, 3))
        return a[-1][1:]

    def on_image(self, msg):
        if self.phase != 'releve' or self.stop:
            return
        t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        p = self.pose_a(t)
        if p is None or p[2] < self.alt - 0.5:
            return
        X, Y, Z = p
        h = Z - HAUT_CAM - HAUT_FEUILLES
        largeur_sol = 2 * h * math.tan(FOV / 2)
        s = largeur_sol / LARGEUR_PX                           # m par pixel
        now = self.get_clock().now().nanoseconds * 1e-9
        if now - self.t_traite < 0.2:                         # ≈ 3 analyses par seconde suffisent à 0,9 m/s
            return
        self.t_traite = now
        img = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        self.nb_images += 1
        # analyse sur une image réduite de moitié (13 mm par pixel : un plant fait encore 25 pixels)
        petit = cv2.resize(img, (LARGEUR_PX // 2, HAUTEUR_PX // 2), interpolation=cv2.INTER_AREA)
        det = plants_aerien(petit, s * 2)
        for d in det:
            d['u'] *= 2
            d['v'] *= 2
        cx, cy = LARGEUR_PX / 2, HAUTEUR_PX / 2
        gardes = []
        for d in det:
            if not (50 < d['u'] < LARGEUR_PX - 50 and 40 < d['v'] < HAUTEUR_PX - 40):
                continue                                       # plant coupé par le bord de l'image
            x = X + DEC_CAM_X + (cy - d['v']) * s              # haut de l'image = +x
            y = Y - (d['u'] - cx) * s                          # droite de l'image = -y
            if not dans_champ(x, y, 0.1):
                continue
            d['x'], d['y'] = x, y
            gardes.append(d)
            self.enregistrer(d)
        self.maj_couverture(X + DEC_CAM_X, Y, s)
        # aperçu annoté pour la console (≈ 4 images par seconde)
        now = self.get_clock().now().nanoseconds * 1e-9
        if now - self.t_img_pub > 0.25:
            self.t_img_pub = now
            pc = int(100 * self.couvert.mean())
            vue = annoter_aerien(img, det, s, f'DRONE  |  alt {Z:.1f} m  |  {len(self.plants_confirmes())} plant(s) repérés  |  couverture {pc} %')
            vue = cv2.resize(vue, (480, 360), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode('.jpg', vue, [cv2.IMWRITE_JPEG_QUALITY, 72])
            if ok:
                c = CompressedImage()
                c.header = msg.header
                c.format = 'jpeg'
                c.data = buf.tobytes()
                self.pub_jpg.publish(c)

    def enregistrer(self, d):
        proche = None
        for pl in self.plants:
            if math.hypot(pl['x'] - d['x'], pl['y'] - d['y']) < 0.2:
                proche = pl
                break
        if proche is None:
            self.plants.append({'id': len(self.plants) + 1, 'x': d['x'], 'y': d['y'], 'vues': 1,
                                'classes': {d['classe']: 1}, 'score': d['score'], 'marque': False})
            return
        n = proche['vues']
        proche['x'] = (proche['x'] * n + d['x']) / (n + 1)
        proche['y'] = (proche['y'] * n + d['y']) / (n + 1)
        proche['vues'] = n + 1
        proche['classes'][d['classe']] = proche['classes'].get(d['classe'], 0) + 1
        proche['score'] = max(proche['score'], d['score'])
        if not proche['marque'] and proche['vues'] >= self.get_parameter('vues_min').value:
            proche['marque'] = True
            self.mark.anneau(f"mk_det_{proche['id']}", proche['x'], proche['y'], 'rouge', 0.2)

    def maj_couverture(self, X, Y, s):
        x0, _, y0, _ = CHAMP
        demi_x = (HAUTEUR_PX / 2) * s * 0.9
        demi_y = (LARGEUR_PX / 2) * s * 0.9
        i0 = max(0, int((X - demi_x - x0) / CELLULE)); i1 = min(self.nx, int((X + demi_x - x0) / CELLULE) + 1)
        j0 = max(0, int((Y - demi_y - y0) / CELLULE)); j1 = min(self.ny, int((Y + demi_y - y0) / CELLULE) + 1)
        if i1 > i0 and j1 > j0:
            self.couvert[i0:i1, j0:j1] = True

    # ------------------------------------------------------------------ sorties
    def plants_confirmes(self):
        vmin = self.get_parameter('vues_min').value
        out = []
        for pl in self.plants:
            if pl['vues'] < vmin:
                continue
            classe = max(pl['classes'], key=pl['classes'].get)
            out.append({'id': pl['id'], 'x': round(pl['x'], 3), 'y': round(pl['y'], 3), 'classe': classe,
                        'score': round(pl['score'], 2), 'vues': pl['vues']})
        return out

    def zones(self, plants):
        """Regroupe les plants voisins (< 0.9 m) en zones à traiter."""
        reste = list(plants)
        zones = []
        while reste:
            groupe = [reste.pop()]
            i = 0
            while i < len(groupe):
                g = groupe[i]
                proches = [p for p in reste if math.hypot(p['x'] - g['x'], p['y'] - g['y']) < 0.9]
                for p in proches:
                    reste.remove(p)
                groupe += proches
                i += 1
            cx = sum(p['x'] for p in groupe) / len(groupe)
            cy = sum(p['y'] for p in groupe) / len(groupe)
            r = max(math.hypot(p['x'] - cx, p['y'] - cy) for p in groupe) + 0.25
            zones.append({'id': len(zones) + 1, 'x': round(cx, 2), 'y': round(cy, 2), 'n': len(groupe),
                          'rayon': round(r, 2), 'plants': [p['id'] for p in groupe]})
        zones.sort(key=lambda z: z['x'])
        for k, z in enumerate(zones):
            z['id'] = k + 1
        return zones

    def publier_zones(self, final=False):
        plants = self.plants_confirmes()
        msg = {'source': 'drone', 'termine': bool(final or self.phase in ('atterrissage', 'atterri')),
               'couverture': round(100 * float(self.couvert.mean()), 1), 'plants': plants, 'zones': self.zones(plants)}
        self.pub_zones.publish(String(data=json.dumps(msg)))

    def publier_etat(self):
        if self.pose is None:
            return
        wp_fait = max(0, self.wp_total - len(self.wp)) if self.wp_total else 0
        etat = {'phase': self.phase, 'mode': self.mode, 'x': round(self.pose[0], 2), 'y': round(self.pose[1], 2),
                'alt': round(self.pose[2], 2), 'vitesse': round(float(np.linalg.norm(self.vit)), 2),
                'batterie': round(self.batterie, 1), 'couverture': round(100 * float(self.couvert.mean()), 1),
                'images': self.nb_images, 'wp': wp_fait, 'wp_total': self.wp_total, 'arret': self.stop}
        self.pub_etat.publish(String(data=json.dumps(etat)))


def main():
    rclpy.init()
    n = Drone()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        n.destroy_node()
        rclpy.try_shutdown()
