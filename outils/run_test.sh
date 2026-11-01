#!/bin/bash
# usage: run_test.sh <mode> <duree_max_s>
source /opt/ros/jazzy/setup.bash
source ~/turtlebot3_ws/install/setup.bash
export TURTLEBOT3_MODEL=waffle
export GALLIUM_DRIVER=d3d12 MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
MODE=${1:-normal}; MAX=${2:-420}
mkdir -p ~/audit && cd ~/audit
pkill -f gz; pkill -f ros2; sleep 2
(ros2 launch agri_sim complet.launch.py gui:=false > run.log 2>&1 &)
sleep 30
ros2 topic pub -t 4 -r 2 /vigie/commande std_msgs/msg/String "{data: 'mode:$MODE'}" > /dev/null
sleep 1
ros2 topic pub -1 /vigie/commande std_msgs/msg/String "{data: 'demarrer'}" > /dev/null
T0=$(date +%s)
while true; do
  sleep 15
  E=$(( $(date +%s) - T0 ))
  python3 - <<PY
import rclpy, json, time
from rclpy.node import Node
from std_msgs.msg import String
rclpy.init(); n=Node('probe'); d={}
for t in ('/vigie/mission','/vigie/drone/etat','/vigie/bilan'):
    n.create_subscription(String,t,lambda m,t=t:d.__setitem__(t,json.loads(m.data)),10)
t=time.time()
while len(d)<3 and time.time()-t<4: rclpy.spin_once(n,timeout_sec=0.3)
m=d.get('/vigie/mission',{}); dr=d.get('/vigie/drone/etat',{})
print(f"[$E s] phase={m.get('phase')} etat='{m.get('etat')}' pose=({m.get('pose',{}).get('x')},{m.get('pose',{}).get('y')}) cibles={len(m.get('cibles',[]))} traites={m.get('traites')} jets={m.get('jets')} dist={m.get('distance')} | drone={dr.get('phase')} alt={dr.get('alt')} cov={dr.get('couverture')}", flush=True)
if m.get('phase')=='termine': print('BILAN', json.dumps(d.get('/vigie/bilan'),ensure_ascii=False))
PY
  if [ $E -gt $MAX ] || grep -q "Mission terminée" run.log; then break; fi
done
sleep 5
python3 - <<PY
import rclpy, json, time
from rclpy.node import Node
from std_msgs.msg import String
rclpy.init(); n=Node('probe2'); d={}
n.create_subscription(String,'/vigie/bilan',lambda m:d.__setitem__('b',json.loads(m.data)),10)
t=time.time()
while 'b' not in d and time.time()-t<4: rclpy.spin_once(n,timeout_sec=0.3)
print('BILAN_FINAL', json.dumps(d.get('b'),ensure_ascii=False,indent=1))
PY
grep -E "Jet|WARN|ERROR|Relevé|Traitement|Mission|confirm" run.log | tail -40
pkill -f gz; pkill -f ros2; pkill -f parameter_bridge; pkill -f robot_state; true
