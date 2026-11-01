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
