from flask import Flask, request, redirect, url_for, render_template_string, session, jsonify
from google.cloud import datastore
from datetime import datetime, timedelta
import os
import random

app = Flask(__name__)
app.secret_key = 'dev-key'  # À changer en prod
client = datastore.Client()

# Templates HTML minimalistes
TEMPLATE_INDEX = '''
<h2>Bienvenue sur Tiny Instagram</h2>
{% if user %}
  Connecté en tant que <b>{{ user }}</b> | <a href="/logout">Déconnexion</a><br><br>
  <form action="/post" method="post">
    <input name="content" placeholder="Votre message" required>
    <button>Poster</button>
  </form>
  <h3>Timeline</h3>
  {% for post in timeline %}
    <div><b>{{ post['author'] }}</b>: {{ post['content'] }}</div>
  {% endfor %}
  <h3>Suivre un utilisateur</h3>
  <form action="/follow" method="post">
    <input name="to_follow" placeholder="Nom d'utilisateur" required>
    <button>Suivre</button>
  </form>
{% else %}
  <form action="/login" method="post">
    <input name="username" placeholder="Nom d'utilisateur" required>
    <button>Connexion</button>
  </form>
{% endif %}
'''

def get_timeline(user: str, limit: int = 20):
    """Retourne la liste des posts (entités) pour la timeline d'un utilisateur."""
    if not user:
        return []
    follow_key = client.key('User', user)
    user_entity = client.get(follow_key)
    follows = []
    if user_entity:
        follows = user_entity.get('follows', [])
    # On ajoute l'utilisateur lui-même pour voir ses propres posts
    follows = list({*follows, user})

    timeline = []
    used_gql = False
    try:
        if hasattr(client, 'gql'):
            gql = client.gql("SELECT * FROM Post WHERE author IN @authors ORDER BY created DESC")
            gql.bindings["authors"] = follows
            timeline = list(gql.fetch(limit=limit))
            used_gql = True
    except Exception:
        pass
    if not used_gql:
        try:
            # Tentative de requête standard avec filtre IN
            query = client.query(kind='Post')
            query.add_filter('author', 'IN', follows)
            query.order = ['-created']
            timeline = list(query.fetch(limit=limit))
        except Exception:
            # Fallback manuel si l'index n'est pas prêt ou erreur de requête
            posts = []
            for author in follows:
                q = client.query(kind='Post')
                q.add_filter('author', '=', author)
                q.order = ['-created']
                posts.extend(list(q.fetch(limit=limit)))
            timeline = sorted(posts, key=lambda p: p.get('created'), reverse=True)[:limit]
    return timeline


def seed_data(users: int = 5, posts_per_user: int = 10, follows_count: int = 5, prefix: str = 'user'):
    """
    Peuple la base de données pour le benchmark.
    - Crée 'users' utilisateurs.
    - Chaque utilisateur suit exactement 'follows_count' autres utilisateurs.
    - Chaque utilisateur publie exactement 'posts_per_user' messages.
    """
    user_names = [f"{prefix}{i}" for i in range(1, users + 1)]
    
    # 1. Création des utilisateurs
    # On vérifie d'abord s'ils existent pour ne pas écraser inutilement, 
    # mais pour le seed initial c'est souvent vide.
    for name in user_names:
        key = client.key('User', name)
        if client.get(key) is None:
            entity = datastore.Entity(key)
            entity['follows'] = []
            client.put(entity)

    # 2. Assignation des Follows (Fixe pour exp 3)
    for name in user_names:
        key = client.key('User', name)
        entity = client.get(key)
        
        # On ne se suit pas soi-même
        others = [u for u in user_names if u != name]
        
        # Sélection aléatoire mais nombre FIXE
        target = min(follows_count, len(others))
        if target > 0:
            # On écrase les follows existants pour garantir le nombre exact demandé par le test
            entity['follows'] = random.sample(others, target)
            client.put(entity)

    # 3. Création des Posts (Posts PAR utilisateur)
    base_time = datetime.utcnow()
    batch = []
    total_posts = 0
    
    for name in user_names:
        for i in range(posts_per_user):
            p = datastore.Entity(client.key('Post'))
            p['author'] = name
            p['content'] = f"Benchmark post {i+1} by {name}"
            # On étale les dates aléatoirement pour le tri
            p['created'] = base_time - timedelta(seconds=random.randint(1, 10000))
            batch.append(p)
            total_posts += 1
            
            # Écriture par paquets de 400 pour éviter les limites de taille/temps
            if len(batch) >= 400:
                client.put_multi(batch)
                batch = []
    
    # Écrire le reste du batch
    if batch:
        client.put_multi(batch)

    return {
        'users_total': users,
        'posts_per_user': posts_per_user,
        'total_posts_created': total_posts,
        'follows_per_user': follows_count,
        'prefix': prefix
    }


@app.route('/', methods=['GET'])
def index():
    user = session.get('user')
    timeline = get_timeline(user) if user else []
    return render_template_string(TEMPLATE_INDEX, user=user, timeline=timeline)


@app.route('/api/timeline')
def api_timeline():
    """Endpoint JSON pour tests de charge (utilise paramètre user=)."""
    user = request.args.get('user') or session.get('user')
    if not user:
        return jsonify({"error": "missing user"}), 400
    try:
        limit = int(request.args.get('limit', '20'))
    except ValueError:
        limit = 20
    limit = max(1, min(limit, 100))
    entities = get_timeline(user, limit=limit)
    data = [
        {
            'author': e.get('author'),
            'content': e.get('content'),
            'created': (e.get('created') or datetime.utcnow()).isoformat() + 'Z'
        }
        for e in entities
    ]
    return jsonify({
        'user': user,
        'count': len(data),
        'items': data
    })


@app.route('/admin/seed', methods=['GET', 'POST'])
def admin_seed():
    """
    Endpoint de seed adapté au benchmark.
    Paramètres URL: users, posts (par user), follows, prefix.
    Exemple: /admin/seed?users=1000&posts=50&follows=20&prefix=exp1
    """
    # Sécurité simple via variable d'env (optionnelle pour le test)
    expected = os.environ.get('SEED_TOKEN')
    token = request.args.get('token')
    if expected and token != expected:
        return jsonify({'error': 'forbidden'}), 403

    try:
        users = int(request.args.get('users', 100))
        posts = int(request.args.get('posts', 10))     # Posts PAR User
        follows = int(request.args.get('follows', 5))  # Follows PAR User
        prefix = request.args.get('prefix', 'u_bench') # Préfixe pour isoler les tests
    except ValueError:
        return jsonify({'error': 'invalid params'}), 400

    # Lancer le seed
    result = seed_data(users=users, posts_per_user=posts, follows_count=follows, prefix=prefix)
    return jsonify({'status': 'ok', 'details': result})


@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    key = client.key('User', username)
    if not client.get(key):
        entity = datastore.Entity(key)
        entity.update({'follows': []})
        client.put(entity)
    session['user'] = username
    return redirect(url_for('index'))


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('index'))


@app.route('/post', methods=['POST'])
def post():
    user = session.get('user')
    if not user:
        return redirect(url_for('index'))
    content = request.form['content']
    entity = datastore.Entity(client.key('Post'))
    entity.update({
        'author': user,
        'content': content,
        'created': datetime.utcnow()
    })
    client.put(entity)
    return redirect(url_for('index'))


@app.route('/follow', methods=['POST'])
def follow():
    user = session.get('user')
    to_follow = request.form['to_follow']
    if not user or user == to_follow:
        return redirect(url_for('index'))
    user_key = client.key('User', user)
    user_entity = client.get(user_key)
    if not user_entity:
         # Si l'user n'existe pas encore (cas rare en prod mais possible ici)
         user_entity = datastore.Entity(user_key)
         user_entity['follows'] = []

    current_follows = user_entity.get('follows', [])
    if to_follow not in current_follows:
        current_follows.append(to_follow)
        user_entity['follows'] = current_follows
        client.put(user_entity)
    return redirect(url_for('index'))


if __name__ == '__main__':
    # Note: En production (App Engine), Gunicorn est utilisé, donc ce bloc n'est pas exécuté.
    # Pour le dev local:
    app.run(host='127.0.0.1', port=8080, debug=True)
