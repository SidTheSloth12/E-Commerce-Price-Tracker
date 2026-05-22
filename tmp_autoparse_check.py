import requests
import json
api = '0482406ecec73d1c704201e552e44c04'
for asin in ['B0FRGJWHJ7', 'B0DRV5L8GC']:
    url = f'http://api.scraperapi.com?api_key={api}&country_code=IN&autoparse=1&url=https://www.amazon.in/dp/{asin}'
    r = requests.get(url, timeout=60)
    print('===', asin, 'status', r.status_code)
    try:
        data = r.json()
        print(json.dumps(data.get('availability_status', data.get('product', {}).get('availability_status', {})), indent=2))
        print('price', data.get('product', {}).get('inventory', {}).get('price', data.get('product', {}).get('price')))
        print('parsed keys', list(data.keys())[:20])
    except Exception as e:
        print('json error', e)
        print('text sample', r.text[:800])
    print('---')
