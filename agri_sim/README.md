# agri_sim

Exploitation de betteraves sucrières pour Gazebo Harmonic (ROS 2 Jazzy).

- Parcelle P-07 : 11 rangs de 12 m sur buttes, écartement 0,60 m, un plant tous les 0,40 m, tournières
- 4 foyers de cercosporiose : plants sains, en début d'infection et malades
- Prairie, chemin empierré, haie, arbres, hangar, aire du drone, station de base du rover

    export TURTLEBOT3_MODEL=waffle   # waffle = caméra
    ros2 launch agri_sim champ_realiste.launch.py

Les maillages et textures sont générés par `generate.py` (python3 + numpy + pillow).
