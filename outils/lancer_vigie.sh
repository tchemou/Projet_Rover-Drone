#!/bin/bash
# Lance la simulation complete Vigie Betterave (Gazebo + drone + rover + noeuds + passerelle web).
# Les motifs [g]z evitent que pkill ne tue ce script lui-meme.
pkill -f "[g]z sim" 2>/dev/null; pkill -f "[r]os2 launch" 2>/dev/null; pkill -f "[p]arameter_bridge" 2>/dev/null
pkill -f "[v]igie_detection" 2>/dev/null; pkill -f "[r]osbridge" 2>/dev/null; pkill -f "[r]obot_state_publisher" 2>/dev/null
sleep 2
source /opt/ros/jazzy/setup.bash
source ~/turtlebot3_ws/install/setup.bash
export TURTLEBOT3_MODEL=waffle
export GALLIUM_DRIVER=d3d12 MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
echo "Demarrage de la simulation... console : http://localhost:8420 (connexion obligatoire)"
if [ -f ~/.vigie/identifiants_initiaux.txt ] && grep -q "Changement obligatoire" ~/.vigie/identifiants_initiaux.txt; then echo "Premiere connexion : identifiants dans \\wsl.localhost\Ubuntu$HOME/.vigie/identifiants_initiaux.txt"; fi
exec ros2 launch agri_sim complet.launch.py
