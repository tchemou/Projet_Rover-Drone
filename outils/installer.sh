#!/bin/bash
# Installation de Vigie Betterave sur Ubuntu 24.04 (WSL2 ou natif) : ROS 2 Jazzy, Gazebo Harmonic, dépendances, compilation.
# Usage : bash installer.sh [dossier_de_travail]   (défaut : ~/turtlebot3_ws ; le dépôt doit être cloné dans <dossier>/src)
set -e
WS="${1:-$HOME/turtlebot3_ws}"
if [ ! -f /opt/ros/jazzy/setup.bash ]; then
  echo "ROS 2 Jazzy absent : voir https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html puis relancer."; exit 1
fi
sudo apt-get update
sudo apt-get install -y ros-jazzy-ros-gz ros-jazzy-rosbridge-suite ros-jazzy-cv-bridge ros-jazzy-turtlebot3-gazebo \
    ros-jazzy-turtlebot3-description python3-opencv python3-tornado python3-colcon-common-extensions
source /opt/ros/jazzy/setup.bash
cd "$WS" && colcon build --symlink-install --packages-select agri_sim vigie_detection
echo
echo "Installé. Étapes suivantes :"
echo " 1. Copier le modèle d'IA :  mkdir -p ~/ia/modele && cp $WS/src/vigie_detection/ia/modele/modele_cercospora_sim.onnx ~/ia/modele/"
echo " 2. Lancer :  VIGIE_WS=$WS bash $WS/src/outils/lancer_vigie.sh   puis ouvrir http://localhost:8420"
echo " 3. Premiers identifiants (créés au premier lancement) : ~/.vigie/identifiants_initiaux.txt"
