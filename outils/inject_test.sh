#!/bin/bash
ulimit -c 0   # pas de copie mémoire (core dump) : elles remplissaient le disque Windows
source /opt/ros/jazzy/setup.bash
source ~/turtlebot3_ws/install/setup.bash
export TURTLEBOT3_MODEL=waffle
MAX=${1:-400}
cd ~/audit; pkill -9 -f "[g]z sim"; pkill -f "[r]os2 "; sleep 2
(ros2 launch agri_sim complet.launch.py gui:=false noeuds:=false > inj.log 2>&1 &)
sleep 26
(ros2 run vigie_detection detecteur > inj_det.log 2>&1 &)
(ros2 run vigie_detection meteo > /dev/null 2>&1 &)
(ros2 run vigie_detection mission > inj_mis.log 2>&1 &)
(ros2 run vigie_detection bilan > inj_bil.log 2>&1 &)
sleep 6
cat > ~/audit/inject.py <<'PY'
import rclpy, json, re, random, time
from rclpy.node import Node
from std_msgs.msg import String
txt=open('/home/pagnol/turtlebot3_ws/src/agri_sim/worlds/champ_realiste.sdf').read()
V=[(m.group(1),float(m.group(3)),float(m.group(4))) for m in re.finditer(r"model://betterave_(saine|debut|malade)_\w</uri><name>(\w+)</name><pose>([-\d.]+) ([-\d.]+)",txt)]
random.seed(1)
pl=[{'id':i+1,'x':round(x+random.gauss(0,0.03),3),'y':round(y+random.gauss(0,0.03),3),'classe':'malade','score':0.97,'vues':20} for i,(c,x,y) in enumerate([v for v in V if v[0]=='malade'])]
rclpy.init(); n=Node('injecteur')
pz=n.create_publisher(String,'/vigie/drone/zones',10); pe=n.create_publisher(String,'/vigie/drone/etat',10)
def tick():
    pz.publish(String(data=json.dumps({'termine':True,'couverture':100,'plants':pl,'zones':[]})))
    pe.publish(String(data=json.dumps({'phase':'atterri','couverture':100,'alt':0.2})))
n.create_timer(1.0,tick); rclpy.spin(n)
PY
(python3 ~/audit/inject.py > /dev/null 2>&1 &)
(python3 ~/audit/events.py > ~/audit/events.log 2>&1 &)
sleep 3
ros2 topic pub -1 /vigie/commande std_msgs/msg/String "{data: 'demarrer'}" > /dev/null
T0=$(date +%s)
while true; do
  sleep 12; E=$(( $(date +%s) - T0 ))
  python3 - <<PY
import rclpy, json, time
from rclpy.node import Node
from std_msgs.msg import String
rclpy.init(); n=Node('probe'); d={}
n.create_subscription(String,'/vigie/mission',lambda m:d.__setitem__('m',json.loads(m.data)),10)
t=time.time()
while 'm' not in d and time.time()-t<4: rclpy.spin_once(n,timeout_sec=0.3)
m=d.get('m',{})
print(f"[$E s] {m.get('phase')} | {m.get('etat')} | pose={m.get('pose')} v={m.get('vitesse')} obst={m.get('dist_obstacle')} traites={m.get('traites')}/{len(m.get('cibles',[]))} jets={m.get('jets')} av_valider={m.get('a_valider')} route0={m.get('route',[None])[:1]}", flush=True)
PY
  if [ $E -gt $MAX ] || grep -q "Mission terminée" inj_mis.log; then break; fi
done
python3 - <<PY
import rclpy, json, time
from rclpy.node import Node
from std_msgs.msg import String
rclpy.init(); n=Node('probe2'); d={}
n.create_subscription(String,'/vigie/bilan',lambda m:d.__setitem__('b',json.loads(m.data)),10)
t=time.time()
while 'b' not in d and time.time()-t<4: rclpy.spin_once(n,timeout_sec=0.3)
print('BILAN', json.dumps(d.get('b'),ensure_ascii=False))
PY
echo '--- EVENEMENTS'; cat ~/audit/events.log
grep -vE "Jet sur" inj_mis.log | tail -25 | cut -c1-250
pkill -9 -f "[g]z sim"; pkill -f "[r]os2 "; pkill -f inject.py; pkill -f events.py; pkill -f parameter_bridge; pkill -f robot_state; pkill -f vigie_detection; true
