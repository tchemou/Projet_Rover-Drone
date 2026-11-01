"""Entraîne un classifieur « feuille saine / cercosporiose » sur le jeu public PSNC (betterave).

Réseau   : ResNet18 pré-entraîné ImageNet (apprentissage par transfert), 2 classes.
Découpage: 70 % apprentissage / 15 % validation / 15 % test, tirage stratifié à graine fixe.
           Le jeu de test n'est utilisé qu'une fois, à la fin, avec le modèle retenu sur la validation.
Mesures  : exactitude brute, exactitude ÉQUILIBRÉE (indispensable : 80 % des images sont malades),
           rappel et précision par classe, F1, matrice de confusion, comparaison à la ligne de base
           « toujours malade ».
Sorties  : modele/modele_cercospora.onnx (lu ensuite par OpenCV dans les nœuds ROS), modele/metriques.json.

Usage : ~/ia/venv/bin/python entrainer.py [--epoques 14] [--donnees ~/ia/donnees/beet] [--sortie ~/ia/modele]
"""
import argparse
import json
import os
import random
import time

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

CLASSES = ['unaffected', 'cercospora']              # 0 = saine, 1 = atteinte
MOYENNE, ECART = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]


def lister(dossier):
    out = []
    for k, c in enumerate(CLASSES):
        d = os.path.join(dossier, c)
        out += [(os.path.join(d, f), k) for f in sorted(os.listdir(d)) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    return out


def decouper(items, graine=7):
    rnd = random.Random(graine)
    parts = {'train': [], 'val': [], 'test': []}
    for k in range(len(CLASSES)):
        cl = [it for it in items if it[1] == k]
        rnd.shuffle(cl)
        n = len(cl)
        a, b = int(.70 * n), int(.85 * n)
        parts['train'] += cl[:a]; parts['val'] += cl[a:b]; parts['test'] += cl[b:]
    return parts


class Jeu(Dataset):
    def __init__(self, items, entrainement, taille=224):
        self.items = items
        self.cache = [Image.open(p).convert('RGB').resize((256, 256), Image.BILINEAR) for p, _ in items]
        if entrainement:
            self.tf = transforms.Compose([
                transforms.RandomResizedCrop(taille, scale=(.45, 1.0), ratio=(.8, 1.25)),
                transforms.RandomHorizontalFlip(), transforms.RandomVerticalFlip(),
                transforms.RandomApply([transforms.ColorJitter(.18, .18, .12, .02)], p=.6),
                transforms.ToTensor(), transforms.Normalize(MOYENNE, ECART)])
        else:
            self.tf = transforms.Compose([transforms.Resize(taille), transforms.CenterCrop(taille), transforms.ToTensor(), transforms.Normalize(MOYENNE, ECART)])

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.tf(self.cache[i]), self.items[i][1]


def evaluer(modele, charge, dev):
    modele.eval()
    ys, ps = [], []
    with torch.no_grad():
        for x, y in charge:
            ps += modele(x.to(dev)).argmax(1).cpu().tolist(); ys += y.tolist()
    return np.array(ys), np.array(ps)


def metriques(y, p):
    m = np.zeros((2, 2), int)
    for a, b in zip(y, p):
        m[a][b] += 1
    rec = [m[k][k] / max(1, m[k].sum()) for k in range(2)]
    pre = [m[k][k] / max(1, m[:, k].sum()) for k in range(2)]
    f1 = [2 * p_ * r_ / max(1e-9, p_ + r_) for p_, r_ in zip(pre, rec)]
    return {'exactitude': round(float((y == p).mean()) * 100, 1), 'exactitude_equilibree': round(float(np.mean(rec)) * 100, 1),
            'rappel': {CLASSES[k]: round(rec[k] * 100, 1) for k in range(2)}, 'precision': {CLASSES[k]: round(pre[k] * 100, 1) for k in range(2)},
            'f1': {CLASSES[k]: round(f1[k] * 100, 1) for k in range(2)}, 'matrice_confusion': m.tolist(),
            'ligne_de_base_toujours_malade': round(float((y == 1).mean()) * 100, 1), 'n': int(len(y))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--donnees', default='~/ia/donnees/beet')
    ap.add_argument('--sortie', default='~/ia/modele')
    ap.add_argument('--epoques', type=int, default=14)
    a = ap.parse_args()
    donnees, sortie = os.path.expanduser(a.donnees), os.path.expanduser(a.sortie)
    os.makedirs(sortie, exist_ok=True)
    torch.manual_seed(7); np.random.seed(7); random.seed(7)
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    parts = decouper(lister(donnees))
    print({k: (len(v), sum(1 for _, c in v if c == 1)) for k, v in parts.items()}, '(images, dont malades) · appareil :', dev, flush=True)
    jeux = {k: Jeu(v, k == 'train') for k, v in parts.items()}
    n1 = sum(1 for _, c in parts['train'] if c == 1); n0 = len(parts['train']) - n1
    poids = [1 / n0 if c == 0 else 1 / n1 for _, c in parts['train']]
    ech = torch.utils.data.WeightedRandomSampler(poids, num_samples=len(poids), replacement=True)     # classes équilibrées à chaque époque
    ch_train = DataLoader(jeux['train'], batch_size=32, sampler=ech, num_workers=2)
    ch_val, ch_test = DataLoader(jeux['val'], batch_size=64), DataLoader(jeux['test'], batch_size=64)

    modele = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
    modele.fc = nn.Linear(modele.fc.in_features, 2)
    modele = modele.to(dev)
    opt = torch.optim.AdamW(modele.parameters(), lr=3e-4, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=6e-4, total_steps=a.epoques * len(ch_train))
    perte = nn.CrossEntropyLoss(label_smoothing=0.05)
    meilleur, etat, hist = -1, None, []
    for ep in range(a.epoques):
        modele.train(); t0 = time.time(); somme = 0
        for x, y in ch_train:
            x, y = x.to(dev), y.to(dev)
            opt.zero_grad(); l = perte(modele(x), y); l.backward(); opt.step(); sched.step(); somme += l.item() * len(y)
        mv = metriques(*evaluer(modele, ch_val, dev))
        hist.append({'epoque': ep + 1, 'perte': round(somme / len(ch_train.dataset), 4), 'val_exactitude_equilibree': mv['exactitude_equilibree']})
        print(f"époque {ep + 1:2d}/{a.epoques}  perte {hist[-1]['perte']:.3f}  validation : exactitude équilibrée {mv['exactitude_equilibree']} %  ({time.time() - t0:.0f} s)", flush=True)
        if mv['exactitude_equilibree'] >= meilleur:
            meilleur, etat = mv['exactitude_equilibree'], {k: v.detach().cpu().clone() for k, v in modele.state_dict().items()}
    modele.load_state_dict(etat)
    res = {'test': metriques(*evaluer(modele, ch_test, dev)), 'validation': metriques(*evaluer(modele, ch_val, dev)), 'historique': hist,
           'jeu': 'PSNC / WODR, Zenodo 10.5281/zenodo.15873360, CC-BY-4.0', 'reseau': 'ResNet18 (ImageNet) affiné', 'decoupage': {k: len(v) for k, v in parts.items()}}
    json.dump(res, open(os.path.join(sortie, 'metriques.json'), 'w'), ensure_ascii=False, indent=1)
    torch.save(etat, os.path.join(sortie, 'resnet18_cercospora.pt'))
    modele.eval().cpu()
    torch.onnx.export(modele, torch.zeros(1, 3, 224, 224), os.path.join(sortie, 'modele_cercospora.onnx'), input_names=['image'], output_names=['logits'],
                      dynamic_axes={'image': {0: 'lot'}, 'logits': {0: 'lot'}}, opset_version=13)
    t = res['test']
    print('\n=== TEST (jamais vu à l’entraînement) ===')
    print(f"exactitude brute {t['exactitude']} %  ·  exactitude ÉQUILIBRÉE {t['exactitude_equilibree']} %  (ligne de base « toujours malade » : {t['ligne_de_base_toujours_malade']} %)")
    print('rappel   :', t['rappel'], '\nprécision:', t['precision'], '\nmatrice de confusion [ligne = réel, colonne = prédit] :', t['matrice_confusion'])


if __name__ == '__main__':
    main()
