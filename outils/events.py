import rclpy, json, time
from rclpy.node import Node
from std_msgs.msg import String
rclpy.init(); n=Node('evenements'); st={}
pub=n.create_publisher(String,'/vigie/commande',10); hb=n.create_publisher(String,'/vigie/heartbeat',10)
n.create_subscription(String,'/vigie/mission',lambda m:st.__setitem__('m',json.loads(m.data)),10)
n.create_subscription(String,'/vigie/bilan',lambda m:st.__setitem__('b',json.loads(m.data)),10)
def wait(cond,timeout=60):
    t=time.time()
    while time.time()-t<timeout:
        rclpy.spin_once(n,timeout_sec=0.1)
        if cond(): return True
    return False
def cmd(c): pub.publish(String(data=c)); rclpy.spin_once(n,timeout_sec=0.05)
def log(s): print('EVT',s,flush=True)
wait(lambda:st.get('m',{}).get('jets',0)>=2,400)
# 1. arret d'urgence en mouvement
wait(lambda:abs(st['m'].get('vitesse',0))>0.2,60)
log('arret urgence a v=%s'%st['m']['vitesse']); cmd('arret_urgence'); cmd('arret_urgence')
wait(lambda:st.get('b',{}).get('arret_s') is not None,10); wait(lambda:False,2)
log('arret_s=%s etat=%s cause=%s'%(st['b'].get('arret_s'),st['m']['etat'],st['m']['arret_cause']))
cmd('rearmer'); wait(lambda:False,1); cmd('reprendre'); wait(lambda:False,1); log('reprise: etat=%s'%st['m']['etat'])
# 2. obstacle sur l'axe
wait(lambda:abs(st['m'].get('vitesse',0))>0.2,60)
cmd('obstacle:poser'); log('obstacle pose')
wait(lambda:st['m'].get('obstacle'),30); log('obstacle detecte=%s dist=%s etat=%s'%(st['m'].get('obstacle'),st['m'].get('dist_obstacle'),st['m']['etat']))
wait(lambda:False,5); log('apres 5 s: v=%s'%st['m']['vitesse'])
cmd('obstacle:retirer'); wait(lambda:not st['m'].get('obstacle'),20); wait(lambda:False,3); log('obstacle retire: v=%s etat=%s'%(st['m']['vitesse'],st['m']['etat']))
# 3. perte de liaison : battements puis silence
for _ in range(10): hb.publish(String(data='ok')); wait(lambda:False,0.2)
wait(lambda:abs(st['m'].get('vitesse',0))>0.2,60)
log('coupure liaison a v=%s'%st['m']['vitesse'])
wait(lambda:st['m'].get('arret_cause')=='liaison',8); wait(lambda:False,2)
log('liaison: cause=%s v=%s etat=%s'%(st['m'].get('arret_cause'),st['m']['vitesse'],st['m']['etat']))
for _ in range(10): hb.publish(String(data='ok')); wait(lambda:False,0.2)
cmd('rearmer'); wait(lambda:False,0.5); cmd('reprendre')
for _ in range(2000): hb.publish(String(data='ok')); wait(lambda:False,0.3)
