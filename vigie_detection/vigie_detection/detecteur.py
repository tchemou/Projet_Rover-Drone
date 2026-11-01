"""Nœud ROS 2 : détection de la cercosporiose sur l'image de la caméra du rover.

La caméra donne la direction des plants atteints, le LiDAR leur distance (fusion caméra + LiDAR).

Abonnements : /camera/image_raw, /scan, /odom
Publications : /vigie/rover/vue                  (std_msgs/String, JSON : détections de l'image courante)
               /vigie/rover/image/compressed     (sensor_msgs/CompressedImage, image annotée)
"""
import json
import math
import time

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image, LaserScan
from std_msgs.msg import String

from .analyse import plants_rover
from .outils import yaw_de

LARGEUR_PX = 640
FOCALE_PX = (LARGEUR_PX / 2) / math.tan(1.02974 / 2)     # caméra du Waffle : champ horizontal 1,03 rad
DEC_CAMERA = 0.069                                       # la caméra est 7 cm devant le centre du rover


class Detecteur(Node):
    def __init__(self):
        super().__init__('detecteur_cercosporiose')
        self.declare_parameter('frequence', 5.0)
        self.declare_parameter('portee_max', 3.5)
        self.bridge = CvBridge()
        self.pose = None
        self.scan = None
        self.t_last = 0.0
        self.t_jpg = 0.0
        self.create_subscription(Image, '/camera/image_raw', self.on_image, qos_profile_sensor_data)
        self.create_subscription(LaserScan, '/scan', lambda m: setattr(self, 'scan', m), qos_profile_sensor_data)
        self.create_subscription(Odometry, '/rover/gnss', self.on_odom, 10)
        self.pub_vue = self.create_publisher(String, '/vigie/rover/vue', 10)
        self.pub_jpg = self.create_publisher(CompressedImage, '/vigie/rover/image/compressed', 5)
        self.get_logger().info('Détecteur du rover prêt (caméra + LiDAR)')

    def on_odom(self, m):
        p = m.pose.pose.position
        self.pose = (p.x, p.y, yaw_de(m.pose.pose.orientation))

    def distance(self, ang):
        """Distance LiDAR dans la direction `ang` (rad, positif à gauche), médiane sur ±2°."""
        s = self.scan
        if s is None:
            return None
        a = ang % (2 * math.pi)
        i0 = int(round((a - s.angle_min) / s.angle_increment))
        n = len(s.ranges)
        k = max(1, int(math.radians(2) / s.angle_increment))
        vals = [s.ranges[(i0 + j) % n] for j in range(-k, k + 1)]
        vals = [r for r in vals if s.range_min < r < min(s.range_max, self.get_parameter('portee_max').value)]
        return float(np.median(vals)) if vals else None

    def on_image(self, msg):
        now = time.monotonic()
        if now - self.t_last < 1.0 / self.get_parameter('frequence').value or self.pose is None:
            return
        self.t_last = now
        img = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        x0, y0, yaw = self.pose
        dets = []
        for d in plants_rover(img):
            ang = math.atan((LARGEUR_PX / 2 - d['u']) / FOCALE_PX)
            ang0 = math.atan((LARGEUR_PX / 2 - d['u1']) / FOCALE_PX)
            ang1 = math.atan((LARGEUR_PX / 2 - d['u0']) / FOCALE_PX)
            r = self.distance(ang)
            out = {'ang': round(ang, 4), 'ang0': round(ang0, 4), 'ang1': round(ang1, 4),
                   'score': round(d['score'], 2), 'classe': 'malade'}
            if r is not None:
                cx, cy = x0 + DEC_CAMERA * math.cos(yaw), y0 + DEC_CAMERA * math.sin(yaw)
                out.update(x=round(cx + (r + 0.05) * math.cos(yaw + ang), 3),
                           y=round(cy + (r + 0.05) * math.sin(yaw + ang), 3), r=round(r, 2))
            dets.append((d, out))
        self.pub_vue.publish(String(data=json.dumps({'pose': [round(x0, 3), round(y0, 3), round(yaw, 3)],
                                                     'dets': [o for _, o in dets]})))
        if now - self.t_jpg > 0.25:
            self.t_jpg = now
            vue = img.copy()
            for d, o in dets:
                top = int(d['v'] - d['h'] / 2)
                cv2.rectangle(vue, (d['u0'], top), (d['u1'], int(d['v'] + d['h'] / 2)), (40, 40, 230), 2)
                txt = f"cercosporiose {o['score']:.2f}" + (f" - {o['r']:.1f} m" if 'r' in o else '')
                cv2.putText(vue, txt, (d['u0'], max(14, top - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 3, cv2.LINE_AA)
                cv2.putText(vue, txt, (d['u0'], max(14, top - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 40, 230), 1, cv2.LINE_AA)
            cv2.rectangle(vue, (0, 0), (vue.shape[1], 24), (95, 36, 163), -1)
            cv2.putText(vue, f'ROVER R1  |  {len(dets)} amas suspect(s)', (8, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            vue = cv2.resize(vue, (480, 270), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode('.jpg', vue, [cv2.IMWRITE_JPEG_QUALITY, 72])
            if ok:
                c = CompressedImage()
                c.header = msg.header
                c.format = 'jpeg'
                c.data = buf.tobytes()
                self.pub_jpg.publish(c)


def main():
    rclpy.init()
    n = Detecteur()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        n.destroy_node()
        rclpy.try_shutdown()
