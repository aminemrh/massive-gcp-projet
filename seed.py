#!/usr/bin/env python3
"""
Script de génération de données pour le projet TinyInsta.
Configure par défaut pour: 1000 utilisateurs, 50 posts/user, 20 follows/user.
"""
from __future__ import annotations
import argparse
import random
from datetime import datetime, timedelta
from google.cloud import datastore

def parse_args():
    p = argparse.ArgumentParser(description="Seed Datastore for Tiny Instagram")
    # Valeurs par défaut demandées par le sujet 
    p.add_argument('--users', type=int, default=1000, help="Nombre d'utilisateurs")
    p.add_argument('--posts', type=int, default=50, help="Nombre de posts PAR utilisateur")
    p.add_argument('--follows', type=int, default=20, help="Nombre de follows PAR utilisateur")
    p.add_argument('--prefix', type=str, default='exp1', help="Préfixe des noms d'utilisateurs")
    p.add_argument('--dry-run', action='store_true', help="Simulation sans écriture")
    return p.parse_args()

def main():
    args = parse_args()
    client = datastore.Client()
    
    print(f"=== CONFIGURATION ===")
    print(f"Utilisateurs : {args.users}")
    print(f"Posts/User   : {args.posts}")
    print(f"Follows/User : {args.follows}")
    print(f"Préfixe      : {args.prefix}")
    print(f"TOTAL POSTS  : {args.users * args.posts}")
    print("=====================")

    if args.dry_run:
        print("[DRY-RUN] Aucune donnée ne sera écrite.")
        return

    user_names = [f"{args.prefix}{i}" for i in range(1, args.users + 1)]
    
    # --- 1. Création des Utilisateurs et des Relations (Follows) ---
    print("\n[1/2] Création des utilisateurs et des follows...")
    batch = []
    count_users = 0
    
    for name in user_names:
        key = client.key('User', name)
        entity = datastore.Entity(key)
        
        # Choix de 20 personnes aléatoires à suivre (parmi les autres)
        others = [u for u in user_names if u != name] # Exclure soi-même
        # On prend le min pour éviter une erreur si < 20 utilisateurs existent
        target_count = min(args.follows, len(others))
        
        if target_count > 0:
            entity['follows'] = random.sample(others, target_count)
        else:
            entity['follows'] = []
            
        batch.append(entity)
        count_users += 1
        
        # Écriture par paquet de 400
        if len(batch) >= 400:
            client.put_multi(batch)
            print(f"   -> {count_users} utilisateurs créés...")
            batch = []
            
    if batch:
        client.put_multi(batch)
        print(f"   -> {count_users} utilisateurs créés (Terminé).")

    # --- 2. Création des Posts ---
    print("\n[2/2] Création des posts (étape la plus longue)...")
    batch = []
    count_posts = 0
    base_time = datetime.utcnow()
    
    for name in user_names:
        for i in range(args.posts):
            key = client.key('Post')
            p = datastore.Entity(key)
            p['author'] = name
            p['content'] = f"Ceci est le message {i+1} de l'utilisateur {name} pour le benchmark."
            
            # On varie la date pour que le tri chronologique ait du sens
            # (Entre maintenant et il y a 100 jours)
            p['created'] = base_time - timedelta(minutes=random.randint(1, 144000))
            
            batch.append(p)
            count_posts += 1
            
            # Écriture par paquet de 400
            if len(batch) >= 400:
                client.put_multi(batch)
                # On affiche un point tous les 400 posts pour montrer que ça tourne
                if count_posts % 4000 == 0:
                     print(f"   -> {count_posts} posts écrits...")
                batch = []
                
    if batch:
        client.put_multi(batch)
    
    print(f"\nSUCCÈS ! Base de données peuplée avec {count_users} utilisateurs et {count_posts} posts.")

if __name__ == '__main__':
    main()
