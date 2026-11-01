import os, random, json, numpy as np, torch, torch.nn as nn
from PIL import Image
from torchvision import models
m = models.resnet18(weights=None); m.fc = nn.Linear(m.fc.in_features, 2); m.load_state_dict(torch.load(os.path.expanduser('~/ia/modele/resnet18_cercospora.pt'), map_location='cpu')); m.eval()
d = os.path.expanduser('~/ia/donnees/beet'); fs = []
for c in ('cercospora', 'unaffected'): fs += [os.path.join(d, c, f) for f in sorted(os.listdir(os.path.join(d, c)))]
random.Random(3).shuffle(fs); fs = fs[:40]
moy = np.array([0.485, 0.456, 0.406], np.float32); ec = np.array([0.229, 0.224, 0.225], np.float32)
x = np.stack([((np.asarray(Image.open(f).convert('RGB').resize((224, 224), Image.BILINEAR), np.float32) / 255 - moy) / ec).transpose(2, 0, 1) for f in fs])
with torch.no_grad(): p = torch.softmax(m(torch.from_numpy(x)), 1)[:, 1].numpy().tolist()
json.dump({'fichiers': fs, 'p': p}, open('/tmp/parite.json', 'w'))
print('PyTorch : ok')
