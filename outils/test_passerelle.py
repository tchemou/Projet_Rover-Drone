"""Test de la passerelle sur une instance isolée (port 8421, données /tmp/vt)."""
import asyncio, json, os, re, sys, time, urllib.request, urllib.error
sys.path.insert(0, os.path.expanduser('~/turtlebot3_ws/src/vigie_detection'))
os.environ['VIGIE_DATA'] = '/tmp/vt'
import tornado.websocket
from vigie_detection import passerelle as P

BASE = 'http://127.0.0.1:8421'
OK = 0; KO = 0
def verif(nom, cond, detail=''):
    global OK, KO
    OK += bool(cond); KO += (not cond)
    print(('  OK  ' if cond else '  ECHEC ') + nom + (f'  [{detail}]' if detail and not cond else ''), flush=True)

def http(methode, url, corps=None, cookie=None, csrf=True):
    req = urllib.request.Request(BASE + url, method=methode, data=json.dumps(corps).encode() if corps is not None else None)
    req.add_header('Content-Type', 'application/json')
    if csrf: req.add_header('X-Vigie', '1')
    if cookie: req.add_header('Cookie', cookie)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k): return None
    op = urllib.request.build_opener(NoRedirect)
    try:
        r = op.open(req, timeout=10); body = r.read().decode(); sc = r.status; hdr = r.headers
    except urllib.error.HTTPError as e:
        body = e.read().decode(); sc = e.code; hdr = e.headers
    try: d = json.loads(body)
    except Exception: d = {}
    return sc, d, hdr

def connexion(nom, mdp):
    sc, d, h = http('POST', '/api/login', {'utilisateur': nom, 'mot_de_passe': mdp})
    ck = None
    for v in h.get_all('Set-Cookie') or []:
        if v.startswith('vigie_session='): ck = v.split(';')[0]
    return sc, d, ck, h

async def ws(cookie, origin=None):
    from tornado.httpclient import HTTPRequest
    r = HTTPRequest('ws://127.0.0.1:8421/ws', headers={'Cookie': cookie or '', 'Origin': origin or BASE})
    return await tornado.websocket.websocket_connect(r)

async def lire(c, topic, delai=3.0):
    fin = time.time() + delai; vus = []
    while time.time() < fin:
        try: m = await asyncio.wait_for(c.read_message(), timeout=max(0.05, fin - time.time()))
        except asyncio.TimeoutError: break
        if m is None: return vus, True
        try: j = json.loads(m)
        except Exception: continue
        if j.get('topic') == topic: vus.append(j['msg'])
    return vus, False

async def lire_tout(c, delai):
    fin = time.time() + delai; out = {}
    while time.time() < fin:
        try: m = await asyncio.wait_for(c.read_message(), timeout=max(0.05, fin - time.time()))
        except asyncio.TimeoutError: break
        if m is None: break
        try: j = json.loads(m)
        except Exception: continue
        out.setdefault(j.get('topic'), []).append(j.get('msg'))
    return out

async def principal():
    mdp0 = re.search(r'mot de passe : (\S+)', open('/tmp/vt/identifiants_initiaux.txt').read()).group(1)
    print('1. Connexion et changement obligatoire')
    sc, d, ck, h = connexion('admin', mdp0)
    verif('connexion admin acceptée', sc == 200 and d.get('doit_changer'))
    verif("cookie HttpOnly + SameSite=Strict", 'HttpOnly' in str(h.get_all('Set-Cookie')) and 'SameSite=Strict' in str(h.get_all('Set-Cookie')))
    verif('API utilisateurs refusée avant changement', http('GET', '/api/users', cookie=ck)[0] == 403)
    c = await ws(ck); m = await c.read_message(); verif('websocket refusée avant changement', m is None)
    verif('POST sans en-tête anti-CSRF refusé', http('POST', '/api/password', {'actuel': mdp0, 'nouveau': 'x'}, cookie=ck, csrf=False)[0] == 403)
    verif('mauvais mot de passe actuel refusé', http('POST', '/api/password', {'actuel': 'faux', 'nouveau': 'NouveauMdp2026x'}, cookie=ck)[0] == 400)
    verif('mot de passe faible refusé', http('POST', '/api/password', {'actuel': mdp0, 'nouveau': 'court'}, cookie=ck)[0] == 400)
    verif('mot de passe sans chiffre refusé', http('POST', '/api/password', {'actuel': mdp0, 'nouveau': 'unmotdepassetreslong'}, cookie=ck)[0] == 400)
    NOUVEAU = 'AdminTest2026xyz'
    verif('changement accepté', http('POST', '/api/password', {'actuel': mdp0, 'nouveau': NOUVEAU}, cookie=ck)[0] == 200)
    verif('API utilisateurs ouverte après changement', http('GET', '/api/users', cookie=ck)[0] == 200)

    print('2. Gestion des comptes')
    verif('création opérateur', http('POST', '/api/users', {'nom': 'op.test', 'role': 'operateur', 'mot_de_passe': 'OperateurTest26'}, cookie=ck)[0] == 200)
    verif('création observateur', http('POST', '/api/users', {'nom': 'obs.test', 'role': 'observateur', 'mot_de_passe': 'ObservTest2026x'}, cookie=ck)[0] == 200)
    verif('nom invalide refusé', http('POST', '/api/users', {'nom': 'A B', 'role': 'operateur', 'mot_de_passe': 'OperateurTest26'}, cookie=ck)[0] == 400)
    verif('doublon refusé', http('POST', '/api/users', {'nom': 'op.test', 'role': 'operateur', 'mot_de_passe': 'OperateurTest26'}, cookie=ck)[0] == 400)
    verif('suppression de son propre compte refusée', http('DELETE', '/api/users/admin', cookie=ck)[0] == 400)
    verif('mot de passe stocké haché (scrypt)', 'scrypt$' in open('/tmp/vt/utilisateurs.json').read() and 'OperateurTest26' not in open('/tmp/vt/utilisateurs.json').read())
    verif('fichier des comptes en 600', oct(os.stat('/tmp/vt/utilisateurs.json').st_mode & 0o777) == '0o600')

    print('3. Rôles et filtrage des commandes')
    _, _, ck_op, _ = connexion('op.test', 'OperateurTest26'); _, d2, _, _ = connexion('op.test', 'OperateurTest26')
    sc, d, ck_op, _ = connexion('op.test', 'OperateurTest26'); verif('opérateur doit changer son mot de passe initial', d.get('doit_changer'))
    http('POST', '/api/password', {'actuel': 'OperateurTest26', 'nouveau': 'OperateurFinal26'}, cookie=ck_op)
    sc, d, ck_op, _ = connexion('op.test', 'OperateurFinal26'); verif('opérateur reconnecté', sc == 200 and not d.get('doit_changer'))
    sc, d, ck_ob, _ = connexion('obs.test', 'ObservTest2026x'); http('POST', '/api/password', {'actuel': 'ObservTest2026x', 'nouveau': 'ObservFinal2026x'}, cookie=ck_ob)
    sc, d, ck_ob, _ = connexion('obs.test', 'ObservFinal2026x'); verif('observateur reconnecté', sc == 200)
    verif('opérateur : pas d’accès à la gestion des comptes', http('GET', '/api/users', cookie=ck_op)[0] == 403)
    verif('opérateur : pas d’accès à l’audit', http('GET', '/api/audit', cookie=ck_op)[0] == 403)
    verif('origine étrangère refusée', await ws_refusee(ck_op, 'http://evil.example'))

    co = await ws(ck_op); cb = await ws(ck_ob)
    co.write_message(json.dumps({'op': 'subscribe', 'topic': '/vigie/commande', 'type': 'std_msgs/msg/String'}))
    co.write_message(json.dumps({'op': 'subscribe', 'topic': '/vigie/teleop', 'type': 'geometry_msgs/msg/Twist'}))
    co.write_message(json.dumps({'op': 'subscribe', 'topic': '/vigie/meteo', 'type': 'std_msgs/msg/String'}))
    cb.write_message(json.dumps({'op': 'subscribe', 'topic': '/vigie/meteo', 'type': 'std_msgs/msg/String'}))
    cb.write_message(json.dumps({'op': 'subscribe', 'topic': '/rosout', 'type': 'rcl_interfaces/msg/Log'}))
    await asyncio.sleep(0.8)
    vus, _ = await lire(cb, '/vigie/meteo', 3); verif('observateur reçoit les données en direct', len(vus) >= 1)
    vus, _ = await lire(cb, '/rosout', 1.5); verif('abonnement hors liste blanche ignoré', len(vus) == 0)
    # écritures de l'opérateur
    for t, msg in [('/vigie/teleop', {'linear': {'x': 5.0}, 'angular': {'z': -9.0}}), ('/vigie/commande', {'data': 'meteo:favorable'}), ('/vigie/commande', {'data': 'rm -rf /'}), ('/vigie/commande', {'data': 'demarrer; echo'})]:
        co.write_message(json.dumps({'op': 'advertise', 'topic': t, 'type': 'x'})); co.write_message(json.dumps({'op': 'publish', 'topic': t, 'msg': msg}))
    co.write_message(json.dumps({'op': 'call_service', 'service': '/rosapi/topics'}))
    await asyncio.sleep(1.0)
    tout = await lire_tout(co, 2.0); tele = tout.get('/vigie/teleop', []); cmds = tout.get('/vigie/commande', [])
    verif('téléopération bornée à 0,6 m/s et 1,5 rad/s', any(abs(x['linear']['x']) <= 0.6 + 1e-9 and abs(x['angular']['z']) <= 1.5 + 1e-9 and x['linear']['x'] > 0 for x in tele), str(tele[:1]))
    verif('commande autorisée transmise (meteo:favorable)', any(x.get('data') == 'meteo:favorable' for x in cmds))
    verif('commande hors liste blanche bloquée', not any('rm' in x.get('data', '') or 'echo' in x.get('data', '') for x in cmds))
    # écritures de l'observateur (hors arrêt d'urgence : testé en test unitaire pour ne pas arrêter la vraie simulation)
    cb.write_message(json.dumps({'op': 'publish', 'topic': '/vigie/commande', 'msg': {'data': 'meteo:sec'}}))
    await asyncio.sleep(1.0)
    cmds, _ = await lire(co, '/vigie/commande', 1.0); verif('observateur ne peut pas envoyer de commande', not any(x.get('data') == 'meteo:sec' for x in cmds))
    # test unitaire du filtre, y compris l'arrêt d'urgence
    so = {'user': 'a', 'role': 'observateur', 'ip': '-', 'actif': 0}; sp = {'user': 'b', 'role': 'operateur', 'ip': '-', 'actif': 0}
    f = lambda s, m: P.filtrer(s, json.dumps(m), None)
    P.audit = lambda *a, **k: None
    verif("arrêt d'urgence autorisé à l'observateur", f(so, {'op': 'publish', 'topic': '/vigie/commande', 'msg': {'data': 'arret_urgence'}}) is not None)
    verif("« demarrer » refusé à l'observateur", f(so, {'op': 'publish', 'topic': '/vigie/commande', 'msg': {'data': 'demarrer'}}) is None)
    verif("« demarrer » autorisé à l'opérateur", f(sp, {'op': 'publish', 'topic': '/vigie/commande', 'msg': {'data': 'demarrer'}}) is not None)
    verif('appel de service refusé', f(sp, {'op': 'call_service', 'service': '/x'}) is None)
    verif('publication sur /cmd_vel refusée', f(sp, {'op': 'publish', 'topic': '/cmd_vel', 'msg': {}}) is None)
    verif('JSON invalide ignoré', P.filtrer(sp, '{pas du json', None) is None)

    print('4. Blocage après échecs répétés')
    for _ in range(5): connexion('obs.test', 'faux-faux')
    sc, d, _, _ = connexion('obs.test', 'ObservFinal2026x'); verif('compte bloqué (429) après 5 échecs, même avec le bon mot de passe', sc == 429 and d.get('attente', 0) > 0, str(sc))

    print('5. Déconnexion')
    http('POST', '/api/logout', {}, cookie=ck_op)
    verif('session invalidée après déconnexion', http('GET', '/api/me', cookie=ck_op)[0] == 401)
    m = await asyncio.wait_for(co.read_message(), 3) if True else None
    for _ in range(30):
        if m is None: break
        m = await asyncio.wait_for(co.read_message(), 3)
    verif('websocket fermée à la déconnexion', m is None)

    print('6. Audit')
    sc, d, _ = http('GET', '/api/audit', cookie=ck)
    evts = {e['evt'] for e in d.get('evenements', [])}
    verif('journal d’audit : connexions, commandes, échecs', {'connexion', 'commande', 'connexion_echec', 'utilisateur_cree'} <= evts, str(evts))
    verif('journal d’audit : aucune trace de mot de passe', 'OperateurFinal26' not in open('/tmp/vt/audit.log').read() and NOUVEAU not in open('/tmp/vt/audit.log').read())
    print(f'\nRésultat : {OK} vérifications réussies, {KO} échec(s)')

async def ws_refusee(cookie, origin):
    try:
        c = await ws(cookie, origin); return False
    except Exception:
        return True

asyncio.run(principal())
