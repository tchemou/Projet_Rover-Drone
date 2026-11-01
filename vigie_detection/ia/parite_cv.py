import os, sys, json, numpy as np, cv2
sys.path.insert(0, os.path.expanduser('~/turtlebot3_ws/src/vigie_detection'))
from vigie_detection.classifieur import Classifieur
d = json.load(open('/tmp/parite.json'))
clf = Classifieur(os.path.expanduser('~/ia/modele/modele_cercospora.onnx'))
p = clf.probabilites([cv2.imread(f) for f in d['fichiers']])
e = np.abs(p - np.array(d['p']))
print('écart maximal entre PyTorch et OpenCV (40 images) :', round(float(e.max()), 4), '· écart moyen', round(float(e.mean()), 4))
print('décisions identiques :', int(((p > .5) == (np.array(d['p']) > .5)).sum()), '/ 40')
