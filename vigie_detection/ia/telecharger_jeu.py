"""Prépare le jeu public « Plant image classification dataset » (betterave : saine / cercosporiose).

Source  : Poznan Supercomputing and Networking Center (PSNC / WODR), Zenodo, DOI 10.5281/zenodo.15873360
Licence : CC-BY-4.0 (citer les auteurs).
Étapes  : téléchargement de l'archive (6,4 Go, un seul flux avec reprise), vérification de l'empreinte MD5,
          puis lecture des seules images de betterave, réduites à 800 px de côté au maximum.
          Rien n'est extrait tel quel : les images sont décodées en mémoire puis réenregistrées en JPEG.

Usage : python3 telecharger_jeu.py [dossier_sortie]
"""
import hashlib
import io
import os
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

URL = 'https://zenodo.org/api/records/15873360/files/dataset.zip/content'
MD5 = '020dba95eee0e624c4c3c91bcf08421f'
COTE_MAX = 800


def telecharger(chemin):
    if os.path.exists(chemin) and os.path.getsize(chemin) > 6_400_000_000:
        return
    for _ in range(6):
        r = subprocess.run(['curl', '-L', '-C', '-', '--retry', '5', '--retry-delay', '5', '-s', '-o', chemin, URL])
        if r.returncode == 0:
            return
    raise RuntimeError('téléchargement impossible')


def md5(chemin):
    h = hashlib.md5()
    with open(chemin, 'rb') as f:
        for bloc in iter(lambda: f.read(1 << 24), b''):
            h.update(bloc)
    return h.hexdigest()


def traiter(args):
    chemin_zip, nom, sortie = args
    classe = 'cercospora' if 'cercospora' in nom.lower() else 'unaffected'
    base = os.path.splitext(os.path.basename(nom))[0].replace(' ', '_')
    chemin = os.path.join(sortie, classe, base + '.jpg')
    if os.path.exists(chemin):
        return classe
    with zipfile.ZipFile(chemin_zip) as z:
        octets = z.read(nom)
    img = Image.open(io.BytesIO(octets)).convert('RGB')
    img.thumbnail((COTE_MAX, COTE_MAX))
    img.save(chemin, 'JPEG', quality=90)
    return classe


def main():
    sortie = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else '~/ia/donnees/beet')
    archive = os.path.join(os.path.dirname(sortie), 'dataset.zip')
    for c in ('cercospora', 'unaffected'):
        os.makedirs(os.path.join(sortie, c), exist_ok=True)
    print('téléchargement de l’archive (6,4 Go)…', flush=True)
    telecharger(archive)
    ok = md5(archive)
    print('empreinte MD5 :', ok, '(conforme)' if ok == MD5 else '(NON CONFORME)', flush=True)
    if ok != MD5:
        sys.exit('archive corrompue')
    with zipfile.ZipFile(archive) as z:
        noms = [i.filename for i in z.infolist()
                if not i.is_dir() and '/beet/' in ('/' + i.filename.lower()) and i.filename.lower().endswith(('.jpg', '.jpeg', '.png'))]
    print(f'{len(noms)} images de betterave', flush=True)
    fait = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        for _ in ex.map(traiter, [(archive, n, sortie) for n in noms]):
            fait += 1
            if fait % 100 == 0 or fait == len(noms):
                print(f'  {fait}/{len(noms)}', flush=True)
    for c in ('cercospora', 'unaffected'):
        print(c, len(os.listdir(os.path.join(sortie, c))), 'images')
    os.remove(archive)
    print('archive supprimée (images réduites conservées)')


if __name__ == '__main__':
    main()
