import glob
from setuptools import setup

package_name = 'vigie_detection'
setup(
    name=package_name,
    version='0.3.1',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob.glob('launch/*.py')),
        ('share/' + package_name + '/console', glob.glob('console/*')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Pagnol TCHEMOU',
    maintainer_email='vianytchemou@gmail.com',
    description='Détection de la cercosporiose (version couleur).',
    license='Apache-2.0',
    entry_points={'console_scripts': [
        'detecteur = vigie_detection.detecteur:main', 'mission = vigie_detection.mission:main',
        'drone = vigie_detection.drone:main', 'meteo = vigie_detection.meteo:main', 'bilan = vigie_detection.bilan:main', 'passerelle = vigie_detection.passerelle:main']},
)
