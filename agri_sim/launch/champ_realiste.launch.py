#!/usr/bin/env python3
"""Exploitation de betteraves + Turtlebot 3 (burger ou waffle selon TURTLEBOT3_MODEL)."""
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import AppendEnvironmentVariable, DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    agri = get_package_share_directory('agri_sim')
    tb3 = get_package_share_directory('turtlebot3_gazebo')
    ros_gz_sim = get_package_share_directory('ros_gz_sim')
    world = os.path.join(agri, 'worlds', 'champ_realiste.sdf')
    gui_config = os.path.join(agri, 'config', 'vigie_gui.config')
    x_pose = LaunchConfiguration('x_pose', default='-6.9')
    y_pose = LaunchConfiguration('y_pose', default='0.3')
    return LaunchDescription([
        DeclareLaunchArgument('gui', default_value='true', description='ouvre la fenetre Gazebo'),
        AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH', os.path.join(agri, 'models')),
        AppendEnvironmentVariable('GZ_SIM_RESOURCE_PATH', os.path.join(tb3, 'models')),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(ros_gz_sim, 'launch', 'gz_sim.launch.py')),
            launch_arguments={'gz_args': ['-r -s -v2 ', world], 'on_exit_shutdown': 'true'}.items()),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(ros_gz_sim, 'launch', 'gz_sim.launch.py')),
            condition=IfCondition(LaunchConfiguration('gui')),
            launch_arguments={'gz_args': ['-g -v2 --gui-config ', gui_config], 'on_exit_shutdown': 'true'}.items()),
        Node(package='ros_gz_sim', executable='create', output='screen',
             arguments=['-name', 'waffle', '-file', os.path.join(agri, 'models', 'rover_agri', 'model.sdf'),
                        '-x', x_pose, '-y', y_pose, '-z', '0.01']),
        Node(package='ros_gz_bridge', executable='parameter_bridge', output='screen',
             arguments=['--ros-args', '-p', f"config_file:={os.path.join(tb3, 'params', 'turtlebot3_waffle_bridge.yaml')}"]),
        Node(package='ros_gz_bridge', executable='parameter_bridge', output='screen', name='pont_gnss',
             arguments=['/rover/gnss@nav_msgs/msg/Odometry[gz.msgs.Odometry']),
        Node(package='ros_gz_image', executable='image_bridge', output='screen', arguments=['/camera/image_raw', '/rover/cam_gauche/image_raw', '/rover/cam_droite/image_raw']),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(tb3, 'launch', 'robot_state_publisher.launch.py')),
            launch_arguments={'use_sim_time': 'true'}.items()),
    ])
