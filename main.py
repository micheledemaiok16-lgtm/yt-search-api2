from flask import Flask, request, jsonify
from concurrent.futures import ThreadPoolExecutor, as_completed
import subprocess
import json
import os

app = Flask(__name__)

# Pool di thread per elaborazione parallela
MAX_WORKERS = 10  # Massimo 10 ricerche in parallelo

def search_single(query, max_results=1):
    """Cerca un singolo video"""
    try:
        cmd = [
            'yt-dlp',
            f'ytsearch{max_results}:{query}',
            '--dump-json',
            '--no-download',
            '--no-warnings',
            '--ignore-errors'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0 and not result.stdout:
            return {"query": query, "success": False, "error": "Search failed"}
        
        # Parse primo risultato
        for line in result.stdout.strip().split('\n'):
            if line:
                try:
                    video = json.loads(line)
                    return {
                        "query": query,
                        "success": True,
                        "id": video.get("id"),
                        "title": video.get("title"),
                        "channel": video.get("channel"),
                        "duration": video.get("duration"),
                        "url": f"https://www.youtube.com/watch?v={video.get('id')}",
                        "thumbnail": video.get("thumbnail")
                    }
                except json.JSONDecodeError:
                    continue
        
        return {"query": query, "success": False, "error": "No results"}
        
    except subprocess.TimeoutExpired:
        return {"query": query, "success": False, "error": "Timeout"}
    except Exception as e:
        return {"query": query, "success": False, "error": str(e)}

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "max_workers": MAX_WORKERS})

@app.route('/search', methods=['POST'])
def search_youtube():
    """Cerca un singolo video"""
    try:
        data = request.json
        query = data.get('query')
        
        if not query:
            return jsonify({"error": "query required"}), 400
        
        result = search_single(query)
        return jsonify(result)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/batch', methods=['POST'])
def batch_search():
    """Cerca multipli video in parallelo"""
    try:
        data = request.json
        queries = data.get('queries', [])  # Array di query strings
        
        # Oppure array di oggetti con artist + song
        songs = data.get('songs', [])
        if songs:
            queries = [f"{s.get('artist', '')} {s.get('song', '')} official video" for s in songs]
        
        if not queries:
            return jsonify({"error": "queries or songs array required"}), 400
        
        if len(queries) > 50:
            return jsonify({"error": "Maximum 50 queries per batch"}), 400
        
        results = []
        
        # Elaborazione parallela
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_query = {executor.submit(search_single, q): q for q in queries}
            
            for future in as_completed(future_to_query):
                result = future.result()
                results.append(result)
        
        # Riordina risultati nell'ordine originale
        query_order = {q: i for i, q in enumerate(queries)}
        results.sort(key=lambda x: query_order.get(x['query'], 999))
        
        return jsonify({
            "success": True,
            "total": len(queries),
            "found": sum(1 for r in results if r.get('success')),
            "results": results
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
```

---

**requirements.txt:**
```
flask==3.0.0
gunicorn==21.2.0
yt-dlp>=2024.1.0
