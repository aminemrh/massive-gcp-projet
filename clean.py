from google.cloud import datastore

def delete_all(kind):
    client = datastore.Client()
    query = client.query(kind=kind)
    query.keys_only()  # On récupère seulement les IDs pour aller plus vite
    
    keys = list(query.fetch())
    
    if not keys:
        print(f"Aucune entité '{kind}' trouvée.")
        return

    print(f"Suppression de {len(keys)} entités de type '{kind}'...")
    
    # Suppression par paquets de 400 (limite Datastore)
    batch_size = 400
    for i in range(0, len(keys), batch_size):
        batch = keys[i:i + batch_size]
        client.delete_multi(batch)
        print(f" - {len(batch)} supprimés...")
    
    print(f"Terminé pour '{kind}'.")

if __name__ == '__main__':
    print("--- NETTOYAGE DE LA BASE DE DONNÉES ---")
    
    # 1. Supprimer les Posts
    delete_all('Post')
    
    # 2. Supprimer les Users
    delete_all('User')
print("\nLa base de données est vide.")
