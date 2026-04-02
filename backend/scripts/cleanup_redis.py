# scripts/cleanup_all_jobs.py
import redis

def cleanup_all_jobs():
    try:
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        r.ping()
        print("✅ Connected to Redis")
        
        # Trouver toutes les clés job
        keys = r.keys("job:*")
        print(f"📋 Found {len(keys)} job keys")
        
        for key in keys:
            r.delete(key)
            print(f"🗑️  Deleted {key}")
        
        print(f"\n✅ Deleted {len(keys)} keys")
        
        # Vérifier
        remaining = r.keys("job:*")
        print(f"📋 Remaining keys: {len(remaining)}")
        
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    cleanup_all_jobs()