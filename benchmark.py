import subprocess
import csv
import os
import sys
import time
import random
import requests
import statistics
import pandas as pd
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- CONFIGURATION ---
URL = "https://tp-big-data-473713.ew.r.appspot.com"
OUT_DIR = "out"

EXP_CONFIG = {
    "conc": {"csv": "conc.csv", "title": "Temps moyen par requête selon la concurrence", "xlabel": "Nombre d'utilisateurs concurrents"},
    "post": {"csv": "post.csv", "title": "Temps moyen selon le nombre de posts", "xlabel": "Nombre de posts par utilisateur"},
    "fanout": {"csv": "fanout.csv", "title": "Temps moyen selon le nombre de followers", "xlabel": "Nombre de followees par utilisateur"},
}

# ------------------ UTILITIES ------------------

def ensure_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)

def run_command(cmd):
    try:
        subprocess.run(cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print(f"Warning: Command failed slightly but continuing: {cmd}")

def reset_db(users, posts, follows, prefix):
    print(f"\n[SETUP] Reset DB: {users} users, {posts} posts, {follows} follows ({prefix})...")
    run_command("python clean.py")
    run_command(f"python seed.py --users {users} --posts {posts} --follows {follows} --prefix {prefix}")
    print("  -> DB reset OK.")

# ------------------ BENCHMARK CORE ------------------

def create_session(concurrency):
    """Crée une session optimisée pour le nombre de threads."""
    session = requests.Session()
    adapter = HTTPAdapter(pool_connections=concurrency, pool_maxsize=concurrency)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session

def fetch_url(session, url):
    """Simple HTTP GET sans retry (Fail fast)."""
    start = time.time()
    try:
        response = session.get(url, timeout=20) 
        latency = (time.time() - start) * 1000
        return latency, response.status_code
    except Exception:
        return 0, 500

def run_threaded_test(concurrency, total_requests, user_prefix, user_count):
    urls = [f"{URL}/api/timeline?user={user_prefix}{random.randint(1, user_count)}"
            for _ in range(total_requests)]

    latencies = []
    errors = 0

    session = create_session(concurrency)
    print(f"  -> Lancement de {total_requests} requêtes avec {concurrency} threads...")

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(fetch_url, session, url) for url in urls]
        
        for f in as_completed(futures):
            lat, status = f.result()
            if status == 200:
                latencies.append(lat)
            else:
                errors += 1
    
    session.close()

    if not latencies:
        return 0, 1 

    avg_time = statistics.mean(latencies)
    is_failed = 1 if errors > 0 else 0
    
    if len(latencies) > 1:
        p95 = statistics.quantiles(latencies, n=100)[94]
        print(f"     Stats: Avg={avg_time:.2f}ms, P95={p95:.2f}ms, Erreurs={errors}")
    else:
        print(f"     Stats: Avg={avg_time:.2f}ms, Erreurs={errors}")

    return avg_time, is_failed

def write_results(filename, data):
    filepath = os.path.join(OUT_DIR, filename)
    with open(filepath, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["PARAM", "AVG_TIME", "RUN", "FAILED"])
        writer.writerows(data)
    print(f"[CSV] Saved -> {filepath}")

def generate_graph(exp_type):
    conf = EXP_CONFIG[exp_type]
    csv_path = os.path.join(OUT_DIR, conf["csv"])
    if not os.path.exists(csv_path): return

    try:
        df = pd.read_csv(csv_path)
        grouped = df.groupby('PARAM')['AVG_TIME'].agg(['mean', 'std'])

        plt.figure(figsize=(10, 6))
        params = grouped.index.astype(str)
        means = grouped['mean']
        stds = grouped['std'].fillna(0)

        plt.bar(params, means, yerr=stds, capsize=5, color='cornflowerblue', edgecolor='black')
        plt.title(conf["title"])
        plt.xlabel(conf["xlabel"])
        plt.ylabel("Temps moyen par requête (ms)")
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        plt.tight_layout()

        img_path = os.path.join(OUT_DIR, f"{exp_type}.png")
        plt.savefig(img_path)
        plt.close("all")
        print(f"[GRAPH] Generated -> {img_path}")
    except Exception as e:
        print(f"Erreur génération graph {exp_type}: {e}")

# ------------------ EXPERIMENT DEFINITIONS ------------------

def run_exp_concurrency():
    print("\n=== EXP 1: CONCURRENCE ===")
    reset_db(1000, 50, 20, "user")

    results = []
    concurrency_levels = [1, 10, 20, 50, 100, 1000]

    for c in concurrency_levels:
        n = max(c * 2, 50)
        if c == 1000: n = 2000
        
        print(f"Testing {c} concurrent users (Target: {n} reqs)")

        for run in range(1, 4):
            avg, failed = run_threaded_test(c, n, "user", 1000)
            print(f"   Run {run}: {avg:.2f} ms (Failed: {failed})")
            results.append([c, avg, run, failed])

    write_results("conc.csv", results)
    generate_graph("conc")

def run_exp_post():
    print("\n=== EXP 2: VOLUME POSTS ===")
    results = []
    concurrency = 50
    
    for p in [10, 100, 1000]:
        prefix = f"post{p}"
        reset_db(1000, p, 20, prefix)
        print(f"Testing {p} posts per user")
        
        for run in range(1, 4):
            avg, failed = run_threaded_test(concurrency, 200, prefix, 1000)
            print(f"   Run {run}: {avg:.2f} ms")
            results.append([p, avg, run, failed])

    write_results("post.csv", results)
    generate_graph("post")

def run_exp_fanout():
    print("\n=== EXP 3: FANOUT ===")
    results = []
    concurrency = 50
    
    for f in [10, 50, 100]:
        prefix = f"fan{f}"
        reset_db(1000, 100, f, prefix)
        print(f"Testing {f} followers per user")
        
        for run in range(1, 4):
            avg, failed = run_threaded_test(concurrency, 200, prefix, 1000)
            print(f"   Run {run}: {avg:.2f} ms")
            results.append([f, avg, run, failed])

    write_results("fanout.csv", results)
    generate_graph("fanout")

# ------------------ MAIN ------------------

if __name__ == "__main__":
    ensure_dir(OUT_DIR)
    mode = sys.argv[1]
    if mode == "conc": run_exp_concurrency()
    elif mode == "post": run_exp_post()
    elif mode == "fanout": run_exp_fanout()
    elif mode == "all":
        run_exp_concurrency()
        run_exp_post()
        run_exp_fanout()
