"""Nœud ROS 2 : conditions du milieu (température, humidité) et indicateur de risque cercosporiose.

La station météo embarquée est simulée : une journée chaude et humide, favorable à la maladie,
ou une journée sèche. Le scénario se change par la commande « meteo:favorable » / « meteo:sec ».

Indicateur de risque (provisoire, à valider avec l'ITB) :
    f_T = 1 entre 27 et 32 °C, décroît linéairement jusqu'à 0 à 15 °C et à 40 °C
    f_H = 0 sous 60 % d'humidité de l'air, 1 à partir de 90 %
    risque = 100 · f_T · f_H
"""
import json
import math
import random

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

SCENARIOS = {
    'favorable': dict(t=29.0, hr=86.0, hs=64.0),
    'sec': dict(t=22.0, hr=52.0, hs=33.0),
}


def facteur_temperature(t):
    if 27 <= t <= 32:
        return 1.0
    if t < 27:
        return max(0.0, (t - 15) / 12)
    return max(0.0, (40 - t) / 8)


def facteur_humidite(hr):
    return min(1.0, max(0.0, (hr - 60) / 30))


def risque(t, hr):
    return 100.0 * facteur_temperature(t) * facteur_humidite(hr)


def niveau(r):
    return 'élevé' if r >= 66 else 'modéré' if r >= 33 else 'faible'


class Meteo(Node):
    def __init__(self):
        super().__init__('station_meteo')
        self.declare_parameter('scenario', 'favorable')
        self.sc = SCENARIOS[self.get_parameter('scenario').value]
        self.t, self.hr, self.hs = self.sc['t'], self.sc['hr'], self.sc['hs']
        self.t0 = self.get_clock().now().nanoseconds * 1e-9
        self.hist = []
        self.pub = self.create_publisher(String, '/vigie/meteo', 10)
        self.create_subscription(String, '/vigie/commande', self.on_commande, 10)
        self.create_timer(0.5, self.tick)
        self.get_logger().info('Station météo simulée prête')

    def on_commande(self, m):
        c = m.data.strip().lower()
        if c.startswith('meteo:') and c[6:] in SCENARIOS:
            self.sc = SCENARIOS[c[6:]]
            self.get_logger().info(f'Scénario météo : {c[6:]}')

    def tick(self):
        now = self.get_clock().now().nanoseconds * 1e-9 - self.t0
        k = 0.06                                              # relaxation vers le scénario
        derive_t = 0.9 * math.sin(2 * math.pi * now / 240.0)
        derive_h = 2.5 * math.sin(2 * math.pi * now / 170.0 + 1.0)
        self.t += k * (self.sc['t'] + derive_t - self.t)
        self.hr += k * (self.sc['hr'] + derive_h - self.hr)
        self.hs += 0.02 * (self.sc['hs'] - self.hs)
        t_mes = self.t + random.gauss(0, 0.08)
        hr_mes = min(100.0, self.hr + random.gauss(0, 0.4))
        hs_mes = self.hs + random.gauss(0, 0.2)
        r = risque(t_mes, hr_mes)
        self.hist.append(r)
        self.hist = self.hist[-40:]
        tend = r - self.hist[0] if len(self.hist) > 10 else 0.0
        msg = {'t_air': round(t_mes, 1), 'hr_air': round(hr_mes, 1), 'hr_sol': round(hs_mes, 1),
               't_sol': round(t_mes - 2.5, 1), 'risque': round(r, 1), 'niveau': niveau(r),
               'tendance': 'hausse' if tend > 3 else 'baisse' if tend < -3 else 'stable',
               'favorable': bool(27 <= t_mes <= 32 and hr_mes >= 85)}
        self.pub.publish(String(data=json.dumps(msg)))


def main():
    rclpy.init()
    n = Meteo()
    try:
        rclpy.spin(n)
    except KeyboardInterrupt:
        pass
    finally:
        n.destroy_node()
        rclpy.try_shutdown()
