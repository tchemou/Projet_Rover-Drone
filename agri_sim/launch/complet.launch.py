#!/usr/bin/env python3
"""Simulation complete : parcelle + rover Turtlebot3 + drone + ponts ROS 2 (+ noeuds du projet).

Arguments : gui:=true|false   noeuds:=true|false (detecteur, drone, meteo, mission, bilan, passerelle, rosbridge)
"""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource, AnyLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    agri = get_package_share_directory('agri_sim')
    ros_gz_sim = get_package_share_directory('ros_gz_sim')
    drone_sdf = os.path.join(agri, 'models', 'drone_agri', 'model.sdf')
    gui = LaunchConfiguration('gui')
    nodes = LaunchConfiguration('noeuds')
    monde = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(agri, 'launch', 'champ_realiste.launch.py')),
        launch_arguments={'gui': gui}.items())
    spawn_drone = Node(package='ros_gz_sim', executable='create', output='screen',
                       arguments=['-world', 'default', '-file', drone_sdf, '-name', 'drone_agri',
                                  '-x', '-9.2', '-y', '-2.2', '-z', '0.13'])
    pont = Node(package='ros_gz_bridge', executable='parameter_bridge', output='screen',
                arguments=['/model/drone_agri/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist',
                           '/model/drone_agri/odometry@nav_msgs/msg/Odometry[gz.msgs.Odometry',
                           '/drone/camera/image_raw@sensor_msgs/msg/Image[gz.msgs.Image'],
                remappings=[('/model/drone_agri/cmd_vel', '/drone/cmd_vel'),
                            ('/model/drone_agri/odometry', '/drone/odom')])
    rosbridge = IncludeLaunchDescription(
        AnyLaunchDescriptionSource(os.path.join(get_package_share_directory('rosbridge_server'),
                                                'launch', 'rosbridge_websocket_launch.xml')),
        launch_arguments={'address': '127.0.0.1'}.items(),     # rosbridge n'est joignable que par la passerelle
        condition=IfCondition(nodes))
    projet = [Node(package='vigie_detection', executable=e, output='screen', condition=IfCondition(nodes))
              for e in ('detecteur', 'drone', 'meteo', 'mission', 'bilan', 'passerelle')]
    return LaunchDescription([
        DeclareLaunchArgument('gui', default_value='true'),
        DeclareLaunchArgument('noeuds', default_value='true'),
        monde, TimerAction(period=6.0, actions=[spawn_drone, pont]),
        rosbridge, TimerAction(period=9.0, actions=projet),
    ])
