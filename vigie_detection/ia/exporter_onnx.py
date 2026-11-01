"""Exporte un modèle ResNet18 entraîné (.pt) au format ONNX (lu ensuite par OpenCV dans les nœuds ROS).

Usage : ~/ia/venv/bin/python exporter_onnx.py [poids.pt] [sortie.onnx]
"""
import os
import sys

import torch
import torch.nn as nn
from torchvision import models

poids = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/ia/modele/resnet18_cercospora.pt')
sortie = os.path.expanduser(sys.argv[2] if len(sys.argv) > 2 else '~/ia/modele/modele_cercospora.onnx')
m = models.resnet18(weights=None)
m.fc = nn.Linear(m.fc.in_features, 2)
m.load_state_dict(torch.load(poids, map_location='cpu'))
m.eval()
torch.onnx.export(m, torch.zeros(1, 3, 224, 224), sortie, input_names=['image'], output_names=['logits'],
                  dynamic_axes={'image': {0: 'lot'}, 'logits': {0: 'lot'}}, opset_version=13, dynamo=False)
print('exporté :', sortie, round(os.path.getsize(sortie) / 1e6, 1), 'Mo')
