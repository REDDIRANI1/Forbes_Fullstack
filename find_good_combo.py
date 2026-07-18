import urllib.request
import json
import datetime

options = json.loads(urllib.request.urlopen('http://localhost:8000/rates/options').read())['combinations']
for opt in options:
    p = opt['provider_name'].replace(' ', '%20')
    t = opt['rate_type'].replace(' ', '%20')
    latest_req = urllib.request.urlopen(f'http://localhost:8000/rates/latest?type={t}')
    latest_data = json.loads(latest_req.read())
    latest_record = next((r for r in latest_data if r['provider_name'] == opt['provider_name']), None)
    if not latest_record: continue
    
    end_date = datetime.datetime.strptime(latest_record['effective_date'], '%Y-%m-%d').date()
    start_date = end_date - datetime.timedelta(days=30)
    
    history_req = urllib.request.urlopen(f'http://localhost:8000/rates/history?provider={p}&type={t}&from={start_date}&to={end_date}&page_size=100')
    history_data = json.loads(history_req.read())
    
    if history_data['count'] > 1:
        print(f"Found: {opt['provider_name']} - {opt['rate_type']} with {history_data['count']} records")
        break
