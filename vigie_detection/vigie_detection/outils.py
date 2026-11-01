"""Constantes et fonctions communes aux nœuds du projet Vigie Betterave.

Repère « monde » = repère Gazebo. La parcelle P-07 est centrée sur l'origine :
11 rangs le long de x, écartement 0,60 m, un plant tous les 0,40 m.
"""
import math

SPAWN = (-6.9, 0.3)                    # station du rover (monde)
AIRE_DRONE = (-9.2, -2.2)              # aire d'envol du drone (monde)
ROWS = [round(-3.0 + 0.6 * i, 3) for i in range(11)]          # rangs de betteraves (y)
ALLEES = [round(-2.7 + 0.6 * i, 3) for i in range(10)]        # allées entre les rangs (y)
X_BOUT = 6.7                           # tournières (x = ± X_BOUT)
CHAMP = (-6.4, 6.4, -3.35, 3.35)       # x_min, x_max, y_min, y_max de la zone plantée
MONDE = 'default'                      # nom du monde Gazebo

DOSE_PLANT_L = 0.006                   # bouillie par plant traité (6 mL, jet ciblé)
DOSE_PLEIN_CHAMP_L_HA = 200.0          # pulvérisation classique, 200 L/ha
SURFACE_PARCELLE_M2 = 12.8 * 6.7       # zone plantée


def litres_plein_champ():
    return SURFACE_PARCELLE_M2 / 10000.0 * DOSE_PLEIN_CHAMP_L_HA


def yaw_de(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def angle_norm(a):
    return math.atan2(math.sin(a), math.cos(a))


def allee_proche(y):
    return min(ALLEES, key=lambda a: abs(a - y))


def dans_champ(x, y, marge=0.0):
    x0, x1, y0, y1 = CHAMP
    return x0 - marge <= x <= x1 + marge and y0 - marge <= y <= y1 + marge
