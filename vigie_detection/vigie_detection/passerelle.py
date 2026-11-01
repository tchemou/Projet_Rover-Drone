"""Passerelle sécurisée de la console Vigie Betterave.

Elle est la SEULE porte d'entrée vers la simulation : rosbridge n'écoute plus que sur 127.0.0.1 et la
console ne parle qu'à cette passerelle, après authentification.

  - comptes (mots de passe hachés avec scrypt), sessions à cookie HttpOnly, limitation des tentatives ;
  - trois rôles : administrateur, opérateur, observateur (lecture seule) ;
  - filtrage des messages vers ROS 2 : liste blanche de commandes, vitesses de téléopération bornées ;
    l'arrêt d'urgence reste accessible à tous les rôles ;
  - journal d'audit (qui, quand, quelle commande) ;
  - gestion des utilisateurs et consultation des rapports depuis la console.

Lancement : ros2 run vigie_detection passerelle [--port 8420] [--reset-admin]
Données   : ~/.vigie/ (comptes, secret, journal d'audit), à ne pas partager.
"""
import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime
from urllib.parse import urlparse

import tornado.httpclient
import tornado.ioloop
import tornado.web
import tornado.websocket

DATA_DIR = os.path.expanduser(os.environ.get('VIGIE_DATA', '~/.vigie'))
RAPPORTS_DIR = os.path.expanduser('~/vigie_rapports')
ROSBRIDGE_URL = os.environ.get('VIGIE_ROSBRIDGE', 'ws://127.0.0.1:9090')
IDLE_S = 60 * float(os.environ.get('VIGIE_IDLE_MIN', '60'))       # inactivité de l'utilisateur avant expiration
MAX_S = 12 * 3600                                                  # durée maximale d'une session
COOKIE = 'vigie_session'
ROLES = ('admin', 'operateur', 'observateur')
NOM_RE = re.compile(r'^[a-z0-9._-]{3,32}$')

# ---------------------------------------------------------------------------------------------- stockage
def _b64(b):
    return base64.b64encode(b).decode()


def hacher(mdp, sel=None):
    sel = sel or os.urandom(16)
    h = hashlib.scrypt(mdp.encode(), salt=sel, n=2 ** 14, r=8, p=1, dklen=32)
    return f'scrypt$14$8$1${_b64(sel)}${_b64(h)}'


def verifier(mdp, stocke):
    try:
        _, n, r, p, sel, h = stocke.split('$')
        calc = hashlib.scrypt(mdp.encode(), salt=base64.b64decode(sel), n=2 ** int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


FAUX_HASH = hacher(secrets.token_urlsafe(16))                      # temps constant si l'utilisateur n'existe pas


def mdp_valide(mdp, nom):
    if len(mdp) < 10:
        return 'Le mot de passe doit contenir au moins 10 caractères.'
    if mdp.lower() == nom.lower() or not (re.search(r'[A-Za-z]', mdp) and re.search(r'\d', mdp)):
        return 'Le mot de passe doit mélanger lettres et chiffres.'
    return None


class Utilisateurs:
    def __init__(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        os.chmod(DATA_DIR, 0o700)
        self.chemin = os.path.join(DATA_DIR, 'utilisateurs.json')
        self.users = json.load(open(self.chemin, encoding='utf-8')) if os.path.exists(self.chemin) else {}

    def sauver(self):
        tmp = self.chemin + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(self.users, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.chemin)

    def creer(self, nom, role, mdp, doit_changer=True):
        self.users[nom] = {'role': role, 'hash': hacher(mdp), 'cree': time.time(), 'derniere_connexion': None, 'doit_changer': doit_changer}
        self.sauver()

    def initialiser_admin(self, forcer=False):
        if self.users.get('admin') and not forcer:
            return
        mdp = secrets.token_urlsafe(12) + '7'
        self.creer('admin', 'admin', mdp, doit_changer=True)
        chemin = os.path.join(DATA_DIR, 'identifiants_initiaux.txt')
        with open(chemin, 'w', encoding='utf-8') as f:
            f.write(f"Compte administrateur initial\nutilisateur : admin\nmot de passe : {mdp}\n\n"
                    "Changement obligatoire à la première connexion. Supprimez ce fichier ensuite.\n")
        os.chmod(chemin, 0o600)
        print(f'[passerelle] compte « admin » créé : identifiants dans {chemin}', flush=True)


# ---------------------------------------------------------------------------------------------- audit
def audit(evenement, utilisateur='-', ip='-', **details):
    ligne = {'t': datetime.now().isoformat(timespec='seconds'), 'evt': evenement, 'user': utilisateur, 'ip': ip, **details}
    with open(os.path.join(DATA_DIR, 'audit.log'), 'a', encoding='utf-8') as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + '\n')


# ---------------------------------------------------------------------------------------------- sessions
SESSIONS = {}
ECHECS = {}                      # (ip, utilisateur) -> {'n': tentatives, 'jusque': instant}
OUVERTS = set()                  # websockets ouverts


def session_depuis(token, toucher=False):
    s = SESSIONS.get(token or '')
    if not s:
        return None
    t = time.time()
    if t - s['debut'] > MAX_S or t - s['actif'] > IDLE_S:
        SESSIONS.pop(token, None)
        return None
    if toucher:
        s['actif'] = t
    return s


class Base(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header('Cache-Control', 'no-store')
        self.set_header('X-Content-Type-Options', 'nosniff')
        self.set_header('X-Frame-Options', 'DENY')
        self.set_header('Referrer-Policy', 'no-referrer')
        self.set_header('Content-Security-Policy',
                        "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                        "img-src 'self' data: blob:; connect-src 'self' ws: wss:; worker-src blob:; frame-ancestors 'none'")

    @property
    def ip(self):
        return self.request.remote_ip

    def session(self, toucher=True):
        return session_depuis(self.get_cookie(COOKIE), toucher)

    def exiger(self, roles=None, changement_ok=False, toucher=True):
        s = self.session(toucher)
        if not s:
            raise tornado.web.HTTPError(401)
        if s['doit_changer'] and not changement_ok:
            raise tornado.web.HTTPError(403, reason='changement-mdp')
        if roles and s['role'] not in roles:
            raise tornado.web.HTTPError(403)
        return s

    def csrf(self):
        if self.request.headers.get('X-Vigie') != '1':
            raise tornado.web.HTTPError(403)

    def corps(self):
        try:
            d = json.loads(self.request.body or b'{}')
            return d if isinstance(d, dict) else {}
        except ValueError:
            raise tornado.web.HTTPError(400)

    def rendre(self, obj, statut=200):
        self.set_status(statut)
        self.set_header('Content-Type', 'application/json; charset=utf-8')
        self.finish(json.dumps(obj, ensure_ascii=False))

    def write_error(self, status_code, **kw):
        raison = self._reason if status_code in (401, 403) else ''
        self.set_header('Content-Type', 'application/json; charset=utf-8')
        self.finish(json.dumps({'erreur': {401: 'Non authentifié', 403: 'Accès refusé', 400: 'Requête invalide', 404: 'Introuvable'}.get(status_code, 'Erreur'), 'code': raison}))


class Page(Base):
    def get(self, nom='app'):
        s = self.session(False)
        if nom == 'login':
            if s and not s['doit_changer']:
                return self.redirect('/')
            return self.fichier('login.html')
        if not s or s['doit_changer']:                 # pas connecté, ou mot de passe initial à changer d'abord
            return self.redirect('/login')
        self.fichier('vigie_console.html')

    def fichier(self, nom):
        self.set_header('Content-Type', 'text/html; charset=utf-8')
        self.finish(open(os.path.join(CONSOLE_DIR, nom), 'rb').read())


class Script3D(Base):
    def get(self):
        if not self.session(False):
            raise tornado.web.HTTPError(401)
        self.set_header('Content-Type', 'application/javascript; charset=utf-8')
        self.finish(open(os.path.join(CONSOLE_DIR, 'vigie3d.js'), 'rb').read())


class Connexion(Base):
    async def post(self):
        self.csrf()
        d = self.corps()
        nom = str(d.get('utilisateur', '')).strip().lower()[:64]
        mdp = str(d.get('mot_de_passe', ''))[:200]
        cle = (self.ip, nom)
        e = ECHECS.get(cle)
        if e and e['jusque'] > time.time():
            audit('connexion_bloquee', nom, self.ip)
            return self.rendre({'erreur': 'Trop de tentatives. Patientez avant de réessayer.', 'attente': int(e['jusque'] - time.time()) + 1}, 429)
        rec = self.application.utilisateurs.users.get(nom)
        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, verifier, mdp, rec['hash'] if rec else FAUX_HASH)
        if not (ok and rec):
            e = ECHECS.setdefault(cle, {'n': 0, 'jusque': 0})
            e['n'] += 1
            if e['n'] >= 5:
                e['jusque'] = time.time() + min(900, 30 * 2 ** (e['n'] - 5))
            audit('connexion_echec', nom, self.ip, tentatives=e['n'])
            await asyncio.sleep(0.6)                        # ralentit les essais en série
            return self.rendre({'erreur': 'Identifiants incorrects.'}, 401)
        ECHECS.pop(cle, None)
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = {'user': nom, 'role': rec['role'], 'debut': time.time(), 'actif': time.time(), 'doit_changer': bool(rec.get('doit_changer')), 'ip': self.ip}
        rec['derniere_connexion'] = time.time()
        self.application.utilisateurs.sauver()
        self.set_cookie(COOKIE, token, httponly=True, samesite='Strict', path='/')
        audit('connexion', nom, self.ip, role=rec['role'])
        self.rendre({'ok': True, 'role': rec['role'], 'doit_changer': bool(rec.get('doit_changer'))})


class Deconnexion(Base):
    def post(self):
        self.csrf()
        token = self.get_cookie(COOKIE)
        s = SESSIONS.pop(token, None)
        if s:
            audit('deconnexion', s['user'], self.ip)
            for ws in list(OUVERTS):
                if ws.token == token:
                    ws.close(4401)
        self.clear_cookie(COOKIE, path='/')
        self.rendre({'ok': True})


class Moi(Base):
    def get(self):
        s = self.exiger(changement_ok=True, toucher=False)
        rec = self.application.utilisateurs.users.get(s['user'], {})
        self.rendre({'utilisateur': s['user'], 'role': s['role'], 'doit_changer': s['doit_changer'],
                     'derniere_connexion': rec.get('derniere_connexion'), 'expire_dans': int(min(MAX_S - (time.time() - s['debut']), IDLE_S - (time.time() - s['actif'])))})


class Ping(Base):
    def post(self):
        self.csrf()
        self.exiger(changement_ok=True)
        self.rendre({'ok': True})


class MotDePasse(Base):
    async def post(self):
        self.csrf()
        s = self.exiger(changement_ok=True)
        d = self.corps()
        rec = self.application.utilisateurs.users[s['user']]
        loop = asyncio.get_running_loop()
        if not await loop.run_in_executor(None, verifier, str(d.get('actuel', ''))[:200], rec['hash']):
            audit('mdp_echec', s['user'], self.ip)
            return self.rendre({'erreur': 'Mot de passe actuel incorrect.'}, 400)
        nouveau = str(d.get('nouveau', ''))[:200]
        msg = mdp_valide(nouveau, s['user'])
        if msg:
            return self.rendre({'erreur': msg}, 400)
        if nouveau == str(d.get('actuel', '')):
            return self.rendre({'erreur': 'Le nouveau mot de passe doit être différent.'}, 400)
        rec['hash'] = await loop.run_in_executor(None, hacher, nouveau)
        rec['doit_changer'] = False
        s['doit_changer'] = False
        self.application.utilisateurs.sauver()
        audit('mdp_change', s['user'], self.ip)
        self.rendre({'ok': True})


class Utilisateurs_(Base):
    def get(self):
        self.exiger(('admin',))
        us = self.application.utilisateurs.users
        self.rendre({'utilisateurs': [{'nom': n, 'role': u['role'], 'cree': u['cree'], 'derniere_connexion': u.get('derniere_connexion'), 'doit_changer': u.get('doit_changer', False)} for n, u in sorted(us.items())]})

    async def post(self):
        self.csrf()
        s = self.exiger(('admin',))
        d = self.corps()
        nom, role, mdp = str(d.get('nom', '')).strip().lower(), str(d.get('role', '')), str(d.get('mot_de_passe', ''))[:200]
        us = self.application.utilisateurs
        if not NOM_RE.match(nom):
            return self.rendre({'erreur': 'Nom invalide (3 à 32 caractères : lettres minuscules, chiffres, . _ -).'}, 400)
        if nom in us.users:
            return self.rendre({'erreur': 'Ce nom existe déjà.'}, 400)
        if role not in ROLES:
            return self.rendre({'erreur': 'Rôle inconnu.'}, 400)
        msg = mdp_valide(mdp, nom)
        if msg:
            return self.rendre({'erreur': msg}, 400)
        await asyncio.get_running_loop().run_in_executor(None, lambda: us.creer(nom, role, mdp))
        audit('utilisateur_cree', s['user'], self.ip, cible=nom, role=role)
        self.rendre({'ok': True})


class UtilisateurUn(Base):
    async def delete(self, nom):
        self.csrf()
        s = self.exiger(('admin',))
        us = self.application.utilisateurs
        if nom == s['user']:
            return self.rendre({'erreur': 'Vous ne pouvez pas supprimer votre propre compte.'}, 400)
        if nom not in us.users:
            raise tornado.web.HTTPError(404)
        us.users.pop(nom)
        us.sauver()
        for tok, se in list(SESSIONS.items()):
            if se['user'] == nom:
                SESSIONS.pop(tok)
        for ws in list(OUVERTS):
            if ws.sess['user'] == nom:
                ws.close(4401)
        audit('utilisateur_supprime', s['user'], self.ip, cible=nom)
        self.rendre({'ok': True})

    async def patch(self, nom):
        """Réinitialise le mot de passe (changement exigé à la prochaine connexion) ou change le rôle."""
        self.csrf()
        s = self.exiger(('admin',))
        us = self.application.utilisateurs
        rec = us.users.get(nom)
        if not rec:
            raise tornado.web.HTTPError(404)
        d = self.corps()
        if 'role' in d:
            if d['role'] not in ROLES or (nom == s['user'] and d['role'] != 'admin'):
                return self.rendre({'erreur': 'Rôle refusé.'}, 400)
            rec['role'] = d['role']
            audit('role_change', s['user'], self.ip, cible=nom, role=d['role'])
        if 'mot_de_passe' in d:
            mdp = str(d['mot_de_passe'])[:200]
            msg = mdp_valide(mdp, nom)
            if msg:
                return self.rendre({'erreur': msg}, 400)
            rec['hash'] = await asyncio.get_running_loop().run_in_executor(None, hacher, mdp)
            rec['doit_changer'] = True
            audit('mdp_reinit', s['user'], self.ip, cible=nom)
        us.sauver()
        self.rendre({'ok': True})


class Audit(Base):
    def get(self):
        self.exiger(('admin',))
        chemin = os.path.join(DATA_DIR, 'audit.log')
        lignes = open(chemin, encoding='utf-8').read().splitlines()[-200:] if os.path.exists(chemin) else []
        self.rendre({'evenements': [json.loads(x) for x in reversed(lignes) if x.strip()]})


class Rapports(Base):
    def get(self, nom=None):
        self.exiger()
        os.makedirs(RAPPORTS_DIR, exist_ok=True)
        if nom is None:
            fs = sorted((f for f in os.listdir(RAPPORTS_DIR) if re.match(r'^mission_[0-9_]+\.json$', f)), reverse=True)
            return self.rendre({'rapports': [{'nom': f, 'taille': os.path.getsize(os.path.join(RAPPORTS_DIR, f)), 'date': os.path.getmtime(os.path.join(RAPPORTS_DIR, f))} for f in fs]})
        if not re.match(r'^mission_[0-9_]+\.json$', nom):
            raise tornado.web.HTTPError(404)
        chemin = os.path.join(RAPPORTS_DIR, nom)
        if not os.path.isfile(chemin):
            raise tornado.web.HTTPError(404)
        self.set_header('Content-Type', 'application/json; charset=utf-8')
        self.set_header('Content-Disposition', f'attachment; filename="{nom}"')
        self.finish(open(chemin, 'rb').read())


# ---------------------------------------------------------------------------------------------- pont WebSocket filtré
TOPICS_LECTURE = re.compile(r'^/(vigie/[a-z0-9_/]+|odom|rover/gnss|drone/odom)$')
COMMANDES = re.compile(r'^(demarrer|pause|reprendre|retour|arret_urgence|rearmer|mode:(normal|degrade)|controle:(auto|manuel)|meteo:(favorable|sec)|obstacle:(poser|retirer)|(valider|rejeter):[0-9]{1,5})$')
ECRITURE = {'/vigie/commande': 'std_msgs/msg/String', '/vigie/teleop': 'geometry_msgs/msg/Twist', '/vigie/heartbeat': 'std_msgs/msg/String'}


def _borne(v, m):
    try:
        return max(-m, min(m, float(v)))
    except (TypeError, ValueError):
        return 0.0


def filtrer(sess, brut, ws):
    """Retourne le message à transmettre à ROS (chaîne) ou None s'il est refusé."""
    try:
        m = json.loads(brut)
    except ValueError:
        return None
    if not isinstance(m, dict):
        return None
    op, role = m.get('op'), sess['role']
    ecrit = role in ('admin', 'operateur')
    if op in ('subscribe', 'unsubscribe'):
        return brut if TOPICS_LECTURE.match(str(m.get('topic', ''))) else None
    if op in ('advertise', 'unadvertise'):
        if ecrit and m.get('topic') in ECRITURE:
            return json.dumps({'op': op, 'topic': m['topic'], 'type': ECRITURE[m['topic']]}) if op == 'advertise' else brut
        return None
    if op == 'publish':
        topic, msg = m.get('topic'), m.get('msg') if isinstance(m.get('msg'), dict) else {}
        if topic == '/vigie/heartbeat' and ecrit:
            return json.dumps({'op': 'publish', 'topic': topic, 'msg': {'data': 'ok'}})
        if topic == '/vigie/teleop' and ecrit:
            lin, ang = msg.get('linear') or {}, msg.get('angular') or {}
            return json.dumps({'op': 'publish', 'topic': topic, 'msg': {'linear': {'x': _borne(lin.get('x'), 0.6), 'y': 0.0, 'z': 0.0}, 'angular': {'x': 0.0, 'y': 0.0, 'z': _borne(ang.get('z'), 1.5)}}})
        if topic == '/vigie/commande':
            c = str(msg.get('data', ''))
            if not COMMANDES.match(c):
                audit('commande_invalide', sess['user'], sess['ip'], commande=c[:60])
                return None
            if c != 'arret_urgence' and not ecrit:            # l'arrêt d'urgence reste ouvert à tous
                audit('commande_refusee', sess['user'], sess['ip'], commande=c, role=role)
                return None
            audit('commande', sess['user'], sess['ip'], commande=c)
            sess['actif'] = time.time()
            return json.dumps({'op': 'publish', 'topic': topic, 'msg': {'data': c}})
        return None
    return None                                               # call_service, set_param… : jamais


class PontWS(tornado.websocket.WebSocketHandler):
    token = None
    sess = None
    websocket_max_message_size = 10_000_000

    def check_origin(self, origin):
        return urlparse(origin).netloc == self.request.host

    async def open(self):
        self.token = self.get_cookie(COOKIE)
        self.sess = session_depuis(self.token)
        if not self.sess or self.sess['doit_changer']:
            return self.close(4401)
        self.bucket, self.t_bucket = 80.0, time.time()
        try:
            self.amont = await tornado.websocket.websocket_connect(ROSBRIDGE_URL, max_message_size=10_000_000)
        except Exception:
            return self.close(4503, 'simulation hors ligne')
        OUVERTS.add(self)
        audit('ws_ouvert', self.sess['user'], self.sess['ip'])
        self.tache = asyncio.ensure_future(self.pomper())

    async def pomper(self):
        while True:
            msg = await self.amont.read_message()
            if msg is None:
                break
            try:
                await self.write_message(msg, binary=isinstance(msg, bytes))
            except tornado.websocket.WebSocketClosedError:
                return
        self.close(4503, 'simulation hors ligne')

    def on_message(self, message):
        if not session_depuis(self.token):
            return self.close(4401)
        t = time.time()
        self.bucket = min(80.0, self.bucket + (t - self.t_bucket) * 80)
        self.t_bucket = t
        if self.bucket < 1:
            return
        self.bucket -= 1
        if isinstance(message, bytes) or len(message) > 20000:
            return
        sortie = filtrer(self.sess, message, self)
        if sortie is not None and getattr(self, 'amont', None):
            self.amont.write_message(sortie)

    def on_close(self):
        OUVERTS.discard(self)
        if self.sess:
            audit('ws_ferme', self.sess['user'], self.sess['ip'])
        if getattr(self, 'tache', None):
            self.tache.cancel()
        if getattr(self, 'amont', None):
            self.amont.close()


def balayer():
    """Ferme les connexions dont la session a expiré."""
    for ws in list(OUVERTS):
        if not session_depuis(ws.token):
            ws.close(4401)


# ---------------------------------------------------------------------------------------------- application
def dossier_console():
    try:
        from ament_index_python.packages import get_package_share_directory
        d = os.path.join(get_package_share_directory('vigie_detection'), 'console')
        if os.path.isfile(os.path.join(d, 'login.html')):
            return d
    except Exception:
        pass
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'console')


CONSOLE_DIR = dossier_console()


def creer_app():
    app = tornado.web.Application([
        (r'/', Page), (r'/(login)', Page), (r'/vigie3d\.js', Script3D),
        (r'/api/login', Connexion), (r'/api/logout', Deconnexion), (r'/api/me', Moi), (r'/api/ping', Ping), (r'/api/password', MotDePasse),
        (r'/api/users', Utilisateurs_), (r'/api/users/([a-z0-9._-]{3,32})', UtilisateurUn), (r'/api/audit', Audit),
        (r'/api/rapports', Rapports), (r'/api/rapports/([A-Za-z0-9_.]+)', Rapports), (r'/ws', PontWS),
    ])
    app.utilisateurs = Utilisateurs()
    app.utilisateurs.initialiser_admin()
    return app


def main():
    ap = argparse.ArgumentParser(description='Passerelle sécurisée Vigie Betterave')
    ap.add_argument('--port', type=int, default=int(os.environ.get('VIGIE_PORT', '8420')))
    ap.add_argument('--adresse', default=os.environ.get('VIGIE_ADRESSE', '127.0.0.1'))
    ap.add_argument('--reset-admin', action='store_true', help="régénère le mot de passe du compte « admin »")
    args, _ = ap.parse_known_args()
    app = creer_app()
    if args.reset_admin:
        app.utilisateurs.initialiser_admin(forcer=True)
    app.listen(args.port, address=args.adresse, max_buffer_size=2_000_000)
    tornado.ioloop.PeriodicCallback(balayer, 30000).start()
    print(f'[passerelle] console sur http://{args.adresse}:{args.port}  ·  rosbridge : {ROSBRIDGE_URL}', flush=True)
    try:
        tornado.ioloop.IOLoop.current().start()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
