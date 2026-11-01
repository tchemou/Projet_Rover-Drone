"""Démonstration Vigie Betterave : passerelle web (rosbridge) + détecteur + mission en attente.

Argument : dossier_debug:=<dossier>  (images de contrôle de la caméra ; vide = désactivé)
Par défaut, sous WSL, le dossier Téléchargements\\vigie_captures de Windows est utilisé s'il existe.
"""
import glob
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def dossier_par_defaut():
    dl = glob.glob('/mnt/c/Users/*/Downloads/vigie_captures')
    return dl[0] if dl else ''


def generate_launch_description():
    rosbridge = os.path.join(get_package_share_directory('rosbridge_server'), 'launch', 'rosbridge_websocket_launch.xml')
    return LaunchDescription([
        DeclareLaunchArgument('dossier_debug', default_value=dossier_par_defaut()),
        IncludeLaunchDescription(AnyLaunchDescriptionSource(rosbridge)),
        Node(package='vigie_detection', executable='detecteur', output='screen',
             parameters=[{'champ_horizontal': 1.03, 'dossier_debug': LaunchConfiguration('dossier_debug')}]),
        Node(package='vigie_detection', executable='mission', output='screen',
             parameters=[{'demarrage_auto': False}]),
    ])
