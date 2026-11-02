@echo off
rem Lance la simulation complete (Gazebo + drone + rover + noeuds + passerelle securisee) dans WSL,
rem puis ouvre la console dans le navigateur. Connexion obligatoire. Pour fermer : fermer cette fenetre.
title Vigie Betterave - simulation
echo.
echo  Vigie Betterave : demarrage de la simulation (environ 40 secondes)...
echo  La console s'ouvrira sur http://localhost:8420 - connexion obligatoire.
echo  Premiere connexion : identifiants dans
echo  \\wsl.localhost\Ubuntu\home\pagnol\.vigie\identifiants_initiaux.txt
echo.
start "" /min cmd /c "timeout /t 45 /nobreak >nul & start "" http://localhost:8420"
wsl -d Ubuntu --cd "~" -- bash lancer_vigie.sh
echo.
echo  La simulation s'est arretee.
pause
