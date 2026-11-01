"""Mesure l'écart « vraies photos / images de simulation » du modèle, puis l'adapte à la simulation.

1. Évalue le modèle entraîné sur le jeu public (ResNet18) sur des recadrages de plants issus de la simulation,
   sans aucune adaptation (« zéro-tir ») : c'est l'écart de domaine.
2. Affine le modèle sur un mélange de vraies photos et de recadrages simulés, puis le réévalue :
   - sur le jeu de test public (il ne doit pas se dégrader),
   - sur des plants simulés tenus à l'écart de l'affinage (découpage PAR PLANT, jamais par recadrage).
   Attention : la simulation n'a que 6 modèles de plants (sain, début, malade × 2 formes) : le test sur plants simulés
   est donc bien plus facile qu'un test sur de vraies feuilles ; seul le test public est représentatif.
3. Exporte le modèle adapté : ~/ia/modele/modele_cercospora_sim.onnx

Classes : 0 = plant sain, 1 = plant atteint (« debut » et « malade » regroupés).
Usage : ~/ia/venv/bin/python affiner_sim.py [--sim ~/ia/donnees/sim] [--epoques 8]
"""
import argparse
import json
import os
import random
import re
import sys

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import ConcatDataset, DataLoader, Dataset
from torchvision import models, transforms

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from entrainer import ECART, MOYENNE, Jeu, decouper, evaluer, lister, metriques   # noqa: E402


class JeuSim(Dataset):
    def __init__(self, items, entrainement, taille=224):
        self.items = items
        self.cache = [Image.open(p).convert('RGB').resize((taille, taille), Image.BILINEAR) for p, _ in items]
        base = [transforms.RandomHorizontalFlip(), transforms.RandomVerticalFlip(), transforms.RandomApply([transforms.ColorJitter(.12, .12, .08, .01)], p=.5),
                transforms.RandomAffine(15, translate=(.06, .06), scale=(.9, 1.1))] if entrainement else []
        self.tf = transforms.Compose(base + [transforms.ToTensor(), transforms.Normalize(MOYENNE, ECART)])

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.tf(self.cache[i]), self.items[i][1]


def lister_sim(dossier):
    """(chemin, étiquette, nom du plant) ; étiquette 1 pour « debut » et « malade »."""
    out = []
    for classe, k in (('saine', 0), ('debut', 1), ('malade', 1)):
        d = os.path.join(dossier, classe)
        if os.path.isdir(d):
            out += [(os.path.join(d, f), k, re.split(r'__v', f)[0], classe) for f in sorted(os.listdir(d)) if f.endswith('.png')]
    return out


def decouper_par_plant(items, graine=5):
    plants = sorted({(n, c) for _, _, n, c in items})
    rnd = random.Random(graine)
    test = set()
    for classe in ('saine', 'debut', 'malade'):
        noms = [n for n, c in plants if c == classe]
        rnd.shuffle(noms)
        test |= set(noms[:max(2, int(.3 * len(noms)))])
    return [it for it in items if it[2] not in test], [it for it in items if it[2] in test]


def charger(poids, dev):
    m = models.resnet18(weights=None)
    m.fc = nn.Linear(m.fc.in_features, 2)
    m.load_state_dict(torch.load(poids, map_location='cpu'))
    return m.to(dev)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim', default='~/ia/donnees/sim')
    ap.add_argument('--donnees', default='~/ia/donnees/beet')
    ap.add_argument('--modele', default='~/ia/modele')
    ap.add_argument('--epoques', type=int, default=8)
    a = ap.parse_args()
    sim, donnees, mod = (os.path.expanduser(x) for x in (a.sim, a.donnees, a.modele))
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    torch.manual_seed(5); random.seed(5); np.random.seed(5)
    reel = decouper(lister(donnees))
    tous = lister_sim(sim)
    app, test_sim = decouper_par_plant(tous)
    print(f'crops simulés : {len(tous)} (apprentissage {len(app)}, test sur plants à l’écart {len(test_sim)})', flush=True)
    ch_test_reel = DataLoader(Jeu(reel['test'], False), batch_size=64)
    ch_test_sim = DataLoader(JeuSim([(p, k) for p, k, _, _ in test_sim], False), batch_size=64)
    res = {}

    m0 = charger(os.path.join(mod, 'resnet18_cercospora.pt'), dev)
    res['zero_tir_sur_sim'] = metriques(*evaluer(m0, ch_test_sim, dev))
    tout_sim = DataLoader(JeuSim([(p, k) for p, k, _, _ in tous], False), batch_size=64)
    res['zero_tir_sur_tous_les_crops_sim'] = metriques(*evaluer(m0, tout_sim, dev))
    print('ZÉRO-TIR (modèle des vraies photos, sans adaptation) sur la simulation :')
    z = res['zero_tir_sur_tous_les_crops_sim']
    print(f"  exactitude {z['exactitude']} % · équilibrée {z['exactitude_equilibree']} % · rappel {z['rappel']}", flush=True)

    # affinage : vraies photos (60 %) + crops simulés équilibrés
    d_reel = Jeu(reel['train'], True)
    sim_sain = [it for it in app if it[1] == 0]
    sim_mal = [it for it in app if it[1] == 1]
    n = min(len(sim_sain), len(sim_mal))
    random.Random(1).shuffle(sim_sain); random.Random(2).shuffle(sim_mal)
    d_sim = JeuSim([(p, k) for p, k, _, _ in (sim_sain[:n] + sim_mal[:n])], True)
    ch = DataLoader(ConcatDataset([d_reel, d_sim]), batch_size=32, shuffle=True, num_workers=2)
    m = charger(os.path.join(mod, 'resnet18_cercospora.pt'), dev)
    opt = torch.optim.AdamW(m.parameters(), lr=1e-4, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2e-4, total_steps=a.epoques * len(ch))
    perte = nn.CrossEntropyLoss(label_smoothing=0.05)
    for ep in range(a.epoques):
        m.train()
        for x, y in ch:
            x, y = x.to(dev), y.to(dev)
            opt.zero_grad(); perte(m(x), y).backward(); opt.step(); sched.step()
        r = metriques(*evaluer(m, ch_test_reel, dev))
        print(f'époque {ep + 1}/{a.epoques} · test public : équilibrée {r["exactitude_equilibree"]} %', flush=True)
    m.eval()
    res['affine_sur_test_public'] = metriques(*evaluer(m, ch_test_reel, dev))
    res['affine_sur_plants_sim_ecartes'] = metriques(*evaluer(m, ch_test_sim, dev))
    # rappel par classe de plant simulé (début d'infection / malade) sur les plants écartés
    par = {}
    for classe in ('saine', 'debut', 'malade'):
        its = [(p, k) for p, k, _, c in test_sim if c == classe]
        if its:
            y, p = evaluer(m, DataLoader(JeuSim(its, False), batch_size=64), dev)
            par[classe] = round(float((p == y).mean()) * 100, 1)
    res['affine_exactitude_par_classe_sim'] = par
    json.dump(res, open(os.path.join(mod, 'metriques_sim.json'), 'w'), ensure_ascii=False, indent=1)
    torch.save({k: v.detach().cpu() for k, v in m.state_dict().items()}, os.path.join(mod, 'resnet18_cercospora_sim.pt'))
    print('\n=== APRÈS ADAPTATION ===')
    for k in ('affine_sur_test_public', 'affine_sur_plants_sim_ecartes'):
        t = res[k]
        print(f"{k}: exactitude {t['exactitude']} % · équilibrée {t['exactitude_equilibree']} % · rappel {t['rappel']}")
    print('exactitude par classe de plant simulé écarté :', par)


if __name__ == '__main__':
    main()
