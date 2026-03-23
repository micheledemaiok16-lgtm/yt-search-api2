from flask import Flask, request, jsonify
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
import json
import os

app = Flask(__name__)

# Pool di thread per elaborazione parallela
MAX_WORKERS = 10  # Massimo 10 ricerche in parallelo

def search_single(query, max_results=1):
    """Cerca video su YouTube"""
    try:
        cmd = [
            'yt-dlp',
            f'ytsearch{max_results}:{query}',
            '--dump-json',
            '--no-download',
            '--no-warnings',
            '--ignore-errors'
        ]
        
        # Aggiunge proxy se configurato
        proxy = os.environ.get('PROXY_URL')
        if proxy:
            cmd.extend(['--proxy', proxy])
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0 and not result.stdout:
            return [{"query": query, "success": False, "error": "Search failed"}]
        
        # Parse risultati
        videos = []
        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    video = json.loads(line)
                    videos.append({
                        "query": query,
                        "success": True,
                        "id": video.get("id"),
                        "title": video.get("title"),
                        "channel": video.get("channel"),
                        "duration": video.get("duration"),
                        "url": f"https://www.youtube.com/watch?v={video.get('id')}",
                        "thumbnail": video.get("thumbnail")
                    })
                except json.JSONDecodeError:
                    continue
        
        if not videos:
            return [{"query": query, "success": False, "error": "No results"}]
        
        return videos
        
    except subprocess.TimeoutExpired:
        return [{"query": query, "success": False, "error": "Timeout"}]
    except Exception as e:
        return [{"query": query, "success": False, "error": str(e)}]

@app.route('/health', methods=['GET'])
def health():
    proxy = os.environ.get('PROXY_URL')
    return jsonify({
        "status": "ok",
        "max_workers": MAX_WORKERS,
        "proxy_configured": bool(proxy)
    })

@app.route('/search', methods=['POST'])
def search_youtube():
    """Cerca video - accetta singolo oggetto o array"""
    try:
        data = request.json
        
        # Se riceve un array, redirige a batch
        if isinstance(data, list):
            return _process_batch(data, global_max_results=1)
        
        query = data.get('query')
        if not query:
            return jsonify({"error": "query required"}), 400
        
        max_results = data.get('max_results', 1)
        results = search_single(query, max_results)
        
        # Se max_results è 1, ritorna singolo oggetto per retrocompatibilità
        if max_results == 1:
            return jsonify(results[0])
        
        return jsonify(results)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/batch', methods=['POST'])
def batch_search():
    """
    Cerca multipli video in parallelo.
    
    Accetta questi formati:
    
    1) Array diretto (formato n8n):
       [{"query": "...", "max_results": 3}, {"query": "..."}]
    
    2) Oggetto con queries:
       {"queries": ["query1", "query2"], "max_results": 3}
       {"queries": [{"query": "...", "max_results": 3}, ...]}
    
    3) Oggetto con songs:
       {"songs": [{"artist": "...", "song": "..."}], "max_results": 3}
    """
    try:
        data = request.json
        
        # Formato 1: Array diretto (n8n)
        if isinstance(data, list):
            return _process_batch(data, global_max_results=1)
        
        global_max_results = data.get('max_results', 1)
        
        # Formato 3: Songs
        songs = data.get('songs', [])
        if songs:
            items = []
            for s in songs:
                items.append({
                    "query": f"{s.get('artist', '')} {s.get('song', '')} official video",
                    "max_results": s.get('max_results', global_max_results)
                })
            return _process_batch(items, global_max_results)
        
        # Formato 2: Queries
        queries = data.get('queries', [])
        if queries:
            # Queries può essere array di stringhe o array di oggetti
            items = []
            for q in queries:
                if isinstance(q, str):
                    items.append({"query": q})
                else:
                    items.append(q)
            return _process_batch(items, global_max_results)
        
        return jsonify({"error": "queries, songs array, or direct array required"}), 400
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def _process_batch(items, global_max_results=1):
    """Elabora un batch di ricerche in parallelo"""
    
    if len(items) > 50:
        return jsonify({"error": "Maximum 50 queries per batch"}), 400
    
    # Normalizza items: ogni elemento deve avere query e max_results
    normalized = []
    for item in items:
        if isinstance(item, str):
            normalized.append({"query": item, "max_results": global_max_results})
        else:
            normalized.append({
                "query": item.get('query', ''),
                "max_results": item.get('max_results', global_max_results)
            })
    
    all_results = []
    
    # Elaborazione parallela
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_item = {
            executor.submit(search_single, item['query'], item['max_results']): item
            for item in normalized
        }
        
        for future in as_completed(future_to_item):
            item = future_to_item[future]
            results = future.result()
            all_results.append({
                "query": item['query'],
                "max_results": item['max_results'],
                "videos": results
            })
    
    # Riordina risultati nell'ordine originale
    query_order = {item['query']: i for i, item in enumerate(normalized)}
    all_results.sort(key=lambda x: query_order.get(x['query'], 999))
    
    total_found = sum(
        sum(1 for v in r['videos'] if v.get('success'))
        for r in all_results
    )
    
    return jsonify({
        "success": True,
        "total_queries": len(normalized),
        "total_found": total_found,
        "results": all_results
    })

@app.route('/debug', methods=['POST'])
def debug_search():
    """Debug endpoint per diagnosticare problemi yt-dlp"""
    try:
        data = request.json
        query = data.get('query', 'test')
        
        cmd = [
            'yt-dlp',
            f'ytsearch1:{query}',
            '--dump-json',
            '--no-download',
            '--no-warnings',
            '--ignore-errors'
        ]
        
        proxy = os.environ.get('PROXY_URL')
        if proxy:
            cmd.extend(['--proxy', proxy])
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        return jsonify({
            "returncode": result.returncode,
            "stdout": result.stdout[:500] if result.stdout else None,
            "stderr": result.stderr[:500] if result.stderr else None,
            "proxy_used": bool(proxy)
        })
        
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timeout after 30s"})
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
